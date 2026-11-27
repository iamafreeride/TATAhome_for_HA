"""Vacuum entity for TATAHome."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity

_LOGGER = logging.getLogger(__name__)

STATE_MAP = {
    "docked": VacuumActivity.DOCKED,
    "charging": VacuumActivity.DOCKED,
    "cleaning": VacuumActivity.CLEANING,
    "paused": VacuumActivity.PAUSED,
    "returning": VacuumActivity.RETURNING,
    "error": VacuumActivity.ERROR,
    "idle": VacuumActivity.IDLE,
    "offline": VacuumActivity.IDLE,
}

FAN_SPEEDS = ["quiet", "standard", "strong", "max"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TATAHome vacuum."""
    async_add_entities([TATAHomeVacuum(entry.runtime_data.coordinator)])


class TATAHomeVacuum(TATAHomeEntity, StateVacuumEntity):
    """One TATAHome robot vacuum."""

    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.SEND_COMMAND
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "vacuum")

    @property
    def activity(self) -> VacuumActivity | None:
        return STATE_MAP.get(str(self._device.get("state", "")).lower())

    @property
    def battery_level(self) -> int | None:
        value = self._device.get("battery")
        return int(value) if value is not None else None

    @property
    def fan_speed(self) -> str | None:
        return self._device.get("suction")

    @property
    def fan_speed_list(self) -> list[str]:
        return FAN_SPEEDS

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        attrs.update(
            {
                "clean_area": self._device.get("area"),
                "clean_time": self._device.get("cleanSeconds"),
                "water_level": self._device.get("water"),
                "cleaning_mode": self._device.get("mode"),
                "map_available": self._device.get("mapAvailable"),
                "error": self._device.get("error"),
                "connection": "local" if self.coordinator.is_local else "cloud",
            }
        )
        return attrs

    async def async_start(self) -> None:
        await self.coordinator.async_send("start")

    async def async_pause(self) -> None:
        await self.coordinator.async_send("pause")

    async def async_stop(self, **kwargs: Any) -> None:
        # The vendor protocol has no distinct stop; pause stops movement.
        await self.coordinator.async_send("pause")

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.async_send("dock")

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        await self.coordinator.async_set("suction", fan_speed)

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        """Support the vendor's extra clean modes as vacuum.send_command."""
        command = command.lower()
        if command not in {"edge", "spot", "mop", "area", "two_pass"}:
            raise ValueError(f"Unsupported TATAHome command: {command}")
        await self.coordinator.async_send(command)
