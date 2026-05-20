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
        StaggSwitch(coordinator, entry, "pre_boil_enabled", "Pre-Boil", "mdi:water-boiler"),
        StaggSwitch(coordinator, entry, "chime_enabled", "Chime", "mdi:bell"),
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
        if self._setting_name == "hold_enabled":
            hold_time = self.coordinator.data.get("hold_time_minutes") or 30
            if hold_time <= 0:
                hold_time = 30
            cmd = f"setsetting hold {hold_time}"
        elif self._setting_name == "pre_boil_enabled":
            cmd = "setsetting boil 1"
        elif self._setting_name == "chime_enabled":
            cmd = "setsetting chime 5"
        elif self._setting_name == "schedule_enabled":
            cmd = "setsetting schedon 1"
        else:
            cmd = f"setsetting {self._setting_name} 1"

        url = f"http://{self.coordinator.ip}/cli?cmd={cmd.replace(' ', '+')}"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn on switch %s: %s", self._setting_name, err)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._setting_name == "hold_enabled":
            cmd = "setsetting hold 0"
        elif self._setting_name == "pre_boil_enabled":
            cmd = "setsetting boil 0"
        elif self._setting_name == "chime_enabled":
            cmd = "setsetting chime 0"
        elif self._setting_name == "schedule_enabled":
            cmd = "setsetting schedon 0"
        else:
            cmd = f"setsetting {self._setting_name} 0"

        url = f"http://{self.coordinator.ip}/cli?cmd={cmd.replace(' ', '+')}"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn off switch %s: %s", self._setting_name, err)
