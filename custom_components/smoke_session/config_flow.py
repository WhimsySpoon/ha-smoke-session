"""Config flow for Smoke Session."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_IMPORTANT_DESTINATIONS,
    CONF_INFO_DESTINATIONS,
    CONF_MEAT_SENSORS,
    CONF_NOTIFY_SCRIPT,
    CONF_PIT_SENSOR,
    DEFAULT_IMPORTANT_DESTINATIONS,
    DEFAULT_INFO_DESTINATIONS,
    DEFAULT_NOTIFY_SCRIPT,
    DESTINATION_OPTIONS,
    DOMAIN,
)

_TEMP = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))
_TEMPS = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature", multiple=True))
_SCRIPT = selector.EntitySelector(selector.EntitySelectorConfig(domain="script"))
_DEST = selector.SelectSelector(
    selector.SelectSelectorConfig(options=DESTINATION_OPTIONS, multiple=True, mode=selector.SelectSelectorMode.LIST, translation_key="destination")
)


def _schema(defaults: dict[str, Any], include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Smoker"))] = str
    fields.update(
        {
            vol.Required(CONF_PIT_SENSOR, default=defaults.get(CONF_PIT_SENSOR, vol.UNDEFINED)): _TEMP,
            vol.Optional(CONF_MEAT_SENSORS, default=defaults.get(CONF_MEAT_SENSORS, [])): _TEMPS,
            vol.Required(CONF_NOTIFY_SCRIPT, default=defaults.get(CONF_NOTIFY_SCRIPT, DEFAULT_NOTIFY_SCRIPT)): _SCRIPT,
            vol.Required(CONF_IMPORTANT_DESTINATIONS, default=defaults.get(CONF_IMPORTANT_DESTINATIONS, DEFAULT_IMPORTANT_DESTINATIONS)): _DEST,
            vol.Required(CONF_INFO_DESTINATIONS, default=defaults.get(CONF_INFO_DESTINATIONS, DEFAULT_INFO_DESTINATIONS)): _DEST,
        }
    )
    return vol.Schema(fields)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if user_input[CONF_PIT_SENSOR] in user_input.get(CONF_MEAT_SENSORS, []):
        errors[CONF_MEAT_SENSORS] = "pit_in_meat"
    if not user_input[CONF_IMPORTANT_DESTINATIONS] or not user_input[CONF_INFO_DESTINATIONS]:
        errors["base"] = "no_destination"
    return errors


class SmokeSessionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a smoker."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_PIT_SENSOR])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}, True), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmokeSessionOptionsFlow()


class SmokeSessionOptionsFlow(OptionsFlow):
    """Change probes and notification routing."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(user_input or current, False), errors=errors)
