"""Lyrics fallback chain with mocked HTTP (no Home Assistant)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from custom_components.spinjam.const import (
    LRCLIB_API,
    LRCLIB_SEARCH_API,
    LYRICS_NOT_FOUND_TTL_SEC,
    LYRICS_PROVIDER_SKIP_SEC,
    LYRICS_STATUS_ERROR,
    LYRICS_STATUS_INSTRUMENTAL,
    LYRICS_STATUS_NOT_FOUND,
    LYRICS_STATUS_PLAIN,
    LYRICS_STATUS_SYNCED,
    QQMUSIC_LYRIC_API,
    QQMUSIC_SEARCH_API,
)
from custom_components.spinjam.lyrics import (
    LrcLibClient,
    clean_title,
    normalize_fallback_providers,
)

_ROOT = Path(__file__).resolve().parents[1]
_CARD = _ROOT / "custom_components" / "spinjam" / "www" / "spinjam-lyrics-card.js"


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Response:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    async def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload if self._payload is not None else {})

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Session:
    def __init__(self, handler) -> None:  # noqa: ANN001
        self._handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((str(url), kwargs))
        outcome = self._handler(str(url), kwargs)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def urls(self) -> list[str]:
        return [url for url, _kwargs in self.calls]


def _client(handler, clock: _Clock | None = None) -> tuple[LrcLibClient, _Session, _Clock]:
    clock = clock or _Clock()
    session = _Session(handler)
    return LrcLibClient(session, monotonic_fn=clock), session, clock


def _synced(text: str = "[00:01.00]Hello there") -> dict[str, Any]:
    return {
        "instrumental": False,
        "syncedLyrics": text,
        "artistName": "Futurist",
        "trackName": "Song",
        "duration": 180,
    }


def _qq_song(
    *,
    mid: str = "mid-good",
    name: str = "Golden Coast",
    artist: str = "Futurist",
    interval: int = 219,
) -> dict[str, Any]:
    return {
        "songmid": mid,
        "songname": name,
        "interval": interval,
        "singer": [{"name": artist}],
    }


def _qq_lyric() -> str:
    return "\n".join(
        [
            "[ti:Golden Coast]",
            "[ar:Futurist]",
            "[al:Coast]",
            "[by:Example]",
            "[offset:0]",
            "[00:00.00]Golden Coast - Futurist",
            "[00:01.00]作词: Example",
            "[00:02.00]作曲: Example",
            "[00:03.00]编曲: Example",
            "[00:04.00]制作人: Example",
            "[00:05.00]Lyrics by Example",
            "[00:06.00]Composed by Example",
            "[00:12.00]Wave on the coast",
            "[00:20.00]Second line",
        ]
    )


def test_clean_title_strips_suffixes() -> None:
    assert clean_title("Song - Remastered 2011") == "Song"
    assert clean_title("Song (feat. X)") == "Song"
    assert clean_title("Song (ft. X)") == "Song"
    assert clean_title("Song (Live at the Hall)") == "Song"
    assert clean_title("Song (Deluxe Version)") == "Song"
    assert clean_title("Song (Radio Edit)") == "Song"
    assert clean_title("Song - Single") == "Song"
    assert clean_title("Song - EP") == "Song"
    assert clean_title("Song (Remastered)") == "Song"


def test_normalize_fallback_providers_preserves_order() -> None:
    assert normalize_fallback_providers(None) == ["lyricsovh"]
    assert normalize_fallback_providers([]) == []
    assert normalize_fallback_providers(["qqmusic", "lyricsovh", "qqmusic"]) == [
        "qqmusic",
        "lyricsovh",
    ]
    assert normalize_fallback_providers(["nope", "lyricsovh"]) == ["lyricsovh"]


@pytest.mark.asyncio
async def test_lrclib_get_404_then_search_prefers_synced() -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> _Response:
        if url == LRCLIB_API:
            return _Response(404)
        assert url == LRCLIB_SEARCH_API
        params = kwargs["params"]
        assert params["track_name"] == "Song"
        assert params["artist_name"] == "Futurist"
        return _Response(
            200,
            [
                {
                    "trackName": "Song",
                    "artistName": "Other",
                    "duration": 180,
                    "syncedLyrics": "[00:01.00]Wrong artist",
                },
                {
                    "trackName": "Song",
                    "artistName": "The Futurist Band",
                    "duration": 190,
                    "syncedLyrics": "[00:01.00]Too far",
                },
                {
                    "trackName": "Song",
                    "artistName": "futurist",
                    "duration": 181,
                    "plainLyrics": "plain only",
                },
                {
                    "trackName": "Song",
                    "artistName": "Futurist",
                    "duration": 182,
                    "syncedLyrics": "[00:01.00]Hello there",
                },
            ],
        )

    client, session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Song",
        duration=180,
        fallback_providers=[],
    )
    assert found.status == LYRICS_STATUS_SYNCED
    assert found.source == "lrclib"
    assert found.result is not None
    assert found.result.lines[0].text == "Hello there"
    assert all("y.qq.com" not in url and "lyrics.ovh" not in url for url in session.urls())
    timeout = session.calls[0][1]["timeout"]
    assert timeout.total <= 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dirty",
    ["Song - Remastered 2011", "Song (feat. X)"],
)
async def test_title_cleanup_retries_lrclib_with_clean_title(dirty: str) -> None:
    gets: list[str] = []

    def handler(url: str, kwargs: dict[str, Any]) -> _Response:
        params = kwargs.get("params") or {}
        if url == LRCLIB_API:
            gets.append(params["track_name"])
            if params["track_name"] == "Song":
                return _Response(200, _synced("[00:04.00]Clean hit"))
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(
                200,
                [
                    {
                        "trackName": "Unrelated",
                        "artistName": "Futurist",
                        "duration": 180,
                        "syncedLyrics": "[00:01.00]No",
                    }
                ],
            )
        raise AssertionError(url)

    client, _session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title=dirty,
        duration=180,
        fallback_providers=[],
    )
    assert found.status == LYRICS_STATUS_SYNCED
    assert found.result is not None
    assert found.result.lines[0].text == "Clean hit"
    assert gets[0] == dirty
    assert "Song" in gets


@pytest.mark.asyncio
async def test_qqmusic_synced_strips_metadata_and_credits() -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> _Response:
        if url in (LRCLIB_API, LRCLIB_SEARCH_API):
            return _Response(404 if url == LRCLIB_API else 200, [] if "search" in url else None)
        if url == QQMUSIC_SEARCH_API:
            headers = kwargs["headers"]
            assert headers["Referer"] == "https://y.qq.com/"
            assert "Mozilla" in headers["User-Agent"]
            assert kwargs["params"]["w"] == "Futurist Golden Coast"
            return _Response(
                200,
                {
                    "data": {
                        "song": {
                            "list": [
                                _qq_song(mid="mid-bad", artist="Someone Else"),
                                _qq_song(),
                            ]
                        }
                    }
                },
            )
        if url == QQMUSIC_LYRIC_API:
            assert kwargs["params"]["songmid"] == "mid-good"
            assert kwargs["params"]["nobase64"] == 1
            return _Response(200, {"lyric": _qq_lyric()})
        raise AssertionError(url)

    client, _session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Golden Coast",
        duration=219,
        fallback_providers=["qqmusic"],
    )
    assert found.status == LYRICS_STATUS_SYNCED
    assert found.source == "qqmusic"
    assert found.result is not None
    texts = [line.text for line in found.result.lines]
    assert texts == ["Wave on the coast", "Second line"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("artist", "interval"),
    [("Someone Else", 219), ("Futurist", 30)],
)
async def test_qqmusic_skips_wrong_artist_or_duration(artist: str, interval: int) -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> _Response:
        if url == LRCLIB_API:
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(200, [])
        if url == QQMUSIC_SEARCH_API:
            return _Response(
                200,
                {"data": {"song": {"list": [_qq_song(artist=artist, interval=interval)]}}},
            )
        if url == QQMUSIC_LYRIC_API:
            raise AssertionError("lyric endpoint should not be called")
        raise AssertionError(url)

    client, _session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Golden Coast",
        duration=219,
        fallback_providers=["qqmusic"],
    )
    assert found.status == LYRICS_STATUS_NOT_FOUND


@pytest.mark.asyncio
async def test_lyricsovh_plain_after_lrclib_and_qq_miss() -> None:
    order: list[str] = []

    def handler(url: str, kwargs: dict[str, Any]) -> _Response:
        order.append(url)
        if url == LRCLIB_API:
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(200, [])
        if url == QQMUSIC_SEARCH_API:
            return _Response(200, {"data": {"song": {"list": []}}})
        if url.startswith("https://api.lyrics.ovh/v1/"):
            assert url.endswith("/Futurist/Golden%20Coast")
            return _Response(200, {"lyrics": "Line one\n\nLine two"})
        raise AssertionError(url)

    client, _session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Golden Coast",
        duration=219,
        fallback_providers=["qqmusic", "lyricsovh"],
    )
    assert found.status == LYRICS_STATUS_PLAIN
    assert found.source == "lyricsovh"
    assert found.result is not None
    assert [line.text for line in found.result.lines] == ["Line one", "Line two"]
    assert order.index(QQMUSIC_SEARCH_API) < order.index(
        "https://api.lyrics.ovh/v1/Futurist/Golden%20Coast"
    )


@pytest.mark.asyncio
async def test_instrumental_stops_the_chain() -> None:
    def handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url == LRCLIB_API:
            return _Response(200, {"instrumental": True, "syncedLyrics": None})
        raise AssertionError(url)

    client, session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Song",
        duration=180,
        fallback_providers=["qqmusic", "lyricsovh"],
    )
    assert found.status == LYRICS_STATUS_INSTRUMENTAL
    assert found.source == "lrclib"
    assert session.urls() == [LRCLIB_API]


@pytest.mark.asyncio
async def test_not_found_is_cached_until_ttl(caplog: pytest.LogCaptureFixture) -> None:
    hits = {"n": 0}

    def handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        hits["n"] += 1
        if url == LRCLIB_API:
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(200, [])
        if url.startswith("https://api.lyrics.ovh/"):
            return _Response(404)
        raise AssertionError(url)

    client, _session, clock = _client(handler)
    caplog.set_level(logging.INFO)
    first = await client.fetch(
        artist="Futurist", title="Song", duration=180, fallback_providers=["lyricsovh"]
    )
    assert first.status == LYRICS_STATUS_NOT_FOUND
    after_first = hits["n"]
    info = [rec for rec in caplog.records if rec.levelno == logging.INFO]
    assert len(info) == 1
    assert "not found" in info[0].message.lower()

    second = await client.fetch(
        artist="Futurist", title="Song", duration=180, fallback_providers=["lyricsovh"]
    )
    assert second.status == LYRICS_STATUS_NOT_FOUND
    assert hits["n"] == after_first

    clock.t += LYRICS_NOT_FOUND_TTL_SEC
    third = await client.fetch(
        artist="Futurist", title="Song", duration=180, fallback_providers=["lyricsovh"]
    )
    assert third.status == LYRICS_STATUS_NOT_FOUND
    assert hits["n"] > after_first


@pytest.mark.asyncio
async def test_timeout_is_not_cached() -> None:
    def handler(_url: str, _kwargs: dict[str, Any]) -> _Response:
        raise TimeoutError

    client, session, _clock = _client(handler)
    first = await client.fetch(
        artist="Futurist", title="Song", duration=180, fallback_providers=["lyricsovh"]
    )
    assert first.status == LYRICS_STATUS_ERROR
    first_calls = len(session.calls)
    assert first_calls > 0
    second = await client.fetch(
        artist="Futurist", title="Song", duration=180, fallback_providers=["lyricsovh"]
    )
    assert second.status == LYRICS_STATUS_ERROR
    assert len(session.calls) > first_calls


@pytest.mark.asyncio
async def test_disabled_provider_is_not_called() -> None:
    def handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if "y.qq.com" in url:
            raise AssertionError("qqmusic is disabled")
        if url == LRCLIB_API:
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(200, [])
        if url.startswith("https://api.lyrics.ovh/"):
            return _Response(200, {"lyrics": "Only ovh"})
        raise AssertionError(url)

    client, session, _clock = _client(handler)
    found = await client.fetch(
        artist="Futurist",
        title="Song",
        duration=180,
        fallback_providers=["lyricsovh"],
    )
    assert found.status == LYRICS_STATUS_PLAIN
    assert all("y.qq.com" not in url for url in session.urls())


@pytest.mark.asyncio
async def test_five_failures_skip_provider_for_one_hour(
    caplog: pytest.LogCaptureFixture,
) -> None:
    qq_calls = {"n": 0}

    def handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url == LRCLIB_API:
            return _Response(404)
        if url == LRCLIB_SEARCH_API:
            return _Response(200, [])
        if url == QQMUSIC_SEARCH_API:
            qq_calls["n"] += 1
            return _Response(500, {})
        raise AssertionError(url)

    client, _session, clock = _client(handler)
    caplog.set_level(logging.DEBUG)
    for _ in range(5):
        found = await client.fetch(
            artist="Futurist",
            title="Song",
            duration=180,
            fallback_providers=["qqmusic"],
        )
        assert found.status == LYRICS_STATUS_ERROR
    assert qq_calls["n"] == 5
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "5 times" in warnings[0].message
    assert "qqmusic" in warnings[0].message

    skipped = await client.fetch(
        artist="Futurist",
        title="Song",
        duration=180,
        fallback_providers=["qqmusic"],
    )
    assert skipped.status == LYRICS_STATUS_ERROR
    assert qq_calls["n"] == 5

    clock.t += LYRICS_PROVIDER_SKIP_SEC
    await client.fetch(
        artist="Futurist",
        title="Song",
        duration=180,
        fallback_providers=["qqmusic"],
    )
    assert qq_calls["n"] == 6


def test_card_shows_source_footer_and_status_messages() -> None:
    text = _CARD.read_text(encoding="utf-8")
    assert "Lyrics: LRCLIB" in text
    assert "Lyrics: QQ Music" in text
    assert "Lyrics: lyrics.ovh" in text
    assert "Lyrics not available for this song" in text
    assert "Instrumental" in text
    assert 'status === "plain"' in text
