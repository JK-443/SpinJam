from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import struct
from typing import Iterable


class AudioState(str, Enum):
    IDLE = "idle"
    MUSIC = "music"
    GAP = "gap"


@dataclass(frozen=True)
class SilenceTransition:
    previous: AudioState
    current: AudioState
    level_db: float


@dataclass
class SilenceConfigValues:
    threshold_db: float = -35.0
    music_hold_ms: int = 400
    gap_hold_ms: int = 1500
    idle_hold_ms: int = 8000
    frame_ms: int = 100


def pcm16_rms_db(frame: bytes, channels: int = 2) -> float:
    """Return RMS level in dBFS for little-endian signed 16-bit PCM."""
    if not frame:
        return -120.0
    count = len(frame) // 2
    if count == 0:
        return -120.0
    samples = struct.unpack("<" + "h" * count, frame[: count * 2])
    if channels > 1:
        # Mix to mono by averaging interleaved channels.
        mono: list[float] = []
        for i in range(0, len(samples) - channels + 1, channels):
            mono.append(sum(samples[i : i + channels]) / channels)
        values = mono
    else:
        values = list(samples)
    if not values:
        return -120.0
    mean_sq = sum(v * v for v in values) / len(values)
    if mean_sq <= 0:
        return -120.0
    rms = math.sqrt(mean_sq)
    return 20.0 * math.log10(rms / 32768.0)


class SilenceFSM:
    """Detect idle / music / inter-track gaps from frame levels."""

    def __init__(self, config: SilenceConfigValues | None = None) -> None:
        self.config = config or SilenceConfigValues()
        self.state = AudioState.IDLE
        self._above_ms = 0
        self._below_ms = 0
        self.last_level_db = -120.0

    def reset(self) -> None:
        self.state = AudioState.IDLE
        self._above_ms = 0
        self._below_ms = 0
        self.last_level_db = -120.0

    def process_level(self, level_db: float, frame_ms: int | None = None) -> SilenceTransition | None:
        frame_ms = self.config.frame_ms if frame_ms is None else frame_ms
        self.last_level_db = level_db
        loud = level_db >= self.config.threshold_db
        previous = self.state

        if loud:
            self._above_ms += frame_ms
            self._below_ms = 0
        else:
            self._below_ms += frame_ms
            self._above_ms = 0

        if self.state == AudioState.IDLE:
            if loud and self._above_ms >= self.config.music_hold_ms:
                self.state = AudioState.MUSIC
        elif self.state == AudioState.MUSIC:
            if (not loud) and self._below_ms >= self.config.gap_hold_ms:
                self.state = AudioState.GAP
        elif self.state == AudioState.GAP:
            if loud and self._above_ms >= self.config.music_hold_ms:
                self.state = AudioState.MUSIC
            elif (not loud) and self._below_ms >= self.config.idle_hold_ms:
                self.state = AudioState.IDLE

        if self.state != previous:
            return SilenceTransition(previous=previous, current=self.state, level_db=level_db)
        return None

    def process_frame(self, frame: bytes, channels: int = 2, frame_ms: int | None = None) -> SilenceTransition | None:
        return self.process_level(pcm16_rms_db(frame, channels=channels), frame_ms=frame_ms)

    def feed_levels(self, levels_db: Iterable[float], frame_ms: int | None = None) -> list[SilenceTransition]:
        transitions: list[SilenceTransition] = []
        for level in levels_db:
            event = self.process_level(level, frame_ms=frame_ms)
            if event is not None:
                transitions.append(event)
        return transitions
