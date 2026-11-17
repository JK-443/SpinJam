"""Config flow for SpinJam."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_LYRICS_ENABLED,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VINYL_PLAYER,
    DEFAULT_LYRICS_ENABLED,
    DEFAULT_NAME,
    DEFAULT_SYNC_OFFSET_MS,
    DOMAIN,
)


def entity_selector_supports_reorder() -> bool:
    """Return True when this HA build's EntitySelector schema accepts reorder."""
    try:
        selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="media_player", multiple=True, reorder=True
            )
        )
    except vol.Invalid:
        return False
    return True


def source_players_selector() -> selector.EntitySelector:
    """Multi media_player picker; enable drag-reorder when HA supports it.

    Config and options both use this so the saved list order is the priority
    order (HA otherwise sorts entity picks alphabetically).
    """
    if entity_selector_supports_reorder():
        return selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="media_player", multiple=True, reorder=True
            )
        )
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="media_player", multiple=True)
    )


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        vol.Required(
            CONF_SOURCE_PLAYERS,
            default=defaults.get(CONF_SOURCE_PLAYERS, []),
        ): source_players_selector(),
        vol.Required(
            CONF_LYRICS_ENABLED,
            default=defaults.get(CONF_LYRICS_ENABLED, DEFAULT_LYRICS_ENABLED),
        ): bool,
        vol.Required(
            CONF_SYNC_OFFSET_MS,
            default=defaults.get(CONF_SYNC_OFFSET_MS, DEFAULT_SYNC_OFFSET_MS),
        ): vol.All(vol.Coerce(int), vol.Range(min=-2000, max=2000)),
    }
    vinyl_default = defaults.get(CONF_VINYL_PLAYER)
    if vinyl_default:
        fields[
            vol.Optional(CONF_VINYL_PLAYER, default=vinyl_default)
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player", multiple=False)
        )
    else:
        fields[vol.Optional(CONF_VINYL_PLAYER)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player", multiple=False)
        )
    return vol.Schema(fields)


class SpinJamConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SpinJam."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            sources = user_input.get(CONF_SOURCE_PLAYERS) or []
            if not sources:
                errors["base"] = "no_sources"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data=user_input,
                )

        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return SpinJamOptionsFlow()


class SpinJamOptionsFlow(config_entries.OptionsFlow):
    """Handle SpinJam options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
