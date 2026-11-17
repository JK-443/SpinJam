"""Config schema smoke test — skipped unless Home Assistant is installed."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous")

from custom_components.spinjam.config_flow import _schema
from custom_components.spinjam.const import CONF_SOURCE_PLAYERS


def test_config_schema_requires_sources() -> None:
    schema = _schema()
    data = schema(
        {
            "name": "SpinJam",
            "source_players": ["media_player.living_room"],
            "lyrics_enabled": True,
            "sync_offset_ms": 0,
        }
    )
    assert data[CONF_SOURCE_PLAYERS] == ["media_player.living_room"]
