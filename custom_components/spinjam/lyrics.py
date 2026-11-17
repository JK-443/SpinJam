"""LRCLIB client and LRC parsing — no third-party deps."""

from __future__ import annotations

from collections import OrderedDict
import logging
import re
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import LRCLIB_API, LYRICS_CACHE_SIZE

_LOGGER = logging.getLogger(__name__)

_LRC_LINE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)")


@dataclass(frozen=True)
class LyricLine:
    start: float
    text: str


@dataclass(frozen=True)
class LyricsResult:
    lines: tuple[LyricLine, ...]
    instrumental: bool = False
    source: str = "lrclib"


def parse_lrc(synced: str | None) -> tuple[LyricLine, ...]:
    if not synced:
        return ()
    lines: list[LyricLine] = []
    for raw in synced.splitlines():
        match = _LRC_LINE.match(raw.strip())
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        frac = match.group(3) or "0"
        # Normalize fractional seconds (1–3 digits)
        frac = (frac + "000")[:3]
        start = minutes * 60 + seconds + int(frac) / 1000.0
        text = match.group(4).strip()
        if text:
            lines.append(LyricLine(start=start, text=text))
    lines.sort(key=lambda line: line.start)
    return tuple(lines)


def line_at(lines: tuple[LyricLine, ...], position: float) -> tuple[str | None, str | None]:
    """Return (current, next) lyric text for a playback position in seconds."""
    if not lines:
        return None, None
    current: str | None = None
    nxt: str | None = None
    for index, line in enumerate(lines):
        if line.start <= position:
            current = line.text
            nxt = lines[index + 1].text if index + 1 < len(lines) else None
        else:
            if current is None:
                nxt = line.text
            break
    return current, nxt


class LyricsCache:
    """Tiny LRU cache of parsed lyrics keyed by track signature."""

    def __init__(self, maxsize: int = LYRICS_CACHE_SIZE) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[str, LyricsResult | None] = OrderedDict()

    @staticmethod
    def key(artist: str, title: str, album: str | None, duration: float | None) -> str:
        dur = int(round(duration)) if duration else 0
        return f"{artist.strip().lower()}|{title.strip().lower()}|{(album or '').strip().lower()}|{dur}"

    def get(self, key: str) -> LyricsResult | None | object:
        """Return cached value; use Ellipsis as miss sentinel."""
        if key not in self._data:
            return Ellipsis
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value: LyricsResult | None) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)


class LrcLibClient:
    def __init__(self, session: ClientSession, cache: LyricsCache | None = None) -> None:
        self._session = session
        self.cache = cache or LyricsCache()

    async def fetch(
        self,
        *,
        artist: str,
        title: str,
        album: str | None = None,
        duration: float | None = None,
    ) -> LyricsResult | None:
        if not artist or not title:
            return None
        cache_key = LyricsCache.key(artist, title, album, duration)
        cached = self.cache.get(cache_key)
        if cached is not Ellipsis:
            return cached  # type: ignore[return-value]

        params: dict[str, Any] = {
            "artist_name": artist,
            "track_name": title,
        }
        if album:
            params["album_name"] = album
        if duration and 1 <= duration <= 3600:
            params["duration"] = int(round(duration))

        try:
            async with self._session.get(LRCLIB_API, params=params, timeout=10) as resp:
                if resp.status == 404:
                    self.cache.set(cache_key, None)
                    return None
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("LRCLIB fetch failed for %s — %s: %s", artist, title, err)
            return None

        if data.get("instrumental"):
            result = LyricsResult(lines=(), instrumental=True)
        else:
            result = LyricsResult(lines=parse_lrc(data.get("syncedLyrics")))
        self.cache.set(cache_key, result)
        return result
