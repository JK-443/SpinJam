"""v0.6.0: HD artwork scoring/cache/resolver, prefetch, lyrics switch."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam.artwork import (
    ArtworkDiskCache,
    ArtworkMemoryCache,
    ArtworkResolver,
    ArtworkResult,
    cache_key,
    itunes_hd_url,
    score_match,
)
from custom_components.spinjam.const import (
    CONF_DISPLAYS,
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.dashboard import CONTROLS_TILES, spinjam_controls_view_config
from custom_components.spinjam.next_track import (
    NextTrackInfo,
    next_from_attributes,
    _parse_ma_queue_payload,
)

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache


def test_itunes_hd_url_rewrites_size() -> None:
    src = "https://example.invalid/image/100x100bb.jpg"
    assert "1500x1500bb" in itunes_hd_url(src, prefer_3000=False)
    assert "3000x3000bb" in itunes_hd_url(src, prefer_3000=True)


def test_score_match_prefers_correct_album_and_duration() -> None:
    good = score_match(
        query_artist="Artist A",
        query_title="Song One",
        query_album="Album Alpha",
        query_duration=200.0,
        cand_artist="Artist A",
        cand_title="Song One",
        cand_album="Album Alpha",
        cand_duration=201.0,
    )
    wrong_album = score_match(
        query_artist="Artist A",
        query_title="Song One",
        query_album="Album Alpha",
        query_duration=200.0,
        cand_artist="Artist A",
        cand_title="Song One",
        cand_album="Greatest Hits",
        cand_duration=201.0,
    )
    assert good > wrong_album
    assert good >= 0.7


def test_cache_key_normalized() -> None:
    assert cache_key("The Artist!", "My Album") == cache_key("the artist", "my album")
    assert "|" in cache_key("Artist", None, title="Track")


def test_memory_and_disk_cache(tmp_path: Path) -> None:
    mem = ArtworkMemoryCache(maxsize=2)
    mem.set("a|b", ArtworkResult(url="https://example.invalid/a.jpg", source="itunes"))
    assert mem.get("a|b").url.endswith("a.jpg")  # type: ignore[union-attr]
    assert mem.get("missing") is Ellipsis

    disk = ArtworkDiskCache(tmp_path / "artwork_cache.json", maxsize=2)
    disk.set("a|b", ArtworkResult(url="https://example.invalid/a.jpg", source="itunes", score=0.9))
    disk.set("c|d", ArtworkResult(url="https://example.invalid/c.jpg", source="coverartarchive"))
    disk2 = ArtworkDiskCache(tmp_path / "artwork_cache.json", maxsize=2)
    hit = disk2.get("a|b")
    assert isinstance(hit, ArtworkResult)
    assert hit.source == "itunes"
    raw = json.loads((tmp_path / "artwork_cache.json").read_text(encoding="utf-8"))
    assert "items" in raw


@pytest.mark.asyncio
async def test_resolver_itunes_then_fallback_entity_picture() -> None:
    session = MagicMock()

    class _Resp:
        status = 200

        async def json(self, content_type=None):
            return {
                "results": [
                    {
                        "artistName": "Artist A",
                        "trackName": "Song One",
                        "collectionName": "Album Alpha",
                        "artworkUrl100": "https://is1-ssl.mzstatic.example/100x100bb.jpg",
                        "trackTimeMillis": 200000,
                    }
                ]
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    session.get = MagicMock(return_value=_Resp())
    resolver = ArtworkResolver(session)
    result = await resolver.resolve(
        artist="Artist A",
        title="Song One",
        album="Album Alpha",
        duration=200.0,
        entity_picture="/api/pic",
    )
    assert result is not None
    assert result.source == "itunes"
    assert "3000x3000bb" in result.url


@pytest.mark.asyncio
async def test_resolver_musicbrainz_caa_fallback() -> None:
    session = MagicMock()

    class _ItunesEmpty:
        status = 200

        async def json(self, content_type=None):
            return {"results": []}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _MbResp:
        status = 200

        async def json(self, content_type=None):
            return {
                "releases": [
                    {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "title": "Album Alpha",
                        "artist-credit": [{"name": "Artist A"}],
                    }
                ]
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _HeadOk:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def _get(url, *args, **kwargs):
        if "itunes" in str(url):
            return _ItunesEmpty()
        return _MbResp()

    session.get = MagicMock(side_effect=_get)
    session.head = MagicMock(return_value=_HeadOk())
    resolver = ArtworkResolver(session)
    with patch("custom_components.spinjam.artwork.MUSICBRAINZ_MIN_INTERVAL", 0):
        result = await resolver.resolve(
            artist="Artist A",
            title="Song One",
            album="Album Alpha",
            entity_picture=None,
        )
    assert result is not None
    assert result.source == "coverartarchive"
    assert "coverartarchive.org" in result.url


def test_next_from_attributes_flat_and_nested() -> None:
    flat = next_from_attributes(
        {
            "media_next_title": "Next Song",
            "media_next_artist": "Artist B",
            "media_next_album": "Album B",
        }
    )
    assert flat is not None
    assert flat.title == "Next Song"
    nested = next_from_attributes(
        {
            "next_track": {
                "media_title": "Queued",
                "media_artist": "Artist C",
                "duration": 180,
            }
        }
    )
    assert nested is not None
    assert nested.title == "Queued"
    assert nested.duration == 180.0


def test_parse_ma_queue_next_item() -> None:
    payload = {
        "current_index": 0,
        "items": [
            {"name": "Now", "artist": "A"},
            {"name": "Later", "artist": "B", "album": {"name": "Alb"}, "duration": 210},
        ],
    }
    nxt = _parse_ma_queue_payload(payload)
    assert nxt is not None
    assert nxt.title == "Later"
    assert nxt.album == "Alb"


def test_controls_dashboard_includes_lyrics_tile() -> None:
    view = spinjam_controls_view_config()
    assert view["path"] == "controls"
    entities = [card["entity"] for card in CONTROLS_TILES]
    assert "switch.spinjam_lyrics" in entities
    assert "switch.spinjam_cast" in entities


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.speaker_a"],
        CONF_DISPLAYS: ["media_player.example_tv"],
        CONF_LYRICS_ENABLED: True,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_RECAST_WHILE_PLAYING: False,
        CONF_HD_ARTWORK: True,
        CONF_PREFETCH: True,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_v060"),
        version=2,
    )


@pytest.mark.asyncio
async def test_lyrics_switch_persists_and_clears_lyrics(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_lyrics_sw")
    entry.add_to_hass(hass)
    mock_restore_cache(hass, [State("switch.spinjam_lyrics", STATE_OFF)])

    with (
        patch.object(
            SpinJamCoordinator,
            "_client",
            return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
        ),
        patch.object(
            SpinJamCoordinator,
            "_artwork_resolver",
            return_value=AsyncMock(
                resolve=AsyncMock(return_value=None),
            ),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    lyrics = hass.states.get("switch.spinjam_lyrics")
    assert lyrics is not None and lyrics.state == STATE_OFF
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.lyrics_enabled is False

    await coordinator.async_set_lyrics_enabled(True)
    assert coordinator._lyrics_display_enabled is True  # noqa: SLF001
    await coordinator.async_set_lyrics_enabled(False)
    assert coordinator.data.lyric_lines is None
    assert coordinator.data.lyrics_enabled is False

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_coordinator_sets_artwork_hd_attributes(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {
            "media_title": "Song One",
            "media_artist": "Artist A",
            "media_album_name": "Album Alpha",
            "entity_picture": "/api/lo.jpg",
            "media_duration": 200,
            "media_position": 10,
        },
    )
    entry = _entry(unique_id=f"{DOMAIN}_art_attrs")
    entry.add_to_hass(hass)

    art = ArtworkResult(
        url="https://example.invalid/hd.jpg", source="itunes", score=0.95
    )
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=art)

    with (
        patch.object(SpinJamCoordinator, "_artwork_resolver", return_value=resolver),
        patch.object(
            SpinJamCoordinator,
            "_client",
            return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
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
        assert coordinator.data.artwork_hd == "https://example.invalid/hd.jpg"
        assert coordinator.data.artwork_source == "itunes"
        assert coordinator.data.lyrics_enabled is True
        await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_prefetch_loads_next_artwork(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.speaker_a",
        "playing",
        {
            "media_title": "Song One",
            "media_artist": "Artist A",
            "media_album_name": "Album Alpha",
            "entity_picture": "/api/lo.jpg",
            "media_duration": 200,
            "media_position": 5,
            "media_next_title": "Next Song",
            "media_next_artist": "Artist B",
        },
    )
    entry = _entry(unique_id=f"{DOMAIN}_prefetch")
    entry.add_to_hass(hass)

    async def _resolve(**kwargs):
        title = kwargs.get("title")
        if title == "Next Song":
            return ArtworkResult(
                url="https://example.invalid/next.jpg", source="itunes"
            )
        return ArtworkResult(url="https://example.invalid/now.jpg", source="itunes")

    resolver = AsyncMock()
    resolver.resolve = AsyncMock(side_effect=_resolve)
    nxt = NextTrackInfo(artist="Artist B", title="Next Song", album="Album B")

    with (
        patch.object(SpinJamCoordinator, "_artwork_resolver", return_value=resolver),
        patch.object(
            SpinJamCoordinator,
            "_client",
            return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
        ),
        patch(
            "custom_components.spinjam.coordinator.async_resolve_next_track",
            new_callable=AsyncMock,
            return_value=nxt,
        ),
    ):
        coordinator = SpinJamCoordinator(hass, entry)
        coordinator._tracking_enabled = True  # noqa: SLF001
        await coordinator.async_refresh()
        assert coordinator.data.active is not None
        assert coordinator.data.artwork_hd == "https://example.invalid/now.jpg"
        art_url = await coordinator._async_prefetch_for_active(  # noqa: SLF001
            coordinator.data.active
        )
        assert art_url == "https://example.invalid/next.jpg"
        coordinator._apply_artwork_next(art_url)  # noqa: SLF001
        assert coordinator.data.artwork_next == "https://example.invalid/next.jpg"
        await coordinator.async_shutdown()
