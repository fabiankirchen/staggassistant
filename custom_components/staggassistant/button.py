"""Support for Fellow Stagg EKG Pro buttons."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import get_stable_id
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class StaggButtonEntityDescription(ButtonEntityDescription):
    """Describes a Stagg button entity."""

    command: str


BUTTON_DESCRIPTIONS: tuple[StaggButtonEntityDescription, ...] = (
    StaggButtonEntityDescription(
        key="press_button_2",
        translation_key="press_button_2",
        command="2",
        entity_category=EntityCategory.CONFIG,
    ),
    StaggButtonEntityDescription(
        key="press_button_1",
        translation_key="press_button_1",
        command="1",
        entity_category=EntityCategory.CONFIG,
    ),
    StaggButtonEntityDescription(
        key="rotate_left",
        translation_key="rotate_left",
        command="q",
        entity_category=EntityCategory.CONFIG,
    ),
    StaggButtonEntityDescription(
        key="rotate_right",
        translation_key="rotate_right",
        command="w",
        entity_category=EntityCategory.CONFIG,
    ),
    StaggButtonEntityDescription(
        key="long_press_2",
        translation_key="long_press_2",
        command="_long_press_2",
    ),
    StaggButtonEntityDescription(
        key="sync_time",
        translation_key="sync_time",
        command="_sync_time",
        entity_category=EntityCategory.CONFIG,
    ),
    StaggButtonEntityDescription(
        key="reload_data",
        translation_key="reload_data",
        command="_reload",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink buttons from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        StaggButton(coordinator, entry, description)
        for description in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)


class StaggButton(StaggEntity, ButtonEntity):
    """Representation of a Stagg EKG Pro action button."""

    entity_description: StaggButtonEntityDescription

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
        description: StaggButtonEntityDescription,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"stagg_{get_stable_id(entry)}_{description.key}"

    async def async_press(self) -> None:
        """Trigger the command when the button is pressed."""
        cmd = self.entity_description.command

        if cmd == "_reload":
            await self.coordinator.async_request_refresh()
            return

        if cmd == "_long_press_2":
            # Hold main dial button for 2 seconds; only send release if press succeeded
            await self.coordinator.async_send_command("2d")
            try:
                await asyncio.sleep(2)
            finally:
                await asyncio.shield(self.coordinator.async_send_command("2u"))
            await self.coordinator.async_request_refresh()
            return

        if cmd == "_sync_time":
            now = dt_util.now()
            cmd = f"setclock {now.hour} {now.minute} {now.second}"

        await self.coordinator.async_send_command(cmd)
        await self.coordinator.async_request_refresh()
