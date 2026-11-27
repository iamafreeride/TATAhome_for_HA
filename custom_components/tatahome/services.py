"""Services for TATAHome."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

SERVICE_SET_NICKNAME = "set_nickname"
SERVICE_SET_QUIET_HOURS = "set_quiet_hours"

SERVICE_SET_NICKNAME_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): str,
        vol.Required("name"): str,
    }
)

SERVICE_SET_QUIET_HOURS_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): str,
        vol.Required("enabled"): bool,
        vol.Required("start"): str,
        vol.Required("end"): str,
    }
)


def _entry(hass: HomeAssistant, call: ServiceCall):
    config_entry_id = call.data.get("config_entry_id")
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if config_entry_id:
        entries = [entry for entry in entries if entry.entry_id == config_entry_id]
    if not entries:
        raise HomeAssistantError("No loaded TATAHome config entry found")
    return entries[0]


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the two account-level services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_NICKNAME):
        return

    async def _set_nickname(call: ServiceCall) -> None:
        entry = _entry(hass, call)
        try:
            await entry.runtime_data.coordinator.async_set("nickname", call.data["name"])
        except Exception as err:  # noqa: BLE001 - translated service error
            raise HomeAssistantError(f"Could not rename device: {err}") from err

    async def _set_quiet_hours(call: ServiceCall) -> None:
        entry = _entry(hass, call)
        try:
            await entry.runtime_data.coordinator.async_set_quiet(
                call.data["enabled"], call.data["start"], call.data["end"]
            )
        except Exception as err:  # noqa: BLE001 - translated service error
            raise HomeAssistantError(f"Could not set quiet hours: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_SET_NICKNAME, _set_nickname, schema=SERVICE_SET_NICKNAME_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_QUIET_HOURS,
        _set_quiet_hours,
        schema=SERVICE_SET_QUIET_HOURS_SCHEMA,
    )
