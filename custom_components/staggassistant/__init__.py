"""Fellow Stagg EKG Pro Home Assistant Integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ISSUE_KETTLE_UNREACHABLE_PREFIX,
    PLATFORMS,
    clamp_scan_interval,
    get_stable_id,
)
from .coordinator import StaggConfigEntry, StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "StaggConfigEntry",
    "_ensure_stable_id",
    "async_remove_entry",
    "async_setup_entry",
    "async_unload_entry",
    "async_update_listener",
]


def _ensure_stable_id(hass: HomeAssistant, entry: ConfigEntry[Any]) -> str:
    """Persist a stable entity identity for entries created before it existed."""
    stable_id = entry.data.get(CONF_DEVICE_ID)
    if stable_id:
        return str(stable_id)

    stable_id = str(entry.data[CONF_IP_ADDRESS]).replace(".", "_")
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_DEVICE_ID: stable_id},
    )
    return stable_id


async def async_setup_entry(hass: HomeAssistant, entry: StaggConfigEntry) -> bool:
    """Set up StaggAssistant from a config entry."""
    interval = clamp_scan_interval(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )
    stable_id = _ensure_stable_id(hass, entry)

    coordinator = StaggLinkCoordinator(
        hass,
        entry.data[CONF_IP_ADDRESS],
        interval,
        storage_key=stable_id,
        config_entry=entry,
    )
    await coordinator.async_load_saved_settings()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_update_listener(hass: HomeAssistant, entry: StaggConfigEntry) -> None:
    """Handle config entry updates."""
    coordinator = entry.runtime_data

    new_ip = entry.data.get(CONF_IP_ADDRESS)
    if new_ip and new_ip != coordinator.ip:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    new_interval = clamp_scan_interval(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )
    coordinator.update_interval = timedelta(seconds=new_interval)


async def async_unload_entry(hass: HomeAssistant, entry: StaggConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data.async_clear_repair_issue()
        await entry.runtime_data.async_flush_store()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
    """Clean up persisted storage files and issues when a config entry is removed."""
    ir.async_delete_issue(
        hass, DOMAIN, f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}{entry.entry_id}"
    )
    keys: set[str] = {get_stable_id(entry)}
    legacy_key = str(entry.data.get(CONF_IP_ADDRESS, "")).replace(".", "_")
    if legacy_key:
        keys.add(legacy_key)

    for key in keys:
        if not key:
            continue
        try:
            await Store(hass, 1, f"staggassistant_{key}").async_remove()
        except Exception as err:
            _LOGGER.debug("Could not remove storage for key %s: %s", key, err)
