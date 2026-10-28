"""Support for Fellow Stagg EKG Pro sensors."""
import logging
from dataclasses import dataclass
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES, DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)

EXTENDED_SENSOR_KEYS = {"boil_temp", "schedule_time", "schedule_temperature"}


@dataclass(frozen=True, kw_only=True)
class StaggSensorDescription(SensorEntityDescription):
    """Describes a Stagg sensor entity."""

    key: str
    name: str


SENSOR_DESCRIPTIONS: tuple[StaggSensorDescription, ...] = (
    StaggSensorDescription(
        key="current_temp",
        translation_key="current_temp",
        name="Current Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer",
    ),
    StaggSensorDescription(
        key="target_temp",
        translation_key="target_temp",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-check",
    ),
    StaggSensorDescription(
        key="boil_temp",
        translation_key="boil_temp",
        name="Boil Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:water-boiler",
        entity_registry_enabled_default=False,
    ),
    StaggSensorDescription(
        key="state_mode",
        translation_key="state_mode",
        name="State Mode",
        icon="mdi:kettle-steam",
    ),
    StaggSensorDescription(
        key="clock_time",
        translation_key="clock_time",
        name="Clock Time",
        icon="mdi:clock-time-eight-outline",
    ),
    StaggSensorDescription(
        key="schedule_time",
        translation_key="schedule_time",
        name="Schedule Time",
        icon="mdi:calendar-clock-outline",
        entity_registry_enabled_default=False,
    ),
    StaggSensorDescription(
        key="schedule_temperature",
        translation_key="schedule_temperature",
        name="Schedule Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-auto",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink sensors from a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]
    enable_extended = entry.options.get(
        CONF_ENABLE_EXTENDED_ENTITIES,
        entry.data.get(CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES),
    )
    entities = [
        StaggSensor(coordinator, entry, desc)
        for desc in SENSOR_DESCRIPTIONS
        if enable_extended or desc.key not in EXTENDED_SENSOR_KEYS
    ]
    async_add_entities(entities, True)


class StaggSensor(CoordinatorEntity[StaggLinkCoordinator], SensorEntity):
    """Representation of a Stagg EKG Pro sensor."""

    entity_description: StaggSensorDescription

    def __init__(self, coordinator: StaggLinkCoordinator, entry, description: StaggSensorDescription):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._ip = entry.data["ip_address"]
        device_id = f"stagglink_{self._ip.replace('.', '_')}"

        self._attr_has_entity_name = True
        self._attr_translation_key = description.key
        self._attr_unique_id = f"stagg_{self._ip.replace('.', '_')}_{description.key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get("name", "Stagg Kettle"),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}",
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        if key == "current_temp":
            return self.coordinator.data.get("temp")
        if key == "target_temp":
            return self.coordinator.data.get("target")
        if key == "boil_temp":
            return self.coordinator.data.get("boil_temp")
        if key == "state_mode":
            mode = self.coordinator.data.get("mode")
            if not mode:
                return None
            if mode == "S_NoWater":
                return "Low Water Alert"
            if mode == "S_Standby":
                return "Standby"
            if mode == "S_StartupToTempr":
                return "Heating to Target"
            if mode.startswith("S_"):
                return mode[2:].replace("_", " ").title()
            return mode
        if key == "clock_time":
            return self.coordinator.data.get("clock_time")
        if key == "schedule_time":
            return self.coordinator.data.get("schedule_time")
        if key == "schedule_temperature":
            return self.coordinator.data.get("schedule_temperature")

        return None
