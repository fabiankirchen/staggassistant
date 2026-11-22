"""Unit tests for all 7 entity platforms, DeviceInfo, safety interlocks, and ESP32 API."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import tests  # noqa: F401 - installs Home Assistant test stubs
from tests import MockConfigEntry

from custom_components.staggassistant import binary_sensor, button, climate, number, select, sensor, switch
from custom_components.staggassistant.api import (
    FirmwareMode,
    StaggKettleClient,
    StaggTimeoutError,
    read_response_text,
    sanitize_temp_json,
)
from custom_components.staggassistant.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    StaggBinarySensor,
)
from custom_components.staggassistant.button import BUTTON_DESCRIPTIONS, StaggButton
from custom_components.staggassistant.climate import StaggKettleClimate
from custom_components.staggassistant.const import (
    CONF_FIRMWARE_VERSION,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_WIFI_MAC,
    ESP32_COMMAND_COOLDOWN,
    LEGACY_TEMP_REPROBE_INTERVAL,
)
from custom_components.staggassistant.coordinator import StaggLinkCoordinator
from custom_components.staggassistant.number import NUMBER_DESCRIPTIONS, StaggNumber
from custom_components.staggassistant.select import SELECT_DESCRIPTIONS, StaggSelect
from custom_components.staggassistant.sensor import SENSOR_DESCRIPTIONS
from custom_components.staggassistant.switch import SWITCH_DESCRIPTIONS, StaggSwitch
from homeassistant.components.climate.const import HVACMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC


def _make_response(status: int = 200, text: str = "OK") -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.content = None
    resp.read = AsyncMock(return_value=text.encode("utf-8"))
    resp.text = AsyncMock(return_value=text)
    return resp


class TestPlatformsAndEsp32(unittest.IsolatedAsyncioTestCase):
    """Test platform metadata, entity edge cases, and ESP32 HTTP client behavior."""

    def setUp(self) -> None:
        self.hass = MagicMock()
        self.hass.config.elevation = 0
        self.coordinator = StaggLinkCoordinator(self.hass, "192.0.2.10", 15)
        self.coordinator.client._cooldown = 0

    async def test_parallel_updates_and_no_update_before_add(self) -> None:
        """Verify PARALLEL_UPDATES on all 7 platforms and async_add_entities never sets update_before_add=True."""
        expected_parallel = {
            climate: 1,
            button: 1,
            number: 1,
            select: 1,
            switch: 1,
            sensor: 0,
            binary_sensor: 0,
        }
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"},
            runtime_data=self.coordinator,
        )

        for mod, expected in expected_parallel.items():
            with self.subTest(module=mod.__name__):
                self.assertEqual(mod.PARALLEL_UPDATES, expected)
                add_mock = MagicMock()
                await mod.async_setup_entry(self.hass, entry, add_mock)
                add_mock.assert_called_once()
                self.assertEqual(len(add_mock.call_args.args), 1)
                self.assertNotIn("update_before_add", add_mock.call_args.kwargs)

    def test_stagg_entity_device_info_optional_fields(self) -> None:
        """DeviceInfo includes sw_version and MAC connection when present and omits when absent."""
        entry_full = MockConfigEntry(
            data={
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_NAME: "Kettle",
                CONF_FIRMWARE_VERSION: "1.2.26",
                CONF_WIFI_MAC: "02:00:00:aa:bb:cc",
            }
        )
        climate_full = StaggKettleClimate(self.coordinator, entry_full)
        info_full = climate_full._attr_device_info
        self.assertEqual(info_full["sw_version"], "1.2.26")
        self.assertEqual(
            info_full["connections"],
            {(CONNECTION_NETWORK_MAC, "02:00:00:aa:bb:cc")},
        )

        entry_min = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"}
        )
        climate_min = StaggKettleClimate(self.coordinator, entry_min)
        info_min = climate_min._attr_device_info
        self.assertNotIn("sw_version", info_min)
        self.assertNotIn("connections", info_min)

    async def test_climate_fail_closed_translation_keys(self) -> None:
        """Climate async_set_hvac_mode(HEAT) fails closed with specific translation keys."""
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"}
        )
        entity = StaggKettleClimate(self.coordinator, entry)
        self.coordinator.async_send_command = AsyncMock()
        self.coordinator.async_request_refresh = AsyncMock()

        cases = [
            (None, "kettle_state_unknown"),
            ({"is_docked": False, "mode": "S_Off", "no_water": False}, "kettle_undocked"),
            ({"is_docked": True, "mode": "S_Off", "no_water": True}, "kettle_no_water"),
            ({"is_docked": True, "mode": "S_NoWater", "no_water": False}, "kettle_no_water"),
        ]
        for data, expected_key in cases:
            with self.subTest(expected_key=expected_key, data=data):
                self.coordinator.data = data
                with self.assertRaises(HomeAssistantError) as ctx:
                    await entity.async_set_hvac_mode(HVACMode.HEAT)
                self.assertEqual(ctx.exception.translation_key, expected_key)
                self.coordinator.async_send_command.assert_not_called()

    def test_sensor_and_binary_sensor_descriptions_and_preboil_heating(self) -> None:
        """No sensor/binary_sensor description hardcodes name, and is_heating is True for S_PreBoil."""
        for desc in (*SENSOR_DESCRIPTIONS, *BINARY_SENSOR_DESCRIPTIONS):
            with self.subTest(key=desc.key):
                self.assertIsNone(getattr(desc, "name", None))

        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"}
        )
        heating_desc = next(
            d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "is_heating"
        )
        bsensor = StaggBinarySensor(self.coordinator, entry, heating_desc)
        self.coordinator.data = {"mode": "S_PreBoil"}
        self.assertTrue(bsensor.is_on)

    async def test_button_long_press_2_failure_and_cancellation_safety(self) -> None:
        """long_press_2 skips 2u if 2d fails, and shields 2u if cancelled during sleep."""
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"}
        )
        long_press_desc = next(
            d for d in BUTTON_DESCRIPTIONS if d.key == "long_press_2"
        )
        btn = StaggButton(self.coordinator, entry, long_press_desc)
        self.coordinator.async_request_refresh = AsyncMock()

        # 1. If "2d" raises HomeAssistantError, "2u" must NOT be sent
        sent_on_fail: list[str] = []

        async def fail_2d(cmd: str) -> str:
            sent_on_fail.append(cmd)
            raise HomeAssistantError("boom")

        self.coordinator.async_send_command = fail_2d
        with self.assertRaises(HomeAssistantError):
            await btn.async_press()
        self.assertEqual(sent_on_fail, ["2d"])

        # 2. If cancelled while sleeping for 2s, "2u" IS still sent via asyncio.shield
        sent_on_cancel: list[str] = []
        sleep_started = asyncio.Event()

        async def record_cmd(cmd: str) -> str:
            sent_on_cancel.append(cmd)
            return "OK"

        async def fake_sleep(_seconds: float) -> None:
            sleep_started.set()
            await asyncio.Future()

        self.coordinator.async_send_command = record_cmd
        with patch("custom_components.staggassistant.button.asyncio.sleep", side_effect=fake_sleep):
            task = asyncio.create_task(btn.async_press())
            await sleep_started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(sent_on_cancel, ["2d", "2u"])

    async def test_number_select_switch_validation_and_none_states(self) -> None:
        """Number/Select raise ServiceValidationError on invalid inputs and return None when missing."""
        entry = MockConfigEntry(
            data={CONF_IP_ADDRESS: "192.0.2.10", CONF_NAME: "Kettle"}
        )

        sch_desc = next(
            d for d in NUMBER_DESCRIPTIONS if d.key == "schedule_temperature"
        )
        num = StaggNumber(self.coordinator, entry, sch_desc)
        self.coordinator.async_send_command = AsyncMock()
        for bad_val in (39, 101, float("nan")):
            with self.subTest(bad_val=bad_val):
                with self.assertRaises(ServiceValidationError) as ctx:
                    await num.async_set_native_value(bad_val)
                self.assertEqual(ctx.exception.translation_key, "value_out_of_range")
                self.coordinator.async_send_command.assert_not_called()

        clock_desc = next(d for d in SELECT_DESCRIPTIONS if d.key == "clock_mode")
        sel = StaggSelect(self.coordinator, entry, clock_desc)
        self.coordinator.data = {}
        self.assertIsNone(sel.current_option)
        with self.assertRaises(ServiceValidationError) as sel_ctx:
            await sel.async_select_option("bogus")
        self.assertEqual(sel_ctx.exception.translation_key, "invalid_option")
        self.coordinator.async_send_command.assert_not_called()

        sw = StaggSwitch(self.coordinator, entry, SWITCH_DESCRIPTIONS[0])
        self.coordinator.data = None
        self.assertIsNone(sw.is_on)

    async def test_api_allow_redirects_false_on_all_gets(self) -> None:
        """All HTTP GET calls pass allow_redirects=False."""
        recorded_calls: list[tuple[str, dict[str, object]]] = []

        resp_404 = _make_response(status=404, text="")
        resp_state = _make_response(
            status=200,
            text="mode=S_Off\ntempr=45.0 C\ntemprT=93.0 C\n",
        )
        resp_settings = _make_response(status=200, text="st: hold = 30\n")
        resp_ok = _make_response(status=200, text="OK")

        def side_effect(url: str, **kwargs: object) -> AsyncMock:
            recorded_calls.append((url, kwargs))
            cm = AsyncMock()
            if "/temp" in url:
                cm.__aenter__.return_value = resp_404
            elif "cmd=state" in url:
                cm.__aenter__.return_value = resp_state
            elif "cmd=prtsettings" in url:
                cm.__aenter__.return_value = resp_settings
            else:
                cm.__aenter__.return_value = resp_ok
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)
        client = StaggKettleClient(session, "192.0.2.10", cooldown=0)

        await client.async_fetch_poll_payload()
        await client.async_send_command("ss S_Heat")

        self.assertGreaterEqual(len(recorded_calls), 4)
        for url, kwargs in recorded_calls:
            with self.subTest(url=url):
                self.assertIs(kwargs.get("allow_redirects"), False)

    async def test_read_response_text_caps_streaming_reads(self) -> None:
        """read_response_text caps reads via response.content.read(limit)."""
        response = MagicMock()
        response.content = MagicMock()
        response.content.read = AsyncMock(return_value=b"abcdef")
        result = await read_response_text(response, limit=6)
        response.content.read.assert_awaited_once_with(6)
        self.assertEqual(result, "abcdef")

    async def test_client_enforces_esp32_command_cooldown(self) -> None:
        """Back-to-back requests wait for ESP32_COMMAND_COOLDOWN under self._lock."""
        resp_ok = _make_response(status=200, text="OK")
        cm_ok = AsyncMock()
        cm_ok.__aenter__.return_value = resp_ok
        session = MagicMock()
        session.get = MagicMock(return_value=cm_ok)

        client = StaggKettleClient(session, "192.0.2.10", cooldown=ESP32_COMMAND_COOLDOWN)
        current_time = [100.0]

        with patch(
            "custom_components.staggassistant.api.time.monotonic",
            side_effect=lambda: current_time[0],
        ), patch(
            "custom_components.staggassistant.api.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await client.async_send_command("1")
            current_time[0] = 100.01
            await client.async_send_command("2")

        mock_sleep.assert_awaited_once()
        slept = mock_sleep.call_args.args[0]
        self.assertAlmostEqual(slept, 0.14, places=4)

    def test_sanitize_temp_json_preserves_quoted_strings(self) -> None:
        """sanitize_temp_json leaves ': nan' inside strings intact while replacing unquoted NaN."""
        raw = '{"note": "temp: nan", "temp": -nan, "other": nan, "state": "S_Off"}'
        sanitized = sanitize_temp_json(raw)
        parsed = json.loads(sanitized)
        self.assertEqual(parsed["note"], "temp: nan")
        self.assertIsNone(parsed["temp"])
        self.assertIsNone(parsed["other"])

    async def test_temp_timeout_fails_fast_and_state_null_or_nowater(self) -> None:
        """/temp TimeoutError fails fast without /cli fallback; null state -> S_Off; S_NoWater -> no_water."""
        called_urls: list[str] = []

        def timeout_side_effect(url: str, **kwargs: object) -> AsyncMock:
            called_urls.append(url)
            cm = AsyncMock()
            cm.__aenter__.side_effect = TimeoutError("timed out")
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=timeout_side_effect)
        client = StaggKettleClient(session, "192.0.2.10", cooldown=0)

        with self.assertRaises(StaggTimeoutError):
            await client.async_fetch_poll_payload()
        self.assertEqual(len(called_urls), 1)
        self.assertIn("/temp", called_urls[0])

        # "state": null -> "S_Off", "state": "S_NoWater" -> no_water=True
        for payload, exp_mode, exp_nw in (
            ('{"state":null,"temp":55.0,"temp_set":90.0}', "S_Off", False),
            ('{"state":"S_NoWater","temp":55.0,"temp_set":90.0}', "S_NoWater", True),
        ):
            with self.subTest(exp_mode=exp_mode):
                resp_temp = _make_response(status=200, text=payload)
                resp_settings = _make_response(status=200, text="<form action=\"cli\">")

                def ok_side_effect(
                    url: str,
                    _resp_temp: MagicMock = resp_temp,
                    _resp_settings: MagicMock = resp_settings,
                    **kwargs: object,
                ) -> AsyncMock:
                    cm = AsyncMock()
                    cm.__aenter__.return_value = (
                        _resp_temp if "/temp" in url else _resp_settings
                    )
                    return cm

                self.coordinator.session.get = MagicMock(side_effect=ok_side_effect)
                data = await self.coordinator._async_update_data()
                self.assertEqual(data["mode"], exp_mode)
                self.assertEqual(data["no_water"], exp_nw)

    async def test_legacy_mode_cached_then_reprobed_and_upgraded(self) -> None:
        """LEGACY_CLI skips /temp until LEGACY_TEMP_REPROBE_INTERVAL elapses, then upgrades to MODERN_TEMP."""
        urls_called: list[str] = []
        temp_available = False

        def side_effect(url: str, **kwargs: object) -> AsyncMock:
            urls_called.append(url)
            cm = AsyncMock()
            if "/temp" in url:
                if temp_available:
                    cm.__aenter__.return_value = _make_response(
                        status=200,
                        text='{"state":"S_Off","temp":50.0,"temp_set":93.0}',
                    )
                else:
                    cm.__aenter__.return_value = _make_response(status=404, text="")
            elif "cmd=state" in url:
                cm.__aenter__.return_value = _make_response(
                    status=200,
                    text="mode=S_Off\ntempr=50.0 C\ntemprT=93.0 C\n",
                )
            else:
                cm.__aenter__.return_value = _make_response(
                    status=200, text="st: hold = 30\n"
                )
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)
        client = StaggKettleClient(session, "192.0.2.10", cooldown=0)

        now = 1000.0
        with patch(
            "custom_components.staggassistant.api.time.monotonic",
            side_effect=lambda: now,
        ):
            # Poll 1: probes /temp (404) -> caches LEGACY_CLI
            await client.async_fetch_poll_payload()
            self.assertEqual(client.firmware_mode, FirmwareMode.LEGACY_CLI)
            self.assertTrue(any("/temp" in u for u in urls_called))

            # Poll 2 (shortly after): skips /temp completely
            urls_called.clear()
            now += 60.0
            await client.async_fetch_poll_payload()
            self.assertEqual(client.firmware_mode, FirmwareMode.LEGACY_CLI)
            self.assertFalse(any("/temp" in u for u in urls_called))

            # Poll 3 (after LEGACY_TEMP_REPROBE_INTERVAL): reprobes /temp -> upgrades to MODERN_TEMP
            urls_called.clear()
            temp_available = True
            now += LEGACY_TEMP_REPROBE_INTERVAL + 1.0
            await client.async_fetch_poll_payload()
            self.assertEqual(client.firmware_mode, FirmwareMode.MODERN_TEMP)
            self.assertTrue(any("/temp" in u for u in urls_called))

    async def test_transient_prtsettings_error_does_not_lock_unsupported(self) -> None:
        """A transient prtsettings failure under /temp leaves prtsettings_supported as None."""

        def side_effect(url: str, **kwargs: object) -> AsyncMock:
            cm = AsyncMock()
            if "/temp" in url:
                cm.__aenter__.return_value = _make_response(
                    status=200,
                    text='{"state":"S_Off","temp":50.0,"temp_set":93.0}',
                )
            else:
                cm.__aenter__.side_effect = aiohttp.ClientError("transient glitch")
            return cm

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)
        client = StaggKettleClient(session, "192.0.2.10", cooldown=0)

        await client.async_fetch_poll_payload()
        self.assertIsNone(client.prtsettings_supported)


if __name__ == "__main__":
    unittest.main()
