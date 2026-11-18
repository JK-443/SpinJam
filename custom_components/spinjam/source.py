"""Pure source selection helpers (unit-testable without HA)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .const import (
    IGNORED_PASSTHROUGH_SOURCES,
    LINE_IN_SOURCES,
    SOURCE_KIND_LINE_IN,
    SOURCE_KIND_STREAM,
    SOURCE_KIND_VINYL,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_line_in_source(source: str | None) -> bool:
    if not source:
        return False
    return source.strip().lower() in LINE_IN_SOURCES


def is_passthrough_source(source: str | None) -> bool:
    """Return True for TV / HDMI / line-in / optical-style input sources."""
    if not source:
        return False
    return source.strip().lower() in IGNORED_PASSTHROUGH_SOURCES


def is_tv_placeholder_track(
    title: str | None, artist: str | None
) -> bool:
    """True when metadata is just a bare 'TV' label with no artist."""
    if artist and str(artist).strip():
        return False
    return (title or "").strip().lower() == "tv"


def estimate_position(
    *,
    media_position: float | None,
    media_position_updated_at: datetime | None,
    state: str,
    sync_offset_ms: int = 0,
    now: datetime | None = None,
) -> float | None:
    if media_position is None:
        return None
    position = float(media_position)
    if state == "playing" and media_position_updated_at is not None:
        current = now or _utcnow()
        updated = media_position_updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        position += max(0.0, (current - updated).total_seconds())
    position += sync_offset_ms / 1000.0
    return max(0.0, position)


@dataclass(frozen=True)
class SourceSnapshot:
    entity_id: str
    state: str
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    art_url: str | None = None
    duration: float | None = None
    position: float | None = None
    position_updated_at: datetime | None = None
    source: str | None = None
    app_id: str | None = None
    last_changed: datetime | None = None


@dataclass(frozen=True)
class ActiveSource:
    entity_id: str
    kind: str
    artist: str | None
    title: str | None
    album: str | None
    art_url: str | None
    duration: float | None
    position: float | None
    playing: bool
    source_label: str | None = None
    # Raw source media_position_updated_at (not SpinJam's publish clock).
    position_updated_at: datetime | None = None


def snapshot_from_state(entity_id: str, state: str, attrs: dict[str, Any]) -> SourceSnapshot:
    updated = attrs.get("media_position_updated_at")
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            updated = None
    last_changed = attrs.get("last_changed")
    if isinstance(last_changed, str):
        try:
            last_changed = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
        except ValueError:
            last_changed = None

    duration = attrs.get("media_duration")
    position = attrs.get("media_position")
    return SourceSnapshot(
        entity_id=entity_id,
        state=state,
        artist=attrs.get("media_artist") or attrs.get("media_album_artist"),
        title=attrs.get("media_title") or attrs.get("media_content_id"),
        album=attrs.get("media_album_name"),
        art_url=attrs.get("entity_picture"),
        duration=float(duration) if duration is not None else None,
        position=float(position) if position is not None else None,
        position_updated_at=updated if isinstance(updated, datetime) else None,
        source=attrs.get("source"),
        app_id=attrs.get("app_id") or attrs.get("app_name"),
        last_changed=last_changed if isinstance(last_changed, datetime) else None,
    )


def _active_from_snap(
    snap: SourceSnapshot,
    *,
    kind: str,
    sync_offset_ms: int,
    now: datetime | None,
) -> ActiveSource:
    position = estimate_position(
        media_position=snap.position,
        media_position_updated_at=snap.position_updated_at,
        state=snap.state,
        sync_offset_ms=sync_offset_ms,
        now=now,
    )
    return ActiveSource(
        entity_id=snap.entity_id,
        kind=kind,
        artist=snap.artist,
        title=snap.title,
        album=snap.album,
        art_url=snap.art_url,
        duration=snap.duration,
        position=position,
        playing=snap.state == "playing",
        source_label=snap.source,
        position_updated_at=snap.position_updated_at,
    )


def select_active_source(
    snapshots: list[SourceSnapshot],
    *,
    priority: list[str],
    vinyl_entity_id: str | None,
    sync_offset_ms: int = 0,
    now: datetime | None = None,
    hold: ActiveSource | None = None,
) -> ActiveSource | None:
    """Pick the active now-playing source.

    Candidates are sources that are playing, or paused with metadata.
    Ranking: any playing source beats any paused source; within the same
    play/pause tier, config list order wins (then recency). Paused wins only
    when nothing is playing. Sonos/Port Line-in defers to the vinyl entity
    when configured.

    When ``hold`` is a still-playing source for the same track, keep it so
    mid-track flaps between sources (e.g. speaker groups) do not retarget.
    Hold is released when that source stops or pauses.
    """
    by_id = {snap.entity_id: snap for snap in snapshots}

    if hold is not None and hold.playing:
        held = by_id.get(hold.entity_id)
        if (
            held is not None
            and held.state == "playing"
            and held.title == hold.title
            and held.artist == hold.artist
            and not is_tv_placeholder_track(held.title, held.artist)
            and not (
                is_passthrough_source(held.source)
                and not is_line_in_source(held.source)
            )
        ):
            # Preserve vinyl/line-in kind when held.
            kind = hold.kind
            if is_line_in_source(held.source) and vinyl_entity_id and vinyl_entity_id in by_id:
                held = by_id[vinyl_entity_id]
                kind = SOURCE_KIND_VINYL
            return _active_from_snap(
                held, kind=kind, sync_offset_ms=sync_offset_ms, now=now
            )

    # (not_playing, priority_index, -recency, snap, kind)
    candidates: list[tuple[bool, int, float, SourceSnapshot, str]] = []

    for index, entity_id in enumerate(priority):
        snap = by_id.get(entity_id)
        if snap is None:
            continue
        kind = SOURCE_KIND_STREAM
        effective = snap

        if is_line_in_source(snap.source):
            kind = SOURCE_KIND_LINE_IN
            if vinyl_entity_id and vinyl_entity_id in by_id:
                effective = by_id[vinyl_entity_id]
                kind = SOURCE_KIND_VINYL
            elif vinyl_entity_id and entity_id == vinyl_entity_id:
                kind = SOURCE_KIND_VINYL
            else:
                # Line-in / passthrough without a vinyl capture node — ignore
                # (avoids tracking HDMI-ARC "TV" after a Cast wake).
                continue
        elif is_passthrough_source(snap.source):
            # TV / HDMI / optical input — not a music now-playing source.
            continue

        if vinyl_entity_id and entity_id == vinyl_entity_id:
            kind = SOURCE_KIND_VINYL

        playing_like = effective.state in ("playing", "paused")
        has_meta = bool(effective.title or effective.artist)
        if not playing_like or (effective.state == "paused" and not has_meta):
            continue
        if effective.state == "playing" and not has_meta and kind != SOURCE_KIND_VINYL:
            # Still allow playing without meta for vinyl node while identifying
            if kind == SOURCE_KIND_STREAM:
                continue
        if is_tv_placeholder_track(effective.title, effective.artist):
            # Soundbar/ARC often exposes media_title="TV" with no artist.
            continue

        recency = effective.position_updated_at or effective.last_changed or datetime.fromtimestamp(0, tz=timezone.utc)
        not_playing = effective.state != "playing"
        candidates.append((not_playing, index, -recency.timestamp(), effective, kind))

    # Also consider vinyl if not already in priority but configured and playing
    if vinyl_entity_id and vinyl_entity_id not in priority and vinyl_entity_id in by_id:
        snap = by_id[vinyl_entity_id]
        if snap.state == "playing" and (snap.title or snap.artist):
            recency = snap.position_updated_at or snap.last_changed or datetime.fromtimestamp(0, tz=timezone.utc)
            candidates.append((False, len(priority) + 1, -recency.timestamp(), snap, SOURCE_KIND_VINYL))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _paused, _prio, _rec, snap, kind = candidates[0]
    return _active_from_snap(snap, kind=kind, sync_offset_ms=sync_offset_ms, now=now)
