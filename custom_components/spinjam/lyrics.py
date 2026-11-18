"""Lyrics lookup: LRCLIB, then optional QQ Music / lyrics.ovh fallbacks.

Parsing is regex-only. HTTP uses the shared aiohttp session from Home Assistant.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
import json
import logging
import re
from time import monotonic
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientTimeout

from .const import (
    DEFAULT_FALLBACK_PROVIDERS,
    LRCLIB_API,
    LRCLIB_SEARCH_API,
    LYRICS_BUDGET_SEC,
    LYRICS_CACHE_SIZE,
    LYRICS_DURATION_TOLERANCE_SEC,
    LYRICS_NOT_FOUND_TTL_SEC,
    LYRICS_PROVIDER_FAIL_LIMIT,
    LYRICS_PROVIDER_LRCLIB,
    LYRICS_PROVIDER_LYRICSOVH,
    LYRICS_PROVIDER_QQMUSIC,
    LYRICS_PROVIDER_SKIP_SEC,
    LYRICS_REQUEST_TIMEOUT,
    LYRICS_STATUS_ERROR,
    LYRICS_STATUS_INSTRUMENTAL,
    LYRICS_STATUS_NOT_FOUND,
    LYRICS_STATUS_PLAIN,
    LYRICS_STATUS_SYNCED,
    LYRICSOVH_API,
    QQMUSIC_LYRIC_API,
    QQMUSIC_SEARCH_API,
)

_LOGGER = logging.getLogger(__name__)

# One or more [mm:ss.xx] stamps, then the rest of the line (may include <mm:ss> words).
_LRC_STAMP = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_WORD_TAG = re.compile(r"<(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?>")
_TITLE_NOISE = re.compile(
    r"(?:"
    r"\s+-\s+Remaster(?:ed)?\b.*"
    r"|\s*\(\s*Remaster[^)]*\)"
    r"|\s*\(\s*(?:feat|ft)\.?(?:\s+[^)]*)?\)"
    r"|\s+-\s+Single\b.*"
    r"|\s+-\s+EP\b.*"
    r"|\s*\(\s*Live\b[^)]*\)"
    r"|\s*\([^)]*\bVersion\s*\)"
    r"|\s*\(\s*Radio\s+Edit\s*\)"
    r")",
    re.IGNORECASE,
)
_META_LINE = re.compile(r"^\[(?:ti|ar|al|by|offset):[^\]]*\]\s*$", re.IGNORECASE)
_CREDIT_TEXT = re.compile(
    r"(作词|作曲|编曲|制作人|lyrics by|composed by)",
    re.IGNORECASE,
)
_QQ_HEADERS = {
    "Referer": "https://y.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
}
_ALLOWED_FALLBACKS = (LYRICS_PROVIDER_QQMUSIC, LYRICS_PROVIDER_LYRICSOVH)


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
    source: str = LYRICS_PROVIDER_LRCLIB
    plain: bool = False
    # Provider duration (LRCLIB ``duration`` / QQ ``interval``), when the API sent one.
    catalog_duration: float | None = None
    # Length used to compare with the player (catalog, or the last stamp).
    reported_duration: float | None = None
    # reported_duration - player duration. Negative means the lyrics run short.
    duration_delta: float | None = None


@dataclass(frozen=True)
class LyricsLookup:
    """Settled lookup. ``result`` is set for synced, plain, and instrumental."""

    status: str
    result: LyricsResult | None = None

    @property
    def source(self) -> str | None:
        if self.result is None:
            return None
        return self.result.source


def lyrics_kind(result: LyricsResult) -> str:
    """Map a cached hit to ``lyrics_status``."""
    if result.instrumental:
        return LYRICS_STATUS_INSTRUMENTAL
    if result.plain:
        return LYRICS_STATUS_PLAIN
    return LYRICS_STATUS_SYNCED


def normalize_fallback_providers(value: Any) -> list[str]:
    """Keep known providers, preserve order, drop duplicates.

    ``None`` and other non-lists use the default (lyrics.ovh on, QQ Music off).
    An empty list means LRCLIB only.
    """
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return list(DEFAULT_FALLBACK_PROVIDERS)
    chosen: list[str] = []
    for item in items:
        name = str(item).strip().lower()
        if name in _ALLOWED_FALLBACKS and name not in chosen:
            chosen.append(name)
    return chosen


def clean_title(title: str) -> str:
    """Strip remaster, featured-artist, live, version, and radio-edit suffixes."""
    cleaned = (title or "").strip()
    previous: str | None = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = _TITLE_NOISE.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -")
    return cleaned


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


def clean_qq_lrc(raw: str, *, titles: list[str], artists: list[str]) -> str:
    """Drop QQ metadata tags, the 00:00 title line, and credit lines."""
    pairs: set[str] = set()
    for title in titles:
        for artist in artists:
            left = (title or "").casefold().strip()
            right = (artist or "").casefold().strip()
            if left and right:
                pairs.add(f"{left} - {right}")
                pairs.add(f"{right} - {left}")
    kept: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or _META_LINE.match(line):
            continue
        text = _LRC_STAMP.sub("", line).strip()
        if _CREDIT_TEXT.search(text):
            continue
        stamps = list(_LRC_STAMP.finditer(line))
        if stamps and text:
            starts = [
                _stamp_to_seconds(stamp.group(1), stamp.group(2), stamp.group(3))
                for stamp in stamps
            ]
            if all(start == 0 for start in starts) and text.casefold() in pairs:
                continue
        kept.append(line)
    return "\n".join(kept)


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


def artists_match(wanted: str, found: str) -> bool:
    """Casefold-equal, or either name contains the other."""
    left = (wanted or "").casefold().strip()
    right = (found or "").casefold().strip()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def titles_match(wanted: str, found: str) -> bool:
    """Casefold-equal after suffix cleanup."""
    left = clean_title(wanted).casefold()
    right = clean_title(found).casefold()
    return bool(left) and left == right


def durations_match(wanted: float | None, found: float | None) -> bool:
    """True when duration is unknown or within the 3 second tolerance."""
    if wanted is None:
        return True
    if found is None:
        return False
    return abs(found - wanted) <= LYRICS_DURATION_TOLERANCE_SEC


def _last_lyric_stamp(result: LyricsResult) -> float | None:
    last: float | None = None
    for line in result.lines:
        stamps = [line.start, *(word.start for word in line.words)]
        for stamp in stamps:
            if stamp is None:
                continue
            last = stamp if last is None else max(last, stamp)
    if last is None or last <= 0:
        return None
    return float(last)


def lyrics_compare_duration(result: LyricsResult) -> float | None:
    """Length used to decide whether these lyrics fit the playing edit.

    Prefer the provider duration. If the last synced stamp ends well before
    that duration (more than 3 s and more than 15% short), use the last stamp
    so a file that runs out early is not treated as a full-length match.
    """
    catalog = (
        float(result.catalog_duration)
        if result.catalog_duration and result.catalog_duration > 0
        else None
    )
    last = _last_lyric_stamp(result)
    if catalog is None:
        return last
    # A one-line hit is not evidence the file ended; trust the provider duration.
    if last is not None and len(result.lines) >= 2:
        early = catalog - last
        if early > max(LYRICS_DURATION_TOLERANCE_SEC, 0.15 * catalog):
            return last
    return catalog


def signed_duration_delta(
    result: LyricsResult, player_duration: float | None
) -> float | None:
    """Lyrics length minus player length. Negative: lyrics finish early."""
    own = lyrics_compare_duration(result)
    if own is None or player_duration is None:
        return None
    return own - float(player_duration)


def duration_acceptable(result: LyricsResult, player_duration: float | None) -> bool:
    """Synced lyrics must land within ~3 s of the player when both lengths are known."""
    if result.instrumental or result.plain:
        return True
    delta = signed_duration_delta(result, player_duration)
    if delta is None:
        return True
    return abs(delta) <= LYRICS_DURATION_TOLERANCE_SEC


def _closest_duration(
    results: list[LyricsResult], player_duration: float | None
) -> LyricsResult:
    def _key(result: LyricsResult) -> float:
        delta = signed_duration_delta(result, player_duration)
        if delta is None:
            return 1e9
        return abs(delta)

    return min(results, key=_key)


def _scaled_line(line: LyricLine, factor: float) -> LyricLine:
    words = tuple(
        LyricWord(start=word.start * factor, text=word.text) for word in line.words
    )
    return LyricLine(start=line.start * factor, text=line.text, words=words)


# Stretch only a moderate edit mismatch. Larger gaps stay unscaled and are logged.
LYRIC_SCALE_MAX_DELTA_SEC = 30.0


def annotate_lyrics_duration(
    result: LyricsResult,
    player_duration: float | None,
    *,
    scale: bool = False,
) -> LyricsResult:
    """Record the lyrics length and delta. Optionally scale synced stamps.

    Scaling is off unless the integration option is enabled. It applies only
    when the gap is larger than the match tolerance and at most 30 seconds.
    """
    own = lyrics_compare_duration(result)
    delta = signed_duration_delta(result, player_duration)
    lines = result.lines
    if (
        scale
        and delta is not None
        and own
        and player_duration
        and not result.plain
        and not result.instrumental
        and LYRICS_DURATION_TOLERANCE_SEC < abs(delta) <= LYRIC_SCALE_MAX_DELTA_SEC
    ):
        factor = float(player_duration) / own
        lines = tuple(_scaled_line(line, factor) for line in result.lines)
    return replace(
        result,
        lines=lines,
        reported_duration=own,
        duration_delta=delta,
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usable_duration(duration: float | None) -> float | None:
    value = _as_float(duration)
    if value is None or not 1 <= value <= 3600:
        return None
    return value


def _parse_jsonish(raw: str) -> Any:
    text = raw.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if not match:
            raise ValueError("lyrics response was not JSON")
        return json.loads(match.group(1))


async def _read_payload(resp: Any) -> Any:
    if hasattr(resp, "text"):
        raw = await resp.text()
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            return _parse_jsonish(raw)
    data = await resp.json(content_type=None)
    if isinstance(data, str):
        return _parse_jsonish(data)
    return data


def _lrclib_result(item: dict[str, Any]) -> LyricsResult | None:
    catalog = _as_float(item.get("duration"))
    if item.get("instrumental"):
        return LyricsResult(
            lines=(),
            instrumental=True,
            source=LYRICS_PROVIDER_LRCLIB,
            catalog_duration=catalog,
        )
    synced = item.get("enhancedLyrics") or item.get("syncedLyrics")
    lines = parse_lrc(synced if isinstance(synced, str) else None)
    if not lines:
        return None
    return LyricsResult(
        lines=lines, source=LYRICS_PROVIDER_LRCLIB, catalog_duration=catalog
    )


def pick_lrclib_match(
    items: list[Any],
    *,
    artist: str,
    title: str,
    duration: float | None,
) -> dict[str, Any] | None:
    """Best LRCLIB search row: artist + cleaned title + duration, prefer synced."""
    usable: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        found_artist = str(item.get("artistName") or item.get("artist_name") or "")
        found_title = str(item.get("trackName") or item.get("track_name") or "")
        if not artists_match(artist, found_artist) or not titles_match(title, found_title):
            continue
        if not durations_match(duration, _as_float(item.get("duration"))):
            continue
        synced = item.get("enhancedLyrics") or item.get("syncedLyrics")
        if item.get("instrumental") or (isinstance(synced, str) and synced.strip()):
            usable.append(item)
    if not usable:
        return None

    def _rank(item: dict[str, Any]) -> tuple[int, float]:
        synced = item.get("enhancedLyrics") or item.get("syncedLyrics")
        has_sync = 0 if isinstance(synced, str) and synced.strip() else 1
        found = _as_float(item.get("duration"))
        # Closest edit wins inside the tolerance (album length over a radio edit).
        delta = abs(found - duration) if duration is not None and found is not None else 0.0
        return (has_sync, delta)

    usable.sort(key=_rank)
    return usable[0]


def _qq_songs(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return []
    song = data.get("song") or {}
    if not isinstance(song, dict):
        return []
    rows = song.get("list")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _qq_singer_names(song: dict[str, Any]) -> list[str]:
    singers = song.get("singer") or []
    names: list[str] = []
    if not isinstance(singers, list):
        return names
    for singer in singers:
        if isinstance(singer, dict) and singer.get("name"):
            names.append(str(singer["name"]))
        elif isinstance(singer, str) and singer.strip():
            names.append(singer)
    return names


def qq_artist_matches(wanted: str, singer_name: str) -> bool:
    """Artist is contained in the singer name, ignoring parenthetical aliases."""
    if artists_match(wanted, singer_name):
        return True
    stripped = re.sub(r"\s*\([^)]*\)", "", singer_name).strip()
    if stripped and artists_match(wanted, stripped):
        return True
    for alias in re.findall(r"\(([^)]*)\)", singer_name):
        if artists_match(wanted, alias):
            return True
    return False


def pick_qq_song(
    songs: list[dict[str, Any]],
    *,
    artist: str,
    title: str,
    duration: float | None,
) -> dict[str, Any] | None:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for song in songs:
        names = _qq_singer_names(song)
        if not any(qq_artist_matches(artist, name) for name in names):
            continue
        songname = str(song.get("songname") or song.get("songName") or "")
        if not titles_match(title, songname):
            continue
        found = _as_float(song.get("interval"))
        if not durations_match(duration, found):
            continue
        mid = song.get("songmid") or song.get("songMid") or song.get("mid")
        if not mid:
            continue
        delta = abs(found - duration) if duration is not None and found is not None else 0.0
        ranked.append((delta, song))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _qq_lyric_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    lyric = payload.get("lyric")
    if isinstance(lyric, str) and lyric.strip():
        return lyric
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("lyric")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def _plain_result(text: str) -> LyricsResult | None:
    stripped = text.replace("\r\n", "\n").strip()
    if not stripped:
        return None
    lines = [
        LyricLine(start=0.0, text=piece.strip())
        for piece in stripped.split("\n")
        if piece.strip()
    ]
    if not lines:
        return None
    return LyricsResult(
        lines=tuple(lines),
        plain=True,
        source=LYRICS_PROVIDER_LYRICSOVH,
    )


@dataclass
class _CacheItem:
    value: LyricsResult | None
    expires: float | None


class LyricsCache:
    """Tiny LRU. Hits stay until eviction; ``None`` may carry a TTL (not-found)."""

    def __init__(
        self,
        maxsize: int = LYRICS_CACHE_SIZE,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self._maxsize = maxsize
        self._now = monotonic_fn or monotonic
        self._data: OrderedDict[str, _CacheItem] = OrderedDict()

    @staticmethod
    def key(artist: str, title: str, album: str | None, duration: float | None) -> str:
        dur = int(round(duration)) if duration else 0
        return (
            f"{artist.strip().lower()}|{title.strip().lower()}|"
            f"{(album or '').strip().lower()}|{dur}"
        )

    def get(self, key: str) -> LyricsResult | None | object:
        """Return cached value; use Ellipsis as miss sentinel."""
        item = self._data.get(key)
        if item is None:
            return Ellipsis
        if item.expires is not None and self._now() >= item.expires:
            self._data.pop(key, None)
            return Ellipsis
        self._data.move_to_end(key)
        return item.value

    def set(self, key: str, value: LyricsResult | None, *, ttl: float | None = None) -> None:
        expires = None if ttl is None else self._now() + ttl
        self._data[key] = _CacheItem(value, expires)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)


class _Budget:
    def __init__(self, seconds: float, now: Callable[[], float]) -> None:
        self._now = now
        self._deadline = now() + seconds

    def timeout(self) -> float | None:
        remaining = self._deadline - self._now()
        if remaining <= 0:
            return None
        return min(LYRICS_REQUEST_TIMEOUT, remaining)


class _ProviderHealth:
    """Skip a provider for an hour after five failures in a row."""

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._fails: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}

    def skipped(self, name: str) -> bool:
        return self._now() < self._skip_until.get(name, 0.0)

    def ok(self, name: str) -> None:
        self._fails[name] = 0

    def fail(self, name: str) -> None:
        count = self._fails.get(name, 0) + 1
        self._fails[name] = count
        _LOGGER.debug("Lyrics provider %s failed (%s in a row)", name, count)
        if count >= LYRICS_PROVIDER_FAIL_LIMIT:
            self._skip_until[name] = self._now() + LYRICS_PROVIDER_SKIP_SEC
            self._fails[name] = 0
            _LOGGER.warning(
                "Lyrics provider %s failed 5 times in a row; skipping it for 1 hour",
                name,
            )


class LrcLibClient:
    """LRCLIB first, then the configured fallback providers."""

    def __init__(
        self,
        session: Any,
        cache: LyricsCache | None = None,
        *,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self._session = session
        self._now = monotonic_fn or monotonic
        self.cache = cache or LyricsCache(monotonic_fn=self._now)
        self._health = _ProviderHealth(self._now)

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        timeout: float,
        provider: str,
    ) -> tuple[str, Any]:
        try:
            async with self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=ClientTimeout(total=timeout),
            ) as resp:
                status = int(getattr(resp, "status", 0) or 0)
                if status == 404:
                    return "miss", None
                if status in (408, 429) or status >= 500:
                    _LOGGER.debug(
                        "Lyrics provider %s returned HTTP %s", provider, status
                    )
                    return "error", None
                if status >= 400:
                    return "miss", None
                try:
                    payload = await _read_payload(resp)
                except (ValueError, TypeError, json.JSONDecodeError) as err:
                    _LOGGER.debug(
                        "Lyrics provider %s returned unreadable JSON: %s",
                        provider,
                        err,
                    )
                    return "error", None
                return "ok", payload
        except (TimeoutError, ClientError, OSError) as err:
            _LOGGER.debug("Lyrics provider %s request failed: %s", provider, err)
            return "error", None

    async def fetch(
        self,
        *,
        artist: str,
        title: str,
        album: str | None = None,
        duration: float | None = None,
        fallback_providers: Any = None,
    ) -> LyricsLookup:
        artist = (artist or "").strip()
        title = (title or "").strip()
        if not artist or not title:
            return LyricsLookup(LYRICS_STATUS_NOT_FOUND)
        album_norm = album.strip() if isinstance(album, str) else album
        usable = _usable_duration(duration)
        cache_key = LyricsCache.key(artist, title, album_norm, usable if usable else duration)
        cached = self.cache.get(cache_key)
        if cached is not Ellipsis:
            if cached is None:
                return LyricsLookup(LYRICS_STATUS_NOT_FOUND)
            assert isinstance(cached, LyricsResult)
            return LyricsLookup(lyrics_kind(cached), cached)

        providers = normalize_fallback_providers(fallback_providers)
        budget = _Budget(LYRICS_BUDGET_SEC, self._now)
        saw_error = False

        kind, result = await self._lrclib(artist, title, album_norm, usable, budget)
        off: list[LyricsResult] = []
        plain: LyricsResult | None = None
        if kind == "hit" and result is not None:
            self.cache.set(cache_key, result)
            return LyricsLookup(lyrics_kind(result), result)
        if kind == "off" and result is not None:
            off.append(result)
        elif kind in ("error", "skipped", "budget"):
            saw_error = True

        query_title = clean_title(title) or title
        for provider in providers:
            if budget.timeout() is None:
                saw_error = True
                break
            if provider == LYRICS_PROVIDER_QQMUSIC:
                kind, result = await self._qqmusic(artist, query_title, usable, budget)
            elif provider == LYRICS_PROVIDER_LYRICSOVH:
                kind, result = await self._lyricsovh(artist, query_title, budget)
            else:
                continue
            if kind == "hit" and result is not None:
                if result.plain:
                    plain = result
                else:
                    self.cache.set(cache_key, result)
                    return LyricsLookup(lyrics_kind(result), result)
            elif kind == "off" and result is not None:
                off.append(result)
            elif kind in ("error", "skipped", "budget"):
                saw_error = True

        if off:
            best = _closest_duration(off, usable)
            own = lyrics_compare_duration(best)
            delta = signed_duration_delta(best, usable)
            _LOGGER.info(
                "Lyrics for %s - %s differ from the player by %.1fs "
                "(lyrics %.1fs, player %.1fs); using the closest candidate",
                artist,
                title,
                0.0 if delta is None else delta,
                0.0 if own is None else own,
                0.0 if usable is None else usable,
            )
            self.cache.set(cache_key, best)
            return LyricsLookup(lyrics_kind(best), best)
        if plain is not None:
            self.cache.set(cache_key, plain)
            return LyricsLookup(lyrics_kind(plain), plain)

        if saw_error:
            return LyricsLookup(LYRICS_STATUS_ERROR)
        self.cache.set(cache_key, None, ttl=LYRICS_NOT_FOUND_TTL_SEC)
        _LOGGER.info("Lyrics not found for %s - %s", artist, title)
        return LyricsLookup(LYRICS_STATUS_NOT_FOUND)

    async def _lrclib(
        self,
        artist: str,
        title: str,
        album: str | None,
        duration: float | None,
        budget: _Budget,
    ) -> tuple[str, LyricsResult | None]:
        if self._health.skipped(LYRICS_PROVIDER_LRCLIB):
            _LOGGER.debug(
                "Lyrics provider %s skipped until cooldown ends", LYRICS_PROVIDER_LRCLIB
            )
            return "skipped", None

        saw_error = False
        budget_hit = False
        original = title.strip()
        cleaned = clean_title(original)

        async def _get(track: str) -> LyricsResult | None:
            nonlocal saw_error, budget_hit
            timeout = budget.timeout()
            if timeout is None:
                budget_hit = True
                return None
            params: dict[str, Any] = {"artist_name": artist, "track_name": track}
            if album:
                params["album_name"] = album
            if duration is not None:
                params["duration"] = int(round(duration))
            kind, payload = await self._request(
                LRCLIB_API,
                params=params,
                headers=None,
                timeout=timeout,
                provider=LYRICS_PROVIDER_LRCLIB,
            )
            if kind == "error":
                saw_error = True
                return None
            if kind != "ok" or not isinstance(payload, dict):
                return None
            return _lrclib_result(payload)

        async def _search(params: dict[str, Any], match_title: str) -> LyricsResult | None:
            nonlocal saw_error, budget_hit
            timeout = budget.timeout()
            if timeout is None:
                budget_hit = True
                return None
            kind, payload = await self._request(
                LRCLIB_SEARCH_API,
                params=params,
                headers=None,
                timeout=timeout,
                provider=LYRICS_PROVIDER_LRCLIB,
            )
            if kind == "error":
                saw_error = True
                return None
            if kind != "ok" or not isinstance(payload, list):
                return None
            match = pick_lrclib_match(
                payload, artist=artist, title=match_title, duration=duration
            )
            if match is None:
                return None
            return _lrclib_result(match)

        far: list[LyricsResult] = []

        def _take(found: LyricsResult | None) -> LyricsResult | None:
            if found is None:
                return None
            if duration_acceptable(found, duration):
                return found
            far.append(found)
            return None

        result = _take(await _get(original))
        if result is not None:
            self._health.ok(LYRICS_PROVIDER_LRCLIB)
            return "hit", result
        if budget_hit:
            return self._lrclib_incomplete(saw_error)

        result = _take(
            await _search({"track_name": original, "artist_name": artist}, original)
        )
        if result is not None:
            self._health.ok(LYRICS_PROVIDER_LRCLIB)
            return "hit", result
        if budget_hit:
            return self._lrclib_incomplete(saw_error)

        if cleaned and cleaned.casefold() != original.casefold():
            result = _take(await _get(cleaned))
            if result is not None:
                self._health.ok(LYRICS_PROVIDER_LRCLIB)
                return "hit", result
            if budget_hit:
                return self._lrclib_incomplete(saw_error)
            result = _take(
                await _search({"track_name": cleaned, "artist_name": artist}, cleaned)
            )
            if result is not None:
                self._health.ok(LYRICS_PROVIDER_LRCLIB)
                return "hit", result
            if budget_hit:
                return self._lrclib_incomplete(saw_error)

        query_title = cleaned or original
        result = _take(await _search({"q": f"{artist} {query_title}"}, query_title))
        if result is not None:
            self._health.ok(LYRICS_PROVIDER_LRCLIB)
            return "hit", result
        if budget_hit:
            return self._lrclib_incomplete(saw_error)
        if far:
            self._health.ok(LYRICS_PROVIDER_LRCLIB)
            return "off", _closest_duration(far, duration)
        if saw_error:
            self._health.fail(LYRICS_PROVIDER_LRCLIB)
            return "error", None
        self._health.ok(LYRICS_PROVIDER_LRCLIB)
        return "miss", None

    def _lrclib_incomplete(self, saw_error: bool) -> tuple[str, None]:
        if saw_error:
            self._health.fail(LYRICS_PROVIDER_LRCLIB)
        return "budget", None

    async def _qqmusic(
        self,
        artist: str,
        title: str,
        duration: float | None,
        budget: _Budget,
    ) -> tuple[str, LyricsResult | None]:
        provider = LYRICS_PROVIDER_QQMUSIC
        if self._health.skipped(provider):
            _LOGGER.debug("Lyrics provider %s skipped until cooldown ends", provider)
            return "skipped", None
        timeout = budget.timeout()
        if timeout is None:
            return "budget", None
        kind, payload = await self._request(
            QQMUSIC_SEARCH_API,
            params={"w": f"{artist} {title}".strip(), "format": "json", "p": 1, "n": 5},
            headers=_QQ_HEADERS,
            timeout=timeout,
            provider=provider,
        )
        if kind == "error":
            self._health.fail(provider)
            return "error", None
        if kind != "ok":
            self._health.ok(provider)
            return "miss", None
        song = pick_qq_song(
            _qq_songs(payload), artist=artist, title=title, duration=duration
        )
        if song is None:
            _LOGGER.debug(
                "Lyrics provider %s: no matching track for %s - %s",
                provider,
                artist,
                title,
            )
            self._health.ok(provider)
            return "miss", None
        mid = str(song.get("songmid") or song.get("songMid") or song.get("mid"))
        timeout = budget.timeout()
        if timeout is None:
            return "budget", None
        kind, payload = await self._request(
            QQMUSIC_LYRIC_API,
            params={"songmid": mid, "format": "json", "nobase64": 1},
            headers=_QQ_HEADERS,
            timeout=timeout,
            provider=provider,
        )
        if kind == "error":
            self._health.fail(provider)
            return "error", None
        text = _qq_lyric_text(payload) if kind == "ok" else None
        if not text:
            self._health.ok(provider)
            return "miss", None
        singers = _qq_singer_names(song)
        cleaned = clean_qq_lrc(
            text,
            titles=[title, str(song.get("songname") or "")],
            artists=[artist, *singers],
        )
        lines = parse_lrc(cleaned)
        if not lines:
            self._health.ok(provider)
            return "miss", None
        self._health.ok(provider)
        catalog = _as_float(song.get("interval"))
        result = LyricsResult(lines=lines, source=provider, catalog_duration=catalog)
        if duration_acceptable(result, duration):
            return "hit", result
        return "off", result

    async def _lyricsovh(
        self,
        artist: str,
        title: str,
        budget: _Budget,
    ) -> tuple[str, LyricsResult | None]:
        provider = LYRICS_PROVIDER_LYRICSOVH
        if self._health.skipped(provider):
            _LOGGER.debug("Lyrics provider %s skipped until cooldown ends", provider)
            return "skipped", None
        timeout = budget.timeout()
        if timeout is None:
            return "budget", None
        url = f"{LYRICSOVH_API}/{quote(artist, safe='')}/{quote(title, safe='')}"
        kind, payload = await self._request(
            url,
            params=None,
            headers=None,
            timeout=timeout,
            provider=provider,
        )
        if kind == "error":
            self._health.fail(provider)
            return "error", None
        lyrics = payload.get("lyrics") if isinstance(payload, dict) else None
        result = _plain_result(lyrics) if isinstance(lyrics, str) else None
        if result is None:
            self._health.ok(provider)
            return "miss", None
        self._health.ok(provider)
        return "hit", result
