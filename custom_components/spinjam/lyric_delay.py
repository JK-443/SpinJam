"""Pure formatting for the lyric-delay readout."""

from __future__ import annotations


def format_lyric_delay_seconds(offset_ms: int) -> str:
    """Signed seconds, e.g. ``+2.0 s``, ``+2.25 s``, ``-0.25 s``, ``0.0 s``."""
    offset_ms = int(offset_ms)
    if offset_ms == 0:
        return "0.0 s"
    seconds = abs(offset_ms) / 1000.0
    text = f"{seconds:.2f}".rstrip("0").rstrip(".")
    if "." not in text:
        text = f"{seconds:.1f}"
    sign = "+" if offset_ms > 0 else "-"
    return f"{sign}{text} s"


def format_lyric_delay(offset_ms: int) -> str:
    """Signed seconds plus direction, e.g. ``+2.0 s (later)``."""
    offset_ms = int(offset_ms)
    if offset_ms > 0:
        word = "later"
    elif offset_ms < 0:
        word = "earlier"
    else:
        word = "on time"
    return f"{format_lyric_delay_seconds(offset_ms)} ({word})"


def lyric_delay_toast(previous_ms: int, next_ms: int) -> str:
    """Overlay copy: ``Lyrics +250 ms later, now +2.25 s``."""
    delta = int(next_ms) - int(previous_ms)
    direction = "later" if delta > 0 else "earlier"
    signed = f"{delta:+d}"
    return (
        f"Lyrics {signed} ms {direction}, now {format_lyric_delay_seconds(int(next_ms))}"
    )
