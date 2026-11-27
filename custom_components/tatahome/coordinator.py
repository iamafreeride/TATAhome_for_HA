"""Coordinator for TATAHome."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import CloudError, CloudSession
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class TATAHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll one TATAHome device and share the snapshot with all entities."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: CloudSession,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.cloud = cloud

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.hass.async_add_executor_job(self.cloud.snapshot)
        except CloudError as err:
            raise UpdateFailed(f"TATAHome update failed: {err}") from err

    async def async_send(self, action: str, mode: str | None = None) -> None:
        """Send a command, then refresh so entities see the new state."""
        await self.hass.async_add_executor_job(self.cloud.command, None, action, mode)
        await self.async_request_refresh()

    async def async_set(self, key: str, value: str) -> None:
        """Write a device setting, then refresh."""
        await self.hass.async_add_executor_job(self.cloud.set_setting, None, key, value)
        await self.async_request_refresh()

    async def async_set_quiet(
        self, enabled: bool, start: str, end: str
    ) -> None:
        """Write quiet hours, then refresh."""
        await self.hass.async_add_executor_job(
            self.cloud.set_quiet_hours, None, enabled, start, end
        )
        await self.async_request_refresh()
