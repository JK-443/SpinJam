"""Coordinator wiring for the lyrics fallback chain."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spinjam.const import (
    CONF_FALLBACK_PROVIDERS,
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_SOURCE_PLAYERS,
    DOMAIN,
    LYRICS_STATUS_DISABLED,
    LYRICS_STATUS_PLAIN,
    LYRICS_STATUS_SYNCED,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.lyrics import LyricLine, LrcLibClient, LyricsResult
from custom_components.spinjam.media_player import SpinJamMediaPlayer


class _Response:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = status
        self._payload = payload if payload is not None else {}

    async def text(self) -> str:
        return json.dumps(self._payload)

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Session:
    def __init__(self, handler) -> None:  # noqa: ANN001
        self._handler = handler

    def get(self, url: str, **kwargs: Any) -> _Response:
        return self._handler(str(url), kwargs)


def _entry(**overrides: Any) -> MockConfigEntry:
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.speaker_a"],
        CONF_LYRICS_ENABLED: True,
        CONF_HD_ARTWORK: False,
        CONF_PREFETCH: False,
        CONF_FALLBACK_PROVIDERS: ["qqmusic", "lyricsovh"],
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title="SpinJam",
        unique_id=str(overrides.get("unique_id", f"{DOMAIN}_lyrics_fb")),
        version=2,
    )


@pytest.mark.asyncio
async def test_lookup_does_not_block_the_coordinator(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {
            "media_title": "Song",
            "media_artist": "Futurist",
            "media_duration": 180,
            "media_position": 1,
        },
    )
    entry = _entry(unique_id=f"{DOMAIN}_lyrics_nonblock")
    entry.add_to_hass(hass)
    gate = asyncio.Event()

    async def slow_fetch(**_kwargs: Any) -> Any:
        await gate.wait()
        return LyricsResult(lines=(LyricLine(0.0, "Hi"),))

    client = type("Client", (), {"fetch": staticmethod(slow_fetch)})()
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._lyrics_client = client  # noqa: SLF001

    await asyncio.wait_for(coordinator.async_set_tracking(True), timeout=1)
    assert coordinator.data.active is not None
    assert coordinator.data.active.title == "Song"
    assert coordinator.data.lyrics_status is None

    gate.set()
    task = coordinator._lyrics_task  # noqa: SLF001
    assert task is not None
    await task
    assert coordinator.data.lyrics_status == LYRICS_STATUS_SYNCED
    assert coordinator.data.lyric_lines == [{"t": 0.0, "text": "Hi"}]
    # The next poll highlights from the live position (published position may be held).
    await coordinator.async_refresh()
    assert coordinator.data.lyric_current == "Hi"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_lyricsovh_plain_sets_entity_status(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {
            "media_title": "Golden Coast",
            "media_artist": "Futurist",
            "media_duration": 219,
            "media_position": 1,
        },
    )
    entry = _entry(unique_id=f"{DOMAIN}_lyrics_plain")
    entry.add_to_hass(hass)

    def handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url.endswith("/api/get"):
            return _Response(404)
        if url.endswith("/api/search"):
            return _Response(200, [])
        if "client_search_cp" in url:
            return _Response(200, {"data": {"song": {"list": []}}})
        if url.startswith("https://api.lyrics.ovh/"):
            return _Response(200, {"lyrics": "Static line"})
        raise AssertionError(url)

    session = _Session(handler)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._lyrics_client = LrcLibClient(session)  # noqa: SLF001
    await coordinator.async_set_tracking(True)
    await coordinator.async_refresh()
    task = coordinator._lyrics_task  # noqa: SLF001
    assert task is not None
    await task
    assert coordinator.data.lyrics_status == LYRICS_STATUS_PLAIN
    assert coordinator.data.lyrics_source == "lyricsovh"
    player = SpinJamMediaPlayer(coordinator, entry)
    attrs = player.extra_state_attributes
    assert attrs["lyrics_status"] == LYRICS_STATUS_PLAIN
    assert attrs["lyrics_source"] == "lyricsovh"
    assert attrs["lyric_lines"] == [{"text": "Static line"}]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_lyrics_switch_off_sets_status_disabled(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {"media_title": "Song", "media_artist": "Futurist"},
    )
    entry = _entry(
        unique_id=f"{DOMAIN}_lyrics_off",
        **{CONF_LYRICS_ENABLED: False},
    )
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    await coordinator.async_set_tracking(True)
    await coordinator.async_refresh()
    assert coordinator.data.lyrics_status == LYRICS_STATUS_DISABLED
    assert coordinator._lyrics_task is None  # noqa: SLF001
    player = SpinJamMediaPlayer(coordinator, entry)
    assert player.extra_state_attributes["lyrics_status"] == LYRICS_STATUS_DISABLED
    await coordinator.async_shutdown()
