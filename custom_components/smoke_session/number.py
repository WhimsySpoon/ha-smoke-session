"""Meat weight for Smoke Session."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmokeSessionConfigEntry
from .engine import SessionManager
from .entity import SmokeSessionEntity


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([WeightNumber(entry.runtime_data, entry.title)])


class WeightNumber(SmokeSessionEntity, NumberEntity):
    _attr_native_min_value = 0.1
    _attr_native_max_value = 20
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_mode = NumberMode.BOX

    def __init__(self, manager: SessionManager, title: str) -> None:
        super().__init__(manager, "meat_weight", title)

    @property
    def native_value(self) -> float:
        return self.manager.weight

    async def async_set_native_value(self, value: float) -> None:
        self.manager.set_setting("weight_kg", round(value, 2))
