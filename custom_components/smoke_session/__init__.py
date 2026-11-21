"""Smoke Session: guided smoker cooks with alerts, built on your own probe sensors."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .engine import USER_EVENT_TYPES, SessionManager
from .profile import load_profiles

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.NUMBER, Platform.TIME]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SmokeSessionConfigEntry = ConfigEntry[SessionManager]

ATTR_ENTRY = "config_entry_id"
_BASE = {vol.Optional(ATTR_ENTRY): cv.string}

START_SCHEMA = vol.Schema(
    {
        **_BASE,
        vol.Optional("profile"): cv.string,
        vol.Optional("weight_kg"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=20)),
        vol.Optional("planned_start"): cv.time,
    }
)
LOG_SCHEMA = vol.Schema({**_BASE, vol.Required("event_type"): vol.In(USER_EVENT_TYPES), vol.Optional("note"): cv.string})
END_SCHEMA = vol.Schema({**_BASE, vol.Optional("notes"): cv.string})
BASE_SCHEMA = vol.Schema(_BASE)


def _manager(hass: HomeAssistant, call: ServiceCall) -> SessionManager:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    wanted = call.data.get(ATTR_ENTRY)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
        if not entries:
            raise ServiceValidationError(f"No loaded Smoke Session entry with id {wanted}")
    if not entries:
        raise ServiceValidationError("Smoke Session isn't set up.")
    if len(entries) > 1:
        raise ServiceValidationError("More than one smoker is set up: pass config_entry_id.")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for the integration."""

    @callback
    def start(call: ServiceCall) -> None:
        _manager(hass, call).start_session(call.data.get("profile"), call.data.get("weight_kg"), call.data.get("planned_start"))

    @callback
    def next_step(call: ServiceCall) -> None:
        _manager(hass, call).complete_step()

    @callback
    def log_event(call: ServiceCall) -> None:
        _manager(hass, call).log_event(call.data["event_type"], call.data.get("note"))

    @callback
    def end(call: ServiceCall) -> None:
        _manager(hass, call).end_session(call.data.get("notes"))

    @callback
    def reset(call: ServiceCall) -> None:
        _manager(hass, call).reset()

    @callback
    def get_session(call: ServiceCall) -> ServiceResponse:
        mgr = _manager(hass, call)
        out: dict[str, Any] = {"session": mgr.session, "settings": mgr.settings, "timeline": mgr.timeline()}
        if mgr.session.get("state") != "idle":
            out["summary"] = mgr.summary()
        out["history"] = [{"profile_id": h.get("profile_id"), "cook_started": h.get("cook_started"), "summary": h.get("summary")} for h in mgr.history]
        return out

    hass.services.async_register(DOMAIN, "start_session", start, schema=START_SCHEMA)
    hass.services.async_register(DOMAIN, "next_step", next_step, schema=BASE_SCHEMA)
    hass.services.async_register(DOMAIN, "log_event", log_event, schema=LOG_SCHEMA)
    hass.services.async_register(DOMAIN, "end_session", end, schema=END_SCHEMA)
    hass.services.async_register(DOMAIN, "reset", reset, schema=BASE_SCHEMA)
    hass.services.async_register(DOMAIN, "get_session", get_session, schema=BASE_SCHEMA, supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry) -> bool:
    profiles = await hass.async_add_executor_job(load_profiles)
    manager = SessionManager(hass, entry.entry_id, {**entry.data, **entry.options}, profiles)
    await manager.async_load()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: SmokeSessionConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok
