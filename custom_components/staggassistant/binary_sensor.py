"""Support for Fellow Stagg EKG Pro binary sensors."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StaggBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Stagg binary sensor entity."""

    key: str


BINARY_SENSOR_DESCRIPTIONS: tuple[StaggBinarySensorDescription, ...] = (
    StaggBinarySensorDescription(
        key="is_docked",
        translation_key="is_docked",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    StaggBinarySensorDescription(
        key="no_water",
        translation_key="no_water",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    StaggBinarySensorDescription(
        key="target_reached",
        translation_key="target_reached",
    ),
    StaggBinarySensorDescription(
        key="in_pre_boil",
        translation_key="in_pre_boil",
        entity_registry_enabled_default=False,
    ),
    StaggBinarySensorDescription(
        key="is_heating",
        translation_key="is_heating",
        device_class=BinarySensorDeviceClass.HEAT,
    ),
    StaggBinarySensorDescription(
        key="is_holding",
        translation_key="is_holding",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            StaggBinarySensor(coordinator, entry, desc)
            for desc in BINARY_SENSOR_DESCRIPTIONS
        ]
    )


class StaggBinarySensor(StaggEntity, BinarySensorEntity):
    """Representation of a Stagg EKG Pro binary sensor."""

    entity_description: StaggBinarySensorDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

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
            return (
                "Heat" in mode
                or mode in ("S_StartupToTempr", "S_PreBoil")
                or "High" in mode
            )
        if key == "is_holding":
            mode = str(self.coordinator.data.get("mode", ""))
            return mode.startswith("S_Hold")

        return None
