from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, PLATFORMS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import StaggLinkCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup StaggAssistant über die UI."""
    
    # Intervall aus der Config lesen, oder Default nutzen falls fehlt
    interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    # Coordinator initialisieren
    coordinator = StaggLinkCoordinator(hass, entry.data["ip_address"], interval)
    await coordinator.async_config_entry_first_refresh()

    # Daten in HA speichern
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Plattformen (Climate) laden
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration entfernen."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, PLATFORMS[0])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
