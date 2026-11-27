"""Select entities for TATAHome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


@dataclass(frozen=True, kw_only=True)
class TATAHomeSelectDescription(SelectEntityDescription):
    setting_key: str
    options: list[str]


SELECTS: tuple[TATAHomeSelectDescription, ...] = (
    TATAHomeSelectDescription(
        key="suction",
        translation_key="suction",
        setting_key="suction",
        options=["quiet", "standard", "strong", "max"],
        icon="mdi:fan",
    ),
    TATAHomeSelectDescription(
        key="water",
        translation_key="water",
        setting_key="water",
        options=["off", "low", "medium", "high"],
        icon="mdi:water",
    ),
    TATAHomeSelectDescription(
        key="mode",
        translation_key="mode",
        setting_key="mode",
        options=["auto", "spot", "edge"],
        icon="mdi:robot-vacuum",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TATAHome selects."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeSelect(coordinator, description) for description in SELECTS]
    )


class TATAHomeSelect(TATAHomeEntity, SelectEntity):
    """A settings select backed by the vendor cloud."""

    entity_description: TATAHomeSelectDescription

    def __init__(self, coordinator, description: TATAHomeSelectDescription) -> None:
        super().__init__(coordinator, f"select_{description.key}")
        self.entity_description = description
        self._attr_options = description.options

    @property
    def current_option(self) -> str | None:
        settings: dict[str, Any] = self.coordinator.data.get("settings", {})
        key = {
            "suction": "suction",
            "water": "water",
            "mode": "mode",
        }[self.entity_description.key]
        return settings.get(key)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set(self.entity_description.setting_key, option)
