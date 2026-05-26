from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, PLATFORMS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import StaggLinkCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up StaggAssistant from a config entry."""
    
    # Get scan interval from config entry, fallback to default if missing
    interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    # Initialize the data coordinator
    coordinator = StaggLinkCoordinator(hass, entry.data["ip_address"], interval)
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator instance in hass data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Forward the setup to all defined platforms (climate, sensor, switch, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
