"""Repairs platform for StaggAssistant."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .config_flow import (
    _build_updated_entry_data,
    _entry_conflicts,
    _unique_id_for_update,
)
from .const import (
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_WIFI_MAC,
    ISSUE_KETTLE_UNREACHABLE_PREFIX,
)
from .kettle_discovery import async_validate_kettle

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult


class KettleUnreachableRepairFlow(RepairsFlow):
    """Handler for repairing an unreachable kettle by updating its IP/host."""

    def __init__(self, entry_id: str) -> None:
        """Initialize the repair flow for a specific config entry."""
        super().__init__()
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step of the repair flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt the user for an updated IP address or hostname."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_create_entry(data={})

        entry_data = entry.data or {}
        current_ip = str(entry_data.get(CONF_IP_ADDRESS, ""))
        entry_name = str(entry.title or entry_data.get(CONF_NAME, "Stagg Kettle"))
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
                    entry, ip, entry_data.get(CONF_WIFI_MAC)
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
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data=updated_data,
                        unique_id=unique_id,
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                    return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=current_ip): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "name": entry_name,
                "ip_address": current_ip,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repair flow for the given issue ID."""
    if issue_id.startswith(ISSUE_KETTLE_UNREACHABLE_PREFIX):
        raw_entry_id = (data or {}).get("entry_id")
        entry_id = (
            str(raw_entry_id)
            if raw_entry_id
            else issue_id.removeprefix(ISSUE_KETTLE_UNREACHABLE_PREFIX)
        )
        return KettleUnreachableRepairFlow(entry_id)
    return ConfirmRepairFlow()
