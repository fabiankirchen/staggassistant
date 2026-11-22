"""Tests for Gold-tier repair issues, translated UpdateFailed, and schema validation."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests  # noqa: F401 - installs Home Assistant test stubs
from tests import MockConfigEntry

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.staggassistant import async_remove_entry, async_unload_entry
from custom_components.staggassistant.api import (
    StaggConnectionError,
    StaggInvalidResponseError,
    StaggTimeoutError,
)
from custom_components.staggassistant.config_flow import (
    StaggAssistantConfigFlow,
    StaggAssistantOptionsFlow,
)
from custom_components.staggassistant.const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    ISSUE_KETTLE_UNREACHABLE_PREFIX,
    REPAIR_FAILURE_THRESHOLD,
)
from custom_components.staggassistant.coordinator import StaggLinkCoordinator
from custom_components.staggassistant.repairs import (
    KettleUnreachableRepairFlow,
    async_create_fix_flow,
)


class TestRepairIssuesAndTranslatedErrors(unittest.IsolatedAsyncioTestCase):
    """Test repair issue creation, clearing, fix flow, and UpdateFailed translations."""

    def setUp(self) -> None:
        ir.ISSUES.clear()

    def tearDown(self) -> None:
        ir.ISSUES.clear()

    def _entry(self, entry_id: str = "entry-repair-1") -> MockConfigEntry:
        return MockConfigEntry(
            entry_id=entry_id,
            unique_id="192.0.2.10",
            title="Kitchen Kettle",
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_NAME: "Kitchen Kettle",
                CONF_SCAN_INTERVAL: 15,
                CONF_DEVICE_ID: "192_0_2_10",
            },
        )

    async def test_repair_issue_created_after_threshold_and_cleared_on_recovery(
        self,
    ) -> None:
        """Issue appears after 5 consecutive failures and clears automatically on recovery."""
        entry = self._entry()
        coord = StaggLinkCoordinator(
            MagicMock(), "192.0.2.10", 15, storage_key="192_0_2_10", config_entry=entry
        )
        coord._settings_loaded = True
        coord.client.async_fetch_poll_payload = AsyncMock(
            side_effect=StaggTimeoutError("timeout", translation_key="timeout")
        )

        # Failures 1..(threshold - 1) must not create an issue yet
        for _ in range(REPAIR_FAILURE_THRESHOLD - 1):
            with self.assertRaises(UpdateFailed) as ctx:
                await coord._async_update_data()
            self.assertEqual(ctx.exception.translation_domain, DOMAIN)
            self.assertEqual(ctx.exception.translation_key, "timeout")
            self.assertEqual(ctx.exception.translation_placeholders, {"host": "192.0.2.10"})
            self.assertEqual(ir.ISSUES, {})

        # Threshold failure creates a fixable warning issue
        with self.assertRaises(UpdateFailed):
            await coord._async_update_data()

        issue_id = f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}{entry.entry_id}"
        self.assertIn((DOMAIN, issue_id), ir.ISSUES)
        issue = ir.ISSUES[(DOMAIN, issue_id)]
        self.assertTrue(issue["is_fixable"])
        self.assertFalse(issue["is_persistent"])
        self.assertEqual(issue["severity"], ir.IssueSeverity.WARNING)
        self.assertEqual(issue["translation_key"], "kettle_unreachable")
        self.assertEqual(
            issue["translation_placeholders"],
            {"name": "Kitchen Kettle", "ip_address": "192.0.2.10"},
        )
        self.assertEqual(issue["data"], {"entry_id": entry.entry_id})

        # Recovery poll deletes the repair issue and resets failure counter
        payload = MagicMock()
        payload.temp_data = {"state": "S_Off", "temp": 25.0, "temp_set": 93.0}
        payload.state_text = None
        payload.settings_text = ""
        coord.client.async_fetch_poll_payload = AsyncMock(return_value=payload)

        data = await coord._async_update_data()
        self.assertEqual(data["temp"], 25.0)
        self.assertEqual(ir.ISSUES, {})
        self.assertEqual(coord._consecutive_failures, 0)

    async def test_translated_update_failed_for_connection_and_invalid_response(
        self,
    ) -> None:
        """UpdateFailed raises translated exceptions for connection and response errors."""
        entry = self._entry()
        coord = StaggLinkCoordinator(
            MagicMock(), "192.0.2.10", 15, storage_key="192_0_2_10", config_entry=entry
        )
        coord._settings_loaded = True

        coord.client.async_fetch_poll_payload = AsyncMock(
            side_effect=StaggConnectionError("refused", translation_key="connection_error")
        )
        with self.assertRaises(UpdateFailed) as conn_ctx:
            await coord._async_update_data()
        self.assertEqual(conn_ctx.exception.translation_domain, DOMAIN)
        self.assertEqual(conn_ctx.exception.translation_key, "connection_error")
        self.assertEqual(
            conn_ctx.exception.translation_placeholders,
            {"host": "192.0.2.10", "error": "refused"},
        )

        coord.client.async_fetch_poll_payload = AsyncMock(
            side_effect=StaggInvalidResponseError("bad html")
        )
        with self.assertRaises(UpdateFailed) as resp_ctx:
            await coord._async_update_data()
        self.assertEqual(resp_ctx.exception.translation_domain, DOMAIN)
        self.assertEqual(resp_ctx.exception.translation_key, "invalid_response")
        self.assertEqual(
            resp_ctx.exception.translation_placeholders, {"error": "bad html"}
        )

    async def test_unload_and_remove_clean_up_repair_issues(self) -> None:
        """Unloading and removing a config entry deletes active repair issues."""
        entry = self._entry()
        coord = StaggLinkCoordinator(
            MagicMock(), "192.0.2.10", 15, storage_key="192_0_2_10", config_entry=entry
        )
        coord._settings_loaded = True
        coord.client.async_fetch_poll_payload = AsyncMock(
            side_effect=StaggTimeoutError("timeout")
        )
        for _ in range(REPAIR_FAILURE_THRESHOLD):
            with self.assertRaises(UpdateFailed):
                await coord._async_update_data()

        issue_id = f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}{entry.entry_id}"
        self.assertIn((DOMAIN, issue_id), ir.ISSUES)

        entry.runtime_data = coord
        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        await async_unload_entry(hass, entry)
        self.assertNotIn((DOMAIN, issue_id), ir.ISSUES)

        # Re-create issue to test async_remove_entry cleanup path directly
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            translation_key="kettle_unreachable",
            data={"entry_id": entry.entry_id},
        )
        with patch("custom_components.staggassistant.Store") as mock_store_cls:
            mock_store_cls.return_value.async_remove = AsyncMock()
            await async_remove_entry(hass, entry)
        self.assertNotIn((DOMAIN, issue_id), ir.ISSUES)

    async def test_repair_fix_flow_updates_ip_preserves_device_id_and_handles_errors(
        self,
    ) -> None:
        """KettleUnreachableRepairFlow validates input, prevents conflicts, and reloads."""
        entry = self._entry()
        other = MockConfigEntry(
            entry_id="entry-other",
            unique_id="192.0.2.99",
            data={CONF_IP_ADDRESS: "192.0.2.99"},
        )
        issue_id = f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}{entry.entry_id}"

        flow = await async_create_fix_flow(
            MagicMock(), issue_id, {"entry_id": entry.entry_id}
        )
        self.assertIsInstance(flow, KettleUnreachableRepairFlow)
        flow.hass.config_entries.async_get_entry.return_value = entry
        flow.hass.config_entries.async_entries.return_value = [entry, other]

        # Initial step shows confirm form with current IP
        form = await flow.async_step_init()
        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "confirm")
        self.assertEqual(
            form["description_placeholders"],
            {"name": "Kitchen Kettle", "ip_address": "192.0.2.10"},
        )

        # Invalid host error
        with patch(
            "custom_components.staggassistant.repairs.async_validate_kettle",
            AsyncMock(return_value="invalid_host"),
        ):
            bad_res = await flow.async_step_confirm({CONF_IP_ADDRESS: "127.0.0.1"})
        self.assertEqual(bad_res["errors"], {CONF_IP_ADDRESS: "invalid_host"})

        # Conflict error
        with patch(
            "custom_components.staggassistant.repairs.async_validate_kettle",
            AsyncMock(return_value=None),
        ):
            conflict_res = await flow.async_step_confirm(
                {CONF_IP_ADDRESS: "192.0.2.99"}
            )
        self.assertEqual(conflict_res["errors"], {"base": "already_configured"})

        # Valid new IP updates entry, preserves CONF_DEVICE_ID, and schedules reload
        with patch(
            "custom_components.staggassistant.repairs.async_validate_kettle",
            AsyncMock(return_value=None),
        ):
            ok_res = await flow.async_step_confirm({CONF_IP_ADDRESS: "192.0.2.50"})
        self.assertEqual(ok_res["type"], "create_entry")
        kwargs = flow.hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["data"][CONF_IP_ADDRESS], "192.0.2.50")
        self.assertEqual(kwargs["data"][CONF_DEVICE_ID], "192_0_2_10")
        self.assertEqual(kwargs["unique_id"], "192.0.2.50")
        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )

    async def test_repair_flow_missing_entry_and_unknown_issue_fallback(self) -> None:
        """Missing entry closes repair cleanly; unknown issue_id falls back to ConfirmRepairFlow."""
        flow = await async_create_fix_flow(
            MagicMock(), f"{ISSUE_KETTLE_UNREACHABLE_PREFIX}missing", None
        )
        flow.hass.config_entries.async_get_entry.return_value = None
        res = await flow.async_step_confirm()
        self.assertEqual(res["type"], "create_entry")

        fallback = await async_create_fix_flow(MagicMock(), "some_other_issue", None)
        self.assertIsInstance(fallback, ConfirmRepairFlow)


class TestRealSchemaValidation(unittest.IsolatedAsyncioTestCase):
    """Verify config/options flow schemas enforce bounds and required fields via voluptuous."""

    async def test_manual_and_options_schemas_validate_inputs(self) -> None:
        """Schemas reject missing fields or out-of-range scan intervals and accept valid ones."""
        config_flow = StaggAssistantConfigFlow()
        manual_form = await config_flow.async_step_manual()
        manual_schema = manual_form["data_schema"]

        with self.assertRaises(vol.Invalid):
            manual_schema({})
        with self.assertRaises(vol.Invalid):
            manual_schema({CONF_IP_ADDRESS: "192.0.2.10", CONF_SCAN_INTERVAL: 4})
        with self.assertRaises(vol.Invalid):
            manual_schema({CONF_IP_ADDRESS: "192.0.2.10", CONF_SCAN_INTERVAL: 121})

        parsed_manual = manual_schema({CONF_IP_ADDRESS: "192.0.2.10", CONF_SCAN_INTERVAL: "30"})
        self.assertEqual(parsed_manual[CONF_SCAN_INTERVAL], 30)
        self.assertEqual(parsed_manual[CONF_NAME], "Stagg Kettle")

        options_flow = StaggAssistantOptionsFlow()
        options_flow.config_entry = MockConfigEntry(data={CONF_IP_ADDRESS: "192.0.2.10"})
        options_form = await options_flow.async_step_init()
        options_schema = options_form["data_schema"]

        with self.assertRaises(vol.Invalid):
            options_schema({CONF_SCAN_INTERVAL: 2})
        with self.assertRaises(vol.Invalid):
            options_schema({CONF_SCAN_INTERVAL: 180})
        self.assertEqual(options_schema({CONF_SCAN_INTERVAL: "20"})[CONF_SCAN_INTERVAL], 20)


if __name__ == "__main__":
    unittest.main()
