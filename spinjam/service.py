from __future__ import annotations

import logging
import signal
import time
from typing import Any

from spinjam.capture import RingBuffer, build_audio_source
from spinjam.config import AppConfig
from spinjam.identify import Identifier, TrackMatch, build_identifier, run_identify_sync
from spinjam.mqtt_ha import MqttHaClient, NowPlaying
from spinjam.silence import AudioState, SilenceConfigValues, SilenceFSM, pcm16_rms_db

log = logging.getLogger(__name__)


class SpinJamService:
    def __init__(self, config: AppConfig, identifier: Identifier | None = None) -> None:
        self.config = config
        self.fsm = SilenceFSM(
            SilenceConfigValues(
                threshold_db=config.silence.threshold_db,
                music_hold_ms=config.silence.music_hold_ms,
                gap_hold_ms=config.silence.gap_hold_ms,
                idle_hold_ms=config.silence.idle_hold_ms,
                frame_ms=config.silence.frame_ms,
            )
        )
        self.identifier = identifier or build_identifier(
            use_shazam=config.identify.use_shazam,
            fixture_fallback=True,
        )
        self.mqtt = MqttHaClient(config, on_command=self.handle_command)
        self.ring = RingBuffer(
            sample_rate=config.capture.sample_rate,
            channels=config.capture.channels,
            seconds=max(config.identify.clip_seconds + 1.0, 8.0),
        )
        self._running = False
        self._status = "idle"
        self._now = NowPlaying()
        self._last_identify_at = 0.0
        self._identify_requested = False
        self._last_level_publish = 0.0
        self._sync_offset_ms = config.sync.offset_ms

    def handle_command(self, command: str, payload: dict[str, Any] | str | None) -> None:
        if command == "identify":
            self._identify_requested = True
            return
        if command == "sync_offset_ms":
            try:
                if isinstance(payload, dict):
                    value = int(payload.get("value", payload.get("offset_ms", 0)))
                else:
                    value = int(payload)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                log.warning("Invalid sync_offset_ms payload: %r", payload)
                return
            self._sync_offset_ms = value
            self.config.sync.offset_ms = value
            self.mqtt.publish_sync_offset(value)
            return
        if command == "clear":
            self._now = NowPlaying(playing=self.fsm.state == AudioState.MUSIC, source="auto")
            self._publish_state()
            return
        log.debug("Unhandled command %s", command)

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self.mqtt.publish_status(status)

    def _publish_state(self, level_db: float | None = None) -> None:
        playing = self.fsm.state == AudioState.MUSIC
        np = NowPlaying(
            artist=self._now.artist,
            title=self._now.title,
            album=self._now.album,
            art_url=self._now.art_url,
            playing=playing,
            position_seconds=self._now.position_seconds,
            duration_seconds=self._now.duration_seconds,
            source=self._now.source,
            provider=self._now.provider,
        )
        self.mqtt.publish_now_playing(np, status=self._status, level_db=level_db)

    def _maybe_identify(self, force: bool = False) -> None:
        if not self.config.identify.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last_identify_at) < self.config.identify.min_interval_seconds:
            return
        clip = self.ring.snapshot(self.config.identify.clip_seconds)
        need_bytes = int(
            self.config.capture.sample_rate
            * self.config.capture.channels
            * 2
            * min(2.0, self.config.identify.clip_seconds)
        )
        if len(clip) < need_bytes:
            log.debug("Not enough audio buffered for identify (%s bytes)", len(clip))
            return
        self._last_identify_at = now
        self._set_status("identifying")
        self._publish_state()
        log.info("Identifying %0.1fs clip (%s bytes)", self.config.identify.clip_seconds, len(clip))
        try:
            match = run_identify_sync(
                self.identifier,
                clip,
                sample_rate=self.config.capture.sample_rate,
                channels=self.config.capture.channels,
            )
        except Exception:
            log.exception("Identify failed")
            match = None
        if match:
            self._apply_match(match)
            self._set_status("locked" if match.album else "music")
        else:
            log.info("No match")
            self._set_status("music" if self.fsm.state == AudioState.MUSIC else self.fsm.state.value)
        self._publish_state()

    def _apply_match(self, match: TrackMatch) -> None:
        position = match.timecode_seconds
        if position is not None:
            position = max(0.0, position + (self._sync_offset_ms / 1000.0))
        self._now = NowPlaying(
            artist=match.artist,
            title=match.title,
            album=match.album,
            art_url=match.art_url,
            playing=True,
            position_seconds=position,
            source="auto",
            provider=match.provider,
        )
        log.info("Match: %s — %s (%s)", match.artist, match.title, match.provider)

    def run(self) -> None:
        self._running = True

        def _stop(signum: int, frame: Any) -> None:  # noqa: ANN401
            _ = signum, frame
            log.info("Shutdown requested")
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        source = build_audio_source(self.config.capture)
        self.mqtt.connect()
        self._set_status("idle")
        self._publish_state()
        frame_ms = self.config.silence.frame_ms
        channels = self.config.capture.channels

        log.info(
            "SpinJam running (capture=%s, shazam=%s)",
            self.config.capture.mode,
            self.config.identify.use_shazam,
        )
        try:
            for frame in source.frames(frame_ms):
                if not self._running:
                    break
                self.ring.write(frame)
                level = pcm16_rms_db(frame, channels=channels)
                transition = self.fsm.process_level(level, frame_ms=frame_ms)

                now = time.monotonic()
                if now - self._last_level_publish >= 1.0:
                    self.mqtt.publish_level(level)
                    self._last_level_publish = now

                if transition is not None:
                    log.info(
                        "Audio state %s → %s (level=%.1f dBFS)",
                        transition.previous.value,
                        transition.current.value,
                        transition.level_db,
                    )
                    if transition.current == AudioState.MUSIC:
                        self._set_status("music")
                        self._publish_state(level_db=level)
                        if self.config.identify.auto_on_music:
                            self._identify_requested = True
                    elif transition.current == AudioState.GAP:
                        self._set_status("gap")
                        self._publish_state(level_db=level)
                    elif transition.current == AudioState.IDLE:
                        self._set_status("idle")
                        self._now = NowPlaying(playing=False, source=self._now.source)
                        self._publish_state(level_db=level)

                if self._identify_requested:
                    self._identify_requested = False
                    self._maybe_identify(force=True)
        finally:
            source.close()
            self.mqtt.disconnect()
            log.info("SpinJam stopped")
