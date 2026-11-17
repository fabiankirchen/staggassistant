"""Discovery helpers for finding a Stagg EKG Pro on the local network.

The kettle advertises a BLE name of the form ``EKG-aa-bb-cc``.  The last three
octets are the last three octets of the kettle's Wi-Fi MAC address.  The
operational GATT status record (``c4b4``) also contains the current IPv4
address, so in most installations no network scanning is needed at all.

If the BLE status characteristic cannot be read, the helpers fall back to
matching the BLE name against the host's ARP table.  Manual IP entry remains
the final fallback.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import subprocess
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BLE_FIRMWARE_UUID,
    BLE_IDENTITY_UUID,
    BLE_NAME_UUID,
    BLE_STATUS_UUID,
)

_LOGGER = logging.getLogger(__name__)

KETTLE_NAME_RE = re.compile(
    r"^EKG-([0-9a-f]{2})-([0-9a-f]{2})-([0-9a-f]{2})$", re.IGNORECASE
)
MAC_RE = re.compile(r"^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.IGNORECASE)
HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)

# Advertised operational/provisioning service UUIDs.  Matching the name is
# enough for real kettles, but service UUIDs help with devices that omit the
# local name from an advertisement.
KETTLE_SERVICE_UUIDS = {
    "7aebf330-6cb1-46e4-b23b-7cc2262c605e",
    "2291c4b5-5d7f-4477-a88b-b266edb97142",
    "021a9004-0382-4aea-bff4-6b3f1c5adfb4",
}

MAX_ARP_HOSTS = 1024
ARP_POPULATE_WAIT = 2.5
BLE_CONNECT_TIMEOUT = 10


@dataclass(slots=True)
class KettleNetworkInfo:
    """Network identity read from a kettle."""

    ip: str
    wifi_mac: str | None = None
    ble_address: str | None = None
    name: str | None = None
    firmware: str | None = None
    ssid: str | None = None
    method: str = "manual"


@dataclass(slots=True)
class KettleBleDevice:
    """A kettle-shaped BLE advertisement."""

    address: str
    name: str
    rssi: int | None = None
    connectable: bool = True

    @property
    def label(self) -> str:
        """Return a human-readable label for a selector."""
        suffix = f" ({self.address}"
        if self.rssi is not None:
            suffix += f", {self.rssi} dBm"
        if not self.connectable:
            suffix += ", passive only"
        suffix += ")"
        return f"{self.name}{suffix}"


def is_valid_host(host: str) -> bool:
    """Validate if a string is a valid IPv4 address or hostname."""
    if not host or any(
        c in host for c in ("/", "?", "#", "@", " ", "\t", "\n", "\r", ":")
    ):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.version == 4
    except ValueError:
        pass
    if len(host) > 253:
        return False
    return bool(HOSTNAME_RE.match(host))


def normalize_mac(mac: str | None) -> str | None:
    """Return a lower-case, colon-separated MAC address."""
    if not mac:
        return None
    mac = mac.strip().lower().replace("-", ":")
    if not MAC_RE.match(mac):
        return None
    return ":".join(part.zfill(2) for part in mac.split(":"))


def name_suffix(name: str | None) -> str | None:
    """Return the last three MAC octets encoded in an ``EKG-aa-bb-cc`` name."""
    if not name:
        return None
    match = KETTLE_NAME_RE.match(name.strip())
    if not match:
        return None
    return ":".join(match.groups()).lower()


def is_kettle_ble_info(info) -> bool:
    """Return True when a Bluetooth service info looks like a Stagg EKG Pro."""
    name = getattr(info, "name", None) or ""
    if KETTLE_NAME_RE.match(name.strip()):
        return True
    advertisement = getattr(info, "advertisement", None)
    service_uuids = getattr(advertisement, "service_uuids", None) or []
    return bool({uuid.lower() for uuid in service_uuids} & KETTLE_SERVICE_UUIDS)


def async_get_kettle_ble_devices(hass: HomeAssistant) -> list[KettleBleDevice]:
    """Return currently discovered kettle BLE devices.

    Home Assistant's Bluetooth manager scans continuously, so this reads its
    cache.  The caller can wait briefly before calling this to give a freshly
    powered kettle time to advertise.
    """
    try:
        from homeassistant.components import bluetooth
    except ImportError:  # pragma: no cover - core always provides bluetooth
        return []

    try:
        infos = bluetooth.async_discovered_service_info(hass, connectable=False)
    except Exception:  # pragma: no cover - Bluetooth may not be configured
        _LOGGER.debug("Bluetooth integration is not available", exc_info=True)
        return []

    devices: dict[str, KettleBleDevice] = {}
    for info in infos:
        if not is_kettle_ble_info(info):
            continue
        address = getattr(info, "address", None)
        if not address:
            continue
        name = getattr(info, "name", None) or f"Stagg Kettle ({address})"
        rssi = getattr(info, "rssi", None)
        connectable = bool(getattr(info, "connectable", True))
        devices[address] = KettleBleDevice(
            address=address,
            name=name,
            rssi=rssi,
            connectable=connectable,
        )

    return sorted(
        devices.values(),
        key=lambda device: (
            not device.name.upper().startswith("EKG-"),
            device.name,
        ),
    )


async def async_get_kettle_ble_device_map(
    hass: HomeAssistant, wait: float = 0
) -> dict[str, str]:
    """Return an address -> label map for a config-flow selector."""
    components = getattr(getattr(hass, "config", None), "components", None)
    if components is not None and "bluetooth" not in components:
        return {}
    if wait:
        await asyncio.sleep(wait)
    devices = async_get_kettle_ble_devices(hass)
    if not devices:
        # Give a freshly powered kettle time to advertise.
        await asyncio.sleep(8)
        devices = async_get_kettle_ble_devices(hass)
    return {device.address: device.label for device in devices}


def parse_status_record(data: bytes) -> dict:
    """Parse the 39-byte operational status record (characteristic ``c4b4``).

    Layout observed on firmware 1.1.7x/1.2.26:
      bytes 0-3   IPv4 address, network byte order
      bytes 4-5   status counter
      bytes 6-37  SSID / status payload (NUL padded)
      byte 38     status flag
    """
    result: dict = {}
    if len(data) >= 4:
        try:
            ip = str(ipaddress.IPv4Address(bytes(data[:4])))
        except ValueError:
            ip = None
        if ip and ip not in ("0.0.0.0", "255.255.255.255"):
            result["ip"] = ip
    if len(data) >= 6:
        result["counter"] = int.from_bytes(data[4:6], "big")
    if len(data) >= 38:
        raw_ssid = bytes(data[6:38]).split(b"\x00", 1)[0]
        result["ssid"] = raw_ssid.decode("utf-8", errors="ignore")
    if len(data) >= 39:
        result["status"] = data[38]
    return result


def _decode_identity(data: bytes) -> str | None:
    """Decode a NUL-padded identity characteristic."""
    if not data:
        return None
    value = bytes(data).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    return value.strip() or None


async def async_read_ble_identity(
    hass: HomeAssistant, address: str
) -> KettleNetworkInfo | None:
    """Connect to the kettle over BLE and read its network identity."""
    try:
        from homeassistant.components import bluetooth
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
    except ImportError:  # pragma: no cover - part of Home Assistant core
        return None

    try:
        ble_device = bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )
    except Exception:  # pragma: no cover - Bluetooth not configured
        _LOGGER.debug("Could not look up BLE device %s", address, exc_info=True)
        return None
    if ble_device is None:
        _LOGGER.debug("BLE device %s is not currently connectable", address)
        return None

    client = None
    try:
        client = await establish_connection(
            BleakClient,
            ble_device,
            "StaggAssistant discovery",
            max_attempts=2,
            timeout=BLE_CONNECT_TIMEOUT,
        )
        status = await client.read_gatt_char(BLE_STATUS_UUID)
        parsed = parse_status_record(status)
        if "ip" not in parsed:
            return None

        info = KettleNetworkInfo(
            ip=parsed["ip"],
            ble_address=address,
            ssid=parsed.get("ssid"),
            method="bluetooth",
        )
        for attribute, uuid in (
            ("wifi_mac", BLE_IDENTITY_UUID),
            ("name", BLE_NAME_UUID),
            ("firmware", BLE_FIRMWARE_UUID),
        ):
            try:
                value = _decode_identity(await client.read_gatt_char(uuid))
            except Exception:
                continue
            if not value:
                continue
            if attribute == "wifi_mac":
                mac = normalize_mac(value)
                if mac:
                    info.wifi_mac = mac
            else:
                setattr(info, attribute, value)
        return info
    except Exception as err:
        _LOGGER.debug("Could not read BLE status from %s: %s", address, err)
        return None
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass


def _mac_candidates(name: str | None, address: str | None) -> set[str]:
    """Build plausible Wi-Fi MAC addresses from the BLE name/address."""
    candidates: set[str] = set()
    suffix = name_suffix(name)
    ble_mac = normalize_mac(address)

    if suffix:
        candidates.add(suffix)
        octets = suffix.split(":")
        try:
            last = int(octets[2], 16)
        except ValueError:
            last = None
        if last is not None:
            for delta in (-2, -1, 1, 2):
                value = (last + delta) % 256
                candidates.add(":".join([octets[0], octets[1], f"{value:02x}"]))
        if ble_mac:
            # Same Espressif OUI / prefix, Wi-Fi suffix from the BLE name.
            candidates.add(":".join(ble_mac.split(":")[:3] + octets))

    if ble_mac:
        candidates.add(ble_mac)
        prefix = ble_mac.split(":")[:5]
        try:
            last = int(ble_mac.split(":")[5], 16)
        except (IndexError, ValueError):
            last = None
        if last is not None:
            for delta in (-2, -1, 1, 2):
                value = (last + delta) % 256
                candidates.add(":".join(prefix + [f"{value:02x}"]))

    return candidates


def _read_arp_table_sync() -> dict[str, str]:
    """Read the ARP/neighbour table without blocking the event loop."""
    entries: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                parts = line.split()
                if len(parts) < 4:
                    continue
                mac = normalize_mac(parts[3])
                if mac and mac != "00:00:00:00:00:00":
                    entries[parts[0]] = mac
    except OSError:
        pass
    if entries:
        return entries

    for command in (["ip", "neigh", "show"], ["arp", "-an"]):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if command[0] == "ip":
            for line in completed.stdout.splitlines():
                parts = line.split()
                if len(parts) < 5 or parts[1] != "dev":
                    continue
                ip_part, mac_part = parts[0], parts[4]
                mac = normalize_mac(mac_part)
                if mac:
                    entries[ip_part] = mac
        else:
            for line in completed.stdout.splitlines():
                match = re.search(r"\(([^)]+)\)\s+at\s+([0-9a-f:]+)", line, re.I)
                if not match:
                    continue
                mac = normalize_mac(match.group(2))
                if mac:
                    entries[match.group(1)] = mac
        if entries:
            break
    return entries


async def async_read_arp_table(hass: HomeAssistant) -> dict[str, str]:
    """Read the host ARP/neighbour table."""
    return await hass.async_add_executor_job(_read_arp_table_sync)


def _populate_arp_sync(targets: set[str]) -> None:
    """Send a tiny UDP datagram to each target so the kernel resolves ARP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        for target in targets:
            try:
                sock.sendto(b"", (target, 80))
            except OSError:
                continue
    finally:
        sock.close()


async def async_populate_arp(hass: HomeAssistant) -> None:
    """Populate the local ARP cache for the directly attached IPv4 network(s)."""
    try:
        from homeassistant.components.network import async_get_adapters
    except ImportError:  # pragma: no cover
        return

    try:
        adapters = await async_get_adapters(hass)
    except Exception:
        _LOGGER.debug("Could not read network adapters", exc_info=True)
        return

    targets: set[str] = set()
    for adapter in adapters:
        if not adapter.get("enabled"):
            continue
        for ipv4 in adapter.get("ipv4", []):
            try:
                interface = ipaddress.ip_interface(
                    f"{ipv4['address']}/{ipv4['network_prefix']}"
                )
            except (KeyError, ValueError):
                continue
            if interface.ip.is_loopback or interface.ip.is_link_local:
                continue
            network = interface.network
            # Very large subnets are not useful for a local ARP probe; limit
            # the probe to the local /24 while still checking the ARP table
            # for all entries.
            if network.prefixlen < 24:
                network = ipaddress.ip_network(f"{interface.ip}/24", strict=False)
            if network.num_addresses > MAX_ARP_HOSTS:
                continue
            targets.update(str(host) for host in network.hosts())

    if not targets:
        return

    try:
        await hass.async_add_executor_job(_populate_arp_sync, targets)
    except Exception:
        _LOGGER.debug("Could not populate ARP cache", exc_info=True)
        return
    await asyncio.sleep(ARP_POPULATE_WAIT)


async def async_resolve_ip_via_arp(
    hass: HomeAssistant, name: str | None, address: str | None
) -> list[str]:
    """Find candidate IP addresses by matching BLE identity against ARP."""
    candidates = _mac_candidates(name, address)
    if not candidates:
        return []

    arp_table = await async_read_arp_table(hass)
    matches = [
        ip for ip, mac in arp_table.items() if normalize_mac(mac) in candidates
    ]
    if matches:
        return matches

    # The kettle may simply not have been contacted recently.  Probe the local
    # subnet once and try again.
    await async_populate_arp(hass)
    arp_table = await async_read_arp_table(hass)
    return [ip for ip, mac in arp_table.items() if normalize_mac(mac) in candidates]


async def _read_response_text(response, limit: int = 65536) -> str:
    """Read response text up to a byte limit safely."""
    if hasattr(response, "read"):
        raw = await response.read()
        if isinstance(raw, bytes):
            return raw[:limit].decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw[:limit]
    if hasattr(response, "text"):
        txt = await response.text()
        return txt[:limit]
    return ""


async def async_validate_kettle(hass: HomeAssistant, host: str) -> str | None:
    """Validate a host and confirm it answers like a Stagg EKG Pro.

    Returns ``None`` on success or a translation error key on failure.
    """
    host = (host or "").strip()
    if not is_valid_host(host):
        return "invalid_ip"

    session = async_get_clientsession(hass)

    try:
        temp_url = f"http://{host}/temp"
        try:
            async with asyncio.timeout(5):
                async with session.get(temp_url) as response:
                    if response.status == 200:
                        raw_text = await _read_response_text(response, 65536)
                        sanitized = re.sub(
                            r":\s*[-+]?nan\b",
                            ": null",
                            raw_text,
                            flags=re.IGNORECASE,
                        )
                        data = json.loads(sanitized)
                        if isinstance(data, dict) and "temp" in data and (
                            "state" in data or "temp_set" in data
                        ):
                            return None
        except (asyncio.TimeoutError, ValueError, TypeError):
            pass
        except Exception:
            pass

        cli_url = f"http://{host}/cli?cmd=state"
        try:
            async with asyncio.timeout(5):
                async with session.get(cli_url) as response:
                    if response.status == 200:
                        text = await _read_response_text(response, 65536)
                        if "mode=" in text or "tempr=" in text:
                            return None
                        return "invalid_auth"
                    return "cannot_connect"
        except (asyncio.TimeoutError, Exception):
            return "cannot_connect"
    except Exception:
        return "cannot_connect"

    return "cannot_connect"


async def async_resolve_kettle(
    hass: HomeAssistant, address: str
) -> KettleNetworkInfo | None:
    """Resolve a BLE address to a kettle network identity.

    Tries the BLE status characteristic first, then ARP, and validates the
    resulting IP over HTTP before returning it.
    """
    ble_info = None
    try:
        from homeassistant.components import bluetooth

        ble_info = bluetooth.async_last_service_info(
            hass, address, connectable=False
        )
    except Exception:
        pass

    name = getattr(ble_info, "name", None) if ble_info else None

    identity = await async_read_ble_identity(hass, address)
    if identity is not None and await async_validate_kettle(hass, identity.ip) is None:
        if not identity.name:
            identity.name = name
        return identity

    try:
        arp_ips = await async_resolve_ip_via_arp(hass, name, address)
    except Exception:
        _LOGGER.debug("ARP lookup for %s failed", address, exc_info=True)
        arp_ips = []

    for ip in arp_ips:
        if await async_validate_kettle(hass, ip) is None:
            return KettleNetworkInfo(
                ip=ip,
                ble_address=address,
                name=name,
                method="arp",
            )

    return None
