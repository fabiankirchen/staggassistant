"""Support for Fellow Stagg EKG Pro binary sensors."""
import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES, DOMAIN
from .coordinator import StaggLinkCoordinator

_LOGGER = logging.getLogger(__name__)

EXTENDED_BINARY_SENSOR_KEYS = {"in_pre_boil"}


@dataclass(frozen=True, kw_only=True)
class StaggBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Stagg binary sensor entity."""

    key: str
    name: str


BINARY_SENSOR_DESCRIPTIONS: tuple[StaggBinarySensorDescription, ...] = (
    StaggBinarySensorDescription(
        key="is_docked",
        translation_key="is_docked",
        name="Docked",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:kettle",
    ),
    StaggBinarySensorDescription(
        key="no_water",
        translation_key="no_water",
        name="Low Water Warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-alert",
    ),
    StaggBinarySensorDescription(
        key="target_reached",
        translation_key="target_reached",
        name="Target Temperature Reached",
        icon="mdi:thermometer-check",
    ),
    StaggBinarySensorDescription(
        key="in_pre_boil",
        translation_key="in_pre_boil",
        name="Pre-Boil Active",
        icon="mdi:water-boiler",
        entity_registry_enabled_default=False,
    ),
    StaggBinarySensorDescription(
        key="is_heating",
        translation_key="is_heating",
        name="Heating Active",
        icon="mdi:fire",
    ),
    StaggBinarySensorDescription(
        key="is_holding",
        translation_key="is_holding",
        name="Hold Active",
        icon="mdi:timer-sand",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up StaggLink binary sensors from a config entry."""
    coordinator: StaggLinkCoordinator = hass.data[DOMAIN][entry.entry_id]
    enable_extended = entry.options.get(
        CONF_ENABLE_EXTENDED_ENTITIES,
        entry.data.get(CONF_ENABLE_EXTENDED_ENTITIES, DEFAULT_ENABLE_EXTENDED_ENTITIES),
    )
    entities = [
        StaggBinarySensor(coordinator, entry, desc)
        for desc in BINARY_SENSOR_DESCRIPTIONS
        if enable_extended or desc.key not in EXTENDED_BINARY_SENSOR_KEYS
    ]
    async_add_entities(entities, True)


class StaggBinarySensor(CoordinatorEntity[StaggLinkCoordinator], BinarySensorEntity):
    """Representation of a Stagg EKG Pro binary sensor."""

    entity_description: StaggBinarySensorDescription

    def __init__(self, coordinator: StaggLinkCoordinator, entry, description: StaggBinarySensorDescription):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._ip = entry.data["ip_address"]
        device_id = f"stagglink_{self._ip.replace('.', '_')}"

        self._attr_has_entity_name = True
        self._attr_translation_key = description.key
        self._attr_unique_id = f"stagg_{self._ip.replace('.', '_')}_{description.key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get("name", "Stagg Kettle"),
            manufacturer="Fellow",
            model="Stagg EKG Pro",
            configuration_url=f"http://{self._ip}",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        if key == "is_docked":
            return bool(self.coordinator.data.get("is_docked"))
        if key == "no_water":
            mode = str(self.coordinator.data.get("mode", ""))
            return bool(self.coordinator.data.get("no_water")) or mode == "S_NoWater"
        if key == "target_reached":
            return bool(self.coordinator.data.get("target_reached"))
        if key == "in_pre_boil":
            return bool(self.coordinator.data.get("in_pre_boil"))
        if key == "is_heating":
            mode = str(self.coordinator.data.get("mode", ""))
            return "Heat" in mode or mode == "S_StartupToTempr" or "High" in mode
        if key == "is_holding":
            mode = str(self.coordinator.data.get("mode", ""))
            return mode.startswith("S_Hold")

        return None
