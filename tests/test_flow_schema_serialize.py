"""Ensure config/options flow schemas stay JSON-serializable for HA forms."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous_serialize")
pytest.importorskip("pytest_homeassistant_custom_component")

import voluptuous_serialize
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spinjam.config_flow import (
    SpinJamConfigFlow,
    SpinJamOptionsFlow,
    _schema,
)
from custom_components.spinjam.const import (
    CONF_BUILTIN_CASTING,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_POWER_OFF_DISPLAY_ON_STOP,
    CONF_RECAST_INTERVAL,
    CONF_RECAST_ON_STARTUP,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VIEW_PATH,
    DEFAULT_DASHBOARD_PATH,
    DOMAIN,
)


def _assert_serializable(schema) -> None:
    converted = voluptuous_serialize.convert(
        schema, custom_serializer=cv.custom_serializer
    )
    assert isinstance(converted, list)
    assert converted


def test_user_schema_serializes_with_defaults() -> None:
    _assert_serializable(_schema())


def test_options_schema_serializes_with_defaults() -> None:
    converted = voluptuous_serialize.convert(
        _schema(options=True), custom_serializer=cv.custom_serializer
    )
    assert isinstance(converted, list)
    assert converted
    fallback = next(item for item in converted if item.get("name") == "fallback_providers")
    assert fallback.get("default") == ["lyricsovh"]


def test_options_schema_serializes_with_existing_entry_defaults() -> None:
    defaults = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_DISPLAYS: ["media_player.example_tv"],
        CONF_LYRICS_ENABLED: True,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_LYRIC_OFFSET_MS: 250,
        CONF_BUILTIN_CASTING: True,
        CONF_DASHBOARD_PATH: DEFAULT_DASHBOARD_PATH,
        CONF_VIEW_PATH: "now",
        CONF_RECAST_WHILE_PLAYING: True,
        CONF_RECAST_INTERVAL: 45,
        CONF_RECAST_ON_STARTUP: False,
        CONF_POWER_OFF_DISPLAY_ON_STOP: False,
    }
    _assert_serializable(_schema(defaults, options=True))


def test_config_flow_step_schemas_serialize() -> None:
    """Audit every flow step schema (user + options init)."""
    flow = SpinJamConfigFlow()
    # Mirror schemas the steps would show (empty defaults / options defaults).
    _assert_serializable(_schema())
    _assert_serializable(_schema(options=True))
    assert flow.VERSION == 3


@pytest.mark.asyncio
async def test_options_invalid_dashboard_path_returns_field_error(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_LYRICS_ENABLED: True,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_LYRIC_OFFSET_MS: 0,
            CONF_DISPLAYS: ["media_player.example_tv"],
            CONF_DASHBOARD_PATH: DEFAULT_DASHBOARD_PATH,
            CONF_VIEW_PATH: "now",
        },
        options={},
        version=2,
        unique_id=f"{DOMAIN}_opts_path",
    )
    entry.add_to_hass(hass)

    flow = SpinJamOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    # Compatibility hook used by OptionsFlow.config_entry in this HA build.
    flow._config_entry = entry  # noqa: SLF001

    result = await flow.async_step_init(
        {
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_DISPLAYS: ["media_player.example_tv"],
            CONF_LYRICS_ENABLED: True,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_LYRIC_OFFSET_MS: 0,
            CONF_BUILTIN_CASTING: True,
            CONF_DASHBOARD_PATH: "spinjam",  # missing hyphen
            CONF_VIEW_PATH: "now",
            CONF_RECAST_WHILE_PLAYING: True,
            CONF_RECAST_INTERVAL: 45,
            CONF_RECAST_ON_STARTUP: False,
            CONF_POWER_OFF_DISPLAY_ON_STOP: False,
        }
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_DASHBOARD_PATH: "invalid_path"}
    # Form must remain serializable after the error path.
    _assert_serializable(result["data_schema"])
