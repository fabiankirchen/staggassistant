"""Support for Fellow Stagg EKG Pro switches."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class StaggSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Stagg switch entity."""

    turn_on_command: str
    turn_off_command: str


SWITCH_DESCRIPTIONS: tuple[StaggSwitchEntityDescription, ...] = (
    StaggSwitchEntityDescription(
        key="pre_boil_enabled",
        translation_key="pre_boil",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        turn_on_command="setsetting boil 1",
        turn_off_command="setsetting boil 0",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink switches from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        StaggSwitch(coordinator, entry, description)
        for description in SWITCH_DESCRIPTIONS
    ]
    async_add_entities(entities)


class StaggSwitch(StaggEntity, SwitchEntity):
    """Representation of a Stagg EKG Pro switch."""

    entity_description: StaggSwitchEntityDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on, or None when unavailable."""
        if not self.coordinator.data:
            return None
        data = cast("dict[str, Any]", self.coordinator.data)
        if self.entity_description.key not in data:
            return None
        val = data[self.entity_description.key]
        if val is None:
            return None
        return bool(val == 1 or val is True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.async_send_command(
            self.entity_description.turn_on_command
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.async_send_command(
            self.entity_description.turn_off_command
        )
        await self.coordinator.async_request_refresh()
