"""High-resolution album art lookup (iTunes → MusicBrainz/CAA → entity_picture)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

ITUNES_SEARCH = "https://itunes.apple.com/search"
MUSICBRAINZ_RELEASE = "https://musicbrainz.org/ws/2/release/"
COVER_ART_FRONT = "https://coverartarchive.org/release/{mbid}/front-1200"

ARTWORK_CACHE_SIZE = 64
HTTP_TIMEOUT = ClientTimeout(total=6, connect=3, sock_read=5)
MUSICBRAINZ_MIN_INTERVAL = 1.05  # respect ~1 req/s
MUSICBRAINZ_USER_AGENT = (
    "SpinJam/0.7.0 (https://github.com/JK-443/SpinJam; home-assistant-integration)"
)

_SIZE_RE = re.compile(r"\d+x\d+bb", re.IGNORECASE)
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ArtworkResult:
    url: str
    source: str  # itunes | coverartarchive | entity_picture
    score: float = 0.0


def normalize_key_part(value: str | None) -> str:
    text = (value or "").strip().lower()
    return _NORMALIZE_RE.sub(" ", text).strip()


def cache_key(artist: str | None, album: str | None, *, title: str | None = None) -> str:
    """Normalized artist|album (title used when album unknown)."""
    a = normalize_key_part(artist)
    album_part = normalize_key_part(album) or normalize_key_part(title)
    return f"{a}|{album_part}"


def similarity(a: str | None, b: str | None) -> float:
    left = normalize_key_part(a)
    right = normalize_key_part(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def score_match(
    *,
    query_artist: str | None,
    query_title: str | None,
    query_album: str | None,
    query_duration: float | None,
    cand_artist: str | None,
    cand_title: str | None,
    cand_album: str | None,
    cand_duration: float | None,
) -> float:
    """Score a candidate so a wrong album is unlikely to win."""
    artist_s = similarity(query_artist, cand_artist)
    title_s = similarity(query_title, cand_title)
    album_s = similarity(query_album, cand_album) if query_album else 0.0
    score = artist_s * 0.45 + title_s * 0.45
    if query_album:
        score = artist_s * 0.35 + title_s * 0.35 + album_s * 0.25
    if (
        query_duration
        and cand_duration
        and query_duration > 0
        and cand_duration > 0
    ):
        delta = abs(float(query_duration) - float(cand_duration))
        if delta <= 2:
            score += 0.1
        elif delta <= 5:
            score += 0.05
        elif delta > 20:
            score -= 0.15
    return max(0.0, min(1.0, score))


def itunes_hd_url(artwork_url: str, *, prefer_3000: bool = True) -> str:
    """Rewrite artworkUrl100 to a large square size."""
    if not artwork_url:
        return artwork_url
    size = "3000x3000bb" if prefer_3000 else "1500x1500bb"
    if _SIZE_RE.search(artwork_url):
        return _SIZE_RE.sub(size, artwork_url, count=1)
    return artwork_url


class ArtworkDiskCache:
    """Small on-disk LRU keyed by normalized artist|album."""

    def __init__(self, path: Path, maxsize: int = ARTWORK_CACHE_SIZE) -> None:
        self._path = path
        self._maxsize = maxsize
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self._path.is_file():
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = raw.get("items") if isinstance(raw, dict) else None
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                url = item.get("url")
                source = item.get("source")
                if isinstance(key, str) and isinstance(url, str) and isinstance(source, str):
                    self._data[key] = {
                        "url": url,
                        "source": source,
                        "score": float(item.get("score") or 0),
                    }
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)
        except (OSError, ValueError, TypeError) as err:
            _LOGGER.debug("Artwork disk cache load failed: %s", err)

    def get(self, key: str) -> ArtworkResult | None | object:
        self.load()
        if key not in self._data:
            return Ellipsis
        self._data.move_to_end(key)
        item = self._data[key]
        if item.get("url") is None:
            return None
        return ArtworkResult(
            url=str(item["url"]),
            source=str(item.get("source") or "cache"),
            score=float(item.get("score") or 0),
        )

    def set(self, key: str, value: ArtworkResult | None) -> None:
        self.load()
        if value is None:
            self._data[key] = {"url": None, "source": "miss", "score": 0}
        else:
            self._data[key] = {
                "url": value.url,
                "source": value.source,
                "score": value.score,
            }
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)
        self._save()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "items": [
                    {"key": key, **value} for key, value in self._data.items()
                ]
            }
            self._path.write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
        except OSError as err:
            _LOGGER.debug("Artwork disk cache save failed: %s", err)


class ArtworkMemoryCache:
    def __init__(self, maxsize: int = ARTWORK_CACHE_SIZE) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[str, ArtworkResult | None] = OrderedDict()

    def get(self, key: str) -> ArtworkResult | None | object:
        if key not in self._data:
            return Ellipsis
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value: ArtworkResult | None) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)


class ArtworkResolver:
    """Resolve HD artwork via iTunes, then MusicBrainz + Cover Art Archive."""

    def __init__(
        self,
        session: ClientSession,
        *,
        disk_path: Path | None = None,
        memory: ArtworkMemoryCache | None = None,
        disk: ArtworkDiskCache | None = None,
    ) -> None:
        self._session = session
        self.memory = memory or ArtworkMemoryCache()
        self.disk = disk or (
            ArtworkDiskCache(disk_path) if disk_path is not None else None
        )
        self._mb_lock = asyncio.Lock()
        self._mb_last = 0.0

    async def resolve(
        self,
        *,
        artist: str | None,
        title: str | None,
        album: str | None = None,
        duration: float | None = None,
        entity_picture: str | None = None,
    ) -> ArtworkResult | None:
        if not artist and not title:
            if entity_picture:
                return ArtworkResult(url=entity_picture, source="entity_picture", score=0)
            return None

        key = cache_key(artist, album, title=title)
        cached = self.memory.get(key)
        if cached is not Ellipsis:
            if cached is None and entity_picture:
                return ArtworkResult(
                    url=entity_picture, source="entity_picture", score=0
                )
            return cached  # type: ignore[return-value]

        if self.disk is not None:
            disk_hit = self.disk.get(key)
            if disk_hit is not Ellipsis:
                self.memory.set(key, disk_hit)  # type: ignore[arg-type]
                if disk_hit is None and entity_picture:
                    return ArtworkResult(
                        url=entity_picture, source="entity_picture", score=0
                    )
                return disk_hit  # type: ignore[return-value]

        result = await self._lookup_itunes(
            artist=artist, title=title, album=album, duration=duration
        )
        if result is None:
            result = await self._lookup_musicbrainz_caa(
                artist=artist, title=title, album=album, duration=duration
            )
        if result is None and entity_picture:
            result = ArtworkResult(
                url=entity_picture, source="entity_picture", score=0
            )

        self.memory.set(key, result)
        if self.disk is not None and result and result.source != "entity_picture":
            self.disk.set(key, result)
        elif self.disk is not None and result is None:
            self.disk.set(key, None)
        return result

    async def _lookup_itunes(
        self,
        *,
        artist: str | None,
        title: str | None,
        album: str | None,
        duration: float | None,
    ) -> ArtworkResult | None:
        term_parts = [p for p in (artist, title, album) if p]
        if not term_parts:
            return None
        params = {
            "term": " ".join(term_parts),
            "media": "music",
            "entity": "song",
            "limit": "8",
        }
        try:
            async with self._session.get(
                ITUNES_SEARCH, params=params, timeout=HTTP_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except (ClientError, TimeoutError, ValueError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("iTunes artwork search failed: %s", err)
            return None
        except Exception as err:  # noqa: BLE001 — DNS/resolver quirks must not break polling
            _LOGGER.debug("iTunes artwork search failed: %s", err)
            return None

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return None

        best: ArtworkResult | None = None
        for item in results:
            if not isinstance(item, dict):
                continue
            art = item.get("artworkUrl100")
            if not art:
                continue
            track_ms = item.get("trackTimeMillis")
            cand_dur = (float(track_ms) / 1000.0) if track_ms else None
            score = score_match(
                query_artist=artist,
                query_title=title,
                query_album=album,
                query_duration=duration,
                cand_artist=item.get("artistName"),
                cand_title=item.get("trackName"),
                cand_album=item.get("collectionName"),
                cand_duration=cand_dur,
            )
            if score < 0.55:
                continue
            candidate = ArtworkResult(
                url=itunes_hd_url(str(art)),
                source="itunes",
                score=score,
            )
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    async def _mb_throttle(self) -> None:
        async with self._mb_lock:
            now = time.monotonic()
            wait = MUSICBRAINZ_MIN_INTERVAL - (now - self._mb_last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._mb_last = time.monotonic()

    async def _lookup_musicbrainz_caa(
        self,
        *,
        artist: str | None,
        title: str | None,
        album: str | None,
        duration: float | None,
    ) -> ArtworkResult | None:
        query_bits: list[str] = []
        if artist:
            query_bits.append(f'artist:"{artist}"')
        if album:
            query_bits.append(f'release:"{album}"')
        elif title:
            query_bits.append(f'recording:"{title}"')
        if not query_bits:
            return None
        query = " AND ".join(query_bits)
        headers = {"User-Agent": MUSICBRAINZ_USER_AGENT, "Accept": "application/json"}
        await self._mb_throttle()
        try:
            async with self._session.get(
                MUSICBRAINZ_RELEASE,
                params={"query": query, "fmt": "json", "limit": "5"},
                headers=headers,
                timeout=HTTP_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except (ClientError, TimeoutError, ValueError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("MusicBrainz search failed: %s", err)
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MusicBrainz search failed: %s", err)
            return None

        releases = data.get("releases") if isinstance(data, dict) else None
        if not isinstance(releases, list) or not releases:
            return None

        best_mbid: str | None = None
        best_score = 0.0
        for rel in releases:
            if not isinstance(rel, dict):
                continue
            mbid = rel.get("id")
            if not mbid:
                continue
            credit = rel.get("artist-credit") or []
            cand_artist = None
            if credit and isinstance(credit, list) and isinstance(credit[0], dict):
                cand_artist = credit[0].get("name") or (
                    (credit[0].get("artist") or {}).get("name")
                )
            score = score_match(
                query_artist=artist,
                query_title=title,
                query_album=album or title,
                query_duration=duration,
                cand_artist=cand_artist,
                cand_title=title,
                cand_album=rel.get("title"),
                cand_duration=None,
            )
            if score > best_score:
                best_score = score
                best_mbid = str(mbid)
        if best_mbid is None or best_score < 0.5:
            return None

        url = COVER_ART_FRONT.format(mbid=quote(best_mbid, safe="-"))
        # HEAD/GET to confirm art exists (CAA redirects).
        try:
            async with self._session.head(
                url,
                headers=headers,
                timeout=HTTP_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                if resp.status >= 400:
                    async with self._session.get(
                        url,
                        headers=headers,
                        timeout=HTTP_TIMEOUT,
                        allow_redirects=True,
                    ) as get_resp:
                        if get_resp.status >= 400:
                            return None
        except (ClientError, TimeoutError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Cover Art Archive check failed: %s", err)
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Cover Art Archive check failed: %s", err)
            return None

        return ArtworkResult(url=url, source="coverartarchive", score=best_score)
