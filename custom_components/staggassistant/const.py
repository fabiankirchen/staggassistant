from datetime import timedelta

DOMAIN = "staggassistant"
CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_EXTENDED_ENTITIES = "enable_extended_entities"

# Default fallback interval in seconds if not configured during setup
DEFAULT_SCAN_INTERVAL = 15 
DEFAULT_ENABLE_EXTENDED_ENTITIES = False

CORE_PLATFORMS = ["climate", "sensor", "binary_sensor", "button"]
EXTENDED_PLATFORMS = ["switch", "number", "select"]
PLATFORMS = CORE_PLATFORMS + EXTENDED_PLATFORMS
