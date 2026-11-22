"""Unit tests for safety blocklist and command verification."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

import tests  # noqa: F401 - installs Home Assistant test stubs

from custom_components.staggassistant.api import ALLOWED_COMMAND_PATTERNS
from custom_components.staggassistant.coordinator import (
    BLOCKED_COMMANDS,
    StaggLinkCoordinator,
)


class TestKettleSafety(unittest.IsolatedAsyncioTestCase):
    """Ensure dangerous direct GPIO and wipe commands are blocked."""

    def setUp(self) -> None:
        self.mock_hass = MagicMock()
        self.coordinator = StaggLinkCoordinator(self.mock_hass, "192.168.1.100", 15)

    async def test_all_18_blocked_commands_present_and_rejected(self) -> None:
        """Verify all 18 BLOCKED_COMMANDS are defined and raise HomeAssistantError."""
        from homeassistant.exceptions import HomeAssistantError

        expected_blocked = {
            "heaton",
            "heatoff",
            "warmon",
            "warmoff",
            "warmduty",
            "gpioset",
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
        }
        self.assertEqual(len(BLOCKED_COMMANDS), 18)
        self.assertEqual(BLOCKED_COMMANDS, expected_blocked)

        for cmd in sorted(BLOCKED_COMMANDS):
            with self.subTest(cmd=cmd):
                with self.assertRaises(HomeAssistantError):
                    await self.coordinator.async_send_command(cmd)

    async def test_blocked_dangerous_commands(self) -> None:
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

    async def test_trailing_newline_injection_blocked_by_z_anchor(self) -> None:
        """Verify trailing newlines cannot bypass ALLOWED_COMMAND_PATTERNS (\\Z protection)."""
        from homeassistant.exceptions import HomeAssistantError

        for payload in ("ss S_Heat\n", "1\n"):
            with self.subTest(payload=payload):
                self.assertFalse(
                    any(p.match(payload) for p in ALLOWED_COMMAND_PATTERNS)
                )
                with self.assertRaises(HomeAssistantError):
                    await self.coordinator.async_send_command(payload)

    async def test_allowed_safe_commands(self) -> None:
        """Verify that legitimate state machine commands pass the safety guard."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.read = AsyncMock(return_value=b"OK")
        mock_response.text = AsyncMock(return_value="OK")

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response

        self.coordinator.session.get = MagicMock(
            side_effect=lambda url, **kwargs: mock_cm
        )

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

    async def test_disallowed_by_strict_allowlist(self) -> None:
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
