"""Diagnostics for TATAHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_PASSWORD

REDACT = {CONF_PASSWORD, CONF_EMAIL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return non-secret diagnostics."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "uid": data.cloud.uid,
        "devices": [
            {
                "devid": device.devid,
                "serial": device.serial,
                "alias": device.alias,
                "firmware": device.firmware,
                "online": device.online,
            }
            for device in data.cloud.devices
        ],
        "snapshot": data.coordinator.data,
    }
