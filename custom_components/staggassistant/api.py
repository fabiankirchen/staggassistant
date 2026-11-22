"""HTTP client, safety validation, and protocol helpers for Fellow Stagg EKG Pro."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

import aiohttp

try:
    from yarl import URL as _YARL_URL
except ImportError:  # pragma: no cover - optional in standalone mock test env
    _YARL_URL = None

from .const import ESP32_COMMAND_COOLDOWN, LEGACY_TEMP_REPROBE_INTERVAL

_LOGGER = logging.getLogger(__name__)

HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z"
)

# Dangerous commands that bypass firmware safety, drive raw GPIOs, or wipe settings
BLOCKED_COMMANDS: frozenset[str] = frozenset(
    {
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
)

# Strict safety allowlist for legitimate commands (\Z prevents trailing newline bypass)
ALLOWED_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^ss (S_Heat|S_Off)\Z"),
    re.compile(r"^setsettingd settempr (?:1[0-9]{2}|20[0-9]|21[0-2])\Z"),
    re.compile(r"^setsetting hold ([0-9]|[1-5][0-9]|60)\Z"),
    re.compile(r"^setsetting boil [01]\Z"),
    re.compile(r"^setsetting chime ([0-9]|10)\Z"),
    re.compile(r"^setsetting language [0-6]\Z"),
    re.compile(r"^setsetting clockmode [0-2]\Z"),
    re.compile(r"^setsetting schedon [01]\Z"),
    re.compile(r"^setsetting repeat_sched [01]\Z", re.IGNORECASE),
    re.compile(r"^setsetting schtempr (?:1[0-9]{2}|20[0-9]|21[0-2])\Z"),
    re.compile(r"^setsetting schtime (?:[01]?[0-9]|2[0-3]):[0-5][0-9]\Z"),
    re.compile(r"^setaltitudem ([0-9]{1,3}|[12][0-9]{3}|3000)\Z"),
    re.compile(r"^setclock (?:[01]?[0-9]|2[0-3]) [0-5]?[0-9] [0-5]?[0-9]\Z"),
    re.compile(r"^(setdigital|setanalog|setunitsc|setunitsf|1|2|q|w|2d|2u)\Z"),
)

_TEMP_JSON_NAN_RE = re.compile(
    r'("(?:\\.|[^"\\])*")|(:\s*)[-+]?nan\b',
    re.IGNORECASE,
)
_CLI_TEMPR_RE = re.compile(r"(?i)\btempr(?![TB])\s*=\s*(-?[0-9.]+|[-+]?nan)")
_CLI_TEMPRT_RE = re.compile(r"(?i)\btemprT\s*=\s*(-?[0-9.]+|[-+]?nan)")
_CLI_MODE_RE = re.compile(r"\bmode\s*=\s*([a-zA-Z0-9_+-]+)")


class FirmwareMode(StrEnum):
    """Detected kettle HTTP API mode."""

    UNKNOWN = "unknown"
    MODERN_TEMP = "modern_temp"
    LEGACY_CLI = "legacy_cli"


class KettleSettings(TypedDict):
    """Persisted kettle settings (excluding volatile clock_time)."""

    hold_time_minutes: int
    hold_enabled: int
    pre_boil_enabled: int
    chime_enabled: int
    chime_volume: int
    altitude_meters: int
    language: int
    units: str
    clock_mode: int
    schedule_enabled: int
    schedule_mode: str
    schedule_time: str | None
    schedule_temperature: float | None


class KettleData(TypedDict):
    """Normalized state dictionary exposed by StaggLinkCoordinator."""

    temp: float | None
    target: float | None
    boil_temp: float | None
    mode: str
    is_docked: bool
    no_water: bool
    target_reached: bool
    in_pre_boil: bool
    hold_flag: bool
    hold_time_minutes: int
    hold_enabled: int
    pre_boil_enabled: int
    chime_enabled: int
    chime_volume: int
    altitude_meters: int
    language: int
    units: str
    clock_mode: int
    clock_time: str | None
    schedule_enabled: int
    schedule_mode: str
    schedule_time: str | None
    schedule_temperature: float | None


class StaggError(Exception):
    """Base exception for StaggAssistant API errors."""

    def __init__(
        self,
        message: str = "",
        translation_key: str | None = None,
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.translation_key = translation_key if translation_key is not None else (message or None)
        self.translation_placeholders = translation_placeholders


class StaggConnectionError(StaggError):
    """Error communicating with the kettle over HTTP."""


class StaggTimeoutError(StaggError):
    """Timeout communicating with the kettle over HTTP."""


class StaggInvalidResponseError(StaggError):
    """Kettle returned an unparseable or unexpected response."""


class StaggCommandNotAllowedError(StaggError):
    """Command rejected by safety blocklist or strict allowlist."""


@dataclass(slots=True)
class PollPayload:
    """Raw HTTP payloads collected during a single kettle poll."""

    temp_data: dict[str, Any] | None = None
    state_text: str | None = None
    settings_text: str = ""


def is_valid_host(host: str) -> bool:
    """Validate if a string is a safe IPv4 address or hostname."""
    if not host or any(
        c in host for c in ("/", "?", "#", "@", " ", "\t", "\n", "\r", ":")
    ):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if ip.version != 4:
            return False
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            return False
        return True

    if len(host) > 253:
        return False
    if all(part.isdigit() for part in host.split(".")):
        return False
    return bool(HOSTNAME_RE.match(host))


def parse_float(value: Any) -> float | None:
    """Parse float safely, handling None, NaN/-nan/+nan, and out-of-range readings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and "nan" in value.lower():
        return None
    try:
        val = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(val) or math.isinf(val) or not (-10 <= val <= 150):
        return None
    return val


def sanitize_temp_json(raw_text: str) -> str:
    """Replace unquoted NaN/-nan/+nan JSON values with null without touching strings."""

    def _replace(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return match.group(1)
        return f"{match.group(2)}null"

    return _TEMP_JSON_NAN_RE.sub(_replace, raw_text)


async def read_response_text(response: Any, limit: int = 65536) -> str:
    """Read response text up to byte limit safely without buffering unbounded bodies."""
    content = getattr(response, "content", None)
    if content is not None and callable(getattr(content, "read", None)):
        raw = await content.read(limit)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw[:limit]

    read_fn = getattr(response, "read", None)
    if callable(read_fn):
        raw = await read_fn()
        if isinstance(raw, bytes):
            return raw[:limit].decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw[:limit]

    text_fn = getattr(response, "text", None)
    if callable(text_fn):
        txt = await text_fn()
        if isinstance(txt, str):
            return txt[:limit]

    return ""


def validate_command(cmd: str) -> str:
    """Validate a kettle CLI command against safety blocklist and strict allowlist."""
    raw_cmd = cmd if isinstance(cmd, str) else ""
    if any(c in raw_cmd for c in ("\n", "\r", ";", "\x00")) or any(
        ord(c) < 32 for c in raw_cmd
    ):
        raise StaggCommandNotAllowedError(
            "Command contains forbidden characters.",
            translation_key="forbidden_characters",
        )

    clean_cmd = raw_cmd.strip()
    if not clean_cmd:
        raise StaggCommandNotAllowedError(
            "Empty command is not allowed.",
            translation_key="empty_command",
        )

    tokens = [t.lower() for t in clean_cmd.split()]
    if any(t in BLOCKED_COMMANDS for t in tokens) or clean_cmd.lower() == "ss":
        raise StaggCommandNotAllowedError(
            "Command not permitted by safety allowlist.",
            translation_key="command_not_allowed",
        )

    if not any(pattern.match(clean_cmd) for pattern in ALLOWED_COMMAND_PATTERNS):
        raise StaggCommandNotAllowedError(
            "Command not permitted by safety allowlist.",
            translation_key="command_not_allowed",
        )

    return clean_cmd


def build_cli_url(host: str, clean_cmd: str) -> str:
    """Build a safe /cli URL with the '+' separator expected by Fellow ESP32 CLI."""
    if not is_valid_host(host):
        raise ValueError(f"Invalid kettle host: {host}")
    encoded_cmd = "+".join(clean_cmd.split())
    if _YARL_URL is not None:
        base = str(_YARL_URL.build(scheme="http", host=host, path="/cli"))
    else:
        base = f"http://{host}/cli"
    return f"{base}?cmd={encoded_cmd}"


def build_temp_url(host: str) -> str:
    """Build a safe /temp URL."""
    if not is_valid_host(host):
        raise ValueError(f"Invalid kettle host: {host}")
    if _YARL_URL is not None:
        return str(_YARL_URL.build(scheme="http", host=host, path="/temp"))
    return f"http://{host}/temp"


def _has_cli_state_fields(state_text: str) -> bool:
    """Return True if a /cli?cmd=state response contains required state fields."""
    return bool(
        _CLI_TEMPR_RE.search(state_text)
        and _CLI_TEMPRT_RE.search(state_text)
        and _CLI_MODE_RE.search(state_text)
    )


class StaggKettleClient:
    """Async HTTP client for a Fellow Stagg EKG Pro kettle."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        cooldown: float = ESP32_COMMAND_COOLDOWN,
    ) -> None:
        """Initialize the kettle HTTP client."""
        if not is_valid_host(host):
            raise ValueError(f"Invalid kettle host: {host}")
        self.session = session
        self.host = host
        self._cooldown = cooldown
        self._lock = asyncio.Lock()
        self._last_request_monotonic: float = 0.0
        self.firmware_mode: FirmwareMode = FirmwareMode.UNKNOWN
        self._last_temp_probe_monotonic: float = 0.0
        self.prtsettings_supported: bool | None = None

    async def _respect_cooldown(self) -> None:
        """Sleep remaining ESP32 inter-request cooldown (caller must hold self._lock)."""
        if self._cooldown > 0 and self._last_request_monotonic > 0:
            elapsed = time.monotonic() - self._last_request_monotonic
            remaining = self._cooldown - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)

    async def async_send_command(self, cmd: str) -> str:
        """Validate and send a CLI command to the kettle."""
        clean_cmd = validate_command(cmd)
        url = build_cli_url(self.host, clean_cmd)

        try:
            async with self._lock:
                await self._respect_cooldown()
                try:
                    async with asyncio.timeout(10):
                        async with self.session.get(url, allow_redirects=False) as response:
                            response.raise_for_status()
                            return await read_response_text(response, 65536)
                finally:
                    self._last_request_monotonic = time.monotonic()
        except TimeoutError as err:
            raise StaggTimeoutError(
                f"Timeout communicating with Stagg kettle at {self.host}",
                translation_key="timeout",
            ) from err
        except aiohttp.ClientError as err:
            raise StaggConnectionError(
                str(err),
                translation_key="connection_error",
            ) from err

    async def async_fetch_temp_json(self) -> dict[str, Any] | None:
        """Fetch and parse the /temp JSON endpoint (Firmware 1.2.26+).

        Raises StaggTimeoutError / StaggConnectionError on transport failures so
        offline kettles fail fast without waiting on a redundant /cli retry.
        Returns None when the endpoint is unsupported or returns non-JSON data.
        """
        url = build_temp_url(self.host)
        try:
            try:
                async with asyncio.timeout(6):
                    async with self.session.get(url, allow_redirects=False) as response:
                        if response.status != 200:
                            return None
                        raw_text = await read_response_text(response, 65536)
            finally:
                self._last_request_monotonic = time.monotonic()
        except TimeoutError as err:
            raise StaggTimeoutError(
                f"Timeout fetching /temp from {self.host}",
                translation_key="timeout",
            ) from err
        except aiohttp.ClientError as err:
            raise StaggConnectionError(
                str(err),
                translation_key="connection_error",
            ) from err

        try:
            sanitized = sanitize_temp_json(raw_text)
            data = json.loads(sanitized)
        except (ValueError, TypeError):
            return None

        if isinstance(data, dict) and "temp" in data and ("temp_set" in data or "state" in data):
            return data
        return None

    async def async_fetch_poll_payload(self) -> PollPayload:
        """Fetch raw state and optional settings for a single coordinator refresh."""
        async with self._lock:
            try:
                async with asyncio.timeout(20):
                    temp_data: dict[str, Any] | None = None
                    state_text: str | None = None

                    should_probe_temp = (
                        self.firmware_mode != FirmwareMode.LEGACY_CLI
                        or (time.monotonic() - self._last_temp_probe_monotonic)
                        >= LEGACY_TEMP_REPROBE_INTERVAL
                    )

                    if should_probe_temp:
                        await self._respect_cooldown()
                        temp_data = await self.async_fetch_temp_json()
                        if temp_data is not None:
                            self.firmware_mode = FirmwareMode.MODERN_TEMP
                        elif self.firmware_mode in (
                            FirmwareMode.UNKNOWN,
                            FirmwareMode.LEGACY_CLI,
                        ):
                            self._last_temp_probe_monotonic = time.monotonic()

                    if temp_data is None:
                        state_url = build_cli_url(self.host, "state")
                        await self._respect_cooldown()
                        try:
                            try:
                                async with asyncio.timeout(6):
                                    async with self.session.get(
                                        state_url, allow_redirects=False
                                    ) as response:
                                        response.raise_for_status()
                                        state_text = await read_response_text(response, 65536)
                            finally:
                                self._last_request_monotonic = time.monotonic()
                        except TimeoutError as err:
                            raise StaggTimeoutError(
                                f"Timeout fetching state from {self.host}",
                                translation_key="timeout",
                            ) from err
                        except aiohttp.ClientError as err:
                            raise StaggConnectionError(
                                str(err),
                                translation_key="connection_error",
                            ) from err

                        if not _has_cli_state_fields(state_text):
                            if '<form action="cli"' in state_text:
                                raise StaggInvalidResponseError(
                                    "Kettle CLI returned only HTML form without state data, "
                                    "and /temp JSON endpoint failed."
                                )
                            raise StaggInvalidResponseError(
                                f"Parsing error. Incomplete response: {state_text[:120]!r}"
                            )

                        self.firmware_mode = FirmwareMode.LEGACY_CLI

                    settings_text = ""
                    if self.prtsettings_supported is not False:
                        settings_url = build_cli_url(self.host, "prtsettings")
                        await self._respect_cooldown()
                        settings_status: Any = None
                        try:
                            try:
                                async with asyncio.timeout(6):
                                    async with self.session.get(
                                        settings_url, allow_redirects=False
                                    ) as resp_settings:
                                        settings_status = getattr(resp_settings, "status", None)
                                        resp_settings.raise_for_status()
                                        settings_text = await read_response_text(
                                            resp_settings, 65536
                                        )
                            finally:
                                self._last_request_monotonic = time.monotonic()
                        except Exception as err:
                            _LOGGER.debug("Could not fetch prtsettings: %s", err)
                            settings_text = ""

                        has_settings = (
                            "st:" in settings_text
                            or re.search(r"\bhold\s*[:=]", settings_text) is not None
                        )
                        if has_settings:
                            self.prtsettings_supported = True
                        elif temp_data is not None and settings_status == 200:
                            # Firmware 1.2.26+ silenced textual output from /cli
                            self.prtsettings_supported = False

                    return PollPayload(
                        temp_data=temp_data,
                        state_text=state_text,
                        settings_text=settings_text,
                    )
            except TimeoutError as err:
                raise StaggTimeoutError(
                    f"Timeout polling kettle at {self.host}",
                    translation_key="timeout",
                ) from err
