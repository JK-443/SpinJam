"""Tests for Cast start/stop hooks and lyric_lines / lyric_offset."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam.const import (
    ATTR_LYRIC_LINES,
    ATTR_LYRIC_OFFSET_MS,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VIEW_PATH,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.lyrics import LyricLine, LyricsResult

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_DISPLAYS: ["media_player.living_room_tv"],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_LYRIC_OFFSET_MS: 0,
        CONF_DASHBOARD_PATH: "spinjam",
        CONF_VIEW_PATH: "now",
        CONF_RECAST_WHILE_PLAYING: False,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_cast"),
    )


@pytest.mark.asyncio
async def test_start_casts_lovelace_view(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cast_start")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    events: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_START, lambda e: events.append(e.data))

    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
        return_value=True,
    ) as show:
        target = await coordinator.async_start("media_player.living_room_tv")
        await hass.async_block_till_done()

    assert target == "media_player.living_room_tv"
    assert coordinator._cast_active is True  # noqa: SLF001
    show.assert_awaited_once()
    kwargs = show.await_args.kwargs
    assert kwargs["entity_id"] == "media_player.living_room_tv"
    assert kwargs["dashboard_path"] == "spinjam"
    assert kwargs["view_path"] == "now"
    assert events and events[-1]["display"] == "media_player.living_room_tv"
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_stop_turns_off_cast_entity(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cast_stop")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = "media_player.living_room_tv"
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = "media_player.living_room_tv"  # noqa: SLF001

    events: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_STOP, lambda e: events.append(e.data))

    with patch(
        "custom_components.spinjam.coordinator.async_end_cast",
        new_callable=AsyncMock,
        return_value=True,
    ) as end:
        await coordinator.async_stop()
        await hass.async_block_till_done()

    end.assert_awaited_once_with(hass, "media_player.living_room_tv")
    assert coordinator._cast_active is False  # noqa: SLF001
    assert events and events[-1].get("display") == "media_player.living_room_tv"
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_cast_helpers_call_services() -> None:
    from custom_components.spinjam import cast as cast_mod

    recorded: list[tuple[str, str, dict]] = []

    async def _fake_call(domain, service, service_data=None, **kwargs):
        recorded.append((domain, service, dict(service_data or {})))

    fake_hass = MagicMock()
    fake_hass.services.has_service.return_value = True
    fake_hass.services.async_call = AsyncMock(side_effect=_fake_call)

    ok = await cast_mod.async_show_now_playing(
        fake_hass,
        entity_id="media_player.living_room_tv",
        dashboard_path="spinjam",
        view_path="now",
    )
    assert ok is True
    ok2 = await cast_mod.async_end_cast(fake_hass, "media_player.living_room_tv")
    assert ok2 is True

    assert recorded[0][:2] == ("cast", "show_lovelace_view")
    assert recorded[0][2]["dashboard_path"] == "spinjam"
    assert recorded[1][:2] == ("media_player", "turn_off")


@pytest.mark.asyncio
async def test_lyric_offset_and_lines(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {
            "media_title": "Everything In Its Right Place",
            "media_artist": "Radiohead",
            "media_album_name": "Kid A",
            "media_duration": 251,
            "media_position": 30,
        },
    )
    entry = _entry(
        unique_id=f"{DOMAIN}_lyrics_offset",
        **{
            CONF_LYRICS_ENABLED: True,
            CONF_LYRIC_OFFSET_MS: -5000,  # 5s earlier → still on "Everything" at t=25
            CONF_DISPLAYS: [],
        },
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

    with patch.object(SpinJamCoordinator, "_client", return_value=mock_client):
        coordinator = SpinJamCoordinator(hass, entry)
        await coordinator.async_refresh()

    # position 30 + (-5s) = 25 → "Everything"
    assert coordinator.data.lyric_current == "Everything"
    assert coordinator.data.lyric_offset_ms == -5000
    assert coordinator.data.lyric_lines is not None
    assert coordinator.data.lyric_lines[1]["text"] == "Everything"
    attrs = coordinator.as_attributes()
    assert attrs[ATTR_LYRIC_OFFSET_MS] == -5000
    assert attrs[ATTR_LYRIC_LINES][0]["t"] == 0.0
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_options_schema_includes_cast_fields() -> None:
    pytest.importorskip("homeassistant")
    from custom_components.spinjam.config_flow import _schema

    schema = _schema(options=True)
    data = schema(
        {
            "name": "SpinJam",
            "source_players": ["media_player.living_room"],
            "displays": ["media_player.living_room_tv"],
            "lyrics_enabled": True,
            "sync_offset_ms": 0,
            "lyric_offset_ms": 100,
            "dashboard_path": "spinjam",
            "view_path": "now",
            "recast_while_playing": True,
            "recast_interval": 45,
        }
    )
    assert data[CONF_DASHBOARD_PATH] == "spinjam"
    assert data[CONF_VIEW_PATH] == "now"
    assert data[CONF_LYRIC_OFFSET_MS] == 100
