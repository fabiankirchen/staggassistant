"""Support for Fellow Stagg EKG Pro switches."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink switches from a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]

    switches = [
        StaggSwitch(coordinator, entry, "pre_boil_enabled", "Pre-Boil", "mdi:water-boiler"),
    ]

    async_add_entities(switches, True)


class StaggSwitch(CoordinatorEntity[StaggLinkCoordinator], SwitchEntity):
    """Representation of a Stagg EKG Pro switch."""

    def __init__(self, coordinator: StaggLinkCoordinator, entry, setting_name: str, name_suffix: str, icon: str):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._setting_name = setting_name
        self._ip = entry.data["ip_address"]
        device_id = f"stagglink_{self._ip.replace('.', '_')}"

        self._attr_has_entity_name = True
        self._attr_translation_key = "pre_boil"
        self._attr_unique_id = f"stagg_{self._ip.replace('.', '_')}_{setting_name}"
        self._attr_icon = icon

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get("name", "Stagg Kettle"),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        if not self.coordinator.data:
            return False
        val = self.coordinator.data.get(self._setting_name)
        return val == 1 or val is True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the pre-boil switch on."""
        await self.coordinator.async_send_command("setsetting boil 1")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the pre-boil switch off."""
        await self.coordinator.async_send_command("setsetting boil 0")
        await self.coordinator.async_request_refresh()
