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
            host = user_input[CONF_IP_ADDRESS]
            try:
                # Firmware 1.2.26+ serves the state as JSON at /temp
                response = await session.get(f"http://{host}/temp", timeout=5)
                text = await response.text() if response.status == 200 else ""
                looks_like_kettle = '"state"' in text or '"temp"' in text

                if not looks_like_kettle:
                    # Fallback: legacy text CLI (firmware < 1.2.26)
                    response = await session.get(f"http://{host}/cli?cmd=state", timeout=5)
                    text = await response.text() if response.status == 200 else ""
                    looks_like_kettle = "mode=" in text or "tempr=" in text

                if looks_like_kettle:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data=user_input
                    )
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_NAME, default="Stagg Kettle"): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }),
            errors=errors
        )
