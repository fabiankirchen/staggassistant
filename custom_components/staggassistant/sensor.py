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
        StaggSensor(coordinator, entry, "hold_time", "Hold Time", None, UnitOfTime.MINUTES, "mdi:timer"),
        StaggSensor(coordinator, entry, "altitude", "Altitude", None, "m", "mdi:elevation-rise"),
        StaggSensor(coordinator, entry, "language", "Language", None, None, "mdi:translate"),
        StaggSensor(coordinator, entry, "chime_volume", "Chime Volume", None, None, "mdi:volume-high"),
        StaggSensor(coordinator, entry, "clock_mode", "Clock Mode", None, None, "mdi:clock-outline"),
        StaggSensor(coordinator, entry, "temperature_units", "Temperature Units", None, None, "mdi:thermometer"),
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
            return self.coordinator.data.get("mode")
        elif self._type == "hold_time":
            return self.coordinator.data.get("hold_time_minutes")
        elif self._type == "altitude":
            return self.coordinator.data.get("altitude_meters")
        elif self._type == "language":
            lang_idx = self.coordinator.data.get("language")
            try:
                return ["en", "fr", "es"][int(lang_idx)]
            except (TypeError, IndexError, ValueError):
                return lang_idx
        elif self._type == "chime_volume":
            vol = self.coordinator.data.get("chime_volume")
            if vol == 0: return "Off"
            if vol in (1, 2): return "Low"
            if vol in (3, 4): return "Medium"
            if vol == 5: return "High"
            return vol
        elif self._type == "clock_mode":
            cm = self.coordinator.data.get("clock_mode")
            try:
                return "analog" if int(cm) == 2 else "digital"
            except (TypeError, ValueError):
                return cm
        elif self._type == "temperature_units":
            return self.coordinator.data.get("units", "C")

        return None

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        if self._type in ("current_temp", "target_temp"):
            unit = self.coordinator.data.get("units", "C") if self.coordinator.data else "C"
            return UnitOfTemperature.FAHRENHEIT if unit == "F" else UnitOfTemperature.CELSIUS
        return self._attr_native_unit_of_measurement
