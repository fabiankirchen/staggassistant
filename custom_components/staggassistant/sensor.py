"""Support for Fellow Stagg EKG Pro sensors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 0

_STATE_MODE_MAP: dict[str, str] = {
    "S_Off": "off",
    "S_Standby": "standby",
    "S_Heat": "heat",
    "S_StartupToTempr": "heating_to_target",
    "S_PreBoil": "pre_boil",
    "S_NoWater": "low_water",
    "S_FAIL": "fail",
    "S_OTA": "ota",
}


def _map_state_mode(raw_mode: Any) -> str | None:
    """Map raw kettle mode string to translated enum option."""
    if not raw_mode:
        return None
    mode = str(raw_mode)
    if not mode:
        return None
    if mode in _STATE_MODE_MAP:
        return _STATE_MODE_MAP[mode]
    if mode.startswith("S_Hold"):
        return "hold"
    return "unknown"


@dataclass(frozen=True, kw_only=True)
class StaggSensorDescription(SensorEntityDescription):
    """Describes a Stagg sensor entity."""

    key: str


SENSOR_DESCRIPTIONS: tuple[StaggSensorDescription, ...] = (
    StaggSensorDescription(
        key="current_temp",
        translation_key="current_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    StaggSensorDescription(
        key="target_temp",
        translation_key="target_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    StaggSensorDescription(
        key="boil_temp",
        translation_key="boil_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    StaggSensorDescription(
        key="state_mode",
        translation_key="state_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "off",
            "standby",
            "heat",
            "heating_to_target",
            "pre_boil",
            "hold",
            "low_water",
            "fail",
            "ota",
            "unknown",
        ],
    ),
    StaggSensorDescription(
        key="clock_time",
        translation_key="clock_time",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    StaggSensorDescription(
        key="schedule_time",
        translation_key="schedule_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    StaggSensorDescription(
        key="schedule_temperature",
        translation_key="schedule_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [StaggSensor(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS]
    )


class StaggSensor(StaggEntity, SensorEntity):
    """Representation of a Stagg EKG Pro sensor."""

    entity_description: StaggSensorDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        if key == "current_temp":
            return self.coordinator.data.get("temp")
        if key == "target_temp":
            return self.coordinator.data.get("target")
        if key == "boil_temp":
            return self.coordinator.data.get("boil_temp")
        if key == "state_mode":
            return _map_state_mode(self.coordinator.data.get("mode"))
        if key == "clock_time":
            return self.coordinator.data.get("clock_time")
        if key == "schedule_time":
            return self.coordinator.data.get("schedule_time")
        if key == "schedule_temperature":
            return self.coordinator.data.get("schedule_temperature")

        return None
