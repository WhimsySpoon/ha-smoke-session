"""Dump real entity states at points in a simulated cook, for testing the card. Not a behaviour test."""

import json
from pathlib import Path

from homeassistant.core import State

from custom_components.smoke_session.const import DOMAIN

from .test_session import MEAT, PIT, advance, press, set_temps, setup  # noqa: F401

OUT = Path(__file__).parent.parent / "card" / "fixtures"


def dump(hass, name):
    OUT.mkdir(exist_ok=True)
    states = {}
    for s in hass.states.async_all():
        if "smoke_session" in s.entity_id or s.entity_id in (PIT, MEAT):
            d = s.as_dict()
            states[s.entity_id] = {"entity_id": d["entity_id"], "state": d["state"], "attributes": dict(d["attributes"]),
                                   "last_changed": str(d["last_changed"]), "last_updated": str(d["last_updated"])}
    (OUT / f"{name}.json").write_text(json.dumps(states, default=str, indent=1))


async def test_snapshots(hass, setup, freezer):
    entry, calls = setup
    hass.states.async_set(MEAT, "11", {"unit_of_measurement": "°C", "device_class": "temperature", "friendly_name": "Smoker Thermometer Temperature Probe 2"})
    dump(hass, "idle")
    await press(hass, "start_session")
    await advance(hass, freezer, 120)
    for _ in range(5):
        await press(hass, "next_step")
    await advance(hass, freezer, 30, pit=lambda m: min(125, 12 + m * 4))
    await advance(hass, freezer, 11, pit=125)
    await press(hass, "next_step")  # ribs on
    await advance(hass, freezer, 25, pit=lambda m: 118 + m * 0.3, meat=lambda m: 8 + m)
    await hass.services.async_call("select", "select_option", {"entity_id": "select.wsm_smoke_session_bottom_vents", "option": "25% open"}, blocking=True)
    await advance(hass, freezer, 70, pit=lambda m: 126 - m * 0.05, meat=lambda m: 33 + m * 0.4)
    await press(hass, "log_spritz")
    await advance(hass, freezer, 5, pit=lambda m: 121 - m * 0.6, meat=62)
    dump(hass, "smoking")
    await press(hass, "next_step")
    await press(hass, "next_step")
    for _ in range(6):
        await press(hass, "next_step")
    dump(hass, "finished")
