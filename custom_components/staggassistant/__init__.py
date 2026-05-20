from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from .const import DOMAIN, PLATFORMS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import StaggLinkCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup StaggAssistant über die UI."""
    
    # Prune obsolete entities from the registry
    ent_reg = er.async_get(hass)
    obsolete_entities = [
        "switch.stagg_kettle_ekg_pro_hold_mode",
        "switch.stagg_kettle_ekg_pro_chime",
        "switch.stagg_kettle_ekg_pro_schedule",
        "select.stagg_kettle_ekg_pro_volume_level",
        "sensor.stagg_kettle_ekg_pro_hold_time",
        "sensor.stagg_kettle_ekg_pro_altitude",
        "sensor.stagg_kettle_ekg_pro_language",
        "sensor.stagg_kettle_ekg_pro_chime_volume",
        "sensor.stagg_kettle_ekg_pro_clock_mode",
        "sensor.stagg_kettle_ekg_pro_temperature_units",
        "sensor.stagg_kettle_ekg_pro_schedule_mode",
    ]
    for entity_id in obsolete_entities:
        # The entity_id might have variations based on the name, so we check the unique_id if possible,
        # but since we want to prune the specific unavailable ones:
        if ent_reg.async_get(entity_id):
            ent_reg.async_remove(entity_id)

    # Intervall aus der Config lesen, oder Default nutzen falls fehlt
    interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    # Coordinator initialisieren
    coordinator = StaggLinkCoordinator(hass, entry.data["ip_address"], interval)
    await coordinator.async_config_entry_first_refresh()

    # Daten in HA speichern
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Plattformen laden
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration entfernen."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
