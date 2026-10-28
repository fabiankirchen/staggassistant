"""Unit tests for safety blocklist and command verification."""
import tests  # noqa: F401 - installs Home Assistant test stubs
import unittest
from unittest.mock import AsyncMock, MagicMock

# Test safety blocklist from coordinator
from custom_components.staggassistant.coordinator import BLOCKED_COMMANDS, StaggLinkCoordinator


class TestKettleSafety(unittest.IsolatedAsyncioTestCase):
    """Ensure dangerous direct GPIO and wipe commands are blocked."""

    def setUp(self):
        self.mock_hass = MagicMock()
        self.coordinator = StaggLinkCoordinator(self.mock_hass, "192.168.1.100", 15)

    async def test_blocked_dangerous_commands(self):
        """Verify that direct hardware heater commands and wipe commands raise an error."""
        from homeassistant.exceptions import HomeAssistantError

        dangerous_samples = [
            "heaton",
            "HEATON",
            "heatoff",
            "warmon",
            "warmoff",
            "warmduty 50",
            "gpioset 12 1",
            "reset",
            "clrsettings",
            "wifierase",
            "wifioff",
            "provreset",
            "eraseotherpart",
            "adcsamples",
            "htest",
            "hperiod",
            "triactrace",
            "lpsleep",
            "lpnow",
            "ss",  # bare ss crashes/reboots kettle
            "  ss  ",
        ]

        for cmd in dangerous_samples:
            with self.subTest(cmd=cmd):
                with self.assertRaises(HomeAssistantError):
                    await self.coordinator.async_send_command(cmd)

    async def test_allowed_safe_commands(self):
        """Verify that legitimate state machine commands pass the safety guard."""
        # Mock session.get context manager
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.read = AsyncMock(return_value=b"OK")
        mock_response.text = AsyncMock(return_value="OK")

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response

        self.coordinator.session.get = MagicMock(return_value=mock_cm)

        safe_samples = [
            "ss S_Heat",
            "ss S_Off",
            "setsettingd settempr 104",
            "setsettingd settempr 185",
            "setsettingd settempr 212",
            "setsetting schtempr 104",
            "setsetting schtempr 190",
            "setsetting schtempr 212",
            "setsetting hold 0",
            "setsetting hold 30",
            "setsetting hold 60",
            "setsetting boil 0",
            "setsetting boil 1",
            "setsetting chime 0",
            "setsetting chime 10",
            "setsetting language 0",
            "setsetting language 6",
            "setsetting clockmode 0",
            "setsetting clockmode 2",
            "setsetting schedon 0",
            "setsetting schedon 1",
            "setsetting repeat_sched 0",
            "setsetting Repeat_sched 1",
            "setsetting schtime 07:30",
            "setsetting schtime 23:59",
            "setaltitudem 0",
            "setaltitudem 500",
            "setaltitudem 3000",
            "setdigital",
            "setanalog",
            "setunitsc",
            "setunitsf",
            "1",
            "2",
            "q",
            "w",
            "2d",
            "2u",
            "setclock 12 30 0",
            "setclock 0 0 0",
            "setclock 23 59 59",
        ]

        for cmd in safe_samples:
            with self.subTest(cmd=cmd):
                result = await self.coordinator.async_send_command(cmd)
                self.assertEqual(result, "OK")

    async def test_disallowed_by_strict_allowlist(self):
        """Verify commands outside the strict allowlist are blocked."""
        from homeassistant.exceptions import HomeAssistantError

        disallowed_samples = [
            "ss S_Hold",
            "setsetting settempr 185",
            "setsettingd settempr 90",
            "setsettingd settempr 250",
            "setsetting hold 61",
            "setsetting chime 11",
            "setsetting language 7",
            "setsetting clockmode 3",
            "setaltitudem 3001",
            "setsetting schtime 25:00",
            "setclock 25 0 0",
            "unknown_command",
            "foo",
        ]

        for cmd in disallowed_samples:
            with self.subTest(cmd=cmd):
                with self.assertRaises(HomeAssistantError) as cm:
                    await self.coordinator.async_send_command(cmd)
                self.assertIn("allowlist", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
