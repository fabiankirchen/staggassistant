"""Base entity class for StaggAssistant."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_NAME,
    CONF_WIFI_MAC,
    DOMAIN,
    get_device_identifier,
)
from .coordinator import StaggLinkCoordinator


class StaggEntity(CoordinatorEntity[StaggLinkCoordinator]):
    """Shared base entity providing device metadata for all Stagg platforms."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: ConfigEntry[Any],
    ) -> None:
        """Initialize the base Stagg entity."""
        super().__init__(coordinator)
        self._ip = coordinator.ip

        device_info = DeviceInfo(
            identifiers={(DOMAIN, get_device_identifier(entry))},
            name=str(entry.data.get(CONF_NAME, "Stagg Kettle")),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{coordinator.ip}",
        )
        if fw := entry.data.get(CONF_FIRMWARE_VERSION):
            device_info["sw_version"] = str(fw)
        if mac := entry.data.get(CONF_WIFI_MAC):
            device_info["connections"] = {(CONNECTION_NETWORK_MAC, str(mac))}

        self._attr_device_info = device_info
