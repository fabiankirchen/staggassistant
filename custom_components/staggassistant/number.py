"""Support for Fellow Stagg EKG Pro numbers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Any, cast

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class StaggNumberEntityDescription(NumberEntityDescription):
    """Describes a Stagg number entity."""

    command_fn: Callable[[float], str]


NUMBER_DESCRIPTIONS: tuple[StaggNumberEntityDescription, ...] = (
    StaggNumberEntityDescription(
        key="hold_time_minutes",
        translation_key="hold_time_minutes",
        native_min_value=0,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: f"setsetting hold {int(round(val))}",
    ),
    StaggNumberEntityDescription(
        key="altitude_meters",
        translation_key="altitude_meters",
        native_min_value=0,
        native_max_value=3000,
        native_step=1,
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=NumberDeviceClass.DISTANCE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: f"setaltitudem {int(round(val))}",
    ),
    StaggNumberEntityDescription(
        key="chime_volume",
        translation_key="chime_volume",
        native_min_value=0,
        native_max_value=10,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: f"setsetting chime {int(round(val))}",
    ),
    StaggNumberEntityDescription(
        key="schedule_temperature",
        translation_key="schedule_temperature",
        native_min_value=40,
        native_max_value=100,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: f"setsetting schtempr {round(val * 1.8 + 32)}",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink numbers from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        StaggNumber(coordinator, entry, description)
        for description in NUMBER_DESCRIPTIONS
    ]
    async_add_entities(entities)


class StaggNumber(StaggEntity, NumberEntity):
    """Representation of a Stagg EKG Pro number configuration."""

    entity_description: StaggNumberEntityDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggNumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the value of the number."""
        if not self.coordinator.data:
            return None
        val = cast("dict[str, Any]", self.coordinator.data).get(
            self.entity_description.key
        )
        if val is None or isinstance(val, bool):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        min_val = self.native_min_value
        max_val = self.native_max_value
        if (
            not math.isfinite(value)
            or value < min_val
            or value > max_val
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_range",
                translation_placeholders={
                    "min": str(min_val),
                    "max": str(max_val),
                },
            )

        cmd = self.entity_description.command_fn(value)
        await self.coordinator.async_send_command(cmd)
        await self.coordinator.async_request_refresh()
