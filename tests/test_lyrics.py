from __future__ import annotations

from custom_components.spinjam.lyrics import LyricsCache, line_at, parse_lrc


def test_parse_lrc_and_line_at() -> None:
    synced = """
[00:00.00] Intro
[00:12.50] First line
[00:20.00] Second line
[01:05.125] Third line
"""
    lines = parse_lrc(synced)
    assert len(lines) == 4
    assert lines[1].text == "First line"
    assert abs(lines[1].start - 12.5) < 0.001
    assert abs(lines[3].start - 65.125) < 0.001

    assert line_at(lines, 0.0) == ("Intro", "First line")
    assert line_at(lines, 12.5) == ("First line", "Second line")
    assert line_at(lines, 90.0) == ("Third line", None)
    assert line_at((), 1.0) == (None, None)


def test_lyrics_cache_lru() -> None:
    cache = LyricsCache(maxsize=2)
    cache.set("a", None)
    cache.set("b", None)
    assert cache.get("a") is None
    cache.set("c", None)
    assert cache.get("b") is Ellipsis
    assert cache.get("a") is None
    assert cache.get("c") is None
