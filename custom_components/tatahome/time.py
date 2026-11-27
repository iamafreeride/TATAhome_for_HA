"""Time entities for TATAHome quiet hours."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up quiet-hour start/end."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeQuietTime(coordinator, "start"), TATAHomeQuietTime(coordinator, "end")]
    )


class TATAHomeQuietTime(TATAHomeEntity, TimeEntity):
    """Start or end of the vendor quiet-hours window."""

    def __init__(self, coordinator, edge: str) -> None:
        super().__init__(coordinator, f"quiet_{edge}")
        self._edge = edge
        self._attr_translation_key = f"quiet_{edge}"

    @property
    def native_value(self) -> time | None:
        settings = self.coordinator.data.get("settings", {})
        raw = settings.get("quietStart" if self._edge == "start" else "quietEnd")
        if not raw:
            return None
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        settings = self.coordinator.data.get("settings", {})
        start = value.strftime("%H:%M") if self._edge == "start" else settings.get("quietStart", "22:00")
        end = value.strftime("%H:%M") if self._edge == "end" else settings.get("quietEnd", "07:00")
        await self.coordinator.async_set_quiet(
            bool(settings.get("doNotDisturb")), start, end
        )
