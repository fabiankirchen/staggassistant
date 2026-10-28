"""DataUpdateCoordinator for Fellow Stagg EKG Pro integration."""
import asyncio
import json
import logging
import math
import re
from datetime import timedelta
import aiohttp

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

# Dangerous commands that bypass firmware safety, drive raw GPIOs, or wipe settings
BLOCKED_COMMANDS = {
    "heaton",
    "heatoff",
    "warmon",
    "warmoff",
    "warmduty",
    "gpioset",
    "reset",
    "clrsettings",
    "wifierase",
    "wifioff",
    "provreset",
    "eraseotherpart",
    "adcsamples",
    "htest",
    "hperiod",
    "triactrace",
    "lpsleep",
    "lpnow",
}

# Strict safety allowlist for legitimate commands
ALLOWED_COMMAND_PATTERNS = [
    re.compile(r"^ss (S_Heat|S_Off)$"),
    re.compile(r"^setsettingd settempr (?:1[0-9]{2}|20[0-9]|21[0-2])$"),
    re.compile(r"^setsetting hold ([0-9]|[1-5][0-9]|60)$"),
    re.compile(r"^setsetting boil [01]$"),
    re.compile(r"^setsetting chime ([0-9]|10)$"),
    re.compile(r"^setsetting language [0-6]$"),
    re.compile(r"^setsetting clockmode [0-2]$"),
    re.compile(r"^setsetting schedon [01]$"),
    re.compile(r"^setsetting repeat_sched [01]$", re.IGNORECASE),
    re.compile(r"^setsetting schtempr (?:1[0-9]{2}|20[0-9]|21[0-2])$"),
    re.compile(r"^setsetting schtime (?:[01]?[0-9]|2[0-3]):[0-5][0-9]$"),
    re.compile(r"^setaltitudem ([0-9]{1,3}|[12][0-9]{3}|3000)$"),
    re.compile(r"^setclock (?:[01]?[0-9]|2[0-3]) [0-5]?[0-9] [0-5]?[0-9]$"),
    re.compile(r"^(setdigital|setanalog|setunitsc|setunitsf|1|2|q|w|2d|2u)$"),
]

DEFAULT_SETTINGS = {
    "hold_time_minutes": 30,
    "hold_enabled": 1,
    "pre_boil_enabled": 0,
    "chime_enabled": 0,
    "chime_volume": 0,
    "altitude_meters": 0,
    "language": 0,
    "units": "C",
    "clock_mode": 0,
    "clock_time": None,
    "schedule_enabled": 0,
    "schedule_mode": "off",
    "schedule_time": None,
    "schedule_temperature": None,
}


def _parse_float(value) -> float | None:
    """Parse float safely, handling None, NaN, -nan, +nan, and out-of-range disconnected readings."""
    if value is None:
        return None
    if isinstance(value, str) and "nan" in value.lower():
        return None
    try:
        val = float(value)
        if math.isnan(val) or not (-10 <= val <= 150):
            return None
        return val
    except (ValueError, TypeError):
        return None


async def _read_response_text(response, limit: int = 65536) -> str:
    """Read response text up to byte limit safely."""
    if hasattr(response, "read"):
        raw = await response.read()
        if isinstance(raw, bytes):
            return raw[:limit].decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw[:limit]
    if hasattr(response, "text"):
        txt = await response.text()
        return txt[:limit]
    return ""


class StaggLinkCoordinator(DataUpdateCoordinator):
    """Central instance to fetch data from and send commands to the kettle CLI API."""

    def __init__(self, hass, ip, update_interval_seconds):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="StaggLink Kettle",
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.ip = ip
        self.session = async_get_clientsession(hass)
        self._lock = asyncio.Lock()
        self._cached_settings: dict = dict(DEFAULT_SETTINGS)
        elevation = getattr(getattr(hass, "config", None), "elevation", 0) or 0
        self._cached_settings["altitude_meters"] = int(elevation)
        self._prtsettings_supported: bool | None = None
        self._store = Store(hass, 1, f"staggassistant_{self.ip.replace('.', '_')}")
        self._settings_loaded = False

    async def async_load_saved_settings(self) -> None:
        """Load cached settings from persistent Home Assistant storage."""
        elevation = getattr(getattr(self.hass, "config", None), "elevation", 0) or 0
        if self._store:
            try:
                stored = await self._store.async_load()
                if isinstance(stored, dict):
                    self._cached_settings.update(stored)
                    if not self._cached_settings.get("altitude_meters") and elevation:
                        self._cached_settings["altitude_meters"] = int(elevation)
                    _LOGGER.debug("Loaded cached settings from storage for %s", self.ip)
            except Exception as err:
                _LOGGER.warning("Could not load stored settings for %s: %s", self.ip, err)
        self._settings_loaded = True

    async def _async_save_cached_settings(self) -> None:
        """Persist cached settings to Home Assistant storage."""
        if self._store:
            try:
                await self._store.async_save(dict(self._cached_settings))
            except Exception as err:
                _LOGGER.warning("Could not persist cached settings for %s: %s", self.ip, err)

    def _optimistically_update_settings(self, clean_cmd: str) -> None:
        """Update cached settings optimistically based on sent CLI commands."""
        cmd_lower = clean_cmd.lower()
        parts = clean_cmd.split()

        try:
            if cmd_lower.startswith("setsetting hold ") and len(parts) >= 3:
                val = int(parts[2])
                self._cached_settings["hold_time_minutes"] = val
                self._cached_settings["hold_enabled"] = 1 if val > 0 else 0
            elif cmd_lower.startswith("setsetting boil ") and len(parts) >= 3:
                self._cached_settings["pre_boil_enabled"] = int(parts[2])
            elif cmd_lower.startswith("setsetting chime ") and len(parts) >= 3:
                val = int(parts[2])
                self._cached_settings["chime_volume"] = val
                self._cached_settings["chime_enabled"] = 1 if val > 0 else 0
            elif cmd_lower.startswith("setsetting language ") and len(parts) >= 3:
                self._cached_settings["language"] = int(parts[2])
            elif cmd_lower.startswith("setsetting clockmode ") and len(parts) >= 3:
                self._cached_settings["clock_mode"] = int(parts[2])
            elif cmd_lower == "setdigital":
                self._cached_settings["clock_mode"] = 1
            elif cmd_lower == "setanalog":
                self._cached_settings["clock_mode"] = 2
            elif cmd_lower == "setunitsc":
                self._cached_settings["units"] = "C"
            elif cmd_lower == "setunitsf":
                self._cached_settings["units"] = "F"
            elif cmd_lower.startswith("setaltitudem ") and len(parts) >= 2:
                self._cached_settings["altitude_meters"] = int(parts[1])
            elif cmd_lower.startswith("setsetting schedon ") and len(parts) >= 3:
                val = int(parts[2])
                self._cached_settings["schedule_enabled"] = val
                if val == 0:
                    self._cached_settings["schedule_mode"] = "off"
                elif self._cached_settings.get("schedule_mode") == "off":
                    self._cached_settings["schedule_mode"] = "once"
            elif cmd_lower.startswith("setsetting repeat_sched ") and len(parts) >= 3:
                val = int(parts[2])
                if self._cached_settings.get("schedule_enabled") != 0:
                    self._cached_settings["schedule_mode"] = "repeat" if val == 1 else "once"
            elif (
                cmd_lower.startswith("setsetting schtempr ")
                or cmd_lower.startswith("setsettingd schtempr ")
            ) and len(parts) >= 3:
                # schtempr parameter is in Fahrenheit
                fahr = float(parts[2])
                self._cached_settings["schedule_temperature"] = round((fahr - 32) / 1.8, 1)
            elif cmd_lower.startswith("setsetting schtime ") and len(parts) >= 3:
                self._cached_settings["schedule_time"] = parts[2]
            elif cmd_lower.startswith("setclock ") and len(parts) >= 3:
                h = int(parts[1])
                m = int(parts[2])
                self._cached_settings["clock_time"] = f"{h:02d}:{m:02d}"
        except Exception as err:
            _LOGGER.debug("Could not parse optimistic settings from '%s': %s", clean_cmd, err)

    async def async_send_command(self, cmd: str) -> str:
        """Send a CLI command safely to the kettle.

        Guards against command injection, raw GPIO heater activation, or destructive commands.
        """
        clean_cmd = cmd.strip() if cmd else ""
        if not clean_cmd:
            _LOGGER.error("Rejected empty command.")
            raise HomeAssistantError("Empty command is not allowed.")

        if any(c in clean_cmd for c in ("\n", "\r", ";", "\x00")) or any(ord(c) < 32 for c in clean_cmd):
            _LOGGER.error("Blocked command containing forbidden characters: %r", clean_cmd)
            raise HomeAssistantError("Command contains forbidden characters.")

        tokens = [t.lower() for t in clean_cmd.split()]
        if any(t in BLOCKED_COMMANDS for t in tokens) or clean_cmd.lower() == "ss":
            _LOGGER.error("Blocked potentially dangerous command: '%s'", clean_cmd)
            raise HomeAssistantError("Command not permitted by safety allowlist.")

        if not any(pattern.match(clean_cmd) for pattern in ALLOWED_COMMAND_PATTERNS):
            _LOGGER.error("Blocked command not permitted by safety allowlist: '%s'", clean_cmd)
            raise HomeAssistantError("Command not permitted by safety allowlist.")

        encoded_cmd = "+".join(clean_cmd.split())
        url = f"http://{self.ip}/cli?cmd={encoded_cmd}"

        try:
            async with self._lock:
                async with asyncio.timeout(10):
                    async with self.session.get(url) as response:
                        response.raise_for_status()
                        result = await _read_response_text(response, 65536)
        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout sending command '%s' to %s", clean_cmd, self.ip)
            raise HomeAssistantError(f"Timeout communicating with Stagg kettle at {self.ip}") from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error sending command '%s' to %s: %s", clean_cmd, self.ip, err)
            raise HomeAssistantError(f"Error communicating with Stagg kettle: {err}") from err

        # Optimistically update cached settings based on sent command
        self._optimistically_update_settings(clean_cmd)
        await self._async_save_cached_settings()

        return result

    async def _async_read_temp_json(self) -> dict | None:
        """Attempt to read and parse the /temp JSON endpoint (Firmware 1.2.26+)."""
        url = f"http://{self.ip}/temp"
        try:
            async with asyncio.timeout(6):
                async with self.session.get(url) as response:
                    if response.status != 200:
                        return None
                    raw_text = await _read_response_text(response, 65536)
                    # Sanitize unquoted nan / -nan / +nan before json.loads
                    sanitized = re.sub(r':\s*[-+]?nan\b', ': null', raw_text, flags=re.IGNORECASE)
                    data = json.loads(sanitized)
                    if isinstance(data, dict) and "temp" in data and ("temp_set" in data or "state" in data):
                        return data
        except Exception as err:
            _LOGGER.debug("Failed to read /temp JSON endpoint: %s", err)
            return None
        return None

    async def _async_update_data(self):
        """Fetch data from the kettle via HTTP endpoints."""
        try:
            if not self._settings_loaded:
                await self.async_load_saved_settings()

            async with self._lock:
                async with asyncio.timeout(20):
                    temp_data = await self._async_read_temp_json()

                    current_temp = None
                    target_temp = None
                    mode = "S_Off"
                    boil_temp = None
                    clock_time = None
                    no_water = False
                    target_reached = False
                    in_pre_boil = False
                    hold_flag = False

                    if temp_data is not None:
                        current_temp = _parse_float(temp_data.get("temp"))
                        target_temp = _parse_float(temp_data.get("temp_set"))
                        mode = str(temp_data.get("state", "S_Off"))
                        boil_temp = _parse_float(temp_data.get("boil_temp") or temp_data.get("temprB"))
                        clock_time = temp_data.get("clock")
                    else:
                        # Fallback to GET http://{self.ip}/cli?cmd=state
                        state_url = f"http://{self.ip}/cli?cmd=state"
                        async with asyncio.timeout(6):
                            async with self.session.get(state_url) as response:
                                response.raise_for_status()
                                state_text = await _read_response_text(response, 65536)

                        temp_match = re.search(r'(?i)\btempr(?![TB])\s*=\s*(-?[0-9.]+|[-+]?nan)', state_text)
                        target_match = re.search(r'(?i)\btemprT\s*=\s*(-?[0-9.]+|[-+]?nan)', state_text)
                        boil_match = re.search(r'(?i)\btemprB\s*=\s*(-?[0-9.]+|[-+]?nan)', state_text)
                        mode_match = re.search(r'\bmode\s*=\s*([a-zA-Z0-9_+-]+)', state_text)

                        if not temp_match or not target_match or not mode_match:
                            if '<form action="cli"' in state_text:
                                raise UpdateFailed(
                                    "Kettle CLI returned only HTML form without state data, and /temp JSON endpoint failed."
                                )
                            raise UpdateFailed(f"Parsing error. Incomplete response: {state_text}")

                        current_temp = _parse_float(temp_match.group(1))
                        target_temp = _parse_float(target_match.group(1))
                        boil_temp = _parse_float(boil_match.group(1)) if boil_match else None
                        mode = mode_match.group(1)

                        clock_match = re.search(r'\bclock\s*=\s*([0-9]+:[0-9]+)', state_text)
                        if clock_match:
                            try:
                                h, m = clock_match.group(1).split(":")
                                clock_time = f"{int(h):02d}:{int(m):02d}"
                            except Exception:
                                clock_time = clock_match.group(1)

                        ketl_match = re.search(r'\bketl\s*=\s*(.*)$', state_text, re.MULTILINE)
                        if ketl_match:
                            flags = dict(re.findall(r'([a-zA-Z]+)\s+([0-9]+)', ketl_match.group(1)))
                            no_water = flags.get("nw") == "1"
                            target_reached = flags.get("tr") == "1"
                            in_pre_boil = flags.get("ipb") == "1"
                            hold_flag = flags.get("ho") == "1"

                    # Fetch prtsettings (skip on subsequent polls if Firmware 1.2.26+ silenced CLI output)
                    settings_text = ""
                    if self._prtsettings_supported is not False:
                        settings_url = f"http://{self.ip}/cli?cmd=prtsettings"
                        try:
                            async with asyncio.timeout(6):
                                async with self.session.get(settings_url) as resp_settings:
                                    resp_settings.raise_for_status()
                                    settings_text = await _read_response_text(resp_settings, 65536)
                        except Exception as err:
                            _LOGGER.debug("Could not fetch prtsettings: %s", err)
                            settings_text = ""

                    # Check if settings_text contains actual settings data
                    has_settings = "st:" in settings_text or re.search(r'\bhold\s*[:=]', settings_text) is not None
                    if has_settings:
                        self._prtsettings_supported = True
                    elif temp_data is not None:
                        # Firmware 1.2.26+ silenced textual output from /cli
                        self._prtsettings_supported = False

                    if has_settings:
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
                            match = re.search(rf'\b{name}\s*=\s*([0-9]+:[0-9]+)', settings_text, re.IGNORECASE)
                            return match.group(1) if match else default

                        sch_tempr_c = None
                        sch_match = re.search(r'schtempr\s*=\s*.*?\s*(-?[0-9.]+)\s*C', settings_text)
                        if sch_match:
                            sch_tempr_c = _parse_float(sch_match.group(1))

                        schedon = get_setting_value("schedon", self._cached_settings.get("schedule_enabled", 0))
                        repeat_sched = get_setting_value("Repeat_sched", 0)
                        if schedon == 0:
                            schedule_mode = "off"
                        elif repeat_sched:
                            schedule_mode = "repeat"
                        else:
                            schedule_mode = "once"

                        hold_val = get_setting_value("hold", self._cached_settings.get("hold_time_minutes", 30))
                        pre_boil_val = get_setting_value("boil", self._cached_settings.get("pre_boil_enabled", 0))
                        chime_val = get_setting_value("chime", self._cached_settings.get("chime_volume", 0))
                        altitude_val = get_setting_value("altitude", self._cached_settings.get("altitude_meters", 0))
                        language_val = get_setting_value("language", self._cached_settings.get("language", 0))
                        units_raw = get_setting_value("units", 1 if self._cached_settings.get("units") == "C" else 0)
                        units_val = "C" if units_raw == 1 else "F"
                        clock_mode_val = get_setting_value("clockmode", self._cached_settings.get("clock_mode", 0))
                        sch_time_val = get_time_value("schtime", self._cached_settings.get("schedule_time"))

                        # Safe type checks
                        hold_enabled_val = 1 if isinstance(hold_val, (int, float)) and hold_val > 0 else 0
                        chime_enabled_val = 1 if isinstance(chime_val, (int, float)) and chime_val > 0 else 0
                        pre_boil_enabled_val = 1 if pre_boil_val in (1, "1", True) else 0

                        self._cached_settings["hold_time_minutes"] = hold_val
                        self._cached_settings["hold_enabled"] = hold_enabled_val
                        self._cached_settings["pre_boil_enabled"] = pre_boil_enabled_val
                        self._cached_settings["chime_enabled"] = chime_enabled_val
                        self._cached_settings["chime_volume"] = chime_val
                        self._cached_settings["altitude_meters"] = altitude_val
                        self._cached_settings["language"] = language_val
                        self._cached_settings["units"] = units_val
                        self._cached_settings["clock_mode"] = clock_mode_val
                        self._cached_settings["schedule_enabled"] = schedon
                        self._cached_settings["schedule_mode"] = schedule_mode
                        if sch_time_val is not None:
                            self._cached_settings["schedule_time"] = sch_time_val
                        if sch_tempr_c is not None:
                            self._cached_settings["schedule_temperature"] = sch_tempr_c

                        await self._async_save_cached_settings()

                    if clock_time is not None:
                        self._cached_settings["clock_time"] = clock_time

                    if boil_temp is None:
                        altitude = self._cached_settings.get("altitude_meters", 0) or 0
                        try:
                            boil_temp = round(100.0 - (float(altitude) / 285.0), 1)
                        except (ValueError, TypeError):
                            boil_temp = 100.0

                    is_docked = current_temp is not None

                    # If using /temp or legacy state had no ketl flags, infer flags
                    if temp_data is not None:
                        hold_flag = mode.startswith("S_Hold")
                        target_reached = bool(
                            is_docked
                            and target_temp is not None
                            and mode != "S_Off"
                            and (current_temp >= target_temp - 0.5 or mode.startswith("S_Hold"))
                        )
                        in_pre_boil = (mode == "S_PreBoil")

                    # Safe type checks for returned settings
                    hold_val = self._cached_settings.get("hold_time_minutes", 30)
                    hold_enabled = 1 if isinstance(hold_val, (int, float)) and hold_val > 0 else 0
                    chime_val = self._cached_settings.get("chime_volume", 0)
                    chime_enabled = 1 if isinstance(chime_val, (int, float)) and chime_val > 0 else 0
                    pre_boil_val = self._cached_settings.get("pre_boil_enabled", 0)
                    pre_boil_enabled = 1 if pre_boil_val in (1, "1", True) else 0

                    return {
                        "temp": current_temp,
                        "target": target_temp,
                        "boil_temp": boil_temp,
                        "mode": mode,
                        "is_docked": is_docked,
                        "no_water": no_water,
                        "target_reached": target_reached,
                        "in_pre_boil": in_pre_boil,
                        "hold_flag": hold_flag,
                        "hold_time_minutes": hold_val,
                        "hold_enabled": hold_enabled,
                        "pre_boil_enabled": pre_boil_enabled,
                        "chime_enabled": chime_enabled,
                        "chime_volume": chime_val,
                        "altitude_meters": self._cached_settings.get("altitude_meters", 0),
                        "language": self._cached_settings.get("language", 0),
                        "units": self._cached_settings.get("units", "C"),
                        "clock_mode": self._cached_settings.get("clock_mode", 0),
                        "clock_time": self._cached_settings.get("clock_time"),
                        "schedule_enabled": self._cached_settings.get("schedule_enabled", 0),
                        "schedule_mode": self._cached_settings.get("schedule_mode", "off"),
                        "schedule_time": self._cached_settings.get("schedule_time"),
                        "schedule_temperature": self._cached_settings.get("schedule_temperature"),
                    }
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Connection error: {err}") from err
