"""Buttons for TATAHome clean modes."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


@dataclass(frozen=True, kw_only=True)
class TATAHomeButtonDescription(ButtonEntityDescription):
    action: str


BUTTONS: tuple[TATAHomeButtonDescription, ...] = (
    TATAHomeButtonDescription(
        key="edge_clean",
        translation_key="edge_clean",
        action="edge",
        icon="mdi:border-outside",
    ),
    TATAHomeButtonDescription(
        key="spot_clean",
        translation_key="spot_clean",
        action="spot",
        icon="mdi:crosshairs",
    ),
    TATAHomeButtonDescription(
        key="mop_clean",
        translation_key="mop_clean",
        action="mop",
        icon="mdi:water",
    ),
    TATAHomeButtonDescription(
        key="area_clean",
        translation_key="area_clean",
        action="area",
        icon="mdi:selection",
    ),
    TATAHomeButtonDescription(
        key="two_pass_clean",
        translation_key="two_pass_clean",
        action="two_pass",
        icon="mdi:repeat",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TATAHome buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeButton(coordinator, description) for description in BUTTONS]
    )


class TATAHomeButton(TATAHomeEntity, ButtonEntity):
    """Start one of the vendor's clean modes."""

    entity_description: TATAHomeButtonDescription

    def __init__(self, coordinator, description: TATAHomeButtonDescription) -> None:
        super().__init__(coordinator, f"button_{description.key}")
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_send(self.entity_description.action)
