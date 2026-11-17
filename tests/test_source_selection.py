from __future__ import annotations

from datetime import datetime, timezone

from custom_components.spinjam.source import (
    SourceSnapshot,
    estimate_position,
    is_line_in_source,
    is_passthrough_source,
    select_active_source,
)


def test_is_line_in_source() -> None:
    assert is_line_in_source("Line-in")
    assert is_line_in_source("LINE_IN")
    assert not is_line_in_source("Spotify")
    assert not is_line_in_source(None)
    assert is_passthrough_source("hdmi arc")


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


def test_playing_beats_higher_priority_paused() -> None:
    """Paused speaker_a (#2) must not beat playing speaker_b (#5)."""
    snaps = [
        SourceSnapshot(entity_id="media_player.kitchen", state="idle"),
        SourceSnapshot(
            entity_id="media_player.speaker_a",
            state="paused",
            title="Paused Track",
            artist="Artist P",
            position=10.0,
        ),
        SourceSnapshot(entity_id="media_player.bedroom", state="idle"),
        SourceSnapshot(entity_id="media_player.office", state="idle"),
        SourceSnapshot(
            entity_id="media_player.speaker_b",
            state="playing",
            title="Playing Track",
            artist="Artist M",
            position=5.0,
        ),
    ]
    active = select_active_source(
        snaps,
        priority=[
            "media_player.kitchen",
            "media_player.speaker_a",
            "media_player.bedroom",
            "media_player.office",
            "media_player.speaker_b",
        ],
        vinyl_entity_id=None,
        sync_offset_ms=0,
    )
    assert active is not None
    assert active.entity_id == "media_player.speaker_b"
    assert active.playing is True
    assert active.title == "Playing Track"


def test_only_paused_picks_highest_priority() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.speaker_a",
            state="paused",
            title="Speaker A Song",
            artist="A",
        ),
        SourceSnapshot(
            entity_id="media_player.speaker_b",
            state="paused",
            title="Speaker B Song",
            artist="B",
        ),
    ]
    active = select_active_source(
        snaps,
        priority=["media_player.speaker_a", "media_player.speaker_b"],
        vinyl_entity_id=None,
        sync_offset_ms=0,
    )
    assert active is not None
    assert active.entity_id == "media_player.speaker_a"
    assert active.playing is False
    assert active.title == "Speaker A Song"


def test_two_playing_uses_list_order() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.living_room",
            state="playing",
            title="First",
            artist="A",
        ),
        SourceSnapshot(
            entity_id="media_player.kitchen",
            state="playing",
            title="Second",
            artist="B",
        ),
    ]
    active = select_active_source(
        snaps,
        priority=["media_player.living_room", "media_player.kitchen"],
        vinyl_entity_id=None,
        sync_offset_ms=0,
    )
    assert active is not None
    assert active.entity_id == "media_player.living_room"
    assert active.title == "First"


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
