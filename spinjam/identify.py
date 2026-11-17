from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import struct
import time
import wave
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Protocol
from urllib.parse import urlencode

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


class AudDIdentifier:
    """Optional AudD REST fallback (https://api.audd.io/)."""

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        if not pcm or not self.api_token:
            return None
        wav = pcm16_to_wav_bytes(pcm, sample_rate=sample_rate, channels=channels)
        try:
            import aiohttp
        except ImportError:
            # stdlib fallback
            return await asyncio.to_thread(self._identify_urllib, wav)

        form = aiohttp.FormData()
        form.add_field("api_token", self.api_token)
        form.add_field("return", "apple_music,spotify")
        form.add_field("file", wav, filename="clip.wav", content_type="audio/wav")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://api.audd.io/", data=form, timeout=20) as resp:
                    data = await resp.json(content_type=None)
        except Exception:
            log.exception("AudD recognition failed")
            return None
        return parse_audd_result(data)

    def _identify_urllib(self, wav: bytes) -> TrackMatch | None:
        import json
        import urllib.request
        import uuid

        boundary = f"----SpinJam{uuid.uuid4().hex}"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="api_token"\r\n\r\n'
                f"{self.api_token}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="return"\r\n\r\n'
                f"apple_music,spotify\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + wav
            + f"\r\n--{boundary}--\r\n".encode()
        )
        req = urllib.request.Request(
            "https://api.audd.io/",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            log.exception("AudD recognition failed")
            return None
        return parse_audd_result(data)


class ACRCloudIdentifier:
    """Optional ACRCloud identify fallback."""

    def __init__(self, host: str, access_key: str, access_secret: str) -> None:
        self.host = host.rstrip("/")
        self.access_key = access_key
        self.access_secret = access_secret

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        if not pcm or not self.access_key or not self.access_secret:
            return None
        wav = pcm16_to_wav_bytes(pcm, sample_rate=sample_rate, channels=channels)
        return await asyncio.to_thread(self._identify_sync, wav)

    def _identify_sync(self, wav: bytes) -> TrackMatch | None:
        import json
        import urllib.request

        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))
        string_to_sign = "\n".join(
            [http_method, http_uri, self.access_key, data_type, signature_version, timestamp]
        )
        sign = base64.b64encode(
            hmac.new(
                self.access_secret.encode("ascii"),
                string_to_sign.encode("ascii"),
                digestmod=hashlib.sha1,
            ).digest()
        ).decode("ascii")

        boundary = "----SpinJamACR"
        fields = {
            "access_key": self.access_key,
            "data_type": data_type,
            "signature_version": signature_version,
            "signature": sign,
            "sample_bytes": str(len(wav)),
            "timestamp": timestamp,
        }
        body = b""
        for key, value in fields.items():
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n"
            ).encode()
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"sample\"; filename=\"clip.wav\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += wav + f"\r\n--{boundary}--\r\n".encode()

        url = f"https://{self.host}{http_uri}"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            log.exception("ACRCloud recognition failed")
            return None
        return parse_acr_result(data)


class ChainIdentifier:
    """Try identifiers in order until one returns a match."""

    def __init__(self, identifiers: list[Identifier]) -> None:
        self.identifiers = identifiers

    async def identify_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
    ) -> TrackMatch | None:
        for identifier in self.identifiers:
            match = await identifier.identify_pcm16(pcm, sample_rate=sample_rate, channels=channels)
            if match is not None:
                return match
        return None


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
    for section in track.get("sections") or []:
        if section.get("type") == "SONG":
            for meta in section.get("metadata") or []:
                if meta.get("title") == "Album":
                    album = meta.get("text")
                    break
        if album:
            break
    art_url = track.get("images", {}).get("coverarthq") or track.get("images", {}).get("coverart")
    timecode = None
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


def parse_audd_result(data: dict | None) -> TrackMatch | None:
    if not data or data.get("status") != "success":
        return None
    result = data.get("result")
    if not result:
        return None
    artist = (result.get("artist") or "").strip()
    title = (result.get("title") or "").strip()
    if not artist and not title:
        return None
    album = result.get("album")
    art_url = None
    apple = result.get("apple_music") or {}
    if isinstance(apple, dict):
        art_url = (apple.get("artwork") or {}).get("url") if isinstance(apple.get("artwork"), dict) else None
        if art_url and "{w}" in art_url:
            art_url = art_url.replace("{w}", "600").replace("{h}", "600")
    timecode = None
    if result.get("timecode"):
        # AudD timecode often "00:31"
        try:
            parts = str(result["timecode"]).split(":")
            if len(parts) == 2:
                timecode = int(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                timecode = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except (TypeError, ValueError):
            timecode = None
    return TrackMatch(
        artist=artist or "Unknown Artist",
        title=title or "Unknown Title",
        album=album,
        art_url=art_url,
        timecode_seconds=timecode,
        provider="audd",
        raw=result,
    )


def parse_acr_result(data: dict | None) -> TrackMatch | None:
    if not data:
        return None
    metadata = (data.get("metadata") or {}).get("music") or []
    if not metadata:
        return None
    track = metadata[0]
    title = (track.get("title") or "").strip()
    artists = track.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists if a.get("name")).strip()
    if not artist and not title:
        return None
    album = None
    if isinstance(track.get("album"), dict):
        album = track["album"].get("name")
    art_url = None
    timecode = track.get("play_offset_ms")
    if timecode is not None:
        try:
            timecode = float(timecode) / 1000.0
        except (TypeError, ValueError):
            timecode = None
    return TrackMatch(
        artist=artist or "Unknown Artist",
        title=title or "Unknown Title",
        album=album,
        art_url=art_url,
        timecode_seconds=timecode,
        provider="acrcloud",
        raw=track,
    )


def build_identifier(
    *,
    use_shazam: bool,
    fixture_fallback: bool = True,
    audd_token: str | None = None,
    acr_host: str | None = None,
    acr_access_key: str | None = None,
    acr_access_secret: str | None = None,
) -> Identifier:
    chain: list[Identifier] = []
    if use_shazam:
        chain.append(ShazamIdentifier())
    if audd_token:
        chain.append(AudDIdentifier(audd_token))
    if acr_host and acr_access_key and acr_access_secret:
        chain.append(ACRCloudIdentifier(acr_host, acr_access_key, acr_access_secret))
    if not chain and fixture_fallback:
        return FixtureIdentifier()
    if not chain:
        return NullIdentifier()
    if len(chain) == 1:
        return chain[0]
    return ChainIdentifier(chain)


def run_identify_sync(identifier: Identifier, pcm: bytes, *, sample_rate: int, channels: int) -> TrackMatch | None:
    return asyncio.run(identifier.identify_pcm16(pcm, sample_rate=sample_rate, channels=channels))


_ = struct, urlencode, Any
