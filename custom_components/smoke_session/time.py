"""Planned start time for Smoke Session."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmokeSessionConfigEntry
from .engine import SessionManager
from .entity import SmokeSessionEntity


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PlannedStart(entry.runtime_data, entry.title)])


class PlannedStart(SmokeSessionEntity, TimeEntity):
    """When the chimney gets lit. The session works the timeline out from this."""

    def __init__(self, manager: SessionManager, title: str) -> None:
        super().__init__(manager, "planned_start", title)

    @property
    def native_value(self) -> time:
        return time.fromisoformat(str(self.manager.settings["planned_start"]))

    async def async_set_value(self, value: time) -> None:
        self.manager.set_setting("planned_start", value.strftime("%H:%M:%S"))
