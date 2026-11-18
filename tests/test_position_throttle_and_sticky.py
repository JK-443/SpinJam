"""Coordinator position publish throttle + sticky mid-track source."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.spinjam.const import (
    CONF_DISPLAYS,
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.source import (
    ActiveSource,
    SourceSnapshot,
    select_active_source,
)

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_hold_keeps_playing_source_mid_track() -> None:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    snaps = [
        SourceSnapshot(
            entity_id="media_player.speaker_a",
            state="playing",
            artist="Artist A",
            title="Song One",
            position=10.0,
            position_updated_at=now,
        ),
        SourceSnapshot(
            entity_id="media_player.speaker_b",
            state="playing",
            artist="Artist A",
            title="Song One",
            position=10.5,
            position_updated_at=now,
        ),
    ]
    # Without hold, speaker_a wins (priority order).
    first = select_active_source(
        snaps,
        priority=["media_player.speaker_a", "media_player.speaker_b"],
        vinyl_entity_id=None,
        now=now,
    )
    assert first is not None
    assert first.entity_id == "media_player.speaker_a"

    # Even if priority would prefer B when A missing from reorder — hold A.
    held = ActiveSource(
        entity_id="media_player.speaker_a",
        kind="stream",
        artist="Artist A",
        title="Song One",
        album=None,
        art_url=None,
        duration=200.0,
        position=10.0,
        playing=True,
    )
    # B listed first now; hold keeps A while still playing same track.
    stuck = select_active_source(
        snaps,
        priority=["media_player.speaker_b", "media_player.speaker_a"],
        vinyl_entity_id=None,
        now=now,
        hold=held,
    )
    assert stuck is not None
    assert stuck.entity_id == "media_player.speaker_a"

    # Pause releases hold.
    snaps[0] = SourceSnapshot(
        entity_id="media_player.speaker_a",
        state="paused",
        artist="Artist A",
        title="Song One",
        position=10.0,
        position_updated_at=now,
    )
    released = select_active_source(
        snaps,
        priority=["media_player.speaker_b", "media_player.speaker_a"],
        vinyl_entity_id=None,
        now=now,
        hold=held,
    )
    assert released is not None
    assert released.entity_id == "media_player.speaker_b"


def _entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.speaker_a"],
            CONF_DISPLAYS: [],
            CONF_LYRICS_ENABLED: False,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_HD_ARTWORK: False,
            CONF_PREFETCH: False,
        },
        title="SpinJam",
        unique_id=f"{DOMAIN}_pos_throttle",
        version=2,
    )


@pytest.mark.asyncio
async def test_position_writes_at_most_once_per_30s_steady(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._tracking_enabled = True  # noqa: SLF001

    writes: list[tuple[float | None, datetime | None]] = []
    base = datetime.now(timezone.utc)

    with patch(
        "custom_components.spinjam.coordinator.async_resolve_next_track",
        new_callable=AsyncMock,
        return_value=None,
    ):
        for second in range(0, 45):
            now = base + timedelta(seconds=second)
            hass.states.async_set(
                "media_player.speaker_a",
                "playing",
                {
                    "media_title": "Song One",
                    "media_artist": "Artist A",
                    "media_duration": 200,
                    "media_position": float(second),
                    "media_position_updated_at": now.isoformat(),
                },
            )
            with (
                patch(
                    "custom_components.spinjam.coordinator.time.monotonic",
                    return_value=float(second),
                ),
                patch(
                    "custom_components.spinjam.source._utcnow",
                    return_value=now,
                ),
            ):
                data = await coordinator._async_update_data()  # noqa: SLF001
                coordinator.data = data
            assert data.active is not None
            pos = data.active.position
            ts = data.position_updated_at
            if not writes or writes[-1][0] != pos or writes[-1][1] != ts:
                writes.append((pos, ts))

    # First write + at most one drift write inside 45s window (30s cadence).
    assert 1 <= len(writes) <= 2
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_track_change_waits_for_new_mpua(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._tracking_enabled = True  # noqa: SLF001
    t0 = datetime.now(timezone.utc).replace(microsecond=0)

    with patch(
        "custom_components.spinjam.coordinator.async_resolve_next_track",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "custom_components.spinjam.coordinator.time.monotonic", return_value=0.0
    ), patch(
        "custom_components.spinjam.source._utcnow", return_value=t0
    ):
        hass.states.async_set(
            "media_player.speaker_a",
            "playing",
            {
                "media_title": "Song One",
                "media_artist": "Artist A",
                "media_position": 10.0,
                "media_position_updated_at": t0.isoformat(),
            },
        )
        first = await coordinator._async_update_data()  # noqa: SLF001
        coordinator.data = first
        assert first.active is not None
        assert first.active.position is not None

        # New title but same media_position_updated_at → withhold position.
        hass.states.async_set(
            "media_player.speaker_a",
            "playing",
            {
                "media_title": "Song Two",
                "media_artist": "Artist A",
                "media_position": 0.0,
                "media_position_updated_at": t0.isoformat(),
            },
        )
        pending = await coordinator._async_update_data()  # noqa: SLF001
        coordinator.data = pending
        assert pending.active is not None
        assert pending.active.position is None

        # Fresh m_p_u_a unlocks position.
        t1 = t0 + timedelta(seconds=2)
        with patch("custom_components.spinjam.source._utcnow", return_value=t1):
            hass.states.async_set(
                "media_player.speaker_a",
                "playing",
                {
                    "media_title": "Song Two",
                    "media_artist": "Artist A",
                    "media_position": 0.5,
                    "media_position_updated_at": t1.isoformat(),
                },
            )
            ready = await coordinator._async_update_data()  # noqa: SLF001
        assert ready.active is not None
        assert ready.active.position is not None

    await coordinator.async_shutdown()
