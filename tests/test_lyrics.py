from __future__ import annotations

from custom_components.spinjam.lyrics import (
    LyricsCache,
    line_at,
    lines_payload,
    parse_lrc,
    parse_word_tags,
)


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


def test_parse_lrc_multiple_timestamps_per_line() -> None:
    """[00:12][00:40]text must create one entry per timestamp, sorted."""
    synced = """
[00:12.00][00:40.50] Shared line
[00:05.00] Earlier alone
"""
    lines = parse_lrc(synced)
    assert [round(line.start, 2) for line in lines] == [5.0, 12.0, 40.5]
    assert lines[0].text == "Earlier alone"
    assert lines[1].text == "Shared line"
    assert lines[2].text == "Shared line"
    assert line_at(lines, 12.0) == ("Shared line", "Shared line")
    assert line_at(lines, 40.5)[0] == "Shared line"


def test_parse_enhanced_word_tags() -> None:
    plain, words = parse_word_tags("<00:12.00>Hello <00:12.40>world")
    assert plain == "Hello world"
    assert len(words) == 2
    assert abs(words[0].start - 12.0) < 0.001
    assert words[0].text.strip() == "Hello"
    assert words[1].text.strip() == "world"

    synced = "[00:12.00]<00:12.00>Hello <00:12.40>world"
    lines = parse_lrc(synced)
    assert len(lines) == 1
    assert lines[0].text == "Hello world"
    assert lines[0].words
    payload = lines_payload(lines)
    assert payload is not None
    assert payload[0]["words"][0]["t"] == 12.0


def test_lines_payload_windows_around_position() -> None:
    synced = "\n".join(f"[00:{i:02d}.00] Line {i}" for i in range(0, 60))
    # mm:ss only goes to 59 — build with minutes for a long list
    synced = "\n".join(
        f"[{i // 60:02d}:{i % 60:02d}.00] Line {i}" for i in range(0, 200)
    )
    lines = parse_lrc(synced)
    assert len(lines) == 200
    payload = lines_payload(lines, position=100.0, max_lines=120, before=40)
    assert payload is not None
    assert len(payload) == 120
    # Window should include the line near t=100
    texts = [row["text"] for row in payload]
    assert "Line 100" in texts
    assert "Line 0" not in texts


def test_lyrics_cache_lru() -> None:
    cache = LyricsCache(maxsize=2)
    cache.set("a", None)
    cache.set("b", None)
    assert cache.get("a") is None
    cache.set("c", None)
    assert cache.get("b") is Ellipsis
    assert cache.get("a") is None
    assert cache.get("c") is None
