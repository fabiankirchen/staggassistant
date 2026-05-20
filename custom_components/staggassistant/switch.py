"""Support for Fellow Stagg EKG Pro switches."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink switches from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    switches = [
        StaggSwitch(coordinator, entry, "hold_enabled", "Hold Mode", "mdi:timer-pause"),
        StaggSwitch(coordinator, entry, "pre_boil_enabled", "Pre-Boil", "mdi:water-boiler"),
        StaggSwitch(coordinator, entry, "chime_enabled", "Chime", "mdi:bell"),
        StaggSwitch(coordinator, entry, "schedule_enabled", "Schedule", "mdi:calendar-clock"),
    ]
    
    async_add_entities(switches, True)

class StaggSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Stagg EKG Pro switch."""

    def __init__(self, coordinator, entry, setting_name, name_suffix, icon):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._setting_name = setting_name
        self._attr_name = f"{entry.data.get('name', 'Stagg Kettle')} {name_suffix}"
        self._attr_unique_id = f"stagg_{entry.data['ip_address'].replace('.', '_')}_{setting_name}"
        self._attr_icon = icon
        self._attr_has_entity_name = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"stagglink_{entry.data['ip_address'].replace('.', '_')}")},
            "name": entry.data.get("name", "Stagg Kettle"),
            "manufacturer": "Fellow",
            "model": "Stagg EKG Pro",
        }

    @property
    def is_on(self):
        """Return true if the switch is on."""
        if not self.coordinator.data:
            return False
        # The API returns 1 or 0 for enabled settings
        val = self.coordinator.data.get(self._setting_name)
        return val == 1 or val is True

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        url = f"http://{self.coordinator.ip}/cli?cmd=setsettingb+{self._setting_name}+1"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn on switch %s: %s", self._setting_name, err)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        url = f"http://{self.coordinator.ip}/cli?cmd=setsettingb+{self._setting_name}+0"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn off switch %s: %s", self._setting_name, err)
