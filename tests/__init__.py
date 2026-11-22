"""Mock minimal Home Assistant modules for standalone unit testing."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum
from typing import Any
from unittest.mock import MagicMock


class MockHomeAssistantError(Exception):
    """Mock HomeAssistantError supporting translation metadata."""

    def __init__(
        self,
        *args: Any,
        translation_domain: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class MockServiceValidationError(MockHomeAssistantError):
    """Mock ServiceValidationError supporting translation metadata."""


class MockUpdateFailed(MockHomeAssistantError):
    """Mock UpdateFailed exception supporting translation metadata."""


_UNDEF = object()


def _install_voluptuous_fallback() -> None:
    """Install a lightweight validating voluptuous shim when voluptuous is absent."""
    vol_mod = types.ModuleType("voluptuous")

    class VolInvalid(Exception):
        """Validation error matching voluptuous.Invalid."""

    class _Marker:
        def __init__(self, schema: Any, default: Any = _UNDEF) -> None:
            self.schema = schema
            self.default = default

        def __hash__(self) -> int:
            return hash(self.schema)

        def __eq__(self, other: object) -> bool:
            if isinstance(other, _Marker):
                return self.schema == other.schema
            return self.schema == other

    class VolRequired(_Marker):
        pass

    class VolOptional(_Marker):
        pass

    def _run_validator(validator: Any, value: Any) -> Any:
        if isinstance(validator, type):
            if validator is bool:
                if not isinstance(value, bool):
                    raise VolInvalid(f"expected bool, got {type(value).__name__}")
                return value
            if not isinstance(value, validator):
                raise VolInvalid(
                    f"expected {validator.__name__}, got {type(value).__name__}"
                )
            return value
        if callable(validator):
            return validator(value)
        return value

    class VolAll:
        def __init__(self, *validators: Any) -> None:
            self.validators = validators

        def __call__(self, value: Any) -> Any:
            current = value
            for validator in self.validators:
                current = _run_validator(validator, current)
            return current

    class VolCoerce:
        def __init__(self, target_type: type[Any]) -> None:
            self.target_type = target_type

        def __call__(self, value: Any) -> Any:
            try:
                return self.target_type(value)
            except (TypeError, ValueError) as err:
                raise VolInvalid(str(err)) from err

    class VolRange:
        def __init__(self, min: Any = None, max: Any = None) -> None:
            self.min = min
            self.max = max

        def __call__(self, value: Any) -> Any:
            if self.min is not None and value < self.min:
                raise VolInvalid(f"value {value} must be at least {self.min}")
            if self.max is not None and value > self.max:
                raise VolInvalid(f"value {value} must be at most {self.max}")
            return value

    class VolIn:
        def __init__(self, container: Any) -> None:
            self.container = container

        def __call__(self, value: Any) -> Any:
            if value not in self.container:
                raise VolInvalid(f"value {value!r} not in allowed options")
            return value

    class VolSchema:
        def __init__(self, schema: dict[Any, Any]) -> None:
            self.schema = schema

        def __call__(self, data: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(data, dict):
                raise VolInvalid("expected a dictionary")
            result: dict[str, Any] = {}
            for marker, validator in self.schema.items():
                key = marker.schema if isinstance(marker, _Marker) else marker
                if key in data:
                    result[key] = _run_validator(validator, data[key])
                elif isinstance(marker, VolRequired):
                    if marker.default is not _UNDEF:
                        default_val = (
                            marker.default()
                            if callable(marker.default)
                            else marker.default
                        )
                        result[key] = _run_validator(validator, default_val)
                    else:
                        raise VolInvalid(f"required key not provided @ data['{key}']")
                elif isinstance(marker, VolOptional) and marker.default is not _UNDEF:
                    default_val = (
                        marker.default()
                        if callable(marker.default)
                        else marker.default
                    )
                    result[key] = _run_validator(validator, default_val)
            return result

    vol_mod.Invalid = VolInvalid  # type: ignore[attr-defined]
    vol_mod.MultipleInvalid = VolInvalid  # type: ignore[attr-defined]
    vol_mod.Required = VolRequired  # type: ignore[attr-defined]
    vol_mod.Optional = VolOptional  # type: ignore[attr-defined]
    vol_mod.All = VolAll  # type: ignore[attr-defined]
    vol_mod.Coerce = VolCoerce  # type: ignore[attr-defined]
    vol_mod.Range = VolRange  # type: ignore[attr-defined]
    vol_mod.In = VolIn  # type: ignore[attr-defined]
    vol_mod.Schema = VolSchema  # type: ignore[attr-defined]
    sys.modules["voluptuous"] = vol_mod


if "voluptuous" not in sys.modules:
    try:
        import voluptuous  # noqa: F401
    except ImportError:
        _install_voluptuous_fallback()


class MockDataUpdateCoordinator:
    """Mock DataUpdateCoordinator supporting generic subscripting."""

    @classmethod
    def __class_getitem__(cls, item: Any) -> type[MockDataUpdateCoordinator]:
        return cls

    def __init__(
        self,
        hass: Any,
        logger: Any,
        name: str,
        update_interval: Any = None,
    ) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None
        self.last_update_success: bool = True
        self.config_entry: Any = None

    async def async_request_refresh(self) -> None:
        pass

    async def async_config_entry_first_refresh(self) -> None:
        if hasattr(self, "_async_update_data"):
            self.data = await self._async_update_data()

    def async_set_updated_data(self, data: Any) -> None:
        self.data = data


class MockCoordinatorEntity:
    """Mock CoordinatorEntity supporting generic subscripting and availability."""

    @classmethod
    def __class_getitem__(cls, item: Any) -> type[MockCoordinatorEntity]:
        return cls

    def __init__(self, coordinator: Any = None) -> None:
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        return bool(getattr(self.coordinator, "last_update_success", True))


class MockDeviceInfo(dict):
    """Mock DeviceInfo dictionary."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class MockConfigEntry:
    """Mock ConfigEntry supporting generic subscripting and runtime_data."""

    @classmethod
    def __class_getitem__(cls, item: Any) -> type[MockConfigEntry]:
        return cls

    def __init__(
        self,
        *,
        domain: str = "staggassistant",
        title: str = "Stagg Kettle",
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        entry_id: str = "entry-1",
        unique_id: str | None = None,
        runtime_data: Any = None,
    ) -> None:
        self.domain = domain
        self.title = title
        self.data = dict(data) if data is not None else {}
        self.options = dict(options) if options is not None else {}
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.runtime_data = runtime_data
        self._unload_callbacks: list[Any] = []

    def async_on_unload(self, func: Any) -> None:
        self._unload_callbacks.append(func)

    def add_update_listener(self, listener: Any) -> Any:
        return listener


REDACTED = "**REDACTED**"


def _async_redact_data(data: Any, to_redact: set[str] | frozenset[str]) -> Any:
    """Recursively redact sensitive keys in dictionaries and lists."""
    if isinstance(data, dict):
        return {
            key: REDACTED if key in to_redact else _async_redact_data(val, to_redact)
            for key, val in data.items()
        }
    if isinstance(data, list):
        return [_async_redact_data(item, to_redact) for item in data]
    return data


# Install mock aiohttp if not present
if "aiohttp" not in sys.modules:
    aiohttp_mock = MagicMock()

    class MockClientError(Exception):
        pass

    aiohttp_mock.ClientError = MockClientError
    sys.modules["aiohttp"] = aiohttp_mock


# Install mock homeassistant packages into sys.modules if not already present
if "homeassistant" not in sys.modules:
    ha = MagicMock()
    sys.modules["homeassistant"] = ha

    ha_exceptions = MagicMock()
    ha_exceptions.HomeAssistantError = MockHomeAssistantError
    ha_exceptions.ServiceValidationError = MockServiceValidationError
    sys.modules["homeassistant.exceptions"] = ha_exceptions
    ha.exceptions = ha_exceptions

    ha_helpers = MagicMock()
    sys.modules["homeassistant.helpers"] = ha_helpers
    ha.helpers = ha_helpers

    ha_coordinator = MagicMock()
    ha_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
    ha_coordinator.CoordinatorEntity = MockCoordinatorEntity
    ha_coordinator.UpdateFailed = MockUpdateFailed
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_coordinator
    ha_helpers.update_coordinator = ha_coordinator

    ha_aiohttp = MagicMock()
    ha_aiohttp.async_get_clientsession = lambda hass: MagicMock()
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_aiohttp
    ha_helpers.aiohttp_client = ha_aiohttp

    ha_device_reg = MagicMock()
    ha_device_reg.DeviceInfo = MockDeviceInfo
    ha_device_reg.CONNECTION_NETWORK_MAC = "mac"
    sys.modules["homeassistant.helpers.device_registry"] = ha_device_reg
    ha_helpers.device_registry = ha_device_reg

    ha_entity_platform = MagicMock()
    ha_entity_platform.AddEntitiesCallback = Any
    sys.modules["homeassistant.helpers.entity_platform"] = ha_entity_platform
    ha_helpers.entity_platform = ha_entity_platform

    ISSUES_REGISTRY: dict[tuple[str, str], dict[str, Any]] = {}

    class MockIssueSeverity(StrEnum):
        CRITICAL = "critical"
        ERROR = "error"
        WARNING = "warning"

    def _async_create_issue(
        hass: Any,
        domain: str,
        issue_id: str,
        *,
        is_fixable: bool = False,
        is_persistent: bool = True,
        severity: Any = MockIssueSeverity.WARNING,
        translation_key: str = "",
        translation_placeholders: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        ISSUES_REGISTRY[(domain, issue_id)] = {
            "domain": domain,
            "issue_id": issue_id,
            "is_fixable": is_fixable,
            "is_persistent": is_persistent,
            "severity": severity,
            "translation_key": translation_key,
            "translation_placeholders": translation_placeholders or {},
            "data": data,
        }

    def _async_delete_issue(hass: Any, domain: str, issue_id: str) -> None:
        ISSUES_REGISTRY.pop((domain, issue_id), None)

    ha_issue_reg = MagicMock()
    ha_issue_reg.IssueSeverity = MockIssueSeverity
    ha_issue_reg.ISSUES = ISSUES_REGISTRY
    ha_issue_reg.async_create_issue = _async_create_issue
    ha_issue_reg.async_delete_issue = _async_delete_issue
    sys.modules["homeassistant.helpers.issue_registry"] = ha_issue_reg
    ha_helpers.issue_registry = ha_issue_reg

    class MockStore:
        """Mock Home Assistant Store with async_delay_save and async_remove."""

        def __init__(self, hass: Any, version: int, key: str) -> None:
            self.hass = hass
            self.version = version
            self.key = key
            self._data: dict[str, Any] | None = None
            self.delay_save_calls: list[tuple[Any, float]] = []
            self._pending_data_func: Any = None
            self.removed: bool = False

        async def async_load(self) -> dict[str, Any] | None:
            return self._data

        async def async_save(self, data: dict[str, Any]) -> None:
            self._data = dict(data)
            self._pending_data_func = None

        def async_delay_save(self, data_func: Any, delay: float = 0) -> None:
            self.delay_save_calls.append((data_func, delay))
            self._pending_data_func = data_func

        async def async_remove(self) -> None:
            self._data = None
            self.removed = True
            self._pending_data_func = None

    ha_storage = MagicMock()
    ha_storage.Store = MockStore
    sys.modules["homeassistant.helpers.storage"] = ha_storage
    ha_helpers.storage = ha_storage

    class MockConfigFlow:
        """Mock ConfigFlow supporting reconfigure and entry updates."""

        def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.hass = MagicMock()
            self.unique_id: str | None = None
            self.context: dict[str, Any] = {}

        async def async_set_unique_id(self, unique_id: str | None) -> None:
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def _get_reconfigure_entry(self) -> Any:
            return getattr(self, "_reconfigure_entry", None) or (
                self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
            )

        def async_update_reload_and_abort(
            self,
            entry: Any,
            *,
            data_updates: dict[str, Any] | None = None,
            unique_id: str | None = None,
            reason: str = "reconfigure_successful",
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.hass.config_entries.async_update_entry(
                entry,
                data=data_updates if data_updates is not None else entry.data,
                unique_id=unique_id,
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return {
                "type": "abort",
                "reason": reason,
                "data_updates": data_updates,
                "unique_id": unique_id,
            }

        def async_show_form(
            self,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                **kwargs,
            }

        def async_show_menu(
            self,
            step_id: str,
            menu_options: list[str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "type": "menu",
                "step_id": step_id,
                "menu_options": menu_options,
                **kwargs,
            }

        def async_abort(self, reason: str) -> dict[str, Any]:
            return {"type": "abort", "reason": reason}

        def async_create_entry(self, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    class MockOptionsFlow:
        """Mock OptionsFlow."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.hass = MagicMock()
            self.config_entry: Any = None

        def async_show_form(
            self,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                **kwargs,
            }

        def async_show_menu(
            self,
            step_id: str,
            menu_options: list[str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "type": "menu",
                "step_id": step_id,
                "menu_options": menu_options,
                **kwargs,
            }

        def async_create_entry(self, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    ha_entries = MagicMock()
    ha_entries.ConfigEntry = MockConfigEntry
    ha_entries.ConfigFlow = MockConfigFlow
    ha_entries.OptionsFlow = MockOptionsFlow
    sys.modules["homeassistant.config_entries"] = ha_entries
    ha.config_entries = ha_entries

    ha_core = MagicMock()
    ha_core.HomeAssistant = MagicMock
    ha_core.callback = lambda f: f
    sys.modules["homeassistant.core"] = ha_core
    ha.core = ha_core

    ha_const = MagicMock()
    ha_const.ATTR_TEMPERATURE = "temperature"

    class MockEntityCategory(StrEnum):
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class MockUnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    class MockUnitOfTime:
        MINUTES = "min"

    class MockUnitOfLength:
        METERS = "m"

    ha_const.EntityCategory = MockEntityCategory
    ha_const.UnitOfTemperature = MockUnitOfTemperature
    ha_const.UnitOfTime = MockUnitOfTime
    ha_const.UnitOfLength = MockUnitOfLength
    sys.modules["homeassistant.const"] = ha_const
    ha.const = ha_const

    ha_components = MagicMock()
    sys.modules["homeassistant.components"] = ha_components
    ha.components = ha_components

    ha_diagnostics = MagicMock()
    ha_diagnostics.async_redact_data = _async_redact_data
    sys.modules["homeassistant.components.diagnostics"] = ha_diagnostics
    ha_components.diagnostics = ha_diagnostics

    class MockClimateEntity:
        pass

    class MockHVACMode(StrEnum):
        OFF = "off"
        HEAT = "heat"

    class MockHVACAction(StrEnum):
        OFF = "off"
        HEATING = "heating"
        IDLE = "idle"

    class MockClimateEntityFeature(IntFlag):
        TARGET_TEMPERATURE = 1
        TURN_OFF = 128
        TURN_ON = 256

    ha_climate = MagicMock()
    ha_climate.ClimateEntity = MockClimateEntity
    sys.modules["homeassistant.components.climate"] = ha_climate
    ha_components.climate = ha_climate

    ha_climate_const = MagicMock()
    ha_climate_const.HVACMode = MockHVACMode
    ha_climate_const.HVACAction = MockHVACAction
    ha_climate_const.ClimateEntityFeature = MockClimateEntityFeature
    sys.modules["homeassistant.components.climate.const"] = ha_climate_const
    ha_climate.const = ha_climate_const

    class MockSensorDeviceClass(StrEnum):
        TEMPERATURE = "temperature"
        ENUM = "enum"

    class MockSensorStateClass(StrEnum):
        MEASUREMENT = "measurement"

    @dataclass(frozen=True, kw_only=True)
    class MockSensorEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        device_class: Any = None
        state_class: Any = None
        native_unit_of_measurement: Any = None
        options: list[str] | None = None
        icon: str | None = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockSensorEntity:
        pass

    ha_sensor = MagicMock()
    ha_sensor.SensorDeviceClass = MockSensorDeviceClass
    ha_sensor.SensorStateClass = MockSensorStateClass
    ha_sensor.SensorEntityDescription = MockSensorEntityDescription
    ha_sensor.SensorEntity = MockSensorEntity
    sys.modules["homeassistant.components.sensor"] = ha_sensor
    ha_components.sensor = ha_sensor

    class MockBinarySensorDeviceClass(StrEnum):
        CONNECTIVITY = "connectivity"
        PROBLEM = "problem"
        HEAT = "heat"

    @dataclass(frozen=True, kw_only=True)
    class MockBinarySensorEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        device_class: Any = None
        icon: str | None = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockBinarySensorEntity:
        pass

    ha_bsensor = MagicMock()
    ha_bsensor.BinarySensorDeviceClass = MockBinarySensorDeviceClass
    ha_bsensor.BinarySensorEntityDescription = MockBinarySensorEntityDescription
    ha_bsensor.BinarySensorEntity = MockBinarySensorEntity
    sys.modules["homeassistant.components.binary_sensor"] = ha_bsensor
    ha_components.binary_sensor = ha_bsensor

    class MockNumberDeviceClass(StrEnum):
        TEMPERATURE = "temperature"
        DURATION = "duration"
        DISTANCE = "distance"

    class MockNumberMode(StrEnum):
        AUTO = "auto"
        BOX = "box"
        SLIDER = "slider"

    @dataclass(frozen=True, kw_only=True)
    class MockNumberEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        native_min_value: float = 0
        native_max_value: float = 100
        native_step: float = 1
        native_unit_of_measurement: Any = None
        device_class: Any = None
        mode: Any = MockNumberMode.AUTO
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockNumberEntity:
        entity_description: MockNumberEntityDescription

        @property
        def native_min_value(self) -> float:
            return self.entity_description.native_min_value

        @property
        def native_max_value(self) -> float:
            return self.entity_description.native_max_value

    ha_number = MagicMock()
    ha_number.NumberDeviceClass = MockNumberDeviceClass
    ha_number.NumberMode = MockNumberMode
    ha_number.NumberEntityDescription = MockNumberEntityDescription
    ha_number.NumberEntity = MockNumberEntity
    sys.modules["homeassistant.components.number"] = ha_number
    ha_components.number = ha_number

    @dataclass(frozen=True, kw_only=True)
    class MockSelectEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        options: list[str] = field(default_factory=list)
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockSelectEntity:
        entity_description: MockSelectEntityDescription

        @property
        def options(self) -> list[str]:
            return self.entity_description.options

    ha_select = MagicMock()
    ha_select.SelectEntityDescription = MockSelectEntityDescription
    ha_select.SelectEntity = MockSelectEntity
    sys.modules["homeassistant.components.select"] = ha_select
    ha_components.select = ha_select

    @dataclass(frozen=True, kw_only=True)
    class MockSwitchEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockSwitchEntity:
        pass

    ha_switch = MagicMock()
    ha_switch.SwitchEntityDescription = MockSwitchEntityDescription
    ha_switch.SwitchEntity = MockSwitchEntity
    sys.modules["homeassistant.components.switch"] = ha_switch
    ha_components.switch = ha_switch

    @dataclass(frozen=True, kw_only=True)
    class MockButtonEntityDescription:
        key: str = ""
        name: Any = None
        translation_key: str | None = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True

    class MockButtonEntity:
        pass

    ha_button = MagicMock()
    ha_button.ButtonEntityDescription = MockButtonEntityDescription
    ha_button.ButtonEntity = MockButtonEntity
    sys.modules["homeassistant.components.button"] = ha_button
    ha_components.button = ha_button

    class MockRepairsFlow:
        """Mock Home Assistant RepairsFlow."""

        def __init__(self) -> None:
            self.hass: Any = MagicMock()

        def async_show_form(
            self,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                **kwargs,
            }

        def async_create_entry(
            self, title: str = "", data: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data or {}}

        def async_abort(self, reason: str) -> dict[str, Any]:
            return {"type": "abort", "reason": reason}

    class MockConfirmRepairFlow(MockRepairsFlow):
        """Mock default confirmation repair flow."""

    ha_repairs = MagicMock()
    ha_repairs.RepairsFlow = MockRepairsFlow
    ha_repairs.ConfirmRepairFlow = MockConfirmRepairFlow
    sys.modules["homeassistant.components.repairs"] = ha_repairs
    ha_components.repairs = ha_repairs

    ha_util = MagicMock()
    ha_dt = MagicMock()
    ha_util.dt = ha_dt
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_dt
    ha.util = ha_util
