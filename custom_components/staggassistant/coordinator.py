import logging
import re
import async_timeout
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

class StaggLinkCoordinator(DataUpdateCoordinator):
    """Zentrale Instanz zum Abrufen der Daten."""

    def __init__(self, hass, ip, update_interval_seconds):
        super().__init__(
            hass,
            _LOGGER,
            name="StaggLink Kettle",
            # Wir wandeln die Integer-Sekunden in ein timedelta um
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.ip = ip
        self.session = async_get_clientsession(hass)

    async def _async_update_data(self):
        """Daten von der CLI abrufen."""
        url = f"http://{self.ip}/cli?cmd=state"
        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(url)
                response.raise_for_status()
                text = await response.text()
                
                temp_match = re.search(r'tempr=([0-9.]+|nan)', text)
                target_match = re.search(r'temprT=([0-9.]+|nan)', text)
                mode_match = re.search(r'mode=([a-zA-Z0-9_]+)', text)
                
                if not temp_match or not target_match or not mode_match:
                    raise UpdateFailed(f"Parsing Fehler. Antwort: {text}")

                def parse_float(value):
                    if value == 'nan': return None
                    try: return float(value)
                    except: return None

                return {
                    "temp": float(temp_match.group(1)),
                    "target": float(target_match.group(1)),
                    "mode": mode_match.group(1)
                }

        except Exception as err:
            raise UpdateFailed(f"Verbindungsfehler: {err}")
