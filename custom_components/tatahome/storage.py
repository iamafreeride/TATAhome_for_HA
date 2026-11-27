"""Persisted desired settings for TATAHome.

The vendor cloud always answers with the robot's current/factory values after a
new login.  Home Assistant keeps the user's desired values separately and
re-applies them after every re-login, so a session drop does not silently reset
suction/water/DND/voice settings.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1

SETTING_KEYS = (
    "mode",
    "suction",
    "water",
    "history_map",
    "breakpoint",
    "carpet_turbo",
    "voice",
    "volume",
)


class TATAHomeSettingsStore:
    """Small versioned store for the values the user wants on the robot."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.settings"
        )

    async def async_load(self) -> dict[str, Any]:
        data = await self._store.async_load()
        return data if isinstance(data, dict) else {}

    async def async_save(self, data: dict[str, Any]) -> None:
        await self._store.async_save(data)

    async def async_update(self, key: str, value: Any) -> None:
        data = await self.async_load()
        data[key] = value
        await self.async_save(data)

    async def async_update_quiet(self, enabled: bool, start: str, end: str) -> None:
        data = await self.async_load()
        data["quiet"] = {"enabled": enabled, "start": start, "end": end}
        await self.async_save(data)
