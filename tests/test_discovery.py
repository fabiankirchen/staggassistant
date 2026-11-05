"""Tests for BLE/ARP discovery and config-entry identity handling."""
import unittest
from unittest.mock import AsyncMock, MagicMock

import tests  # noqa: F401 - installs Home Assistant test stubs

from custom_components.staggassistant import _ensure_stable_id
from custom_components.staggassistant.config_flow import (
    StaggAssistantConfigFlow,
    StaggAssistantOptionsFlow,
)
from custom_components.staggassistant.const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
    get_device_identifier,
    get_stable_id,
)
from custom_components.staggassistant.kettle_discovery import (
    KettleNetworkInfo,
    _mac_candidates,
    is_valid_host,
    name_suffix,
    normalize_mac,
    parse_status_record,
)


class TestKettleDiscoveryHelpers(unittest.TestCase):
    """Test pure discovery helpers."""

    def test_parse_status_record(self):
        """The c4b4 record carries IP, counter, SSID and status."""
        raw = bytes.fromhex(
            "c000020a7100"
            "546573744e6574776f726b"
            "000000000000000000000000000000000000000000"
            "22"
        )
        parsed = parse_status_record(raw)
        self.assertEqual(parsed["ip"], "192.0.2.10")
        self.assertEqual(parsed["counter"], 0x7100)
        self.assertEqual(parsed["ssid"], "TestNetwork")
        self.assertEqual(parsed["status"], 0x22)

    def test_parse_status_record_ignores_unconnected_ip(self):
        """0.0.0.0 is not a usable IP address."""
        self.assertNotIn("ip", parse_status_record(b"\x00\x00\x00\x00"))

    def test_name_suffix_and_candidates(self):
        """The BLE name suffix maps to the Wi-Fi MAC of the same kettle."""
        self.assertEqual(name_suffix("EKG-aa-bb-cc"), "aa:bb:cc")
        self.assertEqual(normalize_mac("02-00-00-AA-BB-CC"), "02:00:00:aa:bb:cc")
        candidates = _mac_candidates("EKG-aa-bb-cc", "02:00:00:00:00:0E")
        self.assertIn("02:00:00:aa:bb:cc", candidates)
        self.assertIn("aa:bb:cc", candidates)

    def test_host_validation(self):
        """Reject IPv6, URLs, injection attempts and malformed hostnames."""
        self.assertTrue(is_valid_host("192.0.2.10"))
        self.assertTrue(is_valid_host("kettle.local"))
        for host in ("2001:db8::1", "192.168.1.1/evil", "a b", "kettle:80"):
            with self.subTest(host=host):
                self.assertFalse(is_valid_host(host))

    def test_stable_identity_helpers(self):
        """Entity identity stays IP-derived for old entries and MAC-based for new ones."""
        old = MagicMock()
        old.data = {CONF_IP_ADDRESS: "192.0.2.10"}
        self.assertEqual(get_stable_id(old), "192_0_2_10")
        self.assertEqual(get_device_identifier(old), "stagglink_192_0_2_10")

        new = MagicMock()
        new.data = {CONF_DEVICE_ID: "02_00_00_aa_bb_cc"}
        self.assertEqual(get_device_identifier(new), "stagglink_02_00_00_aa_bb_cc")

    def test_old_entry_gets_persisted_stable_id(self):
        """An update from an older version persists the old IP-derived identity."""
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {CONF_IP_ADDRESS: "192.0.2.10"}

        stable_id = _ensure_stable_id(hass, entry)

        self.assertEqual(stable_id, "192_0_2_10")
        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["data"][CONF_DEVICE_ID], "192_0_2_10")

    def test_entry_with_stable_id_is_not_rewritten(self):
        """A stored stable id survives later IP changes."""
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {
            CONF_IP_ADDRESS: "192.0.2.10",
            CONF_DEVICE_ID: "02_00_00_aa_bb_cc",
        }

        self.assertEqual(_ensure_stable_id(hass, entry), "02_00_00_aa_bb_cc")
        hass.config_entries.async_update_entry.assert_not_called()


class TestConfigFlowBluetooth(unittest.IsolatedAsyncioTestCase):
    """Test the Bluetooth branch of the config flow."""

    async def test_setup_menu_offers_bluetooth_and_manual(self):
        """The initial setup step is a menu of discovery methods."""
        flow = StaggAssistantConfigFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_user()
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["menu_options"], ["bluetooth", "manual"])

    async def test_bluetooth_discovery_creates_entry(self):
        """Selecting a discovered kettle fills IP, MAC and stable ID."""
        flow = StaggAssistantConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        resolved = KettleNetworkInfo(
            ip="192.0.2.10",
            wifi_mac="02:00:00:aa:bb:cc",
            ble_address="02:00:00:00:00:0E",
            name="EKG-aa-bb-cc",
            method="bluetooth",
        )
        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_get_kettle_ble_device_map",
            AsyncMock(return_value={"02:00:00:00:00:0E": "EKG-aa-bb-cc"}),
        ), unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=resolved),
        ):
            result = await flow.async_step_bluetooth(
                {"ble_address": "02:00:00:00:00:0E"}
            )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_IP_ADDRESS], "192.0.2.10")
        self.assertEqual(result["data"][CONF_WIFI_MAC], "02:00:00:aa:bb:cc")
        self.assertEqual(result["data"][CONF_DEVICE_ID], "02_00_00_aa_bb_cc")
        self.assertEqual(result["title"], "EKG-aa-bb-cc")


class TestOptionsFlowIpUpdate(unittest.IsolatedAsyncioTestCase):
    """Test changing the IP address through the options flow."""

    def _entry(self):
        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.unique_id = "192.0.2.9"
        entry.data = {
            CONF_IP_ADDRESS: "192.0.2.9",
            "name": "Stagg Kettle",
            CONF_SCAN_INTERVAL: 15,
        }
        entry.options = {}
        return entry

    async def test_manual_ip_update_keeps_entity_identity(self):
        """Updating the IP updates entry data/unique id but not the stable entity ID."""
        entry = self._entry()
        flow = StaggAssistantOptionsFlow()
        flow.config_entry = entry
        flow.hass = MagicMock()
        flow.hass.config_entries.async_entries.return_value = []

        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_validate_kettle",
            AsyncMock(return_value=None),
        ):
            result = await flow.async_step_settings(
                {
                    CONF_IP_ADDRESS: "192.0.2.10",
                    CONF_SCAN_INTERVAL: 30,
                    "enable_extended_entities": True,
                }
            )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_SCAN_INTERVAL], 30)
        flow.hass.config_entries.async_update_entry.assert_called_once()
        kwargs = flow.hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["data"][CONF_IP_ADDRESS], "192.0.2.10")
        self.assertEqual(kwargs["data"][CONF_DEVICE_ID], "192_0_2_9")
        self.assertEqual(kwargs["unique_id"], "192.0.2.10")

    async def test_settings_only_update_does_not_require_online_kettle(self):
        """Changing only the interval should not validate/contact the kettle."""
        entry = self._entry()
        flow = StaggAssistantOptionsFlow()
        flow.config_entry = entry
        flow.hass = MagicMock()
        flow.hass.config_entries.async_entries.return_value = []

        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_validate_kettle",
            AsyncMock(return_value="cannot_connect"),
        ) as validate:
            result = await flow.async_step_settings(
                {
                    CONF_IP_ADDRESS: "192.0.2.9",
                    CONF_SCAN_INTERVAL: 45,
                    "enable_extended_entities": True,
                }
            )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_SCAN_INTERVAL], 45)
        validate.assert_not_called()
        flow.hass.config_entries.async_update_entry.assert_not_called()

    async def test_bluetooth_update_sets_mac_and_ip(self):
        """The Bluetooth branch stores the resolved IP and Wi-Fi MAC."""
        entry = self._entry()
        flow = StaggAssistantOptionsFlow()
        flow.config_entry = entry
        flow.hass = MagicMock()
        flow.hass.config_entries.async_entries.return_value = []

        resolved = KettleNetworkInfo(
            ip="192.0.2.10",
            wifi_mac="02:00:00:aa:bb:cc",
            ble_address="02:00:00:00:00:0E",
            method="bluetooth",
        )
        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_get_kettle_ble_device_map",
            AsyncMock(return_value={"02:00:00:00:00:0E": "EKG-aa-bb-cc"}),
        ), unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_resolve_kettle",
            AsyncMock(return_value=resolved),
        ):
            result = await flow.async_step_bluetooth(
                {"ble_address": "02:00:00:00:00:0E"}
            )

        self.assertEqual(result["type"], "create_entry")
        kwargs = flow.hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["data"][CONF_IP_ADDRESS], "192.0.2.10")
        self.assertEqual(kwargs["data"][CONF_WIFI_MAC], "02:00:00:aa:bb:cc")
        self.assertEqual(kwargs["unique_id"], "02:00:00:aa:bb:cc")


if __name__ == "__main__":
    unittest.main()
