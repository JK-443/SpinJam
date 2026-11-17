from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from spinjam.config import load_config
from spinjam.identify import FixtureIdentifier, parse_shazam_result


def test_load_example_config(tmp_path: Path) -> None:
    example = Path("config.example.yaml")
    assert example.exists()
    cfg = load_config(example)
    assert cfg.capture.mode == "file"
    assert cfg.mqtt.topic_prefix == "spinjam"
    assert cfg.identify.clip_seconds == 5.0


@pytest.mark.asyncio
async def test_fixture_identifier_matches_loud_audio() -> None:
    rate = 44100
    channels = 2
    seconds = 1
    samples: list[int] = []
    for i in range(rate * seconds):
        v = int(0.2 * 32767 * math.sin(2 * math.pi * 440 * (i / rate)))
        samples.extend([v, v])
    pcm = struct.pack("<" + "h" * len(samples), *samples)
    match = await FixtureIdentifier().identify_pcm16(pcm, sample_rate=rate, channels=channels)
    assert match is not None
    assert match.provider == "fixture"
    assert match.title == "Test Track"


@pytest.mark.asyncio
async def test_fixture_identifier_rejects_silence() -> None:
    pcm = b"\x00" * (44100 * 2 * 2)
    match = await FixtureIdentifier().identify_pcm16(pcm, sample_rate=44100, channels=2)
    assert match is None


def test_parse_shazam_result() -> None:
    result = {
        "track": {
            "title": "Song",
            "subtitle": "Artist",
            "images": {"coverarthq": "https://example.com/a.jpg"},
            "sections": [
                {"type": "SONG", "metadata": [{"title": "Album", "text": "The Album"}]},
            ],
        },
        "matches": [{"offset": 41.2}],
    }
    match = parse_shazam_result(result)
    assert match is not None
    assert match.artist == "Artist"
    assert match.title == "Song"
    assert match.album == "The Album"
    assert match.art_url == "https://example.com/a.jpg"
    assert match.timecode_seconds == 41.2
