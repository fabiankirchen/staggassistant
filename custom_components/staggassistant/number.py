"""Support for Fellow Stagg EKG Pro numbers."""
import logging
from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import UnitOfLength, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink numbers from a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]

    numbers = [
        StaggNumber(
            coordinator,
            entry,
            "hold_time_minutes",
            "Hold Time Duration",
            0,
            60,
            1,
            UnitOfTime.MINUTES,
            "mdi:timer-sand",
            lambda val: f"setsetting hold {int(val)}",
        ),
        StaggNumber(
            coordinator,
            entry,
            "altitude_meters",
            "Altitude Setting",
            0,
            3000,
            1,
            UnitOfLength.METERS,
            "mdi:elevation-rise",
            lambda val: f"setaltitudem {int(val)}",
        ),
        StaggNumber(
            coordinator,
            entry,
            "chime_volume",
            "Chime Volume",
            0,
            10,
            1,
            None,
            "mdi:volume-high",
            lambda val: f"setsetting chime {int(val)}",
        ),
        StaggNumber(
            coordinator,
            entry,
            "schedule_temperature",
            "Schedule Temperature",
            40,
            100,
            0.5,
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer-auto",
            lambda val: f"setsetting schtempr {round(val * 1.8 + 32)}",
            device_class=NumberDeviceClass.TEMPERATURE,
        ),
    ]

    async_add_entities(numbers, True)


class StaggNumber(CoordinatorEntity[StaggLinkCoordinator], NumberEntity):
    """Representation of a Stagg EKG Pro number configuration."""

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry,
        key: str,
        name_suffix: str,
        min_val: float,
        max_val: float,
        step_val: float,
        unit_of_measurement: str | None,
        icon: str,
        command_generator,
        device_class: NumberDeviceClass | None = None,
    ):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._key = key
        self._ip = entry.data["ip_address"]
        device_id = f"stagglink_{self._ip.replace('.', '_')}"

        self._attr_has_entity_name = True
        self._attr_translation_key = key
        self._attr_unique_id = f"stagg_{self._ip.replace('.', '_')}_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step_val
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon
        self._command_generator = command_generator
        self._attr_device_class = device_class

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get("name", "Stagg Kettle"),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}",
        )

    @property
    def native_value(self) -> float | None:
        """Return the value of the number."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        cmd = self._command_generator(value)
        await self.coordinator.async_send_command(cmd)
        await self.coordinator.async_request_refresh()
