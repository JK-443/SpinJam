"""Config schema smoke test — skipped unless Home Assistant is installed."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous")

from homeassistant.helpers import selector

from custom_components.spinjam.config_flow import (
    _schema,
    entity_selector_supports_reorder,
    source_players_selector,
)
from custom_components.spinjam.const import CONF_SOURCE_PLAYERS


def test_config_schema_requires_sources() -> None:
    schema = _schema()
    data = schema(
        {
            "name": "SpinJam",
            "source_players": ["media_player.living_room", "media_player.kitchen"],
            "lyrics_enabled": True,
            "sync_offset_ms": 0,
            "lyric_offset_ms": 0,
        }
    )
    # Order is preserved as priority; UI reorder keeps user order when supported.
    assert data[CONF_SOURCE_PLAYERS] == [
        "media_player.living_room",
        "media_player.kitchen",
    ]


def test_source_players_selector_enables_reorder_when_supported() -> None:
    entity_selector = source_players_selector()
    assert isinstance(entity_selector, selector.EntitySelector)
    assert entity_selector.config.get("multiple") is True
    if entity_selector_supports_reorder():
        assert entity_selector.config.get("reorder") is True
    else:
        # Older HA test harness (e.g. 2025.1) rejects reorder in CONFIG_SCHEMA.
        assert "reorder" not in entity_selector.config


def test_schema_uses_same_source_selector() -> None:
    schema = _schema()
    key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_SOURCE_PLAYERS
    )
    assert isinstance(schema.schema[key], selector.EntitySelector)
