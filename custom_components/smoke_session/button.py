"""Buttons for Smoke Session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmokeSessionConfigEntry
from .engine import SessionManager
from .entity import SmokeSessionEntity


@dataclass(frozen=True, kw_only=True)
class SmokeButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[SessionManager], None]


BUTTONS = (
    SmokeButtonDescription(key="start_session", press_fn=lambda m: m.start_session()),
    SmokeButtonDescription(key="next_step", press_fn=lambda m: m.complete_step()),
    SmokeButtonDescription(key="log_spritz", press_fn=lambda m: m.log_event("spritz")),
    SmokeButtonDescription(key="log_lid_open", press_fn=lambda m: m.log_event("lid_open")),
    SmokeButtonDescription(key="log_probe_check", press_fn=lambda m: m.log_event("probe_check")),
    SmokeButtonDescription(key="end_session", press_fn=lambda m: m.end_session()),
)


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmokeButton(entry.runtime_data, d, entry.title) for d in BUTTONS)


class SmokeButton(SmokeSessionEntity, ButtonEntity):
    entity_description: SmokeButtonDescription

    def __init__(self, manager: SessionManager, description: SmokeButtonDescription, title: str) -> None:
        super().__init__(manager, description.key, title)
        self.entity_description = description

    async def async_press(self) -> None:
        self.entity_description.press_fn(self.manager)
