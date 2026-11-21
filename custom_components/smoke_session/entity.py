"""Base entity for Smoke Session."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .engine import SessionManager


class SmokeSessionEntity(Entity):
    """Pushes state whenever the session manager changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SessionManager, key: str, title: str) -> None:
        self.manager = manager
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry_id)},
            name=f"{title} Smoke Session",
            manufacturer="Smoke Session",
            model="Cook session",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.manager.entity_ids[self._key] = self.entity_id
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE.format(self.manager.entry_id), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
