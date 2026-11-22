"""Support for Fellow Stagg EKG Pro climate entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_device_identifier
from .coordinator import StaggConfigEntry, StaggLinkCoordinator
from .entity import StaggEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up StaggLink climate platform."""
    coordinator = entry.runtime_data
    async_add_entities([StaggKettleClimate(coordinator, entry)])


class StaggKettleClimate(StaggEntity, ClimateEntity):
    """Representation of a Stagg EKG Pro Kettle as a climate entity."""

    _attr_translation_key = "kettle"
    _attr_name = None
    _enable_turn_on_off_backwards_compatibility = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_min_temp = 40
    _attr_max_temp = 100

    def __init__(
        self,
        coordinator: StaggLinkCoordinator,
        entry: StaggConfigEntry,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = get_device_identifier(entry)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if not self.coordinator.data:
            return HVACMode.OFF
        mode = str(self.coordinator.data.get("mode", ""))
        if mode in ("S_Off", "S_Standby", "S_NoWater", "S_FAIL", "S_OTA"):
            return HVACMode.OFF
        if (
            mode in ("S_Heat", "S_StartupToTempr", "S_PreBoil")
            or mode.startswith("S_Hold")
            or "Heat" in mode
        ) and "HeatOff" not in mode:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation."""
        if not self.coordinator.data:
            return HVACAction.OFF
        mode = str(self.coordinator.data.get("mode", ""))
        if mode in ("S_Off", "S_Standby", "S_NoWater", "S_FAIL", "S_OTA"):
            return HVACAction.OFF
        if (
            mode in ("S_Heat", "S_StartupToTempr", "S_PreBoil")
            or "Heat" in mode
            or "WarmDuty" in mode
        ) and "HeatOff" not in mode:
            return HVACAction.HEATING
        if mode.startswith("S_Hold"):
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.coordinator.data:
            return self.coordinator.data.get("temp")
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target set temperature."""
        if self.coordinator.data:
            return self.coordinator.data.get("target")
        return None

    async def async_turn_on(self) -> None:
        """Turn the kettle heating on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the kettle off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_command("ss S_Off")
        elif hvac_mode == HVACMode.HEAT:
            if not self.coordinator.data:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="kettle_state_unknown",
                )
            if not self.coordinator.data.get("is_docked", False):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="kettle_undocked",
                )
            if (
                self.coordinator.data.get("no_water")
                or str(self.coordinator.data.get("mode", "")) == "S_NoWater"
            ):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="kettle_no_water",
                )
            await self.coordinator.async_send_command("ss S_Heat")

        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            # Clamp to valid operating range
            clamped_c = max(self._attr_min_temp, min(self._attr_max_temp, float(temp)))
            # Convert Celsius to Fahrenheit with proper rounding for precision
            fahrenheit = round(clamped_c * 1.8 + 32)

            # 1. Send temperature target
            await self.coordinator.async_send_command(
                f"setsettingd settempr {fahrenheit}"
            )

            # 2. Only resume / signal heating mode if kettle is already heating and safe
            if self.hvac_mode == HVACMode.HEAT:
                if (
                    not self.coordinator.data
                    or not self.coordinator.data.get("is_docked", False)
                    or self.coordinator.data.get("no_water")
                    or str(self.coordinator.data.get("mode", "")) == "S_NoWater"
                ):
                    _LOGGER.warning(
                        "Refusing to resume heating after set_temperature due to safety interlock (undocked or no water)."
                    )
                else:
                    await self.coordinator.async_send_command("ss S_Heat")

            await self.coordinator.async_request_refresh()
