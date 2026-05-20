"""Support for Fellow Stagg EKG Pro selects."""
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink selects from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    selects = [
        StaggSelect(
            coordinator, entry, "clock_mode", "Clock Style",
            ["off", "digital", "analog"], "mdi:clock-outline",
            lambda val: "setsetting+clockmode+0" if val == "off" else ("setdigital" if val == "digital" else "setanalog")
        ),
        StaggSelect(
            coordinator, entry, "language", "Language Selection", 
            ["en", "fr", "es"], "mdi:translate",
            lambda val: f"setsetting language {['en', 'fr', 'es'].index(val)}"
        ),
        StaggSelect(
            coordinator, entry, "units", "Temperature Units",
            ["C", "F"], "mdi:thermometer",
            lambda val: "setunitsc" if val == "C" else "setunitsf"
        ),
        StaggSelect(
            coordinator, entry, "schedule_mode", "Schedule Mode",
            ["off", "once", "repeat"], "mdi:calendar-clock",
            lambda val: (
                "setsetting schedon 0" if val == "off"
                else "setsetting schedon 1" if val == "once"
                else "setsetting schedon 1"
            )
        ),
    ]

    async_add_entities(selects, True)

class StaggSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Stagg EKG Pro select configuration."""

    def __init__(self, coordinator, entry, key, name_suffix, options, icon, command_generator):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"{entry.data.get('name', 'Stagg Kettle')} {name_suffix}"
        self._attr_unique_id = f"stagg_{entry.data['ip_address'].replace('.', '_')}_{key}"
        self._attr_options = options
        self._attr_icon = icon
        self._command_generator = command_generator
        self._attr_has_entity_name = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"stagglink_{entry.data['ip_address'].replace('.', '_')}")},
            "name": entry.data.get("name", "Stagg Kettle"),
            "manufacturer": "Fellow",
            "model": "Stagg EKG Pro",
        }

    @property
    def current_option(self):
        """Return the current selected option."""
        if not self.coordinator.data:
            return None
        val = self.coordinator.data.get(self._key)
        
        if self._key == "clock_mode":
            # clockmode: 0=off, 1=digital, 2=analog
            try:
                idx = int(val)
                if idx == 0: return "off"
                if idx == 1: return "digital"
                return "analog"
            except (ValueError, TypeError):
                return "off"

        if self._key == "language":
            try:
                idx = int(val)
                if 0 <= idx < len(self._attr_options):
                    return self._attr_options[idx]
            except (ValueError, TypeError):
                pass

        if val in self._attr_options:
            return val

        return self._attr_options[0]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        raw_cmd = self._command_generator(option)
        cmd = raw_cmd.replace(" ", "+")
        url = f"http://{self.coordinator.ip}/cli?cmd={cmd}"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to select option %s for %s: %s", option, self._key, err)
