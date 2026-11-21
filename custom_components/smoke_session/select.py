"""Selects for Smoke Session: cook, bottom vents, which probe is in the meat."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmokeSessionConfigEntry
from .const import VENT_OPTIONS
from .engine import SessionManager
from .entity import SmokeSessionEntity


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    entities: list[SelectEntity] = [CookSelect(m, entry.title), VentSelect(m, entry.title)]
    if m.meat_entities:
        entities.append(MeatProbeSelect(m, entry.title))
    async_add_entities(entities)


class CookSelect(SmokeSessionEntity, SelectEntity):
    """Choose the cook profile. Options are profile names."""

    def __init__(self, manager: SessionManager, title: str) -> None:
        super().__init__(manager, "cook", title)
        self._attr_options = [p.name for p in manager.profiles.values()]

    @property
    def current_option(self) -> str:
        return self.manager.profile.name

    async def async_select_option(self, option: str) -> None:
        pid = next((p.id for p in self.manager.profiles.values() if p.name == option), None)
        if pid is None:
            raise ServiceValidationError(f"Unknown cook '{option}'")
        self.manager.set_setting("profile_id", pid)


class VentSelect(SmokeSessionEntity, SelectEntity):
    """Where the bottom vents are now. Changing it during a cook logs a vent adjustment."""

    _attr_options = VENT_OPTIONS

    def __init__(self, manager: SessionManager, title: str) -> None:
        super().__init__(manager, "bottom_vents", title)

    @property
    def current_option(self) -> str:
        return self.manager.settings["vent"]

    async def async_select_option(self, option: str) -> None:
        if option != self.manager.settings["vent"]:
            self.manager.set_setting("vent", option)


class MeatProbeSelect(SmokeSessionEntity, SelectEntity):
    """Which configured probe is in the meat. Options are entity IDs."""

    def __init__(self, manager: SessionManager, title: str) -> None:
        super().__init__(manager, "meat_probe", title)
        self._attr_options = list(manager.meat_entities)

    @property
    def current_option(self) -> str | None:
        return self.manager.settings.get("meat_probe")

    async def async_select_option(self, option: str) -> None:
        self.manager.set_setting("meat_probe", option)
