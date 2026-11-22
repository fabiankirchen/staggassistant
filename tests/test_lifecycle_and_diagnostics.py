"""Unit tests for integration lifecycle, diagnostics redaction, and Store hygiene."""
from __future__ import annotations

from datetime import timedelta
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests  # noqa: F401 - installs Home Assistant test stubs
from tests import MockConfigEntry

from custom_components.staggassistant import (
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
    async_update_listener,
)
from custom_components.staggassistant.const import (
    CONF_BLE_ADDRESS,
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_MAC,
    CORE_PLATFORMS,
    EXTENDED_PLATFORMS,
    PLATFORMS,
)
from custom_components.staggassistant.coordinator import StaggLinkCoordinator
from custom_components.staggassistant.diagnostics import (
    async_get_config_entry_diagnostics,
)

LEGACY_STATE = """
mode=S_Off
tempr=48.0 C
temprB=100.0 C
temprT=92.0 C
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
clock=09:15
"""

LEGACY_SETTINGS = """
st: hold = 45
st: boil = 1
st: chime = 7
st: altitude = 420
st: language = 2
st: units = 1
st: clockmode = 1
st: schedon = 1
st: Repeat_sched = 1
st: schtime = 07:15
st: schtempr = 185 F (85 C)
"""


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.config.elevation = 0
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock(return_value=True)
    return hass


class TestLifecycleAndDiagnostics(unittest.IsolatedAsyncioTestCase):
    """Test entry lifecycle hooks, diagnostics redaction, and store debouncing."""

    async def test_setup_entry_sets_runtime_data_forwards_platforms_and_clamps_interval(
        self,
    ) -> None:
        """async_setup_entry sets entry.runtime_data, forwards all PLATFORMS, and clamps scan_interval."""
        for raw_interval, expected_interval in ((1, 5), (999, 120)):
            with self.subTest(raw_interval=raw_interval):
                hass = _make_hass()
                entry = MockConfigEntry(
                    data={
                        CONF_IP_ADDRESS: "192.0.2.10",
                        CONF_NAME: "Kettle",
                        CONF_SCAN_INTERVAL: raw_interval,
                        CONF_DEVICE_ID: "02_00_00_aa_bb_cc",
                    }
                )
                with patch.object(
                    StaggLinkCoordinator,
                    "async_load_saved_settings",
                    AsyncMock(),
                ), patch.object(
                    StaggLinkCoordinator,
                    "async_config_entry_first_refresh",
                    AsyncMock(),
                ):
                    ok = await async_setup_entry(hass, entry)

                self.assertTrue(ok)
                self.assertIsInstance(entry.runtime_data, StaggLinkCoordinator)
                self.assertEqual(
                    entry.runtime_data.update_interval,
                    timedelta(seconds=expected_interval),
                )
                self.assertEqual(PLATFORMS, CORE_PLATFORMS + EXTENDED_PLATFORMS)
                hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
                    entry, PLATFORMS
                )

    async def test_unload_entry_unloads_platforms_and_flushes_store(self) -> None:
        """async_unload_entry unloads all PLATFORMS and calls coordinator.async_flush_store()."""
        hass = _make_hass()
        coordinator = StaggLinkCoordinator(hass, "192.0.2.10", 15)
        coordinator.async_flush_store = AsyncMock()
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_DEVICE_ID: "02_00_00_aa_bb_cc"},
            runtime_data=coordinator,
        )

        ok = await async_unload_entry(hass, entry)
        self.assertTrue(ok)
        hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            entry, PLATFORMS
        )
        coordinator.async_flush_store.assert_awaited_once()

    async def test_remove_entry_removes_stable_and_legacy_storage_keys(self) -> None:
        """async_remove_entry removes both stable device_id and legacy IP storage keys."""
        hass = _make_hass()
        entry = MockConfigEntry(
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_DEVICE_ID: "02_00_00_aa_bb_cc",
            }
        )
        created_stores: list[tuple[str, AsyncMock]] = []

        def fake_store(_hass: MagicMock, _version: int, key: str) -> MagicMock:
            store = MagicMock()
            store.async_remove = AsyncMock()
            created_stores.append((key, store.async_remove))
            return store

        with patch("custom_components.staggassistant.Store", side_effect=fake_store):
            await async_remove_entry(hass, entry)

        keys = {key for key, _ in created_stores}
        self.assertEqual(
            keys,
            {"staggassistant_02_00_00_aa_bb_cc", "staggassistant_192_0_2_10"},
        )
        for _, remove_mock in created_stores:
            remove_mock.assert_awaited_once()

    async def test_update_listener_reloads_on_ip_change_and_updates_clamped_interval(
        self,
    ) -> None:
        """async_update_listener reloads on IP change and clamps update_interval on options change."""
        hass = _make_hass()
        coordinator = StaggLinkCoordinator(hass, "192.0.2.10", 15)
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_SCAN_INTERVAL: 15},
            options={CONF_SCAN_INTERVAL: 1},
            runtime_data=coordinator,
        )

        # Same IP -> update interval clamped (1 -> 5) without reload
        await async_update_listener(hass, entry)
        self.assertEqual(coordinator.update_interval, timedelta(seconds=5))
        hass.config_entries.async_reload.assert_not_awaited()

        # High option -> clamped (500 -> 120)
        entry.options = {CONF_SCAN_INTERVAL: 500}
        await async_update_listener(hass, entry)
        self.assertEqual(coordinator.update_interval, timedelta(seconds=120))
        hass.config_entries.async_reload.assert_not_awaited()

        # Changed IP -> triggers reload
        entry.data = {CONF_IP_ADDRESS: "192.0.2.99", CONF_SCAN_INTERVAL: 15}
        await async_update_listener(hass, entry)
        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)

    async def test_diagnostics_redacts_sensitive_fields_and_exposes_runtime(
        self,
    ) -> None:
        """Diagnostics redacts PII/identifiers while exposing safe runtime and coordinator state."""
        hass = _make_hass()
        coordinator = StaggLinkCoordinator(hass, "192.0.2.10", 15)
        coordinator.last_update_success = True
        coordinator.client.prtsettings_supported = False
        coordinator.data = {"temp": 92.5, "mode": "S_Hold", "ssid": "SecretWiFi"}

        entry = MockConfigEntry(
            title="My Kitchen Kettle",
            unique_id="02:00:00:aa:bb:cc",
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_WIFI_MAC: "02:00:00:aa:bb:cc",
                CONF_BLE_ADDRESS: "02:00:00:00:00:0E",
                CONF_DEVICE_ID: "02_00_00_aa_bb_cc",
                CONF_NAME: "My Kitchen Kettle",
                CONF_SCAN_INTERVAL: 15,
            },
            options={CONF_SCAN_INTERVAL: 30},
            runtime_data=coordinator,
        )

        diag = await async_get_config_entry_diagnostics(hass, entry)

        self.assertEqual(diag["entry"]["title"], "**REDACTED**")
        self.assertEqual(diag["entry"]["unique_id"], "**REDACTED**")
        for sensitive_key in (
            CONF_IP_ADDRESS,
            CONF_WIFI_MAC,
            CONF_BLE_ADDRESS,
            CONF_DEVICE_ID,
            CONF_NAME,
        ):
            self.assertEqual(diag["entry"]["data"][sensitive_key], "**REDACTED**")
        self.assertEqual(diag["entry"]["data"][CONF_SCAN_INTERVAL], 15)
        self.assertEqual(diag["entry"]["options"][CONF_SCAN_INTERVAL], 30)

        self.assertEqual(diag["runtime"]["firmware_mode"], "unknown")
        self.assertFalse(diag["runtime"]["prtsettings_supported"])
        self.assertTrue(diag["runtime"]["last_update_success"])
        self.assertEqual(diag["coordinator_data"]["temp"], 92.5)
        self.assertEqual(diag["coordinator_data"]["mode"], "S_Hold")
        self.assertEqual(diag["coordinator_data"]["ssid"], "**REDACTED**")

    async def test_legacy_polls_unchanged_prtsettings_do_not_rewrite_store(self) -> None:
        """Repeated legacy /cli polls with unchanged prtsettings do NOT schedule or write to disk."""
        hass = _make_hass()
        coord = StaggLinkCoordinator(hass, "192.0.2.10", 15)
        coord.client._cooldown = 0
        coord._store.async_save = AsyncMock()

        resp_404 = AsyncMock()
        resp_404.status = 404
        cm_404 = AsyncMock()
        cm_404.__aenter__.return_value = resp_404

        resp_state = AsyncMock()
        resp_state.status = 200
        resp_state.raise_for_status = MagicMock()
        resp_state.text = AsyncMock(return_value=LEGACY_STATE)
        cm_state = AsyncMock()
        cm_state.__aenter__.return_value = resp_state

        resp_settings = AsyncMock()
        resp_settings.status = 200
        resp_settings.raise_for_status = MagicMock()
        resp_settings.text = AsyncMock(return_value=LEGACY_SETTINGS)
        cm_settings = AsyncMock()
        cm_settings.__aenter__.return_value = resp_settings

        def side_effect(url, **kwargs):
            if "/temp" in url:
                return cm_404
            if "cmd=state" in url:
                return cm_state
            return cm_settings

        coord.session.get = MagicMock(side_effect=side_effect)

        # First poll updates cached settings -> schedules one debounced save
        await coord._async_update_data()
        self.assertEqual(len(coord._store.delay_save_calls), 1)
        coord._store.async_save.assert_not_awaited()

        # Subsequent polls with identical prtsettings -> zero additional saves
        coord._store.delay_save_calls.clear()
        await coord._async_update_data()
        await coord._async_update_data()
        self.assertEqual(len(coord._store.delay_save_calls), 0)
        coord._store.async_save.assert_not_awaited()

    async def test_volatile_commands_and_clock_time_do_not_trigger_store_saves(
        self,
    ) -> None:
        """Operational commands and setclock do not schedule saves or persist clock_time."""
        hass = _make_hass()
        coord = StaggLinkCoordinator(hass, "192.0.2.10", 15)
        coord.client._cooldown = 0
        coord._store.async_save = AsyncMock()

        resp_ok = AsyncMock()
        resp_ok.status = 200
        resp_ok.raise_for_status = MagicMock()
        resp_ok.text = AsyncMock(return_value="OK")
        cm_ok = AsyncMock()
        cm_ok.__aenter__.return_value = resp_ok
        coord.session.get = MagicMock(return_value=cm_ok)

        for cmd in ("ss S_Heat", "ss S_Off", "1", "2", "q", "w", "setclock 14 25 30"):
            await coord.async_send_command(cmd)

        self.assertEqual(len(coord._store.delay_save_calls), 0)
        coord._store.async_save.assert_not_awaited()
        self.assertNotIn("clock_time", coord._cached_settings)
        self.assertNotIn("clock_time", coord._get_persistable_settings())
        self.assertEqual(coord._clock_time, "14:25")

    async def test_legacy_store_migration_strips_clock_time_and_deletes_legacy_store(
        self,
    ) -> None:
        """Legacy store migration copies settings without clock_time and deletes _legacy_store."""
        hass = _make_hass()
        coord = StaggLinkCoordinator(
            hass,
            "192.0.2.10",
            15,
            storage_key="02_00_00_aa_bb_cc",
        )
        assert coord._legacy_store is not None
        coord._store._data = None
        coord._legacy_store._data = {
            "hold_time_minutes": 40,
            "chime_volume": 8,
            "clock_time": "11:22",
        }

        await coord.async_load_saved_settings()

        self.assertEqual(coord._cached_settings["hold_time_minutes"], 40)
        self.assertEqual(coord._cached_settings["chime_volume"], 8)
        self.assertNotIn("clock_time", coord._cached_settings)
        self.assertIsNotNone(coord._store._data)
        self.assertNotIn("clock_time", coord._store._data)
        self.assertTrue(coord._legacy_store.removed)
        self.assertIsNone(coord._legacy_store._data)


if __name__ == "__main__":
    unittest.main()
