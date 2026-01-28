from datetime import timedelta

DOMAIN = "staggassistant"
CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval" # Neu

# Default Fallback, falls beim Setup nichts gewählt wird
DEFAULT_SCAN_INTERVAL = 15 

PLATFORMS = ["climate"]