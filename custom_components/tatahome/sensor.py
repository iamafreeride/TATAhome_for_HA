"""Sensors for TATAHome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


@dataclass(frozen=True, kw_only=True)
class TATAHomeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


def _device(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("device", {})


def _consumable(index: int) -> Callable[[dict[str, Any]], Any]:
    def value(data: dict[str, Any]) -> Any:
        items = data.get("consumables") or []
        for item in items:
            if str(item.get("key")) == str(index):
                return item.get("remaining")
        return None

    return value


SENSORS: tuple[TATAHomeSensorDescription, ...] = (
    TATAHomeSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _device(data).get("battery"),
    ),
    TATAHomeSensorDescription(
        key="clean_area",
        translation_key="clean_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:texture-box",
        value_fn=lambda data: _device(data).get("area"),
    ),
    TATAHomeSensorDescription(
        key="clean_time",
        translation_key="clean_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _device(data).get("cleanSeconds"),
    ),
    TATAHomeSensorDescription(
        key="main_brush",
        translation_key="main_brush",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brush",
        value_fn=_consumable(1),
    ),
    TATAHomeSensorDescription(
        key="side_brush",
        translation_key="side_brush",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brush",
        value_fn=_consumable(2),
    ),
    TATAHomeSensorDescription(
        key="filter",
        translation_key="filter",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
        value_fn=_consumable(3),
    ),
    TATAHomeSensorDescription(
        key="mop_pad",
        translation_key="mop_pad",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water",
        value_fn=_consumable(4),
    ),
    TATAHomeSensorDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        entity_registry_enabled_default=False,
        value_fn=lambda data: _device(data).get("firmware"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TATAHome sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeSensor(coordinator, description) for description in SENSORS]
    )


class TATAHomeSensor(TATAHomeEntity, SensorEntity):
    """A sensor backed by the TATAHome snapshot."""

    entity_description: TATAHomeSensorDescription

    def __init__(self, coordinator, description: TATAHomeSensorDescription) -> None:
        super().__init__(coordinator, f"sensor_{description.key}")
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, TypeError, ValueError):
            return None
