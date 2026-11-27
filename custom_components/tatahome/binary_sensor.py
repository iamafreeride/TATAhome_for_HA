"""Binary sensors for TATAHome."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity

DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="docked",
        translation_key="docked",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TATAHome binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeBinarySensor(coordinator, description) for description in DESCRIPTIONS]
    )


class TATAHomeBinarySensor(TATAHomeEntity, BinarySensorEntity):
    """Binary state from the cloud snapshot."""

    entity_description: BinarySensorEntityDescription

    def __init__(self, coordinator, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, f"binary_{description.key}")
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if self.entity_description.key == "online":
            return bool(device.get("online"))
        if self.entity_description.key == "docked":
            return str(device.get("state", "")).lower() in {"docked", "charging"}
        return None
