"""Support for Fellow Stagg EKG Pro sensors."""
import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = [
        StaggSensor(coordinator, entry, "current_temp", "Current Temperature", SensorDeviceClass.TEMPERATURE, None, "mdi:thermometer"),
        StaggSensor(coordinator, entry, "target_temp", "Target Temperature", SensorDeviceClass.TEMPERATURE, None, "mdi:thermometer-check"),
        StaggSensor(coordinator, entry, "state_mode", "State Mode", None, None, "mdi:kettle-steam"),
        StaggSensor(coordinator, entry, "clock_time", "Clock Time", None, None, "mdi:clock-time-eight-outline"),
        StaggSensor(coordinator, entry, "schedule_time", "Schedule Time", None, None, "mdi:calendar-clock-outline"),
        StaggSensor(coordinator, entry, "schedule_temperature", "Schedule Temperature", SensorDeviceClass.TEMPERATURE, None, "mdi:thermometer-auto"),
    ]
    
    async_add_entities(sensors, True)

class StaggSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Stagg EKG Pro sensor."""

    def __init__(self, coordinator, entry, sensor_type, name_suffix, device_class, unit_of_measurement, icon):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._type = sensor_type
        self._attr_name = f"{entry.data.get('name', 'Stagg Kettle')} {name_suffix}"
        self._attr_unique_id = f"stagg_{entry.data['ip_address'].replace('.', '_')}_{sensor_type}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon
        self._attr_has_entity_name = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"stagglink_{entry.data['ip_address'].replace('.', '_')}")},
            "name": entry.data.get("name", "Stagg Kettle"),
            "manufacturer": "Fellow",
            "model": "Stagg EKG Pro",
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
            
        if self._type == "current_temp":
            return self.coordinator.data.get("temp")
        elif self._type == "target_temp":
            return self.coordinator.data.get("target")
        elif self._type == "state_mode":
            mode = self.coordinator.data.get("mode")
            if mode and mode.startswith("S_"):
                return mode[2:].replace("_", " ").title()
            return mode
        elif self._type == "clock_time":
            return self.coordinator.data.get("clock_time")
        elif self._type == "schedule_time":
            return self.coordinator.data.get("schedule_time")
        elif self._type == "schedule_temperature":
            return self.coordinator.data.get("schedule_temperature")

        return None

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        if self._type in ("current_temp", "target_temp"):
            unit = self.coordinator.data.get("units", "C") if self.coordinator.data else "C"
            return UnitOfTemperature.FAHRENHEIT if unit == "F" else UnitOfTemperature.CELSIUS
        return self._attr_native_unit_of_measurement
