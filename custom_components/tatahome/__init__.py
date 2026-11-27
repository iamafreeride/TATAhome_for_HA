"""TATAHome cloud integration for Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .cloud import CloudError, CloudSession
from .const import (
    CONF_EMAIL,
    CONF_HEARTBEAT,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_HEARTBEAT,
    DEFAULT_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import TATAHomeCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TATAHomeRuntimeData:
    """Objects shared by all entities of one config entry."""

    cloud: CloudSession
    coordinator: TATAHomeCoordinator


type TATAHomeConfigEntry = ConfigEntry[TATAHomeRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TATAHomeConfigEntry) -> bool:
    """Set up TATAHome from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    heartbeat = int(entry.options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT))

    cloud = CloudSession(heartbeat_seconds=heartbeat)
    try:
        result = await hass.async_add_executor_job(cloud.login, email, password)
    except CloudError as err:
        await hass.async_add_executor_job(cloud.close)
        raise ConfigEntryNotReady(f"TATAHome cloud login failed: {err}") from err

    if not result.ok:
        await hass.async_add_executor_job(cloud.close)
        if result.errcode in {1001, 1002, 1003, 1004, 1005}:
            raise ConfigEntryAuthFailed(result.errstr or "Invalid credentials")
        raise ConfigEntryNotReady(result.errstr or "TATAHome login rejected")

    coordinator = TATAHomeCoordinator(
        hass,
        entry,
        cloud,
        update_interval=scan_interval,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = TATAHomeRuntimeData(cloud=cloud, coordinator=coordinator)
    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _close(_event) -> None:
        await hass.async_add_executor_job(cloud.close)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TATAHomeConfigEntry) -> bool:
    """Unload a TATAHome config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.cloud.close)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: TATAHomeConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
