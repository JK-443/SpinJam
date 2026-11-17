from __future__ import annotations

from spinjam.identify import parse_acr_result, parse_audd_result


def test_parse_audd_result() -> None:
    data = {
        "status": "success",
        "result": {
            "artist": "Artist",
            "title": "Title",
            "album": "Album",
            "timecode": "01:02",
            "apple_music": {"artwork": {"url": "https://example.com/{w}x{h}.jpg"}},
        },
    }
    match = parse_audd_result(data)
    assert match is not None
    assert match.provider == "audd"
    assert match.timecode_seconds == 62.0
    assert match.art_url == "https://example.com/600x600.jpg"


def test_parse_acr_result() -> None:
    data = {
        "metadata": {
            "music": [
                {
                    "title": "Song",
                    "artists": [{"name": "Band"}],
                    "album": {"name": "LP"},
                    "play_offset_ms": 4500,
                }
            ]
        }
    }
    match = parse_acr_result(data)
    assert match is not None
    assert match.provider == "acrcloud"
    assert match.artist == "Band"
    assert match.timecode_seconds == 4.5
