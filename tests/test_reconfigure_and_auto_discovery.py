"""Tests for ReconfigureFlow, automatic Bluetooth discovery, and host validation."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests  # noqa: F401 - installs Home Assistant test stubs
from tests import MockConfigEntry

from custom_components.staggassistant.config_flow import StaggAssistantConfigFlow
from custom_components.staggassistant.const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_FIRMWARE_VERSION,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
)
from custom_components.staggassistant.kettle_discovery import (
    KettleNetworkInfo,
    async_validate_kettle,
)


def _make_response(status: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.content = MagicMock()
    resp.content.read = AsyncMock(return_value=text.encode("utf-8"))
    resp.read = AsyncMock(return_value=text.encode("utf-8"))
    resp.text = AsyncMock(return_value=text)
    return resp


class TestReconfigureFlow(unittest.IsolatedAsyncioTestCase):
    """Test ReconfigureFlow manual and Bluetooth paths."""

    def _make_entry(self) -> MockConfigEntry:
        return MockConfigEntry(
            entry_id="entry-1",
            unique_id="192.0.2.10",
            title="Stagg Kettle",
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_NAME: "Stagg Kettle",
                CONF_SCAN_INTERVAL: 15,
                CONF_DEVICE_ID: "192_0_2_10",
            },
        )

    async def test_reconfigure_menu_shows_manual_and_bluetooth(self) -> None:
        """Reconfigure step shows menu with current IP placeholder."""
        entry = self._make_entry()
        flow = StaggAssistantConfigFlow()
        flow._reconfigure_entry = entry

        res = await flow.async_step_reconfigure()

        self.assertEqual(res["type"], "menu")
        self.assertEqual(res["step_id"], "reconfigure")
        self.assertEqual(
            res["menu_options"], ["reconfigure_manual", "reconfigure_bluetooth"]
        )
        self.assertEqual(res["description_placeholders"]["current_ip"], "192.0.2.10")

    async def test_reconfigure_manual_preserves_device_id_and_reloads(self) -> None:
        """Manual reconfigure updates IP while keeping CONF_DEVICE_ID stable."""
        entry = self._make_entry()
        flow = StaggAssistantConfigFlow()
        flow._reconfigure_entry = entry
        flow.hass.config_entries.async_entries.return_value = [entry]

        with patch(
            "custom_components.staggassistant.config_flow.async_validate_kettle",
            AsyncMock(return_value=None),
        ):
            res = await flow.async_step_reconfigure_manual(
                {CONF_IP_ADDRESS: "192.0.2.55"}
            )

        self.assertEqual(res["type"], "abort")
        self.assertEqual(res["reason"], "reconfigure_successful")
        self.assertEqual(res["data_updates"][CONF_IP_ADDRESS], "192.0.2.55")
        self.assertEqual(res["data_updates"][CONF_DEVICE_ID], "192_0_2_10")
        self.assertEqual(res["unique_id"], "192.0.2.55")
        flow.hass.config_entries.async_update_entry.assert_called_once()
        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(
            "entry-1"
        )

    async def test_reconfigure_manual_rejects_invalid_host_and_conflicts(self) -> None:
        """Manual reconfigure reports invalid_host and already_configured errors."""
        entry = self._make_entry()
        other = MockConfigEntry(
            entry_id="entry-2",
            unique_id="192.0.2.99",
            data={CONF_IP_ADDRESS: "192.0.2.99"},
        )
        flow = StaggAssistantConfigFlow()
        flow._reconfigure_entry = entry
        flow.hass.config_entries.async_entries.return_value = [entry, other]

        with patch(
            "custom_components.staggassistant.config_flow.async_validate_kettle",
            AsyncMock(return_value="invalid_host"),
        ):
            bad = await flow.async_step_reconfigure_manual({CONF_IP_ADDRESS: "127.0.0.1"})
        self.assertEqual(bad["type"], "form")
        self.assertEqual(bad["errors"], {CONF_IP_ADDRESS: "invalid_host"})

        with patch(
            "custom_components.staggassistant.config_flow.async_validate_kettle",
            AsyncMock(return_value=None),
        ):
            conflict = await flow.async_step_reconfigure_manual(
                {CONF_IP_ADDRESS: "192.0.2.99"}
            )
        self.assertEqual(conflict["type"], "form")
        self.assertEqual(conflict["errors"], {"base": "already_configured"})

    async def test_reconfigure_bluetooth_updates_ip_mac_and_firmware(self) -> None:
        """Bluetooth reconfigure updates IP, Wi-Fi MAC, BLE address, and firmware."""
        entry = self._make_entry()
        flow = StaggAssistantConfigFlow()
        flow._reconfigure_entry = entry
        flow.hass.config_entries.async_entries.return_value = [entry]

        resolved = KettleNetworkInfo(
            ip="192.0.2.77",
            wifi_mac="02:00:00:aa:bb:cc",
            ble_address="02:00:00:00:00:0E",
            name="EKG-aa-bb-cc",
            firmware="1.2.26",
            method="bluetooth",
        )
        with patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=resolved),
        ):
            res = await flow.async_step_reconfigure_bluetooth(
                {CONF_BLE_ADDRESS: "02:00:00:00:00:0E"}
            )

        self.assertEqual(res["type"], "abort")
        self.assertEqual(res["reason"], "reconfigure_successful")
        self.assertEqual(res["data_updates"][CONF_IP_ADDRESS], "192.0.2.77")
        self.assertEqual(res["data_updates"][CONF_WIFI_MAC], "02:00:00:aa:bb:cc")
        self.assertEqual(res["data_updates"][CONF_BLE_ADDRESS], "02:00:00:00:00:0E")
        self.assertEqual(res["data_updates"][CONF_FIRMWARE_VERSION], "1.2.26")
        self.assertEqual(res["data_updates"][CONF_DEVICE_ID], "192_0_2_10")
        self.assertEqual(res["unique_id"], "02:00:00:aa:bb:cc")


class TestAutomaticBluetoothDiscovery(unittest.IsolatedAsyncioTestCase):
    """Test automatic HA Bluetooth discovery and discovery-update-info."""

    async def test_auto_discovery_new_kettle_confirm_creates_entry(self) -> None:
        """Unconfigured BLE kettle proceeds to bluetooth_confirm and stores firmware."""
        flow = StaggAssistantConfigFlow()
        flow.hass.config_entries.async_entries.return_value = []

        discovery_info = MagicMock()
        discovery_info.address = "02:00:00:00:00:0E"
        discovery_info.name = "EKG-aa-bb-cc"

        resolved = KettleNetworkInfo(
            ip="192.0.2.15",
            wifi_mac="02:00:00:aa:bb:cc",
            ble_address="02:00:00:00:00:0E",
            name="EKG-aa-bb-cc",
            firmware="1.2.26",
            method="bluetooth",
        )
        with patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=resolved),
        ):
            confirm_form = await flow.async_step_bluetooth(discovery_info)

        self.assertEqual(confirm_form["type"], "form")
        self.assertEqual(confirm_form["step_id"], "bluetooth_confirm")
        self.assertEqual(confirm_form["description_placeholders"]["ip_address"], "192.0.2.15")
        self.assertEqual(flow.context["title_placeholders"], {"name": "EKG-aa-bb-cc"})

        created = await flow.async_step_bluetooth_confirm(
            {CONF_NAME: "Kitchen Kettle", CONF_SCAN_INTERVAL: 2}
        )
        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["title"], "Kitchen Kettle")
        self.assertEqual(created["data"][CONF_IP_ADDRESS], "192.0.2.15")
        self.assertEqual(created["data"][CONF_SCAN_INTERVAL], 5)
        self.assertEqual(created["data"][CONF_WIFI_MAC], "02:00:00:aa:bb:cc")
        self.assertEqual(created["data"][CONF_FIRMWARE_VERSION], "1.2.26")
        self.assertEqual(created["data"][CONF_DEVICE_ID], "02_00_00_aa_bb_cc")

    async def test_auto_discovery_updates_changed_ip_on_existing_entry(self) -> None:
        """Already-configured kettle with a new IP triggers discovery-update-info reload."""
        existing = MockConfigEntry(
            entry_id="entry-existing",
            unique_id="02:00:00:aa:bb:cc",
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_WIFI_MAC: "02:00:00:aa:bb:cc",
                CONF_BLE_ADDRESS: "02:00:00:00:00:0E",
                CONF_DEVICE_ID: "02_00_00_aa_bb_cc",
            },
        )
        flow = StaggAssistantConfigFlow()
        flow.hass.config_entries.async_entries.return_value = [existing]

        discovery_info = MagicMock()
        discovery_info.address = "02:00:00:00:00:0E"
        discovery_info.name = "EKG-aa-bb-cc"

        resolved = KettleNetworkInfo(
            ip="192.0.2.42",
            wifi_mac="02:00:00:aa:bb:cc",
            ble_address="02:00:00:00:00:0E",
            firmware="1.2.26",
            method="bluetooth",
        )
        with patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=resolved),
        ):
            res = await flow.async_step_bluetooth(discovery_info)

        self.assertEqual(res["type"], "abort")
        self.assertEqual(res["reason"], "already_configured")
        flow.hass.config_entries.async_update_entry.assert_called_once()
        updated_data = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        self.assertEqual(updated_data[CONF_IP_ADDRESS], "192.0.2.42")
        self.assertEqual(updated_data[CONF_FIRMWARE_VERSION], "1.2.26")
        self.assertEqual(updated_data[CONF_DEVICE_ID], "02_00_00_aa_bb_cc")
        flow.hass.config_entries.async_schedule_reload.assert_called_once_with(
            "entry-existing"
        )

    async def test_auto_discovery_aborts_when_ip_unresolvable(self) -> None:
        """Unresolvable BLE device aborts cleanly with cannot_resolve_ip."""
        flow = StaggAssistantConfigFlow()
        discovery_info = MagicMock()
        discovery_info.address = "02:00:00:00:00:0E"
        discovery_info.name = "EKG-aa-bb-cc"

        with patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=None),
        ):
            res = await flow.async_step_bluetooth(discovery_info)

        self.assertEqual(res["type"], "abort")
        self.assertEqual(res["reason"], "cannot_resolve_ip")


class TestValidateKettleEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Test async_validate_kettle host filtering and error mapping."""

    async def test_rejects_loopback_unspecified_multicast_and_malformed(self) -> None:
        """Loopback, unspecified, multicast, and malformed hosts return invalid_host."""
        hass = MagicMock()
        for bad_host in ("127.0.0.1", "0.0.0.0", "224.0.0.1", "evil.com/path", ""):
            with self.subTest(host=bad_host):
                self.assertEqual(await async_validate_kettle(hass, bad_host), "invalid_host")

    async def test_temp_timeout_returns_cannot_connect_without_cli_retry(self) -> None:
        """Timeout on /temp returns cannot_connect immediately without hitting /cli."""
        called_urls: list[str] = []

        def side_effect(url: str, **kwargs: object) -> AsyncMock:
            called_urls.append(url)
            self.assertIs(kwargs.get("allow_redirects"), False)
            cm = AsyncMock()
            cm.__aenter__.side_effect = TimeoutError("timeout")
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)

        with patch(
            "custom_components.staggassistant.kettle_discovery.async_get_clientsession",
            return_value=session,
        ):
            err = await async_validate_kettle(MagicMock(), "192.0.2.10")

        self.assertEqual(err, "cannot_connect")
        self.assertEqual(len(called_urls), 1)
        self.assertIn("/temp", called_urls[0])

    async def test_silenced_cli_form_returns_cannot_connect_and_other_server_invalid_device(
        self,
    ) -> None:
        """v1.2.26 HTML CLI form returns cannot_connect; unrelated HTTP server returns invalid_device."""
        for cli_body, expected_error in (
            ('<form action="cli" method="GET"></form>', "cannot_connect"),
            ("<html><body>Welcome to nginx</body></html>", "invalid_device"),
        ):
            with self.subTest(expected=expected_error):
                resp_404 = _make_response(status=404, text="Not found")
                resp_cli = _make_response(status=200, text=cli_body)
                cm_404 = AsyncMock()
                cm_404.__aenter__.return_value = resp_404
                cm_cli = AsyncMock()
                cm_cli.__aenter__.return_value = resp_cli

                def side_effect(url: str, **kwargs: object) -> AsyncMock:
                    self.assertIs(kwargs.get("allow_redirects"), False)
                    return cm_404 if "/temp" in url else cm_cli

                session = MagicMock()
                session.get = MagicMock(side_effect=side_effect)

                with patch(
                    "custom_components.staggassistant.kettle_discovery.async_get_clientsession",
                    return_value=session,
                ):
                    err = await async_validate_kettle(MagicMock(), "192.0.2.10")

                self.assertEqual(err, expected_error)


if __name__ == "__main__":
    unittest.main()
