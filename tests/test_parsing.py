"""Unit tests for response parsing in coordinator."""
import tests  # noqa: F401 - installs Home Assistant test stubs
import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.staggassistant.coordinator import StaggLinkCoordinator

SAMPLE_STATE_OFF = """
            <form action="cli" method="GET">
            <label for="x">CLI Command:</label><br>
            <input type="text" id="cli" name="cmd"><br>
            </form>         
            I (991010) Cli: cmd len 5: 'state'
I (991010) Main: OTA vd 1 ldt 121 ldr 7 dip 0 waitsec 85411 numf 1 wgi 1 iot r 0
scrname=wnd
value=50662426
mode=S_Off
tempr=50.491463 C
temprB=99.459999 C
temprT=96.111115 C
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
temps=205 F
tempsc=192 2C
units=1
clock=12:26
ticks=991020 0 989274
ble conn=0
I (991040) Cli: command 'state' ret 0
"""

SAMPLE_STATE_HEAT_DRY_BOIL = """
            I (1640440) Cli: cmd len 5: 'state'
mode=S_Heat
tempr=88.157149 C
temprB=99.459999 C
temprT=83.888885 C
ketl= ho 0 wd 0 nw 1 ipb 1 bf 0 tr 1
temps=183 F
tempsc=192 2C
units=1
clock=8:05
"""

SAMPLE_STATE_LIFTED = """
mode=S_Off
tempr=nan
temprB=100.000000 C
temprT=93.000000 C
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
clock=14:50
"""

SAMPLE_SETTINGS = """
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


class TestCoordinatorParsing(unittest.IsolatedAsyncioTestCase):
    """Test response parsing and flag extraction."""

    def setUp(self):
        self.mock_hass = MagicMock()
        self.coordinator = StaggLinkCoordinator(self.mock_hass, "192.168.1.100", 15)

    def _mock_session_responses(self, state_text, settings_text):
        resp_state = AsyncMock()
        resp_state.raise_for_status = MagicMock()
        resp_state.text = AsyncMock(return_value=state_text)

        resp_settings = AsyncMock()
        resp_settings.raise_for_status = MagicMock()
        resp_settings.text = AsyncMock(return_value=settings_text)

        cm_state = AsyncMock()
        cm_state.__aenter__.return_value = resp_state

        cm_settings = AsyncMock()
        cm_settings.__aenter__.return_value = resp_settings

        def side_effect(url, params=None):
            if "cmd=state" in url or (params and params.get("cmd") == "state"):
                return cm_state
            return cm_settings

        self.coordinator.session.get = MagicMock(side_effect=side_effect)

    async def test_parse_normal_state_and_settings(self):
        """Test parsing valid state and settings output."""
        self._mock_session_responses(SAMPLE_STATE_OFF, SAMPLE_SETTINGS)

        data = await self.coordinator._async_update_data()

        self.assertAlmostEqual(data["temp"], 50.491463)
        self.assertAlmostEqual(data["target"], 96.111115)
        self.assertAlmostEqual(data["boil_temp"], 99.459999)
        self.assertEqual(data["mode"], "S_Off")
        self.assertEqual(data["clock_time"], "12:26")
        self.assertTrue(data["is_docked"])
        self.assertFalse(data["no_water"])
        self.assertFalse(data["target_reached"])
        self.assertFalse(data["in_pre_boil"])

        # Settings
        self.assertEqual(data["hold_time_minutes"], 45)
        self.assertEqual(data["pre_boil_enabled"], 1)
        self.assertEqual(data["chime_volume"], 7)
        self.assertEqual(data["altitude_meters"], 420)
        self.assertEqual(data["language"], 2)
        self.assertEqual(data["units"], "C")
        self.assertEqual(data["clock_mode"], 1)
        self.assertEqual(data["schedule_mode"], "repeat")
        self.assertEqual(data["schedule_time"], "07:15")
        self.assertEqual(data["schedule_temperature"], 85.0)

    async def test_parse_dry_boil_and_preboil(self):
        """Test parsing flags for low water / dry boil and pre-boil."""
        self._mock_session_responses(SAMPLE_STATE_HEAT_DRY_BOIL, SAMPLE_SETTINGS)

        data = await self.coordinator._async_update_data()

        self.assertEqual(data["mode"], "S_Heat")
        self.assertTrue(data["no_water"])
        self.assertTrue(data["target_reached"])
        self.assertTrue(data["in_pre_boil"])
        self.assertEqual(data["clock_time"], "08:05")

    async def test_parse_lifted_kettle(self):
        """Test that lifted kettle (nan temperature) marks is_docked as False."""
        self._mock_session_responses(SAMPLE_STATE_LIFTED, SAMPLE_SETTINGS)

        data = await self.coordinator._async_update_data()

        self.assertIsNone(data["temp"])
        self.assertFalse(data["is_docked"])


if __name__ == "__main__":
    unittest.main()
