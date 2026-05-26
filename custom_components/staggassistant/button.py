"""Support for Fellow Stagg EKG Pro buttons."""
import logging
import asyncio
from datetime import datetime
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink buttons from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    buttons = [
        StaggButton(coordinator, entry, "press_button_2", "Press Main Button", "mdi:knob", "2"),
        StaggButton(coordinator, entry, "press_button_1", "Press Menu Button", "mdi:menu", "1"),
        StaggButton(coordinator, entry, "rotate_left", "Rotate Dial Left", "mdi:rotate-left", "q"),
        StaggButton(coordinator, entry, "rotate_right", "Rotate Dial Right", "mdi:rotate-right", "w"),
        StaggButton(coordinator, entry, "long_press_2", "Start Timer", "mdi:timer-play", "_long_press_2"),
        StaggButton(coordinator, entry, "sync_time", "Sync Time", "mdi:clock-check-outline", "_sync_time"),
        StaggButton(coordinator, entry, "reload_data", "Reload Data", "mdi:refresh", "_reload"),
    ]

    async_add_entities(buttons, True)

class StaggButton(CoordinatorEntity, ButtonEntity):
    """Representation of a Stagg EKG Pro action button."""

    def __init__(self, coordinator, entry, key, name_suffix, icon, command):
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"{entry.data.get('name', 'Stagg Kettle')} {name_suffix}"
        self._attr_unique_id = f"stagg_{entry.data['ip_address'].replace('.', '_')}_{key}"
        self._attr_icon = icon
        self._command = command
        self._attr_has_entity_name = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"stagglink_{entry.data['ip_address'].replace('.', '_')}")},
            "name": entry.data.get("name", "Stagg Kettle"),
            "manufacturer": "Fellow",
            "model": "Stagg EKG Pro",
        }

    async def async_press(self) -> None:
        """Trigger the command when the button is pressed."""
        if self._command == "_reload":
            await self.coordinator.async_request_refresh()
            return

        if self._command == "_long_press_2":
            # Hold main dial button (Button A)
            try:
                await self.coordinator.session.get(f"http://{self.coordinator.ip}/cli?cmd=2d")
                # Wait for 2 seconds to simulate long press
                await asyncio.sleep(2)
                # Release button
                await self.coordinator.session.get(f"http://{self.coordinator.ip}/cli?cmd=2u")
                await self.coordinator.async_request_refresh()
            except Exception as err:
                _LOGGER.error("Failed to execute long press for %s: %s", self._key, err)
            return

        if self._command == "_sync_time":
            now = datetime.now()
            cmd = f"setclock+{now.hour}+{now.minute}"
        else:
            cmd = self._command

        url = f"http://{self.coordinator.ip}/cli?cmd={cmd}"
        try:
            async with self.coordinator.session.get(url) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to execute button command %s for %s: %s", self._command, self._key, err)

