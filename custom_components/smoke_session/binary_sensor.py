"""Binary sensors for Smoke Session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmokeSessionConfigEntry
from .engine import SessionManager
from .entity import SmokeSessionEntity


@dataclass(frozen=True, kw_only=True)
class SmokeBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[SessionManager], bool]


BINARY_SENSORS = (
    SmokeBinaryDescription(key="lid_recovering", value_fn=lambda m: m.active and m.suppressed),
    SmokeBinaryDescription(key="stall", value_fn=lambda m: m.stall),
    SmokeBinaryDescription(
        key="pit_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda m: m.active and bool(m.session.get("pit_alerted")),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmokeBinary(entry.runtime_data, d, entry.title) for d in BINARY_SENSORS)


class SmokeBinary(SmokeSessionEntity, BinarySensorEntity):
    entity_description: SmokeBinaryDescription

    def __init__(self, manager: SessionManager, description: SmokeBinaryDescription, title: str) -> None:
        super().__init__(manager, description.key, title)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.manager)
