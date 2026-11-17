#!/usr/bin/env python3
"""Generate fixtures/sample_music.wav for file-mode testing without USB hardware."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "sample_music.wav"
RATE = 44100
CHANNELS = 2
AMP = 0.25  # ~ -12 dBFS peak-ish for sine


def silence(seconds: float) -> bytes:
    n = int(RATE * seconds)
    return struct.pack("<" + "h" * (n * CHANNELS), *([0] * (n * CHANNELS)))


def tone(seconds: float, freq: float = 440.0) -> bytes:
    n = int(RATE * seconds)
    samples: list[int] = []
    for i in range(n):
        v = int(AMP * 32767 * math.sin(2 * math.pi * freq * (i / RATE)))
        samples.extend([v, v])
    return struct.pack("<" + "h" * len(samples), *samples)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # idle → music → gap → music → idle
    # Keep the fixture small for the repo while still exercising idle/music/gap/idle.
    pcm = b"".join(
        [
            silence(0.5),
            tone(1.5, 440.0),
            silence(1.0),
            tone(1.5, 554.37),
            silence(3.0),
        ]
    )
    with wave.open(str(OUT), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(pcm)
    print(f"Wrote {OUT} ({len(pcm)} bytes PCM)")


if __name__ == "__main__":
    main()
