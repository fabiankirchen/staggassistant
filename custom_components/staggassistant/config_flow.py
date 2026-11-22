"""Config flow and options flow for Fellow Stagg EKG Pro integration."""
from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_FIRMWARE_VERSION,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    clamp_scan_interval,
)
from .kettle_discovery import (
    KettleNetworkInfo,
    async_get_kettle_ble_device_map,
    async_resolve_kettle,
    async_validate_kettle,
    normalize_mac,
)

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant


def _looks_like_ip(value: str) -> bool:
    """Return True if a unique id looks like an IPv4 address."""
    try:
        return ipaddress.ip_address(value).version == 4
    except (TypeError, ValueError):
        return False


def _stable_id_from_ip(ip: str) -> str:
    """Return the legacy IP-derived stable identifier."""
    return ip.replace(".", "_")


def _stable_id_from_mac(mac: str | None, ip: str) -> str:
    """Return a stable identifier based on the Wi-Fi MAC when available."""
    if mac:
        return mac.replace(":", "_").lower()
    return _stable_id_from_ip(ip)


def _entry_conflicts(
    hass: HomeAssistant,
    ip: str | None = None,
    wifi_mac: str | None = None,
    ble_address: str | None = None,
    unique_id: str | None = None,
    exclude_entry_id: str | None = None,
) -> ConfigEntry[Any] | None:
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


def _build_updated_entry_data(
    entry: ConfigEntry[Any],
    ip: str,
    wifi_mac: str | None = None,
    ble_address: str | None = None,
    firmware: str | None = None,
) -> dict[str, Any]:
    """Build updated config entry data while preserving entity identity."""
    data = dict(entry.data or {})
    data[CONF_IP_ADDRESS] = ip
    if wifi_mac:
        data[CONF_WIFI_MAC] = wifi_mac
    if ble_address:
        data[CONF_BLE_ADDRESS] = ble_address
    if firmware:
        data[CONF_FIRMWARE_VERSION] = firmware
    if CONF_DEVICE_ID not in data:
        # Preserve the entity identity associated with the current entry.
        old_ip = (entry.data or {}).get(CONF_IP_ADDRESS) or ip
        data[CONF_DEVICE_ID] = _stable_id_from_ip(str(old_ip))
    return data


def _unique_id_for_update(
    entry: ConfigEntry[Any], fallback: str, wifi_mac: str | None
) -> str:
    """Choose a stable config-entry unique id while keeping MACs when known."""
    if wifi_mac:
        return wifi_mac
    current = entry.unique_id
    # Keep an existing non-IP unique id (for example a MAC).
    if current and not _looks_like_ip(str(current)):
        return str(current)
    return fallback


class StaggAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for StaggAssistant."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._discovered_kettle: KettleNetworkInfo | None = None
        if not hasattr(self, "context"):
            self.context: dict[str, Any] = {}

    async def _async_get_ble_scan_options_and_schema(
        self, errors: dict[str, str]
    ) -> tuple[dict[str, str], vol.Schema]:
        """Scan for kettle BLE devices and build the selector schema."""
        if errors:
            options = await async_get_kettle_ble_device_map(self.hass, retry_wait=0)
        else:
            options = await async_get_kettle_ble_device_map(self.hass)
            if not options:
                errors["base"] = "no_bluetooth_devices"

        schema = (
            vol.Schema({vol.Required(CONF_BLE_ADDRESS): vol.In(options)})
            if options
            else vol.Schema({})
        )
        return options, schema

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer Bluetooth discovery or manual IP entry."""
        # Keep accepting the old direct form shape for backwards compatibility.
        if user_input is not None and CONF_IP_ADDRESS in user_input:
            return await self.async_step_manual(user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=["bluetooth_scan", "manual"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual IP address or hostname setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            ip = str(user_input.get(CONF_IP_ADDRESS, "")).strip()
            error = await async_validate_kettle(self.hass, ip)
            if error in ("invalid_host", "invalid_ip"):
                errors[CONF_IP_ADDRESS] = "invalid_host"
            elif error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(ip)
                self._abort_if_unique_id_configured()
                if _entry_conflicts(self.hass, ip=ip):
                    return self.async_abort(reason="already_configured")

                raw_name = str(user_input.get(CONF_NAME) or "").strip()
                name = raw_name or "Stagg Kettle"
                scan_interval = clamp_scan_interval(
                    user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                )
                data: dict[str, Any] = {
                    CONF_IP_ADDRESS: ip,
                    CONF_NAME: name,
                    CONF_SCAN_INTERVAL: scan_interval,
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
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover and select a kettle over Bluetooth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = str(user_input.get(CONF_BLE_ADDRESS) or "").strip()
            if address:
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
                    data: dict[str, Any] = {
                        CONF_IP_ADDRESS: resolved.ip,
                        CONF_NAME: name,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_DEVICE_ID: _stable_id_from_mac(
                            resolved.wifi_mac, resolved.ip
                        ),
                        CONF_WIFI_MAC: resolved.wifi_mac,
                        CONF_BLE_ADDRESS: address,
                    }
                    if resolved.firmware:
                        data[CONF_FIRMWARE_VERSION] = resolved.firmware
                    return self.async_create_entry(title=name, data=data)

        options, schema = await self._async_get_ble_scan_options_and_schema(errors)
        return self.async_show_form(
            step_id="bluetooth_scan",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_count": str(len(options)),
            },
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a kettle discovered automatically by Home Assistant Bluetooth."""
        address = discovery_info.address
        name = getattr(discovery_info, "name", None) or "Stagg Kettle"

        resolved = await async_resolve_kettle(self.hass, address)
        if resolved is None:
            return self.async_abort(reason="cannot_resolve_ip")

        unique_id = resolved.wifi_mac or resolved.ip
        existing = _entry_conflicts(
            self.hass,
            ip=resolved.ip,
            wifi_mac=resolved.wifi_mac,
            ble_address=address,
            unique_id=unique_id,
        )
        if existing is not None:
            existing_data = existing.data or {}
            new_unique_id = _unique_id_for_update(
                existing, resolved.ip, resolved.wifi_mac
            )
            changed = (
                resolved.ip != existing_data.get(CONF_IP_ADDRESS)
                or (
                    bool(resolved.wifi_mac)
                    and resolved.wifi_mac != existing_data.get(CONF_WIFI_MAC)
                )
                or (bool(address) and address != existing_data.get(CONF_BLE_ADDRESS))
                or (
                    bool(resolved.firmware)
                    and resolved.firmware != existing_data.get(CONF_FIRMWARE_VERSION)
                )
                or new_unique_id != existing.unique_id
            )
            if changed:
                updated_data = _build_updated_entry_data(
                    existing,
                    resolved.ip,
                    wifi_mac=resolved.wifi_mac,
                    ble_address=address,
                    firmware=resolved.firmware,
                )
                self.hass.config_entries.async_update_entry(
                    existing,
                    data=updated_data,
                    unique_id=new_unique_id,
                )
                self.hass.config_entries.async_schedule_reload(existing.entry_id)
            return self.async_abort(reason="already_configured")

        self._discovered_kettle = resolved
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": resolved.name or name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm automatic Bluetooth discovery setup."""
        resolved = self._discovered_kettle
        if resolved is None:
            return self.async_abort(reason="cannot_resolve_ip")

        default_name = resolved.name or "Stagg Kettle"
        if user_input is not None:
            raw_name = str(user_input.get(CONF_NAME) or "").strip()
            name = raw_name or default_name
            scan_interval = clamp_scan_interval(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            data: dict[str, Any] = {
                CONF_IP_ADDRESS: resolved.ip,
                CONF_NAME: name,
                CONF_SCAN_INTERVAL: scan_interval,
                CONF_DEVICE_ID: _stable_id_from_mac(resolved.wifi_mac, resolved.ip),
                CONF_WIFI_MAC: resolved.wifi_mac,
                CONF_BLE_ADDRESS: resolved.ble_address,
            }
            if resolved.firmware:
                data[CONF_FIRMWARE_VERSION] = resolved.firmware
            return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=default_name): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
            description_placeholders={
                "name": default_name,
                "ip_address": resolved.ip,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer manual IP update or Bluetooth rediscovery for reconfiguration."""
        entry = self._get_reconfigure_entry()
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_manual", "reconfigure_bluetooth"],
            description_placeholders={
                "current_ip": str((entry.data or {}).get(CONF_IP_ADDRESS, "")),
            },
        )

    async def async_step_reconfigure_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure the kettle's IP address or hostname manually."""
        entry = self._get_reconfigure_entry()
        current_ip = str((entry.data or {}).get(CONF_IP_ADDRESS, ""))
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = str(user_input.get(CONF_IP_ADDRESS, "")).strip()
            error = await async_validate_kettle(self.hass, ip)
            if error in ("invalid_host", "invalid_ip"):
                errors[CONF_IP_ADDRESS] = "invalid_host"
            elif error:
                errors["base"] = error
            else:
                unique_id = _unique_id_for_update(
                    entry, ip, (entry.data or {}).get(CONF_WIFI_MAC)
                )
                if _entry_conflicts(
                    self.hass,
                    ip=ip,
                    unique_id=unique_id,
                    exclude_entry_id=entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    updated_data = _build_updated_entry_data(entry, ip)
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=updated_data,
                        unique_id=unique_id,
                    )

        return self.async_show_form(
            step_id="reconfigure_manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=current_ip): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure the kettle by rediscovering its IP over Bluetooth."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            address = str(user_input.get(CONF_BLE_ADDRESS) or "").strip()
            if address:
                resolved = await async_resolve_kettle(self.hass, address)
                if resolved is None:
                    errors["base"] = "cannot_resolve_ip"
                else:
                    unique_id = _unique_id_for_update(
                        entry, resolved.ip, resolved.wifi_mac
                    )
                    if _entry_conflicts(
                        self.hass,
                        ip=resolved.ip,
                        wifi_mac=resolved.wifi_mac,
                        ble_address=address,
                        unique_id=unique_id,
                        exclude_entry_id=entry.entry_id,
                    ):
                        errors["base"] = "already_configured"
                    else:
                        updated_data = _build_updated_entry_data(
                            entry,
                            resolved.ip,
                            wifi_mac=resolved.wifi_mac,
                            ble_address=address,
                            firmware=resolved.firmware,
                        )
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates=updated_data,
                            unique_id=unique_id,
                        )

        options, schema = await self._async_get_ble_scan_options_and_schema(errors)
        return self.async_show_form(
            step_id="reconfigure_bluetooth",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_count": str(len(options)),
                "current_ip": str((entry.data or {}).get(CONF_IP_ADDRESS, "")),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry[Any],
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return StaggAssistantOptionsFlow()


class StaggAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle StaggAssistant options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration polling interval."""
        if user_input is not None:
            scan_interval = clamp_scan_interval(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            return self.async_create_entry(
                title="",
                data={CONF_SCAN_INTERVAL: scan_interval},
            )

        current_interval = clamp_scan_interval(
            self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
