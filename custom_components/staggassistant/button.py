"""Support for Fellow Stagg EKG Pro buttons."""
import asyncio
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink buttons from a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]

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


class StaggButton(CoordinatorEntity[StaggLinkCoordinator], ButtonEntity):
    """Representation of a Stagg EKG Pro action button."""

    def __init__(self, coordinator: StaggLinkCoordinator, entry, key: str, name_suffix: str, icon: str, command: str):
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._key = key
        self._ip = entry.data["ip_address"]
        device_id = f"stagglink_{self._ip.replace('.', '_')}"

        self._attr_has_entity_name = True
        self._attr_translation_key = key
        self._attr_unique_id = f"stagg_{self._ip.replace('.', '_')}_{key}"
        self._attr_icon = icon
        self._command = command

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get("name", "Stagg Kettle"),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}",
        )

    async def async_press(self) -> None:
        """Trigger the command when the button is pressed."""
        if self._command == "_reload":
            await self.coordinator.async_request_refresh()
            return

        if self._command == "_long_press_2":
            # Hold main dial button for 2 seconds to trigger brew timer
            try:
                await self.coordinator.async_send_command("2d")
                await asyncio.sleep(2)
            finally:
                await self.coordinator.async_send_command("2u")
            await self.coordinator.async_request_refresh()
            return

        if self._command == "_sync_time":
            now = dt_util.now()
            cmd = f"setclock {now.hour} {now.minute} {now.second}"
        else:
            cmd = self._command

        await self.coordinator.async_send_command(cmd)
        await self.coordinator.async_request_refresh()
