from __future__ import annotations

from datetime import datetime, timezone

from custom_components.spinjam.source import (
    SourceSnapshot,
    estimate_position,
    is_line_in_source,
    select_active_source,
)


def test_is_line_in_source() -> None:
    assert is_line_in_source("Line-in")
    assert is_line_in_source("LINE_IN")
    assert not is_line_in_source("Spotify")
    assert not is_line_in_source(None)


def test_estimate_position_advances_while_playing() -> None:
    updated = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
    pos = estimate_position(
        media_position=10.0,
        media_position_updated_at=updated,
        state="playing",
        sync_offset_ms=500,
        now=now,
    )
    assert pos == 15.5


def test_priority_picks_first_playing() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.kitchen",
            state="idle",
            title="Nope",
            artist="X",
        ),
        SourceSnapshot(
            entity_id="media_player.living_room",
            state="playing",
            title="Song A",
            artist="Artist A",
            album="Album",
            position=12.0,
            position_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        SourceSnapshot(
            entity_id="media_player.office",
            state="playing",
            title="Song B",
            artist="Artist B",
            position=1.0,
            position_updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    ]
    active = select_active_source(
        snaps,
        priority=[
            "media_player.kitchen",
            "media_player.living_room",
            "media_player.office",
        ],
        vinyl_entity_id=None,
        sync_offset_ms=0,
        now=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
    )
    assert active is not None
    assert active.entity_id == "media_player.living_room"
    assert active.title == "Song A"
    assert active.kind == "stream"
    assert active.position == 15.0


def test_line_in_defers_to_vinyl() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.living_room_port",
            state="playing",
            source="Line-in",
            title=None,
            artist=None,
        ),
        SourceSnapshot(
            entity_id="media_player.spinjam_turntable",
            state="playing",
            title="Karma Police",
            artist="Radiohead",
            album="OK Computer",
            art_url="https://example.com/ok.jpg",
            position=40.0,
        ),
    ]
    active = select_active_source(
        snaps,
        priority=["media_player.living_room_port", "media_player.spinjam_turntable"],
        vinyl_entity_id="media_player.spinjam_turntable",
        sync_offset_ms=0,
    )
    assert active is not None
    assert active.entity_id == "media_player.spinjam_turntable"
    assert active.kind == "vinyl"
    assert active.title == "Karma Police"
    assert active.art_url == "https://example.com/ok.jpg"
