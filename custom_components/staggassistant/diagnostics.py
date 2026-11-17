"""Diagnostics support for StaggAssistant."""
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
    DOMAIN,
)
from .coordinator import StaggLinkCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "title": entry.title,
            "name": entry.data.get(CONF_NAME),
            "ip_address": entry.data.get(CONF_IP_ADDRESS),
            "wifi_mac": entry.data.get(CONF_WIFI_MAC),
            "ble_address": entry.data.get(CONF_BLE_ADDRESS),
            "device_id": entry.data.get(CONF_DEVICE_ID),
            "scan_interval": entry.options.get(
                CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL)
            ),
        },
        "coordinator_data": coordinator.data,
    }
