"""Comprehensive unit tests for Firmware 1.2.26+ features and security hardening."""
import sys
from unittest.mock import AsyncMock, MagicMock

import tests  # noqa: F401 - installs Home Assistant test stubs

# Provide concrete classes for entity bases to avoid MagicMock metaclass conflict
class MockCoordinatorEntity:
    def __init__(self, coordinator=None):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls

class MockClimateEntity:
    pass

class MockNumberEntity:
    pass

class MockConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

class MockOptionsFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = MockCoordinatorEntity
sys.modules["homeassistant.components.climate"].ClimateEntity = MockClimateEntity
sys.modules["homeassistant.components.number"].NumberEntity = MockNumberEntity
sys.modules["homeassistant.config_entries"].ConfigFlow = MockConfigFlow
sys.modules["homeassistant.config_entries"].OptionsFlow = MockOptionsFlow
sys.modules["homeassistant"].config_entries = sys.modules["homeassistant.config_entries"]
sys.modules.pop("custom_components.staggassistant.config_flow", None)
if "voluptuous" not in sys.modules:
    sys.modules["voluptuous"] = MagicMock()

import unittest
from custom_components.staggassistant.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    StaggBinarySensor,
)
from custom_components.staggassistant.climate import StaggKettleClimate
from custom_components.staggassistant.config_flow import (
    StaggAssistantConfigFlow,
    StaggAssistantOptionsFlow,
)
from custom_components.staggassistant.coordinator import (
    BLOCKED_COMMANDS,
    StaggLinkCoordinator,
    _parse_float,
)
from custom_components.staggassistant.number import StaggNumber
from custom_components.staggassistant.sensor import (
    SENSOR_DESCRIPTIONS,
    StaggSensor,
)
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.components.number import NumberDeviceClass
from homeassistant.const import UnitOfLength, UnitOfTemperature, UnitOfTime
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

SAMPLE_PRTSETTINGS_FORM_ONLY = """
<form action="cli" method="GET">
<label for="x">CLI Command:</label><br>
<input type="text" id="cli" name="cmd"><br>
</form>
"""


class TestFirmware1226AndHardening(unittest.IsolatedAsyncioTestCase):
    """Test suite covering Firmware 1.2.26+, /temp endpoint, injection guards, and URL encoding."""

    def setUp(self):
        self.mock_hass = MagicMock()
        self.coordinator = StaggLinkCoordinator(self.mock_hass, "192.168.1.100", 15)

    def _mock_temp_and_settings(self, temp_json_text, settings_text=SAMPLE_PRTSETTINGS_FORM_ONLY):
        """Mock /temp endpoint and prtsettings."""
        resp_temp = AsyncMock()
        resp_temp.status = 200
        resp_temp.raise_for_status = MagicMock()
        resp_temp.text = AsyncMock(return_value=temp_json_text)

        resp_settings = AsyncMock()
        resp_settings.status = 200
        resp_settings.raise_for_status = MagicMock()
        resp_settings.text = AsyncMock(return_value=settings_text)

        cm_temp = AsyncMock()
        cm_temp.__aenter__.return_value = resp_temp

        cm_settings = AsyncMock()
        cm_settings.__aenter__.return_value = resp_settings

        def side_effect(url, params=None):
            if "/temp" in url:
                return cm_temp
            return cm_settings

        self.coordinator.session.get = MagicMock(side_effect=side_effect)

    # 1. Module-level helper tests
    def test_parse_float_helper(self):
        """Test _parse_float with nan, -nan, +nan, null, negative, and valid numbers."""
        self.assertIsNone(_parse_float(None))
        self.assertIsNone(_parse_float("nan"))
        self.assertIsNone(_parse_float("-nan"))
        self.assertIsNone(_parse_float("+nan"))
        self.assertIsNone(_parse_float("NaN"))
        self.assertIsNone(_parse_float(float("nan")))
        self.assertIsNone(_parse_float(-15.0))
        self.assertIsNone(_parse_float("-273.15"))
        self.assertIsNone(_parse_float(-10.1))
        self.assertIsNone(_parse_float(150.1))
        self.assertIsNone(_parse_float(999.0))
        self.assertIsNone(_parse_float("invalid"))
        self.assertEqual(_parse_float(-10), -10.0)
        self.assertEqual(_parse_float(0), 0.0)
        self.assertEqual(_parse_float("50.5"), 50.5)
        self.assertEqual(_parse_float(150), 150.0)

    # 2. Firmware 1.2.26 /temp JSON endpoint tests
    async def test_firmware_1_2_26_normal_idle(self):
        """Test normal state from Firmware 1.2.26 /temp JSON."""
        json_data = '{"state":"S_Off","temp":48.5,"temp_set":93.0}'
        self._mock_temp_and_settings(json_data)

        data = await self.coordinator._async_update_data()

        self.assertEqual(data["temp"], 48.5)
        self.assertEqual(data["target"], 93.0)
        self.assertEqual(data["mode"], "S_Off")
        self.assertTrue(data["is_docked"])
        self.assertFalse(data["target_reached"])
        self.assertFalse(data["hold_flag"])

    async def test_firmware_1_2_26_heating_and_target_reached(self):
        """Test heating progression and target reached inference."""
        # 1. Under target
        self._mock_temp_and_settings('{"state":"S_Heat","temp":75.0,"temp_set":93.0}')
        data = await self.coordinator._async_update_data()
        self.assertEqual(data["mode"], "S_Heat")
        self.assertFalse(data["target_reached"])

        # 2. Reached within 0.5C threshold
        self._mock_temp_and_settings('{"state":"S_Heat","temp":92.6,"temp_set":93.0}')
        data = await self.coordinator._async_update_data()
        self.assertTrue(data["target_reached"])

        # 3. In keep warm / hold state
        self._mock_temp_and_settings('{"state":"S_Hold","temp":93.0,"temp_set":93.0}')
        data = await self.coordinator._async_update_data()
        self.assertTrue(data["hold_flag"])
        self.assertTrue(data["target_reached"])

    async def test_firmware_1_2_26_lifted_kettle_sanitization(self):
        """Test that unquoted nan, -nan, +nan, null, and large negative readings detect lifted kettle."""
        test_payloads = [
            '{"state":"S_Off","temp":nan,"temp_set":93.0}',
            '{"state":"S_Off","temp":-nan,"temp_set":93.0}',
            '{"state":"S_Off","temp":+nan,"temp_set":93.0}',
            '{"state":"S_Off","temp":null,"temp_set":93.0}',
            '{"state":"S_Off","temp":-273.15,"temp_set":93.0}',
        ]
        for payload in test_payloads:
            with self.subTest(payload=payload):
                self._mock_temp_and_settings(payload)
                data = await self.coordinator._async_update_data()
                self.assertIsNone(data["temp"])
                self.assertFalse(data["is_docked"])

    # 3. Optimistic settings cache updates
    async def test_optimistic_cache_and_form_only_prtsettings(self):
        """Test that async_send_command optimistically updates settings and retains them on v1.2.26."""
        resp_ok = AsyncMock()
        resp_ok.status = 200
        resp_ok.raise_for_status = MagicMock()
        resp_ok.text = AsyncMock(return_value="OK")
        cm_ok = AsyncMock()
        cm_ok.__aenter__.return_value = resp_ok

        resp_temp = AsyncMock()
        resp_temp.status = 200
        resp_temp.raise_for_status = MagicMock()
        resp_temp.text = AsyncMock(return_value='{"state":"S_Off","temp":60.0,"temp_set":90.0}')
        cm_temp = AsyncMock()
        cm_temp.__aenter__.return_value = resp_temp

        resp_form = AsyncMock()
        resp_form.status = 200
        resp_form.raise_for_status = MagicMock()
        resp_form.text = AsyncMock(return_value=SAMPLE_PRTSETTINGS_FORM_ONLY)
        cm_form = AsyncMock()
        cm_form.__aenter__.return_value = resp_form

        def side_effect(url, params=None):
            if "/temp" in url:
                return cm_temp
            if "cmd=prtsettings" in url:
                return cm_form
            return cm_ok

        self.coordinator.session.get = MagicMock(side_effect=side_effect)

        # Send various setting commands
        await self.coordinator.async_send_command("setsetting hold 45")
        await self.coordinator.async_send_command("setsetting boil 1")
        await self.coordinator.async_send_command("setsetting chime 7")
        await self.coordinator.async_send_command("setsetting language 3")
        await self.coordinator.async_send_command("setdigital")
        await self.coordinator.async_send_command("setanalog")
        await self.coordinator.async_send_command("setsetting clockmode 0")
        await self.coordinator.async_send_command("setunitsc")
        await self.coordinator.async_send_command("setunitsf")
        await self.coordinator.async_send_command("setaltitudem 850")
        await self.coordinator.async_send_command("setsetting schedon 1")
        await self.coordinator.async_send_command("setsetting repeat_sched 1")
        await self.coordinator.async_send_command("setsetting schtempr 190")
        await self.coordinator.async_send_command("setsetting schtime 06:45")
        await self.coordinator.async_send_command("setclock 8 30 0")

        # Perform poll where prtsettings returns form only
        data = await self.coordinator._async_update_data()

        self.assertEqual(data["hold_time_minutes"], 45)
        self.assertEqual(data["hold_enabled"], 1)
        self.assertEqual(data["pre_boil_enabled"], 1)
        self.assertEqual(data["chime_volume"], 7)
        self.assertEqual(data["chime_enabled"], 1)
        self.assertEqual(data["language"], 3)
        self.assertEqual(data["clock_mode"], 0)
        self.assertEqual(data["units"], "F")
        self.assertEqual(data["altitude_meters"], 850)
        self.assertEqual(data["schedule_enabled"], 1)
        self.assertEqual(data["schedule_mode"], "repeat")
        self.assertAlmostEqual(data["schedule_temperature"], 87.8, places=1)
        self.assertEqual(data["schedule_time"], "06:45")
        self.assertEqual(data["clock_time"], "08:30")

        # Verify schedule_temperature is retained when schedule is off
        await self.coordinator.async_send_command("setsetting schedon 0")
        data_off = await self.coordinator._async_update_data()
        self.assertEqual(data_off["schedule_mode"], "off")
        self.assertIsNotNone(data_off["schedule_temperature"])

    # 4. Command injection blocking
    async def test_command_injection_guards(self):
        """Test blocking of newlines, carriage returns, semicolons, null bytes, and empty inputs."""
        injection_payloads = [
            "",
            "   ",
            "ss S_Heat\nheaton",
            "ss S_Heat\rheaton",
            "ss S_Off;wifierase",
            "setsetting hold 30\x00heaton",
            "ss S_Off\tsetsetting hold 0",
        ]
        for payload in injection_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(HomeAssistantError):
                    await self.coordinator.async_send_command(payload)

    # 5. URL encoding verification
    async def test_url_encoding_plus_separator(self):
        """Verify async_send_command uses '+' for space separation in URL query string."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = AsyncMock(return_value="OK")
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        self.coordinator.session.get = MagicMock(return_value=mock_cm)

        await self.coordinator.async_send_command("ss S_Heat")
        called_url = self.coordinator.session.get.call_args[0][0]
        self.assertEqual(called_url, "http://192.168.1.100/cli?cmd=ss+S_Heat")
        self.assertNotIn("%20", called_url)

    # 6. Climate setsettingd settempr verification
    async def test_climate_target_temperature_command(self):
        """Verify climate async_set_temperature sends setsettingd settempr and only heats if already active."""
        sent_commands = []

        async def fake_send(cmd):
            sent_commands.append(cmd)
            return "OK"

        self.coordinator.async_send_command = AsyncMock(side_effect=fake_send)
        self.coordinator.async_request_refresh = AsyncMock()

        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        climate = StaggKettleClimate(self.coordinator, entry)

        # 1. When kettle is off: setting target temperature should NOT trigger ss S_Heat
        self.coordinator.data = {"mode": "S_Off"}
        await climate.async_set_temperature(temperature=85.0)

        # 85 C = 185 F
        self.assertIn("setsettingd settempr 185", sent_commands)
        self.assertNotIn("ss S_Heat", sent_commands)

        # 2. When kettle is already heating: setting target temperature SHOULD send ss S_Heat
        sent_commands.clear()
        self.coordinator.data = {"mode": "S_Heat"}
        await climate.async_set_temperature(temperature=90.0)

        # 90 C = 194 F
        self.assertIn("setsettingd settempr 194", sent_commands)
        self.assertIn("ss S_Heat", sent_commands)

    # 7. Legacy fallback when /temp returns 404
    async def test_legacy_fallback_when_temp_404(self):
        """Test fallback to /cli?cmd=state and prtsettings when /temp is 404."""
        resp_404 = AsyncMock()
        resp_404.status = 404
        cm_404 = AsyncMock()
        cm_404.__aenter__.return_value = resp_404

        legacy_state = """
mode=S_Off
tempr=50.0 C
temprT=95.0 C
temprB=100.0 C
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
clock=10:15
"""
        resp_state = AsyncMock()
        resp_state.status = 200
        resp_state.raise_for_status = MagicMock()
        resp_state.text = AsyncMock(return_value=legacy_state)
        cm_state = AsyncMock()
        cm_state.__aenter__.return_value = resp_state

        legacy_settings = """
st: hold = 30
st: boil = 0
st: chime = 5
st: altitude = 100
st: language = 1
st: units = 1
st: clockmode = 1
st: schedon = 0
st: schtempr = 180 F (82 C)
"""
        resp_settings = AsyncMock()
        resp_settings.status = 200
        resp_settings.raise_for_status = MagicMock()
        resp_settings.text = AsyncMock(return_value=legacy_settings)
        cm_settings = AsyncMock()
        cm_settings.__aenter__.return_value = resp_settings

        def side_effect(url, params=None):
            if "/temp" in url:
                return cm_404
            if "cmd=state" in url or (params and params.get("cmd") == "state"):
                return cm_state
            return cm_settings

        self.coordinator.session.get = MagicMock(side_effect=side_effect)

        data = await self.coordinator._async_update_data()
        self.assertEqual(data["temp"], 50.0)
        self.assertEqual(data["target"], 95.0)
        self.assertEqual(data["boil_temp"], 100.0)
        self.assertEqual(data["mode"], "S_Off")
        self.assertEqual(data["clock_time"], "10:15")
        self.assertEqual(data["hold_time_minutes"], 30)
        self.assertEqual(data["chime_volume"], 5)
        self.assertEqual(data["schedule_temperature"], 82.0)

    # 8. Legacy NaN / -nan / negative variations
    async def test_legacy_nan_variations(self):
        """Test that -nan, NaN, and extreme negative temps are treated as lifted kettle on legacy firmware."""
        for raw in ["-nan", "NaN", "+nan", "-273.15"]:
            with self.subTest(raw=raw):
                resp_404 = AsyncMock()
                resp_404.status = 404
                cm_404 = AsyncMock()
                cm_404.__aenter__.return_value = resp_404

                state_text = f"""
mode=S_Off
tempr={raw}
temprB=100.0 C
temprT=93.0 C
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
"""
                resp_state = AsyncMock()
                resp_state.status = 200
                resp_state.raise_for_status = MagicMock()
                resp_state.text = AsyncMock(return_value=state_text)
                cm_state = AsyncMock()
                cm_state.__aenter__.return_value = resp_state

                resp_form = AsyncMock()
                resp_form.status = 200
                resp_form.raise_for_status = MagicMock()
                resp_form.text = AsyncMock(return_value=SAMPLE_PRTSETTINGS_FORM_ONLY)
                cm_form = AsyncMock()
                cm_form.__aenter__.return_value = resp_form

                def side_effect(url, params=None):
                    if "/temp" in url:
                        return cm_404
                    if "cmd=state" in url or (params and params.get("cmd") == "state"):
                        return cm_state
                    return cm_form

                self.coordinator.session.get = MagicMock(side_effect=side_effect)
                data = await self.coordinator._async_update_data()
                self.assertIsNone(data["temp"])
                self.assertFalse(data["is_docked"])

    # 9. HTML form only without /temp raises UpdateFailed
    async def test_html_form_only_without_temp_raises_update_failed(self):
        """Test that if /temp fails and /cli?cmd=state returns only HTML form, UpdateFailed is raised."""
        resp_404 = AsyncMock()
        resp_404.status = 404
        cm_404 = AsyncMock()
        cm_404.__aenter__.return_value = resp_404

        resp_form = AsyncMock()
        resp_form.status = 200
        resp_form.raise_for_status = MagicMock()
        resp_form.text = AsyncMock(return_value=SAMPLE_PRTSETTINGS_FORM_ONLY)
        cm_form = AsyncMock()
        cm_form.__aenter__.return_value = resp_form

        def side_effect(url, params=None):
            if "/temp" in url:
                return cm_404
            return cm_form

        self.coordinator.session.get = MagicMock(side_effect=side_effect)

        with self.assertRaises(UpdateFailed) as ctx:
            await self.coordinator._async_update_data()

        self.assertIn("Kettle CLI returned only HTML form without state data, and /temp JSON endpoint failed.", str(ctx.exception))

    # 10. Config flow validation tests
    async def test_config_flow_modern_temp_success(self):
        """Test config flow succeeds via /temp JSON endpoint."""
        flow = StaggAssistantConfigFlow()
        flow.hass = self.mock_hass
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        resp = AsyncMock()
        resp.status = 200
        resp.text = AsyncMock(return_value='{"state":"S_Off","temp":20.0}')
        cm = AsyncMock()
        cm.__aenter__.return_value = resp

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await flow.async_step_user({"ip_address": "192.168.1.50"})
            self.assertEqual(result, {"type": "create_entry"})

    async def test_config_flow_legacy_fallback_success(self):
        """Test config flow succeeds via legacy /cli?cmd=state when /temp 404s."""
        flow = StaggAssistantConfigFlow()
        flow.hass = self.mock_hass
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        resp_404 = AsyncMock()
        resp_404.status = 404
        cm_404 = AsyncMock()
        cm_404.__aenter__.return_value = resp_404

        resp_state = AsyncMock()
        resp_state.status = 200
        resp_state.text = AsyncMock(return_value="mode=S_Off\ntempr=20.0 C\n")
        cm_state = AsyncMock()
        cm_state.__aenter__.return_value = resp_state

        def side_effect(url, **kwargs):
            if "/temp" in url:
                return cm_404
            return cm_state

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=side_effect)

        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await flow.async_step_user({"ip_address": "192.168.1.50"})
            self.assertEqual(result, {"type": "create_entry"})

    # 11. Number entity configuration verification
    def test_number_entities_configuration(self):
        """Verify number entities use UnitOfTime.MINUTES, UnitOfLength.METERS, and NumberDeviceClass.TEMPERATURE."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}

        # hold_time_minutes
        num_hold = StaggNumber(
            self.coordinator,
            entry,
            "hold_time_minutes",
            "Hold Time Duration",
            0,
            60,
            1,
            UnitOfTime.MINUTES,
            "mdi:timer-sand",
            lambda val: f"setsetting hold {int(val)}",
        )
        self.assertEqual(num_hold._attr_native_unit_of_measurement, UnitOfTime.MINUTES)

        # altitude_meters
        num_alt = StaggNumber(
            self.coordinator,
            entry,
            "altitude_meters",
            "Altitude Setting",
            0,
            3000,
            1,
            UnitOfLength.METERS,
            "mdi:elevation-rise",
            lambda val: f"setaltitudem {int(val)}",
        )
        self.assertEqual(num_alt._attr_native_unit_of_measurement, UnitOfLength.METERS)

        # schedule_temperature
        num_sch = StaggNumber(
            self.coordinator,
            entry,
            "schedule_temperature",
            "Schedule Temperature",
            40,
            100,
            0.5,
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer-auto",
            lambda val: f"setsetting schtempr {round(val * 1.8 + 32)}",
            device_class=NumberDeviceClass.TEMPERATURE,
        )
        self.assertEqual(num_sch._attr_native_unit_of_measurement, UnitOfTemperature.CELSIUS)
        self.assertEqual(num_sch._attr_device_class, NumberDeviceClass.TEMPERATURE)

    # 12. Extended entities filtering and altitude-based boil temperature
    async def test_extended_entities_filtering(self):
        """Verify unreadable sensors are excluded by default and included when enable_extended_entities=True."""
        from custom_components.staggassistant.binary_sensor import (
            EXTENDED_BINARY_SENSOR_KEYS,
            async_setup_entry as bsensor_setup,
        )
        from custom_components.staggassistant.sensor import (
            EXTENDED_SENSOR_KEYS,
            async_setup_entry as sensor_setup,
        )

        entry_default = MagicMock()
        entry_default.entry_id = "test_entry"
        entry_default.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        entry_default.options = {}

        self.mock_hass.data = {"staggassistant": {"test_entry": self.coordinator}}

        # Default: extended entities disabled
        sensors_default = []
        await sensor_setup(self.mock_hass, entry_default, lambda ents, _: sensors_default.extend(ents))
        sensor_keys_default = {s.entity_description.key for s in sensors_default}
        self.assertTrue(EXTENDED_SENSOR_KEYS.isdisjoint(sensor_keys_default))
        self.assertIn("current_temp", sensor_keys_default)
        self.assertIn("target_temp", sensor_keys_default)
        self.assertIn("state_mode", sensor_keys_default)

        bsensors_default = []
        await bsensor_setup(self.mock_hass, entry_default, lambda ents, _: bsensors_default.extend(ents))
        bsensor_keys_default = {s.entity_description.key for s in bsensors_default}
        self.assertTrue(EXTENDED_BINARY_SENSOR_KEYS.isdisjoint(bsensor_keys_default))
        self.assertIn("is_docked", bsensor_keys_default)
        self.assertIn("is_heating", bsensor_keys_default)
        self.assertIn("no_water", bsensor_keys_default)

        # Extended enabled: all entities included
        entry_extended = MagicMock()
        entry_extended.entry_id = "test_entry"
        entry_extended.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        entry_extended.options = {"enable_extended_entities": True}

        sensors_ext = []
        await sensor_setup(self.mock_hass, entry_extended, lambda ents, _: sensors_ext.extend(ents))
        sensor_keys_ext = {s.entity_description.key for s in sensors_ext}
        self.assertTrue(EXTENDED_SENSOR_KEYS.issubset(sensor_keys_ext))

        bsensors_ext = []
        await bsensor_setup(self.mock_hass, entry_extended, lambda ents, _: bsensors_ext.extend(ents))
        bsensor_keys_ext = {s.entity_description.key for s in bsensors_ext}
        self.assertTrue(EXTENDED_BINARY_SENSOR_KEYS.issubset(bsensor_keys_ext))

    async def test_boil_temperature_calculated_from_altitude(self):
        """Test boil_temp is estimated from altitude if kettle returns no boil_temp."""
        self.coordinator._cached_settings["altitude_meters"] = 285
        self._mock_temp_and_settings('{"state":"S_Off","temp":40.0,"temp_set":90.0}')

        data = await self.coordinator._async_update_data()
        # 100 - (285 / 285) = 99.0 C
        self.assertEqual(data["boil_temp"], 99.0)

    # 13. Firmware 1.2.26 enhancements: Low water binary sensor
    def test_firmware_1_2_26_low_water_binary_sensor(self):
        """Test that S_NoWater mode and no_water flag trigger no_water binary sensor."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        no_water_desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "no_water")
        sensor = StaggBinarySensor(self.coordinator, entry, no_water_desc)

        # 1. coordinator data is None
        self.coordinator.data = None
        self.assertIsNone(sensor.is_on)

        # 2. S_NoWater state natively reported on Firmware 1.2.26+
        self.coordinator.data = {"mode": "S_NoWater", "no_water": False}
        self.assertTrue(sensor.is_on)

        # 3. nw flag reported via legacy ketl flags
        self.coordinator.data = {"mode": "S_Heat", "no_water": True}
        self.assertTrue(sensor.is_on)

        # 4. Normal heating with water
        self.coordinator.data = {"mode": "S_Heat", "no_water": False}
        self.assertFalse(sensor.is_on)

        # 5. Normal idle off
        self.coordinator.data = {"mode": "S_Off", "no_water": False}
        self.assertFalse(sensor.is_on)

    # 14. Firmware 1.2.26 enhancements: S_Standby HVAC mode and action
    def test_firmware_1_2_26_standby_climate_mode_and_action(self):
        """Test that S_Standby sets hvac_mode to HVACMode.OFF and hvac_action to HVACAction.OFF."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        climate = StaggKettleClimate(self.coordinator, entry)

        # S_Standby
        self.coordinator.data = {"mode": "S_Standby"}
        self.assertEqual(climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(climate.hvac_action, HVACAction.OFF)

        # S_Off
        self.coordinator.data = {"mode": "S_Off"}
        self.assertEqual(climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(climate.hvac_action, HVACAction.OFF)

        # S_NoWater
        self.coordinator.data = {"mode": "S_NoWater"}
        self.assertEqual(climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(climate.hvac_action, HVACAction.OFF)

        # S_FAIL
        self.coordinator.data = {"mode": "S_FAIL"}
        self.assertEqual(climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(climate.hvac_action, HVACAction.OFF)

        # S_OTA
        self.coordinator.data = {"mode": "S_OTA"}
        self.assertEqual(climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(climate.hvac_action, HVACAction.OFF)

        # S_Heat
        self.coordinator.data = {"mode": "S_Heat"}
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(climate.hvac_action, HVACAction.HEATING)

        # S_StartupToTempr
        self.coordinator.data = {"mode": "S_StartupToTempr"}
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(climate.hvac_action, HVACAction.HEATING)

        # S_Hold (holding temperature - thermostat is active and idle)
        self.coordinator.data = {"mode": "S_Hold"}
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(climate.hvac_action, HVACAction.IDLE)

        # S_PreBoil (actively heating to 100C)
        self.coordinator.data = {"mode": "S_PreBoil"}
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(climate.hvac_action, HVACAction.HEATING)

    # 15. Firmware 1.2.26 actuator and bench commands blocked
    async def test_firmware_1_2_26_blocked_actuator_commands(self):
        """Test that htest, hperiod, triactrace, lpsleep, lpnow are in BLOCKED_COMMANDS and rejected."""
        new_blocked = ["htest", "hperiod", "triactrace", "lpsleep", "lpnow"]
        for cmd in new_blocked:
            self.assertIn(cmd, BLOCKED_COMMANDS)

        test_commands = [
            "htest",
            "htest 1",
            "hperiod",
            "hperiod 100",
            "triactrace",
            "triactrace on",
            "lpsleep",
            "lpnow",
        ]
        for cmd in test_commands:
            with self.subTest(cmd=cmd):
                with self.assertRaises(HomeAssistantError):
                    await self.coordinator.async_send_command(cmd)

    # 16. State mode sensor formatting for S_NoWater and S_Standby
    def test_firmware_1_2_26_state_mode_sensor_formatting(self):
        """Test state_mode sensor formatting for S_NoWater, S_Standby, and other modes."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        state_mode_desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "state_mode")
        sensor = StaggSensor(self.coordinator, entry, state_mode_desc)

        # S_NoWater -> "Low Water Alert"
        self.coordinator.data = {"mode": "S_NoWater"}
        self.assertEqual(sensor.native_value, "Low Water Alert")

        # S_Standby -> "Standby"
        self.coordinator.data = {"mode": "S_Standby"}
        self.assertEqual(sensor.native_value, "Standby")

        # S_StartupToTempr -> "Heating to Target"
        self.coordinator.data = {"mode": "S_StartupToTempr"}
        self.assertEqual(sensor.native_value, "Heating to Target")

        # S_Heat -> "Heat"
        self.coordinator.data = {"mode": "S_Heat"}
        self.assertEqual(sensor.native_value, "Heat")

        # S_Hold_Indefinite -> "Hold Indefinite"
        self.coordinator.data = {"mode": "S_Hold_Indefinite"}
        self.assertEqual(sensor.native_value, "Hold Indefinite")

        # None / missing mode
        self.coordinator.data = {}
        self.assertIsNone(sensor.native_value)

    # 17. OptionsFlow modern signature and execution
    async def test_options_flow_signature_and_execution(self):
        """Test OptionsFlow takes no __init__ args and handles steps properly."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "scan_interval": 15, "enable_extended_entities": False}
        entry.options = {}

        # async_get_options_flow returns StaggAssistantOptionsFlow() with no arguments
        flow = StaggAssistantConfigFlow.async_get_options_flow(entry)
        self.assertIsInstance(flow, StaggAssistantOptionsFlow)

        # In modern HA, HA sets flow.config_entry
        flow.config_entry = entry

        # Test initial form show
        form_res = await flow.async_step_init()
        self.assertEqual(form_res["type"], "form")
        self.assertEqual(form_res["step_id"], "init")

        # Test options submission
        submit_res = await flow.async_step_init({"scan_interval": 30, "enable_extended_entities": True})
        self.assertEqual(submit_res["type"], "create_entry")
        self.assertEqual(submit_res["data"]["scan_interval"], 30)
        self.assertTrue(submit_res["data"]["enable_extended_entities"])

    # 18. Settings cache persistent storage (survives HA restarts)
    async def test_settings_cache_storage_persistence(self):
        """Test coordinator loads saved settings on startup and persists updates."""
        mock_hass = MagicMock()
        coord = StaggLinkCoordinator(mock_hass, "192.168.1.100", 15)

        # 1. Simulate existing persisted settings in HA storage
        coord._store.async_load = AsyncMock(return_value={
            "hold_time_minutes": 45,
            "altitude_meters": 1200,
            "chime_volume": 7,
            "clock_mode": 1,
        })
        coord._store.async_save = AsyncMock()

        await coord.async_load_saved_settings()
        self.assertEqual(coord._cached_settings["hold_time_minutes"], 45)
        self.assertEqual(coord._cached_settings["altitude_meters"], 1200)
        self.assertEqual(coord._cached_settings["chime_volume"], 7)
        self.assertEqual(coord._cached_settings["clock_mode"], 1)

        # 2. When async_send_command sends a command, settings are persisted
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.read = AsyncMock(return_value=b"OK")
        mock_resp.text = AsyncMock(return_value="OK")
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        coord.session.get = MagicMock(return_value=mock_cm)

        await coord.async_send_command("setsetting hold 25")
        self.assertEqual(coord._cached_settings["hold_time_minutes"], 25)
        coord._store.async_save.assert_called()
        last_saved = coord._store.async_save.call_args[0][0]
        self.assertEqual(last_saved["hold_time_minutes"], 25)
        self.assertEqual(last_saved["altitude_meters"], 1200)

    # 19. Config flow IP input validation and injection rejection
    async def test_config_flow_input_validation_and_rejection(self):
        """Test config flow rejects dangerous or invalid IP addresses and hostnames."""
        flow = StaggAssistantConfigFlow()
        flow.hass = MagicMock()

        invalid_hosts = [
            "192.168.1.1/evil",
            "192.168.1.1?cmd=foo",
            "192.168.1.1#section",
            "admin@192.168.1.1",
            "192.168. 1.1",
            "kettle:8080",
            "2001:db8::1",  # IPv6 not accepted
            "invalid..host",
        ]

        for host in invalid_hosts:
            with self.subTest(host=host):
                res = await flow.async_step_user({"ip_address": host})
                self.assertEqual(res["type"], "form")
                self.assertIn("ip_address", res["errors"])
                self.assertEqual(res["errors"]["ip_address"], "invalid_ip")

    # 20. Config flow /temp endpoint validation and fallback
    async def test_config_flow_temp_endpoint_malformed_json_fallback(self):
        """Test that malformed JSON or non-dict payloads on /temp fall back to legacy CLI."""
        flow = StaggAssistantConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        # Mock /temp returning invalid JSON or array
        resp_temp = AsyncMock()
        resp_temp.status = 200
        resp_temp.read = AsyncMock(return_value=b'["not", "a", "dict"]')
        resp_temp.text = AsyncMock(return_value='["not", "a", "dict"]')
        cm_temp = AsyncMock()
        cm_temp.__aenter__.return_value = resp_temp

        # Mock legacy /cli?cmd=state returning valid state
        resp_cli = AsyncMock()
        resp_cli.status = 200
        resp_cli.read = AsyncMock(return_value=b"mode=S_Off\ntempr=22.0 C\n")
        resp_cli.text = AsyncMock(return_value="mode=S_Off\ntempr=22.0 C\n")
        cm_cli = AsyncMock()
        cm_cli.__aenter__.return_value = resp_cli

        def side_effect(url, **kwargs):
            if "/temp" in url:
                return cm_temp
            return cm_cli

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)

        with unittest.mock.patch(
            "custom_components.staggassistant.config_flow.async_get_clientsession",
            return_value=session,
        ):
            result = await flow.async_step_user({"ip_address": "192.168.1.100"})
            self.assertEqual(result["type"], "create_entry")
            self.assertEqual(result["data"]["ip_address"], "192.168.1.100")

    # 21. Climate safety interlock (blocks heating when undocked or low water)
    async def test_climate_safety_interlock_blocks_heating(self):
        """Test that attempting to turn on heating while undocked or low water raises HomeAssistantError."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        climate = StaggKettleClimate(self.coordinator, entry)
        self.coordinator.async_send_command = AsyncMock()
        self.coordinator.async_request_refresh = AsyncMock()

        # Undocked
        self.coordinator.data = {"is_docked": False, "mode": "S_Off", "no_water": False}
        with self.assertRaises(HomeAssistantError) as ctx:
            await climate.async_set_hvac_mode(HVACMode.HEAT)
        self.assertIn("not on the base", str(ctx.exception))
        self.coordinator.async_send_command.assert_not_called()

        # Low water warning
        self.coordinator.data = {"is_docked": True, "mode": "S_NoWater", "no_water": True}
        with self.assertRaises(HomeAssistantError) as ctx:
            await climate.async_set_hvac_mode(HVACMode.HEAT)
        self.assertIn("low or no water", str(ctx.exception))
        self.coordinator.async_send_command.assert_not_called()

        # Safe on base with water
        self.coordinator.data = {"is_docked": True, "mode": "S_Off", "no_water": False}
        await climate.async_set_hvac_mode(HVACMode.HEAT)
        self.coordinator.async_send_command.assert_called_with("ss S_Heat")

    # 22. Climate set_temperature safety interlock
    async def test_climate_set_temperature_safety_interlock(self):
        """Test set_temperature sets target but refuses to resume heating if undocked or no water."""
        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        climate = StaggKettleClimate(self.coordinator, entry)
        self.coordinator.async_send_command = AsyncMock()
        self.coordinator.async_request_refresh = AsyncMock()

        # Undocked while in HEAT mode
        self.coordinator.data = {"is_docked": False, "mode": "S_Heat", "no_water": False}
        await climate.async_set_temperature(temperature=85)
        # Should set target temperature (85 C -> 185 F) but NOT send ss S_Heat
        self.coordinator.async_send_command.assert_called_once_with("setsettingd settempr 185")

    # 23. Button long_press_2 guarantees button release (2u)
    async def test_button_long_press_2_guarantees_release(self):
        """Test that long_press_2 always sends 2u release command even on failure."""
        from custom_components.staggassistant.button import StaggButton

        entry = MagicMock()
        entry.data = {"ip_address": "192.168.1.100", "name": "Kettle"}
        btn = StaggButton(self.coordinator, entry, "long_press_2", "Start Timer", "mdi:timer-play", "_long_press_2")

        commands_sent = []
        async def mock_send(cmd):
            commands_sent.append(cmd)
            return "OK"

        self.coordinator.async_send_command = mock_send
        self.coordinator.async_request_refresh = AsyncMock()

        with unittest.mock.patch("asyncio.sleep", new_callable=AsyncMock):
            await btn.async_press()
        self.assertEqual(commands_sent, ["2d", "2u"])

    # 24. Persistent storage HA elevation fallback
    async def test_storage_elevation_fallback(self):
        """Test coordinator falls back to hass.config.elevation if stored altitude is missing."""
        mock_hass = MagicMock()
        mock_hass.config.elevation = 450
        coord = StaggLinkCoordinator(mock_hass, "192.168.1.100", 15)
        coord._store.async_load = AsyncMock(return_value={"altitude_meters": 0})

        await coord.async_load_saved_settings()
        self.assertEqual(coord._cached_settings["altitude_meters"], 450)


if __name__ == "__main__":
    unittest.main()
