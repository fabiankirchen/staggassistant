"""Config flow and options flow for Fellow Stagg EKG Pro integration."""
import asyncio
import ipaddress
import json
import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ENABLE_EXTENDED_ENTITIES,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLE_EXTENDED_ENTITIES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _is_valid_host(host: str) -> bool:
    """Validate if string is a valid IPv4 address or hostname."""
    if not host or any(c in host for c in ("/", "?", "#", "@", " ", "\t", "\n", "\r", ":")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.version == 4
    except ValueError:
        pass
    if len(host) > 253:
        return False
    hostname_regex = re.compile(
        r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
    )
    return bool(hostname_regex.match(host))


async def _read_response_text(response, limit: int = 65536) -> str:
    """Read response text up to byte limit safely."""
    if hasattr(response, "read"):
        raw = await response.read()
        if isinstance(raw, bytes):
            return raw[:limit].decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw[:limit]
    if hasattr(response, "text"):
        txt = await response.text()
        return txt[:limit]
    return ""


class StaggAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for StaggAssistant."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}
        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS].strip()

            if not _is_valid_host(ip):
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            else:
                # Guard against duplicate entries for the same device IP
                await self.async_set_unique_id(ip)
                self._abort_if_unique_id_configured()

                session = async_get_clientsession(self.hass)
                connected = False
                try:
                    # 1. Try modern /temp JSON endpoint (Firmware 1.2.26+)
                    temp_url = f"http://{ip}/temp"
                    try:
                        async with asyncio.timeout(5):
                            async with session.get(temp_url) as response:
                                if response.status == 200:
                                    raw_text = await _read_response_text(response, 65536)
                                    sanitized = re.sub(r':\s*[-+]?nan\b', ': null', raw_text, flags=re.IGNORECASE)
                                    data = json.loads(sanitized)
                                    if isinstance(data, dict) and "temp" in data and (
                                        "state" in data or "temp_set" in data
                                    ):
                                        connected = True
                    except (asyncio.TimeoutError, Exception):
                        connected = False

                    # 2. Fall back to /cli?cmd=state (Legacy firmware)
                    if not connected:
                        cli_url = f"http://{ip}/cli?cmd=state"
                        async with asyncio.timeout(5):
                            async with session.get(cli_url) as response:
                                if response.status == 200:
                                    text = await _read_response_text(response, 65536)
                                    if "mode=" in text or "tempr=" in text:
                                        connected = True
                                    else:
                                        errors["base"] = "invalid_auth"
                                else:
                                    errors["base"] = "cannot_connect"

                    if connected:
                        return self.async_create_entry(
                            title=user_input.get(CONF_NAME, "Stagg Kettle"),
                            data=user_input,
                        )
                    elif "base" not in errors:
                        errors["base"] = "cannot_connect"
                except (asyncio.TimeoutError, Exception):
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_NAME, default="Stagg Kettle"): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=120)
                ),
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return StaggAssistantOptionsFlow()


class StaggAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle StaggAssistant options."""

    async def async_step_init(self, user_input=None):
        """Manage integration options (e.g. polling interval)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_extended = self.config_entry.options.get(
            CONF_ENABLE_EXTENDED_ENTITIES,
            self.config_entry.data.get(
                CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES
            ),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=120)
                ),
                vol.Optional(CONF_ENABLE_EXTENDED_ENTITIES, default=current_extended): bool,
            }),
        )
