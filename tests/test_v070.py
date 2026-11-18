"""v0.7.0: source select, derived tracking, registry cleanup, device page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.spinjam.const import (
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VINYL_PLAYER,
    DEVICE_PAGE_TRANSLATION_KEYS,
    DOMAIN,
    SELECT_SOURCE_ENTITY_ID,
)
from custom_components.spinjam.dashboard import async_upgrade_configured_dashboard

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME, EntityCategory, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

ROOT = Path(__file__).resolve().parents[1]


def _entry(**overrides) -> MockConfigEntry:
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.speaker_a", "media_player.speaker_b"],
        CONF_VINYL_PLAYER: "media_player.turntable",
        CONF_DISPLAYS: ["media_player.example_tv"],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_RECAST_WHILE_PLAYING: False,
        CONF_HD_ARTWORK: False,
        CONF_PREFETCH: False,
        CONF_DASHBOARD_PATH: "spinjam-tv",
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title="SpinJam",
        unique_id=overrides.get("unique_id", f"{DOMAIN}_v070"),
        version=overrides.get("version", 3),
    )


def _playing(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {
            "friendly_name": "Speaker A",
            "media_title": "Track A",
            "media_artist": "Artist A",
            "media_position": 4,
            "media_duration": 200,
        },
    )
    hass.states.async_set(
        "media_player.speaker_b",
        "playing",
        {
            "friendly_name": "Room Speaker",
            "media_title": "Track B",
            "media_artist": "Artist B",
            "media_position": 9,
            "media_duration": 180,
        },
    )
    hass.states.async_set(
        "media_player.turntable",
        "playing",
        {
            "friendly_name": "Turntable",
            "media_title": "Side A",
            "media_artist": "Artist V",
            "media_position": 1,
            "media_duration": 400,
        },
    )


def test_device_page_translation_keys_icons_and_config_category() -> None:
    strings = json.loads((ROOT / "custom_components/spinjam/strings.json").read_text())
    english = json.loads(
        (ROOT / "custom_components/spinjam/translations/en.json").read_text()
    )
    assert strings["entity"] == english["entity"]
    for domain, key, name in DEVICE_PAGE_TRANSLATION_KEYS:
        assert strings["entity"][domain][key]["name"] == name

    from custom_components.spinjam.media_player import SpinJamMediaPlayer
    from custom_components.spinjam.number import SpinJamLyricOffsetNumber
    from custom_components.spinjam.select import SpinJamDisplaySelect, SpinJamSourceSelect
    from custom_components.spinjam.switch import SpinJamCastSwitch, SpinJamLyricsSwitch

    assert getattr(SpinJamCastSwitch, "__attr_translation_key") == "cast"
    assert getattr(SpinJamCastSwitch, "__attr_icon") == "mdi:cast"
    assert getattr(SpinJamDisplaySelect, "__attr_translation_key") == "display"
    assert getattr(SpinJamDisplaySelect, "__attr_icon") == "mdi:television"
    assert getattr(SpinJamSourceSelect, "__attr_translation_key") == "source"
    assert getattr(SpinJamSourceSelect, "__attr_icon") == "mdi:speaker-multiple"
    assert getattr(SpinJamLyricsSwitch, "__attr_translation_key") == "lyrics"
    assert getattr(SpinJamLyricsSwitch, "__attr_icon") == "mdi:microphone-variant"
    assert getattr(SpinJamMediaPlayer, "__attr_translation_key") == "now_playing"
    assert getattr(SpinJamMediaPlayer, "__attr_icon") == "mdi:album"
    assert getattr(SpinJamLyricOffsetNumber, "__attr_translation_key") == "lyric_offset"
    assert (
        getattr(SpinJamLyricOffsetNumber, "__attr_entity_category")
        == EntityCategory.CONFIG
    )
    assert "__attr_entity_category" not in SpinJamCastSwitch.__dict__


@pytest.mark.asyncio
async def test_source_select_fixed_persists_and_refreshes_options(
    hass: HomeAssistant,
) -> None:
    _playing(hass)
    entry = _entry(unique_id=f"{DOMAIN}_source_select")
    entry.add_to_hass(hass)
    mock_restore_cache(
        hass,
        [
            State(
                SELECT_SOURCE_ENTITY_ID,
                "Speaker B",
                {"source_entity_id": "media_player.speaker_b"},
            )
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    select_state = hass.states.get(SELECT_SOURCE_ENTITY_ID)
    assert select_state is not None
    # Friendly name changed since the stored label; entity id still matches.
    assert select_state.state == "Room Speaker"
    options = list(select_state.attributes["options"])
    assert options[0] == "Automatic"
    assert "Speaker A" in options
    assert "Room Speaker" in options
    assert "Turntable" in options

    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_set_tracking(True)
    await hass.async_block_till_done()
    player = hass.states.get("media_player.spinjam_now_playing")
    assert player is not None
    assert player.attributes["selected_source"] == "media_player.speaker_b"
    assert coordinator.tracking_enabled is True
    assert player.attributes["active_source"] == "media_player.speaker_b"
    assert player.attributes["media_title"] == "Track B"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT_SOURCE_ENTITY_ID, "option": "Automatic"},
        blocking=True,
    )
    await hass.async_block_till_done()
    player = hass.states.get("media_player.spinjam_now_playing")
    assert player is not None
    assert player.attributes["selected_source"] == "Automatic"
    # Sticky within the track: speaker_b is still playing, so it stays.
    assert player.attributes["active_source"] == "media_player.speaker_b"

    hass.states.async_set(
        "media_player.speaker_b",
        "paused",
        {
            "friendly_name": "Room Speaker",
            "media_title": "Track B",
            "media_artist": "Artist B",
            "media_position": 9,
            "media_duration": 180,
        },
    )
    await hass.async_block_till_done()
    await coordinator.async_refresh()
    player = hass.states.get("media_player.spinjam_now_playing")
    assert player is not None
    assert player.attributes["active_source"] == "media_player.speaker_a"
    assert player.attributes["media_title"] == "Track A"

    hass.states.async_set(
        "media_player.speaker_c",
        "idle",
        {"friendly_name": "Speaker C"},
    )
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_SOURCE_PLAYERS: ["media_player.speaker_c"],
            CONF_VINYL_PLAYER: "",
        },
    )
    await hass.async_block_till_done()
    select_state = hass.states.get(SELECT_SOURCE_ENTITY_ID)
    assert select_state is not None
    refreshed = list(select_state.attributes["options"])
    assert refreshed == ["Automatic", "Speaker C"]
    assert select_state.state == "Automatic"
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_cast_drives_tracking_and_registry_drops_old_switch(
    hass: HomeAssistant,
) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_tracking_gone", version=2)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "switch",
        DOMAIN,
        "spinjam_tracking",
        suggested_object_id="spinjam_tracking",
        config_entry=entry,
    )
    hass.states.async_set("switch.spinjam_tracking", STATE_ON)
    assert registry.async_get("switch.spinjam_tracking") is not None

    registry.async_get_or_create(
        "media_player",
        "demo",
        "example_tv_unique",
        suggested_object_id="example_tv",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 3
    assert registry.async_get("switch.spinjam_tracking") is None
    assert hass.states.get("switch.spinjam_tracking") is None
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.tracking_enabled is False

    from custom_components.spinjam.switch import async_remove_legacy_tracking_switch

    assert async_remove_legacy_tracking_switch(hass) is None

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.spinjam_cast"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.cast_active is True
    assert coordinator.tracking_enabled is True
    assert hass.states.get("switch.spinjam_cast").state == STATE_ON

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.spinjam_cast"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.cast_active is False
    assert coordinator.tracking_enabled is False
    assert hass.states.get("switch.spinjam_tracking") is None
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_setup_upgrades_controls_dashboard(hass: HomeAssistant) -> None:
    class _Store:
        def __init__(self) -> None:
            self.config = {
                "views": [
                    {
                        "title": "Controls",
                        "path": "controls",
                        "type": "masonry",
                        "cards": [
                            {
                                "type": "tile",
                                "entity": "switch.spinjam_cast",
                                "name": "Cast",
                            },
                            {
                                "type": "tile",
                                "entity": "switch.spinjam_tracking",
                                "name": "Tracking",
                            },
                            {"type": "markdown", "content": "leave this card"},
                        ],
                    }
                ]
            }

        async def async_load(self, force: bool = False) -> dict:
            _ = force
            return self.config

        async def async_save(self, config: dict) -> None:
            self.config = config

    store = _Store()
    hass.data["lovelace"] = {
        "dashboards": {"spinjam-tv": store},
        "dashboards_collection": object(),
    }
    entry = _entry(unique_id=f"{DOMAIN}_dash_setup")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    cards = store.config["views"][0]["cards"]
    entities = [card.get("entity") for card in cards]
    assert "switch.spinjam_tracking" not in entities
    assert "select.spinjam_source" in entities
    assert "select.spinjam_display" in entities
    assert "switch.spinjam_lyrics" in entities
    assert any(card.get("content") == "leave this card" for card in cards)
    first = [dict(card) for card in cards]

    assert await async_upgrade_configured_dashboard(hass, entry) is True
    assert store.config["views"][0]["cards"] == first
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
