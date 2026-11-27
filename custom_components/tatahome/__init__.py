"""TATAHome cloud integration for Home Assistant."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .cloud import CloudDevice, CloudError, CloudSession
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
from .storage import TATAHomeSettingsStore

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TATAHomeRuntimeData:
    """Objects shared by all entities of one config entry."""

    cloud: CloudSession
    coordinator: TATAHomeCoordinator
    store: TATAHomeSettingsStore
    is_local: bool = False
    local_host: str | None = None
    local_port: int | None = None


type TATAHomeConfigEntry = ConfigEntry[TATAHomeRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TATAHomeConfigEntry) -> bool:
    """Set up TATAHome from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    heartbeat = int(entry.options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT))

    store = TATAHomeSettingsStore(hass, entry.entry_id)
    saved = await store.async_load()
    cloud: CloudSession | None = None
    device: CloudDevice | None = None
    is_local = False
    local_host: str | None = None
    local_port: int | None = None

    # Fast path: reuse the last LAN endpoint, even when the cloud is down.
    cached = saved.get("local") if isinstance(saved.get("local"), dict) else None
    if cached:
        local: CloudSession | None = None
        try:
            cached_device = CloudDevice(
                devid=int(cached["devid"]),
                serial=str(cached["serial"]),
                alias=str(cached.get("alias", "TATAHome")),
                firmware=str(cached.get("firmware", "-")),
                online=True,
            )
            local = CloudSession(heartbeat_seconds=heartbeat)
            await hass.async_add_executor_job(
                local.connect_local,
                str(cached["host"]),
                int(cached["port"]),
                int(cached.get("uid", 0)),
                cached_device,
            )
            probe = await hass.async_add_executor_job(local.snapshot)
        except (CloudError, KeyError, TypeError, ValueError) as err:
            _LOGGER.info("Cached TATAHome LAN endpoint unavailable: %s", err)
            if local is not None:
                await hass.async_add_executor_job(local.close)
        else:
            if probe.get("device", {}).get("online"):
                cloud = local
                device = cached_device
                is_local = True
                local_host = str(cached["host"])
                local_port = int(cached["port"])
                _LOGGER.info("Using cached TATAHome LAN endpoint %s:%s", local_host, local_port)
            else:
                await hass.async_add_executor_job(local.close)

    # Slow path: cloud login + LAN discovery.
    if cloud is None:
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

        device = cloud.devices[0]
        try:
            wlan = await hass.async_add_executor_job(cloud.get_wlan_info)
            if wlan.get("ip") and wlan.get("port"):
                local = CloudSession(heartbeat_seconds=heartbeat)
                try:
                    await hass.async_add_executor_job(
                        local.connect_local,
                        wlan["ip"],
                        int(wlan["port"]),
                        cloud.uid,
                        device,
                    )
                    probe = await hass.async_add_executor_job(local.snapshot)
                except CloudError as err:
                    _LOGGER.info("TATAHome LAN endpoint unavailable: %s", err)
                    await hass.async_add_executor_job(local.close)
                else:
                    if probe.get("device", {}).get("online"):
                        try:
                            quiet = await hass.async_add_executor_job(cloud.quiet_hours, device)
                            local._quiet_cache[device.devid] = (time.time(), quiet)
                            cloud_state = await hass.async_add_executor_job(cloud.snapshot)
                            settings = cloud_state.get("settings", {})
                            local.default_suction = settings.get("suction")
                            local.default_water = settings.get("water")
                            local.default_mode = settings.get("mode", "auto")
                            local.history_map = bool(settings.get("historyMap", True))
                            local.breakpoint_resume = bool(
                                settings.get("breakpointResume", True)
                            )
                            local.carpet_turbo = bool(settings.get("carpetTurbo", False))
                            local.voice_enabled = bool(settings.get("voice", True))
                            local.volume = int(settings.get("volume", 50))
                        except CloudError:
                            pass
                        await hass.async_add_executor_job(cloud.close)
                        cloud = local
                        is_local = True
                        local_host = str(wlan["ip"])
                        local_port = int(wlan["port"])
                        await store.async_update(
                            "local",
                            {
                                "host": local_host,
                                "port": local_port,
                                "uid": cloud.uid,
                                "devid": device.devid,
                                "serial": device.serial,
                                "alias": device.alias,
                                "firmware": device.firmware,
                            },
                        )
                        _LOGGER.info(
                            "Using TATAHome local TCP at %s:%s", local_host, local_port
                        )
                    else:
                        await hass.async_add_executor_job(local.close)
        except CloudError as err:
            _LOGGER.info("TATAHome LAN discovery unavailable, using cloud: %s", err)

    assert cloud is not None and device is not None
    coordinator = TATAHomeCoordinator(
        hass,
        entry,
        cloud,
        store,
        update_interval=scan_interval,
        is_local=is_local,
        local_host=local_host,
        local_port=local_port,
        uid=cloud.uid,
        device=device,
    )
    await coordinator.async_apply_saved_settings()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = TATAHomeRuntimeData(
        cloud=cloud,
        coordinator=coordinator,
        store=store,
        is_local=is_local,
        local_host=local_host,
        local_port=local_port,
    )
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
