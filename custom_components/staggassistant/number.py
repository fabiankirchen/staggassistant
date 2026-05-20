"""Support for Fellow Stagg EKG Pro numbers."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink numbers from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    numbers = [
        StaggNumber(coordinator, entry, "hold_time_minutes", "Hold Time Duration", 0, 60, 1, "min", "mdi:timer-sand", "setsetting hold"),
        StaggNumber(coordinator, entry, "altitude_meters", "Altitude Setting", 0, 3000, 1, "m", "mdi:elevation-rise", "setaltitudem"),
        StaggNumber(coordinator, entry, "chime_volume", "Chime Volume", 0, 10, 1, None, "mdi:volume-high", "setsetting chime"),
    ]
    
    async_add_entities(numbers, True)

class StaggNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Stagg EKG Pro number configuration."""

    def __init__(self, coordinator, entry, key, name_suffix, min_val, max_val, step_val, unit_of_measurement, icon, command_prefix):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"{entry.data.get('name', 'Stagg Kettle')} {name_suffix}"
        self._attr_unique_id = f"stagg_{entry.data['ip_address'].replace('.', '_')}_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step_val
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon
        self._command_prefix = command_prefix
        self._attr_has_entity_name = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"stagglink_{entry.data['ip_address'].replace('.', '_')}")},
            "name": entry.data.get("name", "Stagg Kettle"),
            "manufacturer": "Fellow",
            "model": "Stagg EKG Pro",
        }

    @property
    def native_value(self):
        """Return the value of the number."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        int_value = int(value)
        # Format the command with '+' for spaces
        cmd = f"{self._command_prefix} {int_value}".replace(" ", "+")
        url = f"http://{self.coordinator.ip}/cli?cmd={cmd}"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to set number value for %s: %s", self._key, err)
