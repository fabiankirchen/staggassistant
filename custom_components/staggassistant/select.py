"""Support for Fellow Stagg EKG Pro selects."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 1

_CLOCK_MODE_FROM_INT: dict[int, str] = {
    0: "off",
    1: "digital",
    2: "analog",
}

_CLOCK_MODE_COMMANDS: dict[str, list[str]] = {
    "off": ["setsetting clockmode 0"],
    "digital": ["setdigital"],
    "analog": ["setanalog"],
}

_LANGUAGE_OPTIONS: list[str] = ["en", "fr", "es", "zh-hans", "zh-hant", "ko", "ja"]
_LANGUAGE_INDEX: dict[str, int] = {
    option: idx for idx, option in enumerate(_LANGUAGE_OPTIONS)
}

_UNITS_COMMANDS: dict[str, list[str]] = {
    "c": ["setunitsc"],
    "f": ["setunitsf"],
}

_SCHEDULE_MODE_COMMANDS: dict[str, list[str]] = {
    "off": ["setsetting schedon 0"],
    "once": ["setsetting schedon 1", "setsetting Repeat_sched 0"],
    "repeat": ["setsetting schedon 1", "setsetting Repeat_sched 1"],
}


@dataclass(frozen=True, kw_only=True)
class StaggSelectEntityDescription(SelectEntityDescription):
    """Describes a Stagg select entity."""

    command_fn: Callable[[str], list[str]]


SELECT_DESCRIPTIONS: tuple[StaggSelectEntityDescription, ...] = (
    StaggSelectEntityDescription(
        key="clock_mode",
        translation_key="clock_mode",
        options=["off", "digital", "analog"],
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: _CLOCK_MODE_COMMANDS[val],
    ),
    StaggSelectEntityDescription(
        key="language",
        translation_key="language",
        options=list(_LANGUAGE_OPTIONS),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: [f"setsetting language {_LANGUAGE_INDEX[val]}"],
    ),
    StaggSelectEntityDescription(
        key="units",
        translation_key="units",
        options=["c", "f"],
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: _UNITS_COMMANDS[val],
    ),
    StaggSelectEntityDescription(
        key="schedule_mode",
        translation_key="schedule_mode",
        options=["off", "once", "repeat"],
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        command_fn=lambda val: _SCHEDULE_MODE_COMMANDS[val],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink selects from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        StaggSelect(coordinator, entry, description)
        for description in SELECT_DESCRIPTIONS
    ]
    async_add_entities(entities)


class StaggSelect(StaggEntity, SelectEntity):
    """Representation of a Stagg EKG Pro select configuration."""

    entity_description: StaggSelectEntityDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggSelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the current selected option, or None when unknown."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        val = cast("dict[str, Any]", self.coordinator.data).get(key)
        if val is None:
            return None

        if key == "clock_mode":
            if isinstance(val, bool):
                return None
            try:
                return _CLOCK_MODE_FROM_INT.get(int(val))
            except (ValueError, TypeError):
                return None

        if key == "language":
            if isinstance(val, bool):
                return None
            try:
                idx = int(val)
            except (ValueError, TypeError):
                return None
            if 0 <= idx < len(self.options):
                return self.options[idx]
            return None

        if key == "units":
            if isinstance(val, str) and val.lower() in self.options:
                return val.lower()
            return None

        if isinstance(val, str) and val in self.options:
            return val

        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self.options:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            )

        for cmd in self.entity_description.command_fn(option):
            await self.coordinator.async_send_command(cmd)

        await self.coordinator.async_request_refresh()
