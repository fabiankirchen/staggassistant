from datetime import timedelta

DOMAIN = "staggassistant"
CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"

# Default fallback interval in seconds if not configured during setup
DEFAULT_SCAN_INTERVAL = 15 

PLATFORMS = ["climate", "sensor", "switch", "number", "select", "button"]
