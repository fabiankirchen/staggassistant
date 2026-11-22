"""DataUpdateCoordinator for Fellow Stagg EKG Pro integration."""
from __future__ import annotations

from datetime import timedelta
import logging
import re
from typing import TYPE_CHECKING, Any, TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ALLOWED_COMMAND_PATTERNS,
    BLOCKED_COMMANDS,
    KettleData,
    KettleSettings,
    StaggCommandNotAllowedError,
    StaggConnectionError,
    StaggInvalidResponseError,
    StaggKettleClient,
    StaggTimeoutError,
    parse_float,
    validate_command,
)
from .const import (
    CONF_NAME,
    DOMAIN,
    ISSUE_KETTLE_UNREACHABLE_PREFIX,
    REPAIR_FAILURE_THRESHOLD,
    STORE_SAVE_DELAY,
    clamp_scan_interval,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

StaggConfigEntry: TypeAlias = ConfigEntry["StaggLinkCoordinator"]

_LOGGER = logging.getLogger(__name__)

# Re-export safety constants and float helper for backwards compatibility
_parse_float = parse_float

__all__ = [
    "ALLOWED_COMMAND_PATTERNS",
    "BLOCKED_COMMANDS",
    "DEFAULT_SETTINGS",
    "StaggConfigEntry",
    "StaggLinkCoordinator",
    "_parse_float",
]

DEFAULT_SETTINGS: KettleSettings = {
    "hold_time_minutes": 30,
    "hold_enabled": 1,
    "pre_boil_enabled": 0,
    "chime_enabled": 0,
    "chime_volume": 0,
    "altitude_meters": 0,
    "language": 0,
    "units": "C",
    "clock_mode": 0,
    "schedule_enabled": 0,
    "schedule_mode": "off",
    "schedule_time": None,
    "schedule_temperature": None,
}

_SCHTEMPR_C_RE = re.compile(r"schtempr\s*=\s*[^(\n]*\(\s*(-?[0-9.]+)\s*C\s*\)")
_SCHTEMPR_F_RE = re.compile(r"schtempr\s*=\s*(-?[0-9.]+)\s*F")


def _safe_elevation(hass: HomeAssistant) -> int:
    """Return Home Assistant's configured elevation as a safe integer."""
    elevation = getattr(getattr(hass, "config", None), "elevation", 0) or 0
    if isinstance(elevation, bool):
        return 0
    try:
        return int(elevation)
    except (TypeError, ValueError):
        return 0


def _coerce_int(value: Any, default: int) -> int:
    """Coerce a parsed setting value to int safely."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


class StaggLinkCoordinator(DataUpdateCoordinator[KettleData]):
    """Central instance to fetch data from and send commands to the kettle API."""

    def __init__(
        self,
        hass: HomeAssistant,
        ip: str,
        update_interval_seconds: int,
        storage_key: str | None = None,
        config_entry: ConfigEntry[Any] | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="StaggLink Kettle",
            update_interval=timedelta(
                seconds=clamp_scan_interval(update_interval_seconds)
            ),
        )
        self.config_entry = config_entry
        self.ip = ip
        self.session = async_get_clientsession(hass)
        self.client = StaggKettleClient(self.session, ip)
        self._lock = self.client._lock

        self._cached_settings: KettleSettings = {
            **DEFAULT_SETTINGS,
            "altitude_meters": _safe_elevation(hass),
        }
        self._clock_time: str | None = None
        self._storage_key = storage_key or self.ip.replace(".", "_")
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"staggassistant_{self._storage_key}"
        )
        self._legacy_store: Store[dict[str, Any]] | None = None
        legacy_key = self.ip.replace(".", "_")
        if storage_key and storage_key != legacy_key:
            self._legacy_store = Store(hass, 1, f"staggassistant_{legacy_key}")
        self._settings_loaded = False
        self._store_dirty = False
        self._consecutive_failures = 0
        self._repair_issue_created = False

    def _repair_issue_id(self) -> str | None:
        """Return the repair issue ID for the associated config entry."""
        entry_id = getattr(self.config_entry, "entry_id", None)
        if not entry_id:
            return None
        return f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}{entry_id}"

    def _record_connection_failure(self) -> None:
        """Track consecutive connection/timeout failures and raise a repair issue."""
        self._consecutive_failures += 1
        if (
            self._consecutive_failures < REPAIR_FAILURE_THRESHOLD
            or self._repair_issue_created
        ):
            return
        issue_id = self._repair_issue_id()
        if not issue_id:
            return
        entry = self.config_entry
        entry_data = getattr(entry, "data", {}) or {}
        entry_name = (
            getattr(entry, "title", None)
            or entry_data.get(CONF_NAME)
            or "Stagg Kettle"
        )
        entry_id = getattr(entry, "entry_id", None)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="kettle_unreachable",
            translation_placeholders={
                "name": str(entry_name),
                "ip_address": self.ip,
            },
            data={"entry_id": entry_id},
        )
        self._repair_issue_created = True

    def async_clear_repair_issue(self) -> None:
        """Reset failure counter and delete any active unreachable repair issue."""
        self._consecutive_failures = 0
        if not self._repair_issue_created:
            return
        issue_id = self._repair_issue_id()
        if issue_id:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._repair_issue_created = False

    @property
    def _prtsettings_supported(self) -> bool | None:
        """Return whether the kettle supports textual prtsettings output."""
        return self.client.prtsettings_supported

    @_prtsettings_supported.setter
    def _prtsettings_supported(self, value: bool | None) -> None:
        self.client.prtsettings_supported = value

    async def async_load_saved_settings(self) -> None:
        """Load cached settings from persistent Home Assistant storage."""
        elevation = _safe_elevation(self.hass)
        if self._store:
            try:
                stored = await self._store.async_load()
                if stored is None and self._legacy_store is not None:
                    stored = await self._legacy_store.async_load()
                    if isinstance(stored, dict):
                        migrated = {
                            k: v for k, v in stored.items() if k != "clock_time"
                        }
                        await self._store.async_save(migrated)
                        try:
                            await self._legacy_store.async_remove()
                        except Exception as remove_err:
                            _LOGGER.debug(
                                "Could not remove legacy store for %s: %s",
                                self.ip,
                                remove_err,
                            )
                        _LOGGER.debug(
                            "Migrated cached settings for %s to stable storage key",
                            self.ip,
                        )
                if isinstance(stored, dict):
                    cleaned = {k: v for k, v in stored.items() if k != "clock_time"}
                    self._cached_settings.update(cleaned)  # type: ignore[typeddict-item]
                    if not self._cached_settings.get("altitude_meters") and elevation:
                        self._cached_settings["altitude_meters"] = elevation
                    _LOGGER.debug("Loaded cached settings from storage for %s", self.ip)
            except Exception as err:
                _LOGGER.warning("Could not load stored settings for %s: %s", self.ip, err)
        self._settings_loaded = True

    def _get_persistable_settings(self) -> dict[str, Any]:
        """Return a copy of cached settings safe for persistence."""
        return dict(self._cached_settings)

    def _schedule_save_if_dirty(self, previous: dict[str, Any]) -> None:
        """Schedule debounced storage write only when cached settings changed."""
        if previous != self._cached_settings:
            self._store_dirty = True
            self._store.async_delay_save(
                self._get_persistable_settings, STORE_SAVE_DELAY
            )

    async def async_flush_store(self) -> None:
        """Flush any pending debounced settings save immediately."""
        if self._store_dirty:
            try:
                await self._store.async_save(self._get_persistable_settings())
                self._store_dirty = False
            except Exception as err:
                _LOGGER.warning(
                    "Could not flush cached settings for %s: %s", self.ip, err
                )

    async def async_remove_storage(self) -> None:
        """Remove persistent storage files associated with this coordinator."""
        try:
            await self._store.async_remove()
        except Exception as err:
            _LOGGER.debug("Could not remove store for %s: %s", self.ip, err)
        if self._legacy_store is not None:
            try:
                await self._legacy_store.async_remove()
            except Exception as err:
                _LOGGER.debug("Could not remove legacy store for %s: %s", self.ip, err)

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
                    self._cached_settings["schedule_mode"] = (
                        "repeat" if val == 1 else "once"
                    )
            elif cmd_lower.startswith("setsetting schtempr ") and len(parts) >= 3:
                fahr = float(parts[2])
                self._cached_settings["schedule_temperature"] = round(
                    (fahr - 32) / 1.8, 1
                )
            elif cmd_lower.startswith("setsetting schtime ") and len(parts) >= 3:
                self._cached_settings["schedule_time"] = parts[2]
            elif cmd_lower.startswith("setclock ") and len(parts) >= 3:
                h = int(parts[1])
                m = int(parts[2])
                self._clock_time = f"{h:02d}:{m:02d}"
        except Exception as err:
            _LOGGER.debug(
                "Could not parse optimistic settings from '%s': %s", clean_cmd, err
            )

    async def async_send_command(self, cmd: str) -> str:
        """Validate and send a CLI command safely to the kettle."""
        try:
            clean_cmd = validate_command(cmd)
            result = await self.client.async_send_command(clean_cmd)
        except StaggCommandNotAllowedError as err:
            _LOGGER.warning("Blocked kettle command (%s)", err.translation_key)
            raise HomeAssistantError(
                str(err),
                translation_domain=DOMAIN,
                translation_key=err.translation_key or "command_not_allowed",
            ) from err
        except StaggTimeoutError as err:
            _LOGGER.warning("Timeout sending command to %s", self.ip)
            raise HomeAssistantError(
                str(err),
                translation_domain=DOMAIN,
                translation_key="timeout",
                translation_placeholders={"host": self.ip},
            ) from err
        except StaggConnectionError as err:
            _LOGGER.warning("Connection error sending command to %s: %s", self.ip, err)
            raise HomeAssistantError(
                str(err),
                translation_domain=DOMAIN,
                translation_key="connection_error",
                translation_placeholders={"host": self.ip, "error": str(err)},
            ) from err

        previous = dict(self._cached_settings)
        self._optimistically_update_settings(clean_cmd)
        self._schedule_save_if_dirty(previous)
        return result

    def _apply_prtsettings(self, settings_text: str) -> None:
        """Parse legacy textual prtsettings output and persist changes when dirty."""

        def get_setting_value(name: str, default: Any = None) -> Any:
            match = re.search(
                rf"\b{name}\s*[:=]\s*([a-zA-Z0-9_.-]+)",
                settings_text,
                re.IGNORECASE,
            )
            if match:
                val = match.group(1).strip()
                try:
                    if "." in val:
                        return float(val)
                    return int(val)
                except ValueError:
                    return val
            return default

        def get_time_value(name: str, default: str | None = None) -> str | None:
            match = re.search(
                rf"\b{name}\s*=\s*([0-9]+:[0-9]+)",
                settings_text,
                re.IGNORECASE,
            )
            return match.group(1) if match else default

        sch_tempr_c: float | None = None
        sch_match = _SCHTEMPR_C_RE.search(settings_text)
        if sch_match:
            sch_tempr_c = parse_float(sch_match.group(1))
        else:
            sch_f_match = _SCHTEMPR_F_RE.search(settings_text)
            if sch_f_match:
                raw_f = sch_f_match.group(1)
                try:
                    sch_tempr_c = parse_float(round((float(raw_f) - 32.0) / 1.8, 1))
                except ValueError:
                    sch_tempr_c = None

        schedon = _coerce_int(
            get_setting_value(
                "schedon", self._cached_settings.get("schedule_enabled", 0)
            ),
            0,
        )
        repeat_sched = _coerce_int(get_setting_value("Repeat_sched", 0), 0)
        if schedon == 0:
            schedule_mode = "off"
        elif repeat_sched:
            schedule_mode = "repeat"
        else:
            schedule_mode = "once"

        hold_val = _coerce_int(
            get_setting_value(
                "hold", self._cached_settings.get("hold_time_minutes", 30)
            ),
            30,
        )
        pre_boil_raw = get_setting_value(
            "boil", self._cached_settings.get("pre_boil_enabled", 0)
        )
        chime_val = _coerce_int(
            get_setting_value("chime", self._cached_settings.get("chime_volume", 0)),
            0,
        )
        altitude_val = _coerce_int(
            get_setting_value(
                "altitude", self._cached_settings.get("altitude_meters", 0)
            ),
            0,
        )
        language_val = _coerce_int(
            get_setting_value("language", self._cached_settings.get("language", 0)),
            0,
        )
        units_raw = get_setting_value(
            "units", 1 if self._cached_settings.get("units") == "C" else 0
        )
        units_val = "C" if units_raw == 1 else "F"
        clock_mode_val = _coerce_int(
            get_setting_value("clockmode", self._cached_settings.get("clock_mode", 0)),
            0,
        )
        sch_time_val = get_time_value(
            "schtime", self._cached_settings.get("schedule_time")
        )

        hold_enabled_val = 1 if hold_val > 0 else 0
        chime_enabled_val = 1 if chime_val > 0 else 0
        pre_boil_enabled_val = 1 if pre_boil_raw in (1, "1", True) else 0

        previous = dict(self._cached_settings)
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

        self._schedule_save_if_dirty(previous)

    async def _async_update_data(self) -> KettleData:
        """Fetch and normalize kettle telemetry and settings."""
        if not self._settings_loaded:
            await self.async_load_saved_settings()

        try:
            payload = await self.client.async_fetch_poll_payload()
        except StaggTimeoutError as err:
            self._record_connection_failure()
            raise UpdateFailed(
                str(err),
                translation_domain=DOMAIN,
                translation_key="timeout",
                translation_placeholders={"host": self.ip},
            ) from err
        except StaggConnectionError as err:
            self._record_connection_failure()
            raise UpdateFailed(
                str(err),
                translation_domain=DOMAIN,
                translation_key="connection_error",
                translation_placeholders={"host": self.ip, "error": str(err)},
            ) from err
        except StaggInvalidResponseError as err:
            raise UpdateFailed(
                str(err),
                translation_domain=DOMAIN,
                translation_key="invalid_response",
                translation_placeholders={"error": str(err)},
            ) from err
        except Exception as err:
            raise UpdateFailed(
                f"Connection error: {err}",
                translation_domain=DOMAIN,
                translation_key="connection_error",
                translation_placeholders={"host": self.ip, "error": str(err)},
            ) from err

        current_temp: float | None = None
        target_temp: float | None = None
        mode = "S_Off"
        boil_temp: float | None = None
        clock_time: str | None = None
        no_water = False
        target_reached = False
        in_pre_boil = False
        hold_flag = False

        if payload.temp_data is not None:
            temp_data = payload.temp_data
            current_temp = parse_float(temp_data.get("temp"))
            target_temp = parse_float(temp_data.get("temp_set"))
            raw_state = temp_data.get("state")
            mode = str(raw_state) if raw_state else "S_Off"
            boil_temp = parse_float(temp_data.get("boil_temp") or temp_data.get("temprB"))
            raw_clock = temp_data.get("clock")
            clock_time = str(raw_clock) if raw_clock is not None else None
            no_water = mode == "S_NoWater"
        else:
            state_text = payload.state_text or ""
            temp_match = re.search(
                r"(?i)\btempr(?![TB])\s*=\s*(-?[0-9.]+|[-+]?nan)", state_text
            )
            target_match = re.search(
                r"(?i)\btemprT\s*=\s*(-?[0-9.]+|[-+]?nan)", state_text
            )
            boil_match = re.search(
                r"(?i)\btemprB\s*=\s*(-?[0-9.]+|[-+]?nan)", state_text
            )
            mode_match = re.search(r"\bmode\s*=\s*([a-zA-Z0-9_+-]+)", state_text)

            if not temp_match or not target_match or not mode_match:
                if '<form action="cli"' in state_text:
                    msg = (
                        "Kettle CLI returned only HTML form without state data, "
                        "and /temp JSON endpoint failed."
                    )
                    raise UpdateFailed(
                        msg,
                        translation_domain=DOMAIN,
                        translation_key="invalid_response",
                        translation_placeholders={"error": msg},
                    )
                msg = f"Parsing error. Incomplete response: {state_text[:120]!r}"
                raise UpdateFailed(
                    msg,
                    translation_domain=DOMAIN,
                    translation_key="invalid_response",
                    translation_placeholders={"error": msg},
                )

            current_temp = parse_float(temp_match.group(1))
            target_temp = parse_float(target_match.group(1))
            boil_temp = parse_float(boil_match.group(1)) if boil_match else None
            mode = mode_match.group(1)

            clock_match = re.search(r"\bclock\s*=\s*([0-9]+:[0-9]+)", state_text)
            if clock_match:
                try:
                    h, m = clock_match.group(1).split(":")
                    clock_time = f"{int(h):02d}:{int(m):02d}"
                except Exception:
                    clock_time = clock_match.group(1)

            ketl_match = re.search(r"\bketl\s*=\s*(.*)$", state_text, re.MULTILINE)
            if ketl_match:
                flags = dict(
                    re.findall(r"([a-zA-Z]+)\s+([0-9]+)", ketl_match.group(1))
                )
                no_water = flags.get("nw") == "1"
                target_reached = flags.get("tr") == "1"
                in_pre_boil = flags.get("ipb") == "1"
                hold_flag = flags.get("ho") == "1"

        settings_text = payload.settings_text
        has_settings = (
            "st:" in settings_text
            or re.search(r"\bhold\s*[:=]", settings_text) is not None
        )
        if has_settings:
            self._apply_prtsettings(settings_text)

        if clock_time is not None:
            self._clock_time = clock_time

        if boil_temp is None:
            altitude = self._cached_settings.get("altitude_meters", 0) or 0
            try:
                boil_temp = round(100.0 - (float(altitude) / 285.0), 1)
            except (ValueError, TypeError):
                boil_temp = 100.0

        is_docked = current_temp is not None

        if payload.temp_data is not None:
            hold_flag = mode.startswith("S_Hold")
            target_reached = bool(
                is_docked
                and current_temp is not None
                and target_temp is not None
                and mode != "S_Off"
                and (current_temp >= target_temp - 0.5 or mode.startswith("S_Hold"))
            )
            in_pre_boil = mode == "S_PreBoil"

        hold_val = self._cached_settings.get("hold_time_minutes", 30)
        hold_enabled = 1 if isinstance(hold_val, (int, float)) and hold_val > 0 else 0
        chime_val = self._cached_settings.get("chime_volume", 0)
        chime_enabled = 1 if isinstance(chime_val, (int, float)) and chime_val > 0 else 0
        pre_boil_val = self._cached_settings.get("pre_boil_enabled", 0)
        pre_boil_enabled = 1 if pre_boil_val in (1, "1", True) else 0

        self.async_clear_repair_issue()

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
            "clock_time": self._clock_time,
            "schedule_enabled": self._cached_settings.get("schedule_enabled", 0),
            "schedule_mode": self._cached_settings.get("schedule_mode", "off"),
            "schedule_time": self._cached_settings.get("schedule_time"),
            "schedule_temperature": self._cached_settings.get("schedule_temperature"),
        }
