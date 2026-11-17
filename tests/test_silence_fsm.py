from __future__ import annotations

import math
import struct

from spinjam.silence import AudioState, SilenceConfigValues, SilenceFSM, pcm16_rms_db


def _sine_frame(ms: int = 100, freq: float = 440.0, amp: float = 0.2, rate: int = 44100, channels: int = 2) -> bytes:
    n = int(rate * ms / 1000)
    samples: list[int] = []
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * (i / rate)))
        samples.extend([v] * channels)
    return struct.pack("<" + "h" * len(samples), *samples)


def _silent_frame(ms: int = 100, rate: int = 44100, channels: int = 2) -> bytes:
    n = int(rate * ms / 1000) * channels
    return struct.pack("<" + "h" * n, *([0] * n))


def test_pcm16_rms_db_silence_and_tone() -> None:
    assert pcm16_rms_db(_silent_frame()) <= -100
    level = pcm16_rms_db(_sine_frame(amp=0.25))
    assert -25 < level < -5


def test_idle_to_music_to_gap_to_music_to_idle() -> None:
    fsm = SilenceFSM(
        SilenceConfigValues(
            threshold_db=-35.0,
            music_hold_ms=300,
            gap_hold_ms=500,
            idle_hold_ms=1000,
            frame_ms=100,
        )
    )
    events = []

    # 400 ms loud → MUSIC
    for _ in range(4):
        ev = fsm.process_frame(_sine_frame())
        if ev:
            events.append(ev)
    assert fsm.state == AudioState.MUSIC
    assert events[-1].previous == AudioState.IDLE
    assert events[-1].current == AudioState.MUSIC

    # 600 ms silence → GAP
    for _ in range(6):
        ev = fsm.process_frame(_silent_frame())
        if ev:
            events.append(ev)
    assert fsm.state == AudioState.GAP
    assert events[-1].current == AudioState.GAP

    # music again
    for _ in range(4):
        ev = fsm.process_frame(_sine_frame())
        if ev:
            events.append(ev)
    assert fsm.state == AudioState.MUSIC

    # long silence → IDLE
    for _ in range(12):
        ev = fsm.process_frame(_silent_frame())
        if ev:
            events.append(ev)
    assert fsm.state == AudioState.IDLE
    assert events[-1].current == AudioState.IDLE


def test_brief_dip_does_not_trigger_gap() -> None:
    fsm = SilenceFSM(
        SilenceConfigValues(
            threshold_db=-35.0,
            music_hold_ms=200,
            gap_hold_ms=800,
            idle_hold_ms=2000,
            frame_ms=100,
        )
    )
    for _ in range(3):
        fsm.process_frame(_sine_frame())
    assert fsm.state == AudioState.MUSIC
    # 300 ms silence — shorter than gap_hold
    for _ in range(3):
        fsm.process_frame(_silent_frame())
    assert fsm.state == AudioState.MUSIC


def test_feed_levels_helper() -> None:
    fsm = SilenceFSM(
        SilenceConfigValues(threshold_db=-30, music_hold_ms=200, gap_hold_ms=200, idle_hold_ms=400, frame_ms=100)
    )
    # two loud frames, two quiet, four quiet more
    levels = [-10, -10, -60, -60, -60, -60, -60, -60]
    transitions = fsm.feed_levels(levels)
    states = [t.current for t in transitions]
    assert AudioState.MUSIC in states
    assert AudioState.GAP in states
    assert AudioState.IDLE in states
