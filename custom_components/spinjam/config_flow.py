"""Config flow for SpinJam."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .cast_entities import non_cast_displays
from .const import (
    CONF_BUILTIN_CASTING,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_RECAST_INTERVAL,
    CONF_RECAST_ON_STARTUP,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VIEW_PATH,
    CONF_VINYL_PLAYER,
    DEFAULT_BUILTIN_CASTING,
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_LYRIC_OFFSET_MS,
    DEFAULT_LYRICS_ENABLED,
    DEFAULT_NAME,
    DEFAULT_RECAST_INTERVAL,
    DEFAULT_RECAST_ON_STARTUP,
    DEFAULT_RECAST_WHILE_PLAYING,
    DEFAULT_SYNC_OFFSET_MS,
    DEFAULT_VIEW_PATH,
    DOMAIN,
)
from .dashboard import validate_dashboard_url_path


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


def entity_selector_supports_integration_filter() -> bool:
    """Return True when EntitySelector accepts integration=cast."""
    try:
        selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="media_player", integration="cast", multiple=True
            )
        )
    except vol.Invalid:
        return False
    return True


def source_players_selector() -> selector.EntitySelector:
    """Multi media_player picker; enable drag-reorder when HA supports it."""
    if entity_selector_supports_reorder():
        return selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="media_player", multiple=True, reorder=True
            )
        )
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="media_player", multiple=True)
    )


def displays_selector() -> selector.EntitySelector:
    """Cast media_player picker when the selector supports integration filter."""
    kwargs: dict[str, Any] = {"domain": "media_player", "multiple": True}
    if entity_selector_supports_integration_filter():
        kwargs["integration"] = "cast"
    if entity_selector_supports_reorder():
        kwargs["reorder"] = True
        try:
            return selector.EntitySelector(selector.EntitySelectorConfig(**kwargs))
        except vol.Invalid:
            kwargs.pop("reorder", None)
    return selector.EntitySelector(selector.EntitySelectorConfig(**kwargs))


def _add_optional_single_media_player(
    fields: dict[Any, Any], key: str, default: str | None
) -> None:
    entity_selector = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="media_player", multiple=False)
    )
    if default:
        fields[vol.Optional(key, default=default)] = entity_selector
    else:
        fields[vol.Optional(key)] = entity_selector


def _schema(defaults: dict[str, Any] | None = None, *, options: bool = False) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        vol.Required(
            CONF_SOURCE_PLAYERS,
            default=defaults.get(CONF_SOURCE_PLAYERS, []),
        ): source_players_selector(),
        vol.Optional(
            CONF_DISPLAYS,
            default=defaults.get(CONF_DISPLAYS, []),
        ): displays_selector(),
        vol.Required(
            CONF_LYRICS_ENABLED,
            default=defaults.get(CONF_LYRICS_ENABLED, DEFAULT_LYRICS_ENABLED),
        ): bool,
        vol.Required(
            CONF_SYNC_OFFSET_MS,
            default=defaults.get(CONF_SYNC_OFFSET_MS, DEFAULT_SYNC_OFFSET_MS),
        ): vol.All(vol.Coerce(int), vol.Range(min=-2000, max=2000)),
        vol.Required(
            CONF_LYRIC_OFFSET_MS,
            default=defaults.get(CONF_LYRIC_OFFSET_MS, DEFAULT_LYRIC_OFFSET_MS),
        ): vol.All(vol.Coerce(int), vol.Range(min=-5000, max=5000)),
    }
    _add_optional_single_media_player(
        fields, CONF_VINYL_PLAYER, defaults.get(CONF_VINYL_PLAYER)
    )
    if options:
        fields[vol.Required(
            CONF_BUILTIN_CASTING,
            default=defaults.get(CONF_BUILTIN_CASTING, DEFAULT_BUILTIN_CASTING),
        )] = bool
        fields[vol.Required(
            CONF_DASHBOARD_PATH,
            default=defaults.get(CONF_DASHBOARD_PATH, DEFAULT_DASHBOARD_PATH),
        )] = validate_dashboard_url_path
        fields[vol.Required(
            CONF_VIEW_PATH,
            default=defaults.get(CONF_VIEW_PATH, DEFAULT_VIEW_PATH),
        )] = str
        fields[vol.Required(
            CONF_RECAST_WHILE_PLAYING,
            default=defaults.get(
                CONF_RECAST_WHILE_PLAYING, DEFAULT_RECAST_WHILE_PLAYING
            ),
        )] = bool
        fields[vol.Required(
            CONF_RECAST_INTERVAL,
            default=defaults.get(CONF_RECAST_INTERVAL, DEFAULT_RECAST_INTERVAL),
        )] = vol.All(vol.Coerce(float), vol.Range(min=15, max=300))
        fields[vol.Required(
            CONF_RECAST_ON_STARTUP,
            default=defaults.get(CONF_RECAST_ON_STARTUP, DEFAULT_RECAST_ON_STARTUP),
        )] = bool
    return vol.Schema(fields)


def _normalize_displays(user_input: dict[str, Any]) -> list[str]:
    displays = user_input.get(CONF_DISPLAYS) or []
    if isinstance(displays, str):
        displays = [displays]
    return list(displays)


async def _async_validate_cast_displays(
    hass: HomeAssistant, displays: list[str]
) -> str | None:
    """Return an error key if any display is a known non-cast entity."""
    bad = non_cast_displays(hass, displays)
    if not bad:
        return None
    return "displays_not_cast"


class SpinJamConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SpinJam."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            sources = user_input.get(CONF_SOURCE_PLAYERS) or []
            if not sources:
                errors["base"] = "no_sources"
            else:
                displays = _normalize_displays(user_input)
                user_input[CONF_DISPLAYS] = displays
                cast_error = await _async_validate_cast_displays(self.hass, displays)
                if cast_error:
                    errors["base"] = cast_error
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
        errors: dict[str, str] = {}
        if user_input is not None:
            displays = _normalize_displays(user_input)
            user_input[CONF_DISPLAYS] = displays
            cast_error = await _async_validate_cast_displays(self.hass, displays)
            if cast_error:
                errors["base"] = cast_error
            else:
                try:
                    user_input[CONF_DASHBOARD_PATH] = validate_dashboard_url_path(
                        user_input.get(CONF_DASHBOARD_PATH)
                    )
                except vol.Invalid:
                    errors["base"] = "invalid_dashboard_path"
                else:
                    return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        if not current.get(CONF_DISPLAYS) and current.get("display_entity"):
            current[CONF_DISPLAYS] = [current["display_entity"]]
        if not current.get(CONF_DASHBOARD_PATH):
            current[CONF_DASHBOARD_PATH] = DEFAULT_DASHBOARD_PATH
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current, options=True),
            errors=errors,
        )
