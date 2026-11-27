"""Constants for the TATAHome integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "tatahome"
NAME: Final = "TATAHome"
VERSION: Final = "0.1.0"

CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_HEARTBEAT: Final = "heartbeat"

DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_HEARTBEAT: Final = 120
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

PLATFORMS: Final = [
    "vacuum",
    "sensor",
    "binary_sensor",
    "switch",
    "select",
    "number",
    "time",
]

UPDATE_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

# Opcodes recovered from the vendor library. Kept here so the HA layer never
# needs to know wire details.
OP_EDGE: Final = 0x107F
OP_SPOT: Final = 0x1073
OP_MOP: Final = 0x107D
OP_AREA: Final = 0x106B
