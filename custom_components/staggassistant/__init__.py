"""Fellow Stagg EKG Pro Home Assistant Integration."""
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENABLE_EXTENDED_ENTITIES,
    CONF_SCAN_INTERVAL,
    CORE_PLATFORMS,
    DEFAULT_ENABLE_EXTENDED_ENTITIES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTENDED_PLATFORMS,
    PLATFORMS,
)
from .coordinator import StaggLinkCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up StaggAssistant from a config entry."""
    interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    coordinator = StaggLinkCoordinator(hass, entry.data["ip_address"], interval)
    await coordinator.async_load_saved_settings()
    await coordinator.async_config_entry_first_refresh()

    enable_extended = entry.options.get(
        CONF_ENABLE_EXTENDED_ENTITIES,
        entry.data.get(CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES),
    )
    platforms = list(CORE_PLATFORMS)
    if enable_extended:
        platforms.extend(EXTENDED_PLATFORMS)

    coordinator.loaded_platforms = set(platforms)
    coordinator.enable_extended_entities = enable_extended

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]

    new_extended = entry.options.get(
        CONF_ENABLE_EXTENDED_ENTITIES,
        entry.data.get(CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES),
    )
    current_extended = getattr(coordinator, "enable_extended_entities", DEFAULT_ENABLE_EXTENDED_ENTITIES)
    if new_extended != current_extended:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    new_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    coordinator.update_interval = timedelta(seconds=new_interval)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: StaggLinkCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    platforms = list(getattr(coordinator, "loaded_platforms", PLATFORMS)) if coordinator else PLATFORMS

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
