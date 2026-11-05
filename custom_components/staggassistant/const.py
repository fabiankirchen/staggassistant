from datetime import timedelta

DOMAIN = "staggassistant"
CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_EXTENDED_ENTITIES = "enable_extended_entities"
CONF_DEVICE_ID = "device_id"
CONF_WIFI_MAC = "wifi_mac"
CONF_BLE_ADDRESS = "ble_address"

# BLE GATT characteristics exposed by the Stagg EKG Pro operational service.
BLE_STATUS_UUID = "2291c4b4-5d7f-4477-a88b-b266edb97142"
BLE_IDENTITY_UUID = "2291c4b9-5d7f-4477-a88b-b266edb97142"
BLE_NAME_UUID = "2291c4b8-5d7f-4477-a88b-b266edb97142"
BLE_FIRMWARE_UUID = "2291c4b7-5d7f-4477-a88b-b266edb97142"

# Default fallback interval in seconds if not configured during setup
DEFAULT_SCAN_INTERVAL = 15 
DEFAULT_ENABLE_EXTENDED_ENTITIES = False

CORE_PLATFORMS = ["climate", "sensor", "binary_sensor", "button"]
EXTENDED_PLATFORMS = ["switch", "number", "select"]
PLATFORMS = CORE_PLATFORMS + EXTENDED_PLATFORMS


def get_stable_id(entry) -> str:
    """Return the stable identifier used for entity/device registry IDs.

    Older installations used the IP address as the entity identity.  The value
    is now persisted in the config entry so changing the IP address no longer
    creates a second set of entities.
    """
    data = getattr(entry, "data", {}) or {}
    stable_id = data.get(CONF_DEVICE_ID)
    if stable_id:
        return str(stable_id)
    return str(data.get(CONF_IP_ADDRESS, "")).replace(".", "_")


def get_device_identifier(entry) -> str:
    """Return the device registry identifier for a config entry."""
    return f"stagglink_{get_stable_id(entry)}"
