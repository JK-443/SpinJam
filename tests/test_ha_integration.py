"""Home Assistant integration tests (pytest-homeassistant-custom-component)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spinjam.const import (
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VINYL_PLAYER,
    DOMAIN,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.lyrics import LyricLine, LyricsResult


def _entry(unique_id: str = DOMAIN, **data_overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_VINYL_PLAYER: None,
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_HD_ARTWORK: False,
        CONF_PREFETCH: False,
    }
    data.update(data_overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=unique_id,
    )


@pytest.mark.asyncio
async def test_coordinator_aggregates_stream_source(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {
            "media_title": "Everything In Its Right Place",
            "media_artist": "Radiohead",
            "media_album_name": "Kid A",
            "media_duration": 251,
            "media_position": 30,
            "entity_picture": "https://example.com/kid-a.jpg",
        },
    )
    entry = _entry(
        unique_id=f"{DOMAIN}_stream",
        **{CONF_LYRICS_ENABLED: True},
    )
    entry.add_to_hass(hass)

    lyrics = LyricsResult(
        lines=(
            LyricLine(0.0, "Intro"),
            LyricLine(25.0, "Everything"),
            LyricLine(40.0, "In its right place"),
        )
    )
    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=lyrics)

    mock_art = AsyncMock(
        resolve=AsyncMock(
            return_value=None,
        )
    )
    with (
        patch.object(SpinJamCoordinator, "_client", return_value=mock_client),
        patch.object(SpinJamCoordinator, "_artwork_resolver", return_value=mock_art),
        patch(
            "custom_components.spinjam.coordinator.async_resolve_next_track",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        coordinator = SpinJamCoordinator(hass, entry)
        await coordinator.async_set_tracking(True)
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.data.active is not None
        assert coordinator.data.active.title == "Everything In Its Right Place"
        assert coordinator.data.active.artist == "Radiohead"
        assert coordinator.data.active.kind == "stream"
        assert coordinator.data.lyric_current == "Everything"
        assert coordinator.data.lyric_next == "In its right place"
        mock_client.fetch.assert_awaited()
        await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_coordinator_line_in_uses_vinyl(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.living_room_port",
        "playing",
        {"source": "Line-in"},
    )
    hass.states.async_set(
        "media_player.spinjam_turntable",
        "playing",
        {
            "media_title": "Karma Police",
            "media_artist": "Radiohead",
            "media_album_name": "OK Computer",
        },
    )
    entry = _entry(
        unique_id=f"{DOMAIN}_vinyl",
        **{
            CONF_SOURCE_PLAYERS: [
                "media_player.living_room_port",
                "media_player.spinjam_turntable",
            ],
            CONF_VINYL_PLAYER: "media_player.spinjam_turntable",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            SpinJamCoordinator,
            "_artwork_resolver",
            return_value=AsyncMock(resolve=AsyncMock(return_value=None)),
        ),
        patch(
            "custom_components.spinjam.coordinator.async_resolve_next_track",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        coordinator = SpinJamCoordinator(hass, entry)
        await coordinator.async_set_tracking(True)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.active is not None
        assert coordinator.data.active.entity_id == "media_player.spinjam_turntable"
        assert coordinator.data.active.kind == "vinyl"
        await coordinator.async_shutdown()
    assert coordinator.data.active.title == "Karma Police"


@pytest.mark.asyncio
async def test_full_setup_registers_entity_and_services(hass: HomeAssistant) -> None:
    hass.states.async_set("media_player.living_room", "idle", {})
    entry = _entry(unique_id=f"{DOMAIN}_full")
    entry.add_to_hass(hass)

    with patch.object(
        SpinJamCoordinator,
        "_client",
        return_value=MagicMock(fetch=AsyncMock(return_value=None)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("media_player.spinjam_now_playing")
        assert state is not None
        assert state.state == "idle"
        assert hass.services.has_service(DOMAIN, "identify")
        assert hass.services.has_service(DOMAIN, "set_sync_offset")
        assert hass.services.has_service(DOMAIN, "select_album")
        assert hass.services.has_service(DOMAIN, "clear_lock")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await hass.async_stop()
