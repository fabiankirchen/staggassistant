"""Config flow and options flow for Fellow Stagg EKG Pro integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_ENABLE_EXTENDED_ENTITIES,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
    DEFAULT_ENABLE_EXTENDED_ENTITIES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .kettle_discovery import (
    async_get_kettle_ble_device_map,
    async_resolve_kettle,
    async_validate_kettle,
    normalize_mac,
)


def _stable_id_from_ip(ip: str) -> str:
    """Return the legacy IP-derived stable identifier."""
    return ip.replace(".", "_")


def _stable_id_from_mac(mac: str | None, ip: str) -> str:
    """Return a stable identifier based on the Wi-Fi MAC when available."""
    if mac:
        return mac.replace(":", "_").lower()
    return _stable_id_from_ip(ip)


def _entry_conflicts(
    hass,
    ip: str | None = None,
    wifi_mac: str | None = None,
    ble_address: str | None = None,
    unique_id: str | None = None,
    exclude_entry_id: str | None = None,
):
    """Return an existing entry that already represents this kettle."""
    wifi_mac = normalize_mac(wifi_mac)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        if unique_id and entry.unique_id == unique_id:
            return entry
        data = entry.data or {}
        if ip and data.get(CONF_IP_ADDRESS) == ip:
            return entry
        if wifi_mac and normalize_mac(data.get(CONF_WIFI_MAC)) == wifi_mac:
            return entry
        if wifi_mac and data.get(CONF_DEVICE_ID) == wifi_mac.replace(":", "_").lower():
            return entry
        if ble_address and data.get(CONF_BLE_ADDRESS) == ble_address:
            return entry
    return None


class StaggAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for StaggAssistant."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Offer Bluetooth discovery or manual IP entry."""
        # Keep accepting the old direct form shape for backwards compatibility
        # (and for users who submit an IP without going through the menu).
        if user_input is not None and CONF_IP_ADDRESS in user_input:
            return await self.async_step_manual(user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=["bluetooth", "manual"],
        )

    async def async_step_manual(self, user_input=None):
        """Handle manual IP address setup."""
        errors = {}
        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS].strip()
            error = await async_validate_kettle(self.hass, ip)
            if error == "invalid_ip":
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            elif error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(ip)
                self._abort_if_unique_id_configured()
                if _entry_conflicts(self.hass, ip=ip):
                    return self.async_abort(reason="already_configured")

                name = user_input.get(CONF_NAME, "Stagg Kettle")
                data = {
                    CONF_IP_ADDRESS: ip,
                    CONF_NAME: name,
                    CONF_SCAN_INTERVAL: user_input.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                    CONF_DEVICE_ID: _stable_id_from_ip(ip),
                }
                return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS): str,
                    vol.Optional(CONF_NAME, default="Stagg Kettle"): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(self, user_input=None):
        """Discover and select a kettle over Bluetooth."""
        errors = {}
        options = {}

        if user_input is not None:
            address = (user_input.get(CONF_BLE_ADDRESS) or "").strip()
            if not address:
                errors["base"] = "no_bluetooth_devices"
            else:
                resolved = await async_resolve_kettle(self.hass, address)
                if resolved is None:
                    errors["base"] = "cannot_resolve_ip"
                else:
                    unique_id = resolved.wifi_mac or resolved.ip
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    if _entry_conflicts(
                        self.hass,
                        ip=resolved.ip,
                        wifi_mac=resolved.wifi_mac,
                        ble_address=address,
                        unique_id=unique_id,
                    ):
                        return self.async_abort(reason="already_configured")

                    name = resolved.name or "Stagg Kettle"
                    data = {
                        CONF_IP_ADDRESS: resolved.ip,
                        CONF_NAME: name,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_DEVICE_ID: _stable_id_from_mac(
                            resolved.wifi_mac, resolved.ip
                        ),
                        CONF_WIFI_MAC: resolved.wifi_mac,
                        CONF_BLE_ADDRESS: address,
                    }
                    return self.async_create_entry(title=name, data=data)

        if not errors:
            options = await async_get_kettle_ble_device_map(self.hass)
        if not options and not errors:
            errors["base"] = "no_bluetooth_devices"

        if options:
            address_field = vol.Required(CONF_BLE_ADDRESS)
            address_validator = vol.In(options)
        else:
            address_field = vol.Optional(CONF_BLE_ADDRESS, default="")
            address_validator = str

        return self.async_show_form(
            step_id="bluetooth",
            data_schema=vol.Schema(
                {
                    address_field: address_validator,
                }
            ),
            errors=errors,
            description_placeholders={
                "device_count": str(len(options)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return StaggAssistantOptionsFlow()


class StaggAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle StaggAssistant options."""

    async def async_step_init(self, user_input=None):
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "bluetooth"],
        )

    def _current_options(self) -> dict:
        """Return the current option values (including data fallbacks)."""
        return {
            CONF_SCAN_INTERVAL: self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            ),
            CONF_ENABLE_EXTENDED_ENTITIES: self.config_entry.options.get(
                CONF_ENABLE_EXTENDED_ENTITIES,
                self.config_entry.data.get(
                    CONF_ENABLE_EXTENDED_ENTITIES,
                    DEFAULT_ENABLE_EXTENDED_ENTITIES,
                ),
            ),
        }

    def _updated_entry_data(
        self,
        ip: str,
        wifi_mac: str | None = None,
        ble_address: str | None = None,
    ) -> dict:
        """Build updated config entry data without changing entity identity."""
        data = dict(self.config_entry.data)
        data[CONF_IP_ADDRESS] = ip
        if wifi_mac:
            data[CONF_WIFI_MAC] = wifi_mac
        if ble_address:
            data[CONF_BLE_ADDRESS] = ble_address
        if CONF_DEVICE_ID not in data:
            # Preserve the entity identity associated with the current entry.
            old_ip = self.config_entry.data.get(CONF_IP_ADDRESS) or ip
            data[CONF_DEVICE_ID] = _stable_id_from_ip(old_ip)
        return data

    def _unique_id_for_update(self, fallback: str, wifi_mac: str | None) -> str:
        """Choose a stable config-entry unique id while keeping MACs when known."""
        if wifi_mac:
            return wifi_mac
        current = self.config_entry.unique_id
        # Keep an existing non-IP unique id (for example a MAC).
        if current and not _looks_like_ip(current):
            return current
        return fallback

    async def async_step_settings(self, user_input=None):
        """Manage polling interval, extended entities and the IP address."""
        errors = {}
        current_ip = self.config_entry.data.get(CONF_IP_ADDRESS, "")
        current_options = self._current_options()

        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS].strip()
            options_data = {
                CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                CONF_ENABLE_EXTENDED_ENTITIES: user_input[
                    CONF_ENABLE_EXTENDED_ENTITIES
                ],
            }

            if ip == current_ip:
                # Settings-only change: do not require the kettle to be online.
                return self.async_create_entry(title="", data=options_data)

            error = await async_validate_kettle(self.hass, ip)
            if error == "invalid_ip":
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            elif error:
                errors["base"] = error
            else:
                unique_id = self._unique_id_for_update(
                    ip, self.config_entry.data.get(CONF_WIFI_MAC)
                )
                if _entry_conflicts(
                    self.hass,
                    ip=ip,
                    unique_id=unique_id,
                    exclude_entry_id=self.config_entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=self._updated_entry_data(ip),
                        unique_id=unique_id,
                    )
                    return self.async_create_entry(title="", data=options_data)

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=current_ip): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=current_options[CONF_SCAN_INTERVAL],
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                    vol.Optional(
                        CONF_ENABLE_EXTENDED_ENTITIES,
                        default=current_options[CONF_ENABLE_EXTENDED_ENTITIES],
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(self, user_input=None):
        """Find the kettle's current IP over Bluetooth and update the entry."""
        errors = {}
        options = {}

        if user_input is not None:
            address = (user_input.get(CONF_BLE_ADDRESS) or "").strip()
            if not address:
                errors["base"] = "no_bluetooth_devices"
            else:
                resolved = await async_resolve_kettle(self.hass, address)
                if resolved is None:
                    errors["base"] = "cannot_resolve_ip"
                else:
                    unique_id = self._unique_id_for_update(
                        resolved.ip, resolved.wifi_mac
                    )
                    if _entry_conflicts(
                        self.hass,
                        ip=resolved.ip,
                        wifi_mac=resolved.wifi_mac,
                        ble_address=address,
                        unique_id=unique_id,
                        exclude_entry_id=self.config_entry.entry_id,
                    ):
                        errors["base"] = "already_configured"
                    else:
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data=self._updated_entry_data(
                                resolved.ip,
                                wifi_mac=resolved.wifi_mac,
                                ble_address=address,
                            ),
                            unique_id=unique_id,
                        )
                        return self.async_create_entry(
                            title="", data=self._current_options()
                        )

        if not errors:
            options = await async_get_kettle_ble_device_map(self.hass)
        if not options and not errors:
            errors["base"] = "no_bluetooth_devices"

        if options:
            address_field = vol.Required(CONF_BLE_ADDRESS)
            address_validator = vol.In(options)
        else:
            address_field = vol.Optional(CONF_BLE_ADDRESS, default="")
            address_validator = str

        return self.async_show_form(
            step_id="bluetooth",
            data_schema=vol.Schema(
                {
                    address_field: address_validator,
                }
            ),
            errors=errors,
            description_placeholders={
                "device_count": str(len(options)),
                "current_ip": self.config_entry.data.get(CONF_IP_ADDRESS, ""),
            },
        )


def _looks_like_ip(value: str) -> bool:
    """Return True if a unique id looks like an IPv4 address."""
    try:
        import ipaddress

        return ipaddress.ip_address(value).version == 4
    except (TypeError, ValueError):
        return False
