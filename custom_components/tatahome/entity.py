"""Base entity for TATAHome."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TATAHomeCoordinator


class TATAHomeEntity(CoordinatorEntity[TATAHomeCoordinator]):
    """Common device info and availability for all TATAHome entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TATAHomeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.cloud.devices[0].serial}_{key}"

    @property
    def _device(self) -> dict[str, Any]:
        return self.coordinator.data.get("device", {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._device.get("online"))

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.cloud.devices[0]
        return DeviceInfo(
            identifiers={(DOMAIN, device.serial)},
            manufacturer="TATAHome",
            model=device.alias or "TATAHome robot vacuum",
            name=device.alias or "TATAHome",
            sw_version=device.firmware,
            serial_number=device.serial,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device
        return {
            "serial": device.get("serial"),
            "firmware": device.get("firmware"),
            "last_updated": device.get("updatedAt"),
        }
