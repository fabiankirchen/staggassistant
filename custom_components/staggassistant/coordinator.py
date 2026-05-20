import logging
import re
import async_timeout
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

class StaggLinkCoordinator(DataUpdateCoordinator):
    """Zentrale Instanz zum Abrufen der Daten."""

    def __init__(self, hass, ip, update_interval_seconds):
        super().__init__(
            hass,
            _LOGGER,
            name="StaggLink Kettle",
            # Wir wandeln die Integer-Sekunden in ein timedelta um
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.ip = ip
        self.session = async_get_clientsession(hass)

    async def _async_update_data(self):
        """Daten von der CLI abrufen."""
        state_url = f"http://{self.ip}/cli?cmd=state"
        settings_url = f"http://{self.ip}/cli?cmd=prtsettings"
        
        try:
            async with async_timeout.timeout(20):
                # 1. State abrufen
                response = await self.session.get(state_url)
                response.raise_for_status()
                state_text = await response.text()
                
                # 2. Settings abrufen
                response_settings = await self.session.get(settings_url)
                response_settings.raise_for_status()
                settings_text = await response_settings.text()
                
                temp_match = re.search(r'tempr=([0-9.]+|nan)', state_text)
                target_match = re.search(r'temprT=([0-9.]+|nan)', state_text)
                mode_match = re.search(r'mode=([a-zA-Z0-9_]+)', state_text)
                
                if not temp_match or not target_match or not mode_match:
                    raise UpdateFailed(f"Parsing Fehler. Antwort: {state_text}")

                def parse_float(value):
                    if value == 'nan': return None
                    try: return float(value)
                    except: return None

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

                # 3. Clock time from prtclock
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

                # Schedule temperature: "schtempr=N F (X C ...)" → extract C value
                sch_tempr_c = None
                sch_match = re.search(r'schtempr\s*=\s*[^\(]+\(\s*(-?[0-9.]+)\s*C', settings_text)
                if sch_match:
                    try:
                        sch_tempr_c = float(sch_match.group(1))
                    except ValueError:
                        pass

                schedon = get_setting_value("schedon", 0)
                repeat_sched = get_setting_value("Repeat_sched", 0)
                if schedon == 0:
                    schedule_mode = "off"
                elif repeat_sched:
                    schedule_mode = "repeat"
                else:
                    schedule_mode = "once"

                return {
                    "temp": parse_float(temp_match.group(1)),
                    "target": parse_float(target_match.group(1)),
                    "mode": mode_match.group(1),
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
            raise UpdateFailed(f"Verbindungsfehler: {err}")
