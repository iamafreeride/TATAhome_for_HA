"""Switches for TATAHome."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TATAHomeConfigEntry
from .entity import TATAHomeEntity


@dataclass(frozen=True, kw_only=True)
class TATAHomeSwitchDescription(SwitchEntityDescription):
    setting_key: str


SWITCHES: tuple[TATAHomeSwitchDescription, ...] = (
    TATAHomeSwitchDescription(
        key="do_not_disturb",
        translation_key="do_not_disturb",
        setting_key="dnd",
        icon="mdi:weather-night",
    ),
    TATAHomeSwitchDescription(
        key="history_map",
        translation_key="history_map",
        setting_key="history_map",
        icon="mdi:map-marker-path",
    ),
    TATAHomeSwitchDescription(
        key="breakpoint_resume",
        translation_key="breakpoint_resume",
        setting_key="breakpoint",
        icon="mdi:restart",
    ),
    TATAHomeSwitchDescription(
        key="carpet_turbo",
        translation_key="carpet_turbo",
        setting_key="carpet_turbo",
        icon="mdi:rug",
    ),
    TATAHomeSwitchDescription(
        key="voice",
        translation_key="voice",
        setting_key="voice",
        icon="mdi:volume-high",
    ),
)


@dataclass(frozen=True, kw_only=True)
class TATAHomeCleanSwitchDescription(SwitchEntityDescription):
    action: str


CLEAN_SWITCHES: tuple[TATAHomeCleanSwitchDescription, ...] = (
    TATAHomeCleanSwitchDescription(
        key="edge_clean",
        translation_key="edge_clean",
        action="edge",
        icon="mdi:border-outside",
    ),
    TATAHomeCleanSwitchDescription(
        key="spot_clean",
        translation_key="spot_clean",
        action="spot",
        icon="mdi:crosshairs",
    ),
    TATAHomeCleanSwitchDescription(
        key="area_clean",
        translation_key="area_clean",
        action="area",
        icon="mdi:selection",
    ),
    TATAHomeCleanSwitchDescription(
        key="two_pass_clean",
        translation_key="two_pass_clean",
        action="two_pass",
        icon="mdi:repeat",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TATAHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TATAHome switches."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [TATAHomeSwitch(coordinator, description) for description in SWITCHES]
        + [
            TATAHomeCleanModeSwitch(coordinator, description)
            for description in CLEAN_SWITCHES
        ]
    )


class TATAHomeSwitch(TATAHomeEntity, SwitchEntity):
    """A settings switch backed by the vendor cloud."""

    entity_description: TATAHomeSwitchDescription

    def __init__(self, coordinator, description: TATAHomeSwitchDescription) -> None:
        super().__init__(coordinator, f"switch_{description.key}")
        self.entity_description = description

    @property
    def _settings(self) -> dict:
        return self.coordinator.data.get("settings", {})

    @property
    def is_on(self) -> bool:
        if self.entity_description.key == "do_not_disturb":
            return bool(self._settings.get("doNotDisturb"))
        key = {
            "history_map": "historyMap",
            "breakpoint_resume": "breakpointResume",
            "carpet_turbo": "carpetTurbo",
            "voice": "voice",
        }[self.entity_description.key]
        return bool(self._settings.get(key))

    async def async_turn_on(self, **kwargs) -> None:
        if self.entity_description.key == "do_not_disturb":
            await self.coordinator.async_set_quiet(
                True,
                self._settings.get("quietStart", "22:00"),
                self._settings.get("quietEnd", "07:00"),
            )
            return
        await self.coordinator.async_set(self.entity_description.setting_key, "1")

    async def async_turn_off(self, **kwargs) -> None:
        if self.entity_description.key == "do_not_disturb":
            await self.coordinator.async_set_quiet(
                False,
                self._settings.get("quietStart", "22:00"),
                self._settings.get("quietEnd", "07:00"),
            )
            return
        await self.coordinator.async_set(self.entity_description.setting_key, "0")


class TATAHomeCleanModeSwitch(TATAHomeEntity, SwitchEntity):
    """A clean mode exposed as a switch.

    On starts the mode and off pauses the robot.  The vendor status does not
    expose the current clean type, so the active mode is tracked by the
    coordinator for this HA session.
    """

    entity_description: TATAHomeCleanSwitchDescription

    def __init__(
        self, coordinator, description: TATAHomeCleanSwitchDescription
    ) -> None:
        super().__init__(coordinator, f"switch_{description.key}")
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return (
            self.coordinator.active_mode == self.entity_description.action
            and str(self._device.get("state", "")).lower() == "cleaning"
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_send(self.entity_description.action)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send("pause")
