"""Coordinator for TATAHome."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import CloudError, CloudSession
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .storage import SETTING_KEYS, TATAHomeSettingsStore

_LOGGER = logging.getLogger(__name__)

CLEAN_ACTIONS = {"edge", "spot", "mop", "area", "two_pass", "start"}


class TATAHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll one TATAHome device and share the snapshot with all entities."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: CloudSession,
        store: TATAHomeSettingsStore,
        update_interval: int,
        *,
        is_local: bool = False,
        local_host: str | None = None,
        local_port: int | None = None,
        uid: int = 0,
        device: Any = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.cloud = cloud
        self.store = store
        self.active_mode: str | None = None
        self.is_local = is_local
        self.local_host = local_host
        self.local_port = local_port
        self.uid = uid
        self.device = device

    async def _async_relogin(self) -> None:
        """Reconnect locally when possible, otherwise fall back to cloud."""
        if self.is_local and self.local_host and self.local_port and self.device:
            try:
                await self.hass.async_add_executor_job(
                    self.cloud.connect_local,
                    self.local_host,
                    self.local_port,
                    self.uid,
                    self.device,
                )
            except CloudError as err:
                _LOGGER.warning("TATAHome local reconnect failed: %s", err)
                self.is_local = False
            else:
                _LOGGER.info("TATAHome local TCP reconnected")
                await self.async_apply_saved_settings()
                return

        _LOGGER.warning("TATAHome session lost; re-authenticating with cloud")
        result = await self.hass.async_add_executor_job(
            self.cloud.login,
            self.config_entry.data[CONF_EMAIL],
            self.config_entry.data[CONF_PASSWORD],
        )
        if not result.ok:
            raise ConfigEntryAuthFailed(result.errstr or "TATAHome login rejected")
        await self.async_apply_saved_settings()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.hass.async_add_executor_job(self.cloud.snapshot)
            error = str(data.get("device", {}).get("error") or "").lower()
            auth_lost = any(
                marker in error
                for marker in ("not connected", "closed", "session", "login", "auth")
            )
            if self.cloud.sock is None or auth_lost:
                if self.cloud.sock is not None:
                    await self.hass.async_add_executor_job(self.cloud.close)
                await self._async_relogin()
                data = await self.hass.async_add_executor_job(self.cloud.snapshot)
            return data
        except CloudError as err:
            raise UpdateFailed(f"TATAHome update failed: {err}") from err

    async def async_apply_saved_settings(self) -> None:
        """Write persisted desired values back after a fresh login."""
        data = await self.store.async_load()
        if not data:
            return
        await self.hass.async_add_executor_job(self._apply_blocking, data)

    def _apply_blocking(self, data: dict[str, Any]) -> None:
        for key in SETTING_KEYS:
            if key not in data:
                continue
            try:
                self.cloud.set_setting(None, key, str(data[key]))
            except CloudError as err:
                _LOGGER.warning("Could not restore TATAHome setting %s: %s", key, err)
        quiet = data.get("quiet")
        if isinstance(quiet, dict):
            try:
                self.cloud.set_quiet_hours(
                    None,
                    bool(quiet.get("enabled")),
                    str(quiet.get("start", "22:00")),
                    str(quiet.get("end", "07:00")),
                )
            except CloudError as err:
                _LOGGER.warning("Could not restore TATAHome quiet hours: %s", err)

    async def async_send(self, action: str, mode: str | None = None) -> None:
        """Send a command, then refresh so entities see the new state."""
        await self.hass.async_add_executor_job(self.cloud.command, None, action, mode)
        if action in CLEAN_ACTIONS:
            self.active_mode = "auto" if action == "start" else action
        elif action in {"pause", "dock"}:
            self.active_mode = None
        await self.async_request_refresh()

    async def async_set(self, key: str, value: str) -> None:
        """Write a device setting, remember it, then refresh."""
        await self.hass.async_add_executor_job(self.cloud.set_setting, None, key, value)
        await self.store.async_update(key, value)
        await self.async_request_refresh()

    async def async_set_quiet(self, enabled: bool, start: str, end: str) -> None:
        """Write quiet hours, remember them, then refresh."""
        await self.hass.async_add_executor_job(
            self.cloud.set_quiet_hours, None, enabled, start, end
        )
        await self.store.async_update_quiet(enabled, start, end)
        await self.async_request_refresh()
