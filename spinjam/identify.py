from __future__ import annotations

import asyncio
import logging
import struct
import wave
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackMatch:
    artist: str
    title: str
    album: str | None = None
    art_url: str | None = None
    timecode_seconds: float | None = None
    provider: str = "shazam"
    raw: dict | None = None


class Identifier(Protocol):
    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None: ...


def pcm16_to_wav_bytes(pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class NullIdentifier:
    """No-op identifier for offline / fixture runs."""

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        _ = pcm, sample_rate, channels
        return None


class FixtureIdentifier:
    """Returns a canned match when enough non-silent audio is present (no network)."""

    def __init__(
        self,
        artist: str = "SpinJam Fixture",
        title: str = "Test Track",
        album: str = "Fixture Album",
        art_url: str | None = "https://via.placeholder.com/600x600.png?text=SpinJam",
        min_rms_db: float = -50.0,
    ) -> None:
        self.artist = artist
        self.title = title
        self.album = album
        self.art_url = art_url
        self.min_rms_db = min_rms_db

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        from spinjam.silence import pcm16_rms_db

        _ = sample_rate
        level = pcm16_rms_db(pcm, channels=channels)
        if level < self.min_rms_db:
            return None
        return TrackMatch(
            artist=self.artist,
            title=self.title,
            album=self.album,
            art_url=self.art_url,
            timecode_seconds=12.0,
            provider="fixture",
            raw={"level_db": level},
        )


class ShazamIdentifier:
    """Identify using shazamio (unofficial). Lazy-imports to keep cold start light."""

    def __init__(self) -> None:
        self._shazam = None

    def _client(self):
        if self._shazam is None:
            from shazamio import Shazam

            self._shazam = Shazam()
        return self._shazam

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        if not pcm:
            return None
        wav = pcm16_to_wav_bytes(pcm, sample_rate=sample_rate, channels=channels)
        try:
            result = await self._client().recognize(wav)
        except Exception:
            log.exception("Shazam recognition failed")
            return None
        return parse_shazam_result(result)


def parse_shazam_result(result: dict | None) -> TrackMatch | None:
    if not result:
        return None
    track = result.get("track") or {}
    if not track:
        return None
    artist = (track.get("subtitle") or track.get("artist") or "").strip()
    title = (track.get("title") or "").strip()
    if not artist and not title:
        return None
    album = None
    sections = track.get("sections") or []
    for section in sections:
        if section.get("type") == "SONG":
            for meta in section.get("metadata") or []:
                if meta.get("title") == "Album":
                    album = meta.get("text")
                    break
        if album:
            break
    art_url = track.get("images", {}).get("coverarthq") or track.get("images", {}).get("coverart")
    timecode = None
    # shazamio sometimes includes matches with offset; keep optional
    matches = result.get("matches") or []
    if matches and isinstance(matches[0], dict) and "offset" in matches[0]:
        try:
            timecode = float(matches[0]["offset"])
        except (TypeError, ValueError):
            timecode = None
    return TrackMatch(
        artist=artist or "Unknown Artist",
        title=title or "Unknown Title",
        album=album,
        art_url=art_url,
        timecode_seconds=timecode,
        provider="shazam",
        raw=result,
    )


def build_identifier(*, use_shazam: bool, fixture_fallback: bool = True) -> Identifier:
    if use_shazam:
        return ShazamIdentifier()
    if fixture_fallback:
        return FixtureIdentifier()
    return NullIdentifier()


def run_identify_sync(identifier: Identifier, pcm: bytes, *, sample_rate: int, channels: int) -> TrackMatch | None:
    return asyncio.run(identifier.identify_pcm16(pcm, sample_rate=sample_rate, channels=channels))


# Keep struct import used for potential future PCM helpers without lint noise in some setups.
_ = struct
