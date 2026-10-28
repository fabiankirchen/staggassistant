"""Diagnostics support for StaggAssistant."""
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_NAME, CONF_SCAN_INTERVAL, DOMAIN
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
            "scan_interval": entry.options.get(
                CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL)
            ),
        },
        "coordinator_data": coordinator.data,
    }
