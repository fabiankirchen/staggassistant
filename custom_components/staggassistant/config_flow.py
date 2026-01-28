import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_IP_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL

class StaggAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            url = f"http://{user_input[CONF_IP_ADDRESS]}/cli?cmd=state"
            try:
                response = await session.get(url, timeout=5)
                if response.status == 200:
                    text = await response.text()
                    if "mode=" in text or "tempr=" in text:
                        return self.async_create_entry(
                            title=user_input[CONF_NAME], 
                            data=user_input
                        )
                    else:
                         errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_NAME, default="Stagg Kettle"): str,
                # Hier ist das neue Feld mit Default 15
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }),
            errors=errors
        )