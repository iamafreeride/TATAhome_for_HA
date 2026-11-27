"""Number entities for TATAHome."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TATAHome volume number."""
    async_add_entities([TATAHomeVolume(entry.runtime_data.coordinator)])


class TATAHomeVolume(TATAHomeEntity, NumberEntity):
    """Voice prompt volume (0-100)."""

    _attr_translation_key = "volume"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:volume-high"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "number_volume")

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.get("settings", {}).get("volume")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set("volume", str(int(value)))
