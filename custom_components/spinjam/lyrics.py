"""LRCLIB client and LRC parsing — no third-party deps."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import re
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import LRCLIB_API, LYRICS_CACHE_SIZE

_LOGGER = logging.getLogger(__name__)

# One or more [mm:ss.xx] stamps, then the rest of the line (may include <mm:ss> words).
_LRC_STAMP = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_WORD_TAG = re.compile(r"<(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?>")


@dataclass(frozen=True)
class LyricWord:
    start: float
    text: str


@dataclass(frozen=True)
class LyricLine:
    start: float
    text: str
    words: tuple[LyricWord, ...] = ()


@dataclass(frozen=True)
class LyricsResult:
    lines: tuple[LyricLine, ...]
    instrumental: bool = False
    source: str = "lrclib"


def _stamp_to_seconds(minutes: str, seconds: str, frac: str | None) -> float:
    frac_n = ((frac or "0") + "000")[:3]
    return int(minutes) * 60 + int(seconds) + int(frac_n) / 1000.0


def parse_word_tags(text: str) -> tuple[str, tuple[LyricWord, ...]]:
    """Parse LRCLIB enhanced ``<mm:ss.xx>`` word tags; return (plain_text, words)."""
    words: list[LyricWord] = []
    last = 0
    last_t: float | None = None
    for match in _WORD_TAG.finditer(text):
        if last_t is not None:
            chunk = text[last : match.start()]
            if chunk.strip():
                words.append(LyricWord(start=last_t, text=chunk))
        last_t = _stamp_to_seconds(match.group(1), match.group(2), match.group(3))
        last = match.end()
    if last_t is not None:
        chunk = text[last:]
        if chunk.strip():
            words.append(LyricWord(start=last_t, text=chunk))
    plain = _WORD_TAG.sub("", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain, tuple(words)


def parse_lrc(synced: str | None) -> tuple[LyricLine, ...]:
    """Parse LRC text.

    Lines with several timestamps (``[00:12][00:40]text``) yield one entry per
    stamp, sharing the same text / word tags, sorted by start time.
    """
    if not synced:
        return ()
    lines: list[LyricLine] = []
    for raw in synced.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        stamps = list(_LRC_STAMP.finditer(stripped))
        if not stamps:
            continue
        text = stripped[stamps[-1].end() :].strip()
        if not text:
            continue
        plain, words = parse_word_tags(text)
        display = plain or text
        for stamp in stamps:
            start = _stamp_to_seconds(stamp.group(1), stamp.group(2), stamp.group(3))
            lines.append(LyricLine(start=start, text=display, words=words))
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


def lines_payload(
    lines: tuple[LyricLine, ...],
    *,
    position: float | None = None,
    max_lines: int = 120,
    before: int = 40,
) -> list[dict[str, Any]] | None:
    """Serialize lyric lines for state attributes (capped / windowed)."""
    if not lines:
        return None
    indexed = list(enumerate(lines))
    if len(indexed) > max_lines:
        cur = 0
        if position is not None:
            for i, line in enumerate(lines):
                if line.start <= position:
                    cur = i
                else:
                    break
        start = max(0, cur - before)
        end = min(len(lines), start + max_lines)
        start = max(0, end - max_lines)
        indexed = indexed[start:end]

    payload: list[dict[str, Any]] = []
    for _, line in indexed:
        item: dict[str, Any] = {"t": round(line.start, 3), "text": line.text}
        if line.words:
            item["words"] = [
                {"t": round(word.start, 3), "text": word.text} for word in line.words
            ]
        payload.append(item)
    return payload


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
            # Prefer enhancedLyrics when LRCLIB provides word tags; else syncedLyrics.
            synced = data.get("enhancedLyrics") or data.get("syncedLyrics")
            result = LyricsResult(lines=parse_lrc(synced))
        self.cache.set(cache_key, result)
        return result
