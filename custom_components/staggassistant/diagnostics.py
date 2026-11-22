"""Diagnostics support for StaggAssistant."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_WIFI_MAC,
)
from .coordinator import StaggConfigEntry

TO_REDACT: set[str] = {
    CONF_IP_ADDRESS,
    CONF_WIFI_MAC,
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_NAME,
    "title",
    "unique_id",
    "ssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StaggConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data

    payload: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": {
            "firmware_mode": coordinator.client.firmware_mode.value,
            "prtsettings_supported": coordinator.client.prtsettings_supported,
            "last_update_success": getattr(coordinator, "last_update_success", None),
        },
        "coordinator_data": coordinator.data,
    }
    return async_redact_data(payload, TO_REDACT)
