"""Mock minimal Home Assistant modules for standalone unit testing."""
import sys
from unittest.mock import MagicMock


class MockHomeAssistantError(Exception):
    pass


class MockUpdateFailed(Exception):
    pass


class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

    async def async_request_refresh(self):
        pass


class MockDeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


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
    sys.modules["homeassistant.exceptions"] = ha_exceptions

    ha_coordinator = MagicMock()
    ha_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
    ha_coordinator.UpdateFailed = MockUpdateFailed
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_coordinator

    ha_aiohttp = MagicMock()
    ha_aiohttp.async_get_clientsession = lambda hass: MagicMock()
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_aiohttp

    ha_device_reg = MagicMock()
    ha_device_reg.DeviceInfo = MockDeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = ha_device_reg

    class MockStore:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key
            self._data = None

        async def async_load(self):
            return self._data

        async def async_save(self, data):
            self._data = dict(data)

    ha_storage = MagicMock()
    ha_storage.Store = MockStore
    sys.modules["homeassistant.helpers.storage"] = ha_storage

    class MockConfigFlow:
        def __init__(self, *args, **kwargs):
            self.hass = MagicMock()
            self.unique_id = None

        async def async_set_unique_id(self, unique_id):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            pass

        def async_show_form(self, step_id, data_schema=None, errors=None):
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors}

        def async_create_entry(self, title, data):
            return {"type": "create_entry", "title": title, "data": data}

    class MockOptionsFlow:
        def __init__(self, *args, **kwargs):
            self.hass = MagicMock()
            self.config_entry = None

        def async_show_form(self, step_id, data_schema=None, errors=None):
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors}

        def async_create_entry(self, title, data):
            return {"type": "create_entry", "title": title, "data": data}

    ha_entries = MagicMock()
    ha_entries.ConfigEntry = MagicMock
    ha_entries.ConfigFlow = MockConfigFlow
    ha_entries.OptionsFlow = MockOptionsFlow
    sys.modules["homeassistant.config_entries"] = ha_entries

    ha_core = MagicMock()
    ha_core.HomeAssistant = MagicMock
    ha_core.callback = lambda f: f
    sys.modules["homeassistant.core"] = ha_core

    ha_const = MagicMock()
    ha_const.ATTR_TEMPERATURE = "temperature"

    class MockUnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    class MockUnitOfTime:
        MINUTES = "min"

    class MockUnitOfLength:
        METERS = "m"

    ha_const.UnitOfTemperature = MockUnitOfTemperature
    ha_const.UnitOfTime = MockUnitOfTime
    ha_const.UnitOfLength = MockUnitOfLength
    sys.modules["homeassistant.const"] = ha_const

    ha_climate = MagicMock()
    sys.modules["homeassistant.components.climate"] = ha_climate
    sys.modules["homeassistant.components.climate.const"] = MagicMock()

    from dataclasses import dataclass

    @dataclass(frozen=True, kw_only=True)
    class MockSensorEntityDescription:
        key: str = ""
        name: str = ""
        translation_key: str | None = None
        device_class: any = None
        state_class: any = None
        native_unit_of_measurement: any = None
        icon: str | None = None
        entity_registry_enabled_default: bool = True

    @dataclass(frozen=True, kw_only=True)
    class MockBinarySensorEntityDescription:
        key: str = ""
        name: str = ""
        translation_key: str | None = None
        device_class: any = None
        icon: str | None = None
        entity_registry_enabled_default: bool = True

    class MockBinarySensorEntity:
        pass

    class MockSensorEntity:
        pass

    ha_sensor = MagicMock()
    ha_sensor.SensorEntityDescription = MockSensorEntityDescription
    ha_sensor.SensorEntity = MockSensorEntity
    sys.modules["homeassistant.components.sensor"] = ha_sensor

    ha_bsensor = MagicMock()
    ha_bsensor.BinarySensorEntityDescription = MockBinarySensorEntityDescription
    ha_bsensor.BinarySensorEntity = MockBinarySensorEntity
    sys.modules["homeassistant.components.binary_sensor"] = ha_bsensor

    ha_number = MagicMock()
    sys.modules["homeassistant.components.number"] = ha_number

    ha_select = MagicMock()
    sys.modules["homeassistant.components.select"] = ha_select

    ha_switch = MagicMock()
    sys.modules["homeassistant.components.switch"] = ha_switch

    class MockButtonEntity:
        pass

    ha_button = MagicMock()
    ha_button.ButtonEntity = MockButtonEntity
    sys.modules["homeassistant.components.button"] = ha_button

    ha_util = MagicMock()
    ha_dt = MagicMock()
    ha_util.dt = ha_dt
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_dt
