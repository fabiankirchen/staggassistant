"""Support for Fellow Stagg EKG Pro climate entity."""
import logging
import async_timeout
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, HVACAction, ClimateEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink climate platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StaggKettleClimate(coordinator, entry)], True)

class StaggKettleClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Stagg EKG Pro Kettle as a climate entity."""
    
    coordinator: StaggLinkCoordinator

    def __init__(self, coordinator, entry):
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._ip = entry.data["ip_address"]
        self._attr_name = entry.data.get("name", "Stagg Kettle")
        self._attr_unique_id = f"stagglink_{self._ip.replace('.', '_')}"
        self._attr_has_entity_name = True 
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self._attr_name,
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}"
        )

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_step = 0.5
        
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.TURN_OFF | 
            ClimateEntityFeature.TURN_ON
        )
        self._attr_min_temp = 40
        self._attr_max_temp = 100

    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        if not self.coordinator.data:
            return HVACMode.OFF
        return HVACMode.OFF if self.coordinator.data["mode"] == "S_Off" else HVACMode.HEAT

    @property
    def hvac_action(self):
        """Return the current running hvac operation."""
        if not self.coordinator.data:
            return HVACAction.IDLE
        mode = self.coordinator.data["mode"]
        if mode == "S_Off": 
            return HVACAction.OFF
        if "High" in mode or "Heat" in mode: 
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def icon(self):
        """Return dynamic icon based on state."""
        if self.hvac_action == HVACAction.HEATING:
            return "mdi:kettle-steam"
        return "mdi:kettle"

    @property
    def current_temperature(self): 
        """Return the current temperature."""
        if self.coordinator.data:
            return self.coordinator.data["temp"]
        return None

    @property
    def target_temperature(self): 
        """Return the temperature we try to reach."""
        if self.coordinator.data:
            return self.coordinator.data["target"]
        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self._send_command("ss+S_Off")
        elif hvac_mode == HVACMode.HEAT:
            await self._send_command("ss+S_Heat")
        
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp:
            # Convert Celsius to Fahrenheit for the API
            fahrenheit = int(temp * 1.8 + 32)
            
            # 1. Send temperature target
            await self._send_command(f"setsettingd+settempr+{fahrenheit}")
            
            # 2. Ensure the heating element turns on
            await self._send_command("ss+S_Heat")
            
            await self.coordinator.async_request_refresh()

    async def _send_command(self, cmd):
        """Send a command to the kettle CLI API."""
        url = f"http://{self._ip}/cli?cmd={cmd}"
        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(10):
                await session.get(url)
        except Exception as e:
             _LOGGER.error("Error sending command '%s': %s", cmd, e)
