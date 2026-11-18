"""Lyric delay formatting, buttons, clamp, and live updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.spinjam.const import (
    CONF_DISPLAYS,
    CONF_HD_ARTWORK,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
    BUTTON_LYRICS_EARLIER_ENTITY_ID,
    BUTTON_LYRICS_LATER_ENTITY_ID,
    BUTTON_LYRIC_DELAY_RESET_ENTITY_ID,
    NUMBER_LYRIC_OFFSET_ENTITY_ID,
    SENSOR_LYRIC_DELAY_ENTITY_ID,
)
from custom_components.spinjam.lyric_delay import format_lyric_delay, lyric_delay_toast
from custom_components.spinjam.lyrics import (
    LyricLine,
    LyricsResult,
    annotate_lyrics_duration,
    lyrics_compare_duration,
)

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_delay_words_match_the_sign() -> None:
    assert format_lyric_delay(2000) == "+2.0 s (later)"
    assert format_lyric_delay(2250) == "+2.25 s (later)"
    assert format_lyric_delay(-250) == "-0.25 s (earlier)"
    assert format_lyric_delay(0) == "0.0 s (on time)"
    assert lyric_delay_toast(2000, 2250) == "Lyrics +250 ms later, now +2.25 s"


def test_scale_is_off_unless_asked_and_only_for_a_moderate_gap() -> None:
    result = LyricsResult(
        lines=(LyricLine(0.0, "Start"), LyricLine(180.0, "End")),
        catalog_duration=180.0,
    )
    assert lyrics_compare_duration(result) == 180.0
    plain = annotate_lyrics_duration(result, 200.0, scale=False)
    assert plain.lines[1].start == 180.0
    assert plain.duration_delta == pytest.approx(-20.0)
    assert plain.reported_duration == 180.0
    scaled = annotate_lyrics_duration(result, 200.0, scale=True)
    assert scaled.lines[1].start == pytest.approx(200.0)
    assert scaled.duration_delta == pytest.approx(-20.0)
    huge = annotate_lyrics_duration(result, 400.0, scale=True)
    assert huge.lines[1].start == 180.0


@pytest.mark.asyncio
async def test_delay_buttons_clamp_persist_and_publish_live(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.speaker_a"],
            CONF_DISPLAYS: ["media_player.example_tv"],
            CONF_LYRICS_ENABLED: False,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_LYRIC_OFFSET_MS: 2000,
            CONF_RECAST_WHILE_PLAYING: False,
            CONF_HD_ARTWORK: False,
            CONF_PREFETCH: False,
        },
        title="SpinJam",
        unique_id=f"{DOMAIN}_delay_buttons",
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    number = hass.states.get(NUMBER_LYRIC_OFFSET_ENTITY_ID)
    assert number is not None
    assert float(number.state) == 2000
    assert hass.states.get(SENSOR_LYRIC_DELAY_ENTITY_ID).state == "+2.0 s (later)"

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": BUTTON_LYRICS_LATER_ENTITY_ID},
            blocking=True,
        )
        await hass.async_block_till_done()
        reload.assert_not_awaited()

    assert float(hass.states.get(NUMBER_LYRIC_OFFSET_ENTITY_ID).state) == 2250
    assert hass.states.get(SENSOR_LYRIC_DELAY_ENTITY_ID).state == "+2.25 s (later)"
    player = hass.states.get("media_player.spinjam_now_playing")
    assert player is not None
    assert player.attributes["lyric_offset_ms"] == 2250
    assert entry.options[CONF_LYRIC_OFFSET_MS] == 2250

    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_set_lyric_offset(4900)
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": BUTTON_LYRICS_LATER_ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.lyric_offset_ms == 5000
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": BUTTON_LYRICS_LATER_ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.lyric_offset_ms == 5000

    await coordinator.async_set_lyric_offset(-4900)
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": BUTTON_LYRICS_EARLIER_ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.lyric_offset_ms == -5000
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": BUTTON_LYRICS_EARLIER_ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.lyric_offset_ms == -5000

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": BUTTON_LYRIC_DELAY_RESET_ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.lyric_offset_ms == 2000
    assert hass.states.get(SENSOR_LYRIC_DELAY_ENTITY_ID).state == "+2.0 s (later)"

    restarted = type(coordinator)(hass, entry)
    assert restarted.lyric_offset_ms == 2000
    await restarted.async_shutdown()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
