"""DataUpdateCoordinator for Fellow Stagg EKG Pro integration."""
import logging
import re
import async_timeout
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


def _parse_float(value):
    """Convert a value to float, treating None/NaN/'nan' as missing."""
    if value is None or value == 'nan':
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # NaN is the only value that is not equal to itself
    return None if result != result else result


class StaggLinkCoordinator(DataUpdateCoordinator):
    """Central instance to fetch data from the kettle CLI API."""

    def __init__(self, hass, ip, update_interval_seconds):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="StaggLink Kettle",
            # Convert integer seconds into a timedelta object
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.ip = ip
        self.session = async_get_clientsession(hass)

    async def _read_state(self):
        """Return (temp, target, mode) for the kettle.

        Firmware 1.2.26 dropped the textual `/cli?cmd=state` output (the CLI
        endpoint now only echoes an input form) and exposes the live state as
        JSON at `/temp`:
            {"temp":27.4,"temp_set":97.0,"state":"S_Off","pwm":-10,"timestamp":...}
        Temperatures are in degrees Celsius and `state` keeps the same mode
        tokens as before (S_Off, S_Heat, ...). We prefer that endpoint and fall
        back to the legacy text command so older firmware keeps working.
        """
        # Preferred: JSON endpoint (firmware 1.2.26+)
        try:
            response = await self.session.get(f"http://{self.ip}/temp")
            if response.status == 200:
                data = await response.json(content_type=None)
                if "state" in data:
                    return (
                        _parse_float(data.get("temp")),
                        _parse_float(data.get("temp_set")),
                        data["state"],
                    )
        except Exception:
            pass  # fall through to the legacy text endpoint

        # Fallback: legacy text CLI (firmware < 1.2.26)
        response = await self.session.get(f"http://{self.ip}/cli?cmd=state")
        response.raise_for_status()
        state_text = await response.text()
        temp_match = re.search(r'tempr=([0-9.]+|nan)', state_text)
        target_match = re.search(r'temprT=([0-9.]+|nan)', state_text)
        mode_match = re.search(r'mode=([a-zA-Z0-9_]+)', state_text)
        if not temp_match or not target_match or not mode_match:
            raise UpdateFailed(f"Parsing error. Response: {state_text}")
        return (
            _parse_float(temp_match.group(1)),
            _parse_float(target_match.group(1)),
            mode_match.group(1),
        )

    async def _async_update_data(self):
        """Fetch data from the kettle."""
        settings_url = f"http://{self.ip}/cli?cmd=prtsettings"

        try:
            async with async_timeout.timeout(20):
                # 1. Fetch current device state (temperature / target / mode)
                temp, target, mode = await self._read_state()

                # 2. Fetch system settings dump.
                #    Firmware 1.2.26+ no longer prints CLI output, so on those
                #    devices the parsed settings below simply fall back to their
                #    defaults (the climate entity keeps working from /temp).
                response_settings = await self.session.get(settings_url)
                response_settings.raise_for_status()
                settings_text = await response_settings.text()

                def get_setting_value(name, default=None):
                    match = re.search(rf'\b{name}\s*[:=]\s*([a-zA-Z0-9_.-]+)', settings_text, re.IGNORECASE)
                    if match:
                        val = match.group(1).strip()
                        try:
                            if '.' in val:
                                return float(val)
                            return int(val)
                        except ValueError:
                            return val
                    return default

                def get_time_value(name, default=None):
                    """Parse HH:MM values (colons not matched by get_setting_value)."""
                    match = re.search(rf'\b{name}\s*=\s*([0-9]+:[0-9]+)', settings_text, re.IGNORECASE)
                    return match.group(1) if match else default

                # 3. Fetch current clock time from prtclock
                clock_time = None
                try:
                    response_clock = await self.session.get(f"http://{self.ip}/cli?cmd=prtclock")
                    response_clock.raise_for_status()
                    clock_text = await response_clock.text()
                    clock_match = re.search(r'clock=([0-9]+:[0-9]+)', clock_text)
                    if clock_match:
                        h, m = clock_match.group(1).split(":")
                        clock_time = f"{int(h):02d}:{int(m):02d}"
                except Exception:
                    pass

                # Schedule temperature: "schtempr=N F (X C ...)" or "schtempr=N C (X C ...)"
                sch_tempr_c = None
                sch_match = re.search(r'schtempr\s*=\s*.*?\s*(-?[0-9.]+)\s*C', settings_text)
                if sch_match:
                    try:
                        sch_tempr_c = float(sch_match.group(1))
                    except ValueError:
                        pass

                schedon = get_setting_value("schedon", 0)
                repeat_sched = get_setting_value("Repeat_sched", 0)
                if schedon == 0:
                    schedule_mode = "off"
                    sch_tempr_c = None # Hide temperature if schedule is off
                elif repeat_sched:
                    schedule_mode = "repeat"
                else:
                    schedule_mode = "once"

                return {
                    "temp": temp,
                    "target": target,
                    "mode": mode,
                    "hold_time_minutes": get_setting_value("hold", 30),
                    "hold_enabled": 1 if get_setting_value("hold", 0) > 0 else 0,
                    "pre_boil_enabled": get_setting_value("boil", 0),
                    "chime_enabled": 1 if get_setting_value("chime", 0) > 0 else 0,
                    "chime_volume": get_setting_value("chime", 0),
                    "altitude_meters": get_setting_value("altitude", 0),
                    "language": get_setting_value("language", 0),
                    "units": "C" if get_setting_value("units", 1) == 1 else "F",
                    "clock_mode": get_setting_value("clockmode", 0),
                    "clock_time": clock_time,
                    "schedule_enabled": schedon,
                    "schedule_mode": schedule_mode,
                    "schedule_time": get_time_value("schtime"),
                    "schedule_temperature": sch_tempr_c,
                }

        except Exception as err:
            raise UpdateFailed(f"Connection error: {err}")
