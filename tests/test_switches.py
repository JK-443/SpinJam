"""Tests for switch.spinjam_cast and switch.spinjam_tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.spinjam.const import (
    CONF_BUILTIN_CASTING,
    CONF_DISPLAYS,
    CONF_LYRICS_ENABLED,
    CONF_RECAST_ON_STARTUP,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache
from homeassistant.core import State


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_DISPLAYS: ["media_player.living_room_tv"],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_RECAST_WHILE_PLAYING: False,
        CONF_BUILTIN_CASTING: True,
        CONF_RECAST_ON_STARTUP: False,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_switches"),
    )


@pytest.mark.asyncio
async def test_cast_switch_syncs_with_start_stop(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cast_sw")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    from custom_components.spinjam.switch import SpinJamCastSwitch

    switch = SpinJamCastSwitch(coordinator, entry)
    coordinator.cast_switch = switch
    assert switch.is_on is False

    events_start: list[dict] = []
    events_stop: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_START, lambda e: events_start.append(e.data))
    hass.bus.async_listen(EVENT_SPINJAM_STOP, lambda e: events_stop.append(e.data))

    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
        return_value=True,
    ) as show:
        await switch.async_turn_on()
        await hass.async_block_till_done()
    assert switch.is_on is True
    assert coordinator.cast_active is True
    show.assert_awaited()
    assert events_start

    with patch(
        "custom_components.spinjam.coordinator.async_end_cast",
        new_callable=AsyncMock,
        return_value=True,
    ) as end:
        await switch.async_turn_off()
        await hass.async_block_till_done()
    assert switch.is_on is False
    assert coordinator.cast_active is False
    end.assert_awaited()
    assert events_stop

    # Service path keeps switch in sync.
    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await coordinator.async_start()
        await hass.async_block_till_done()
    assert switch.is_on is True
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_builtin_casting_off_fires_events_only(hass: HomeAssistant) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_no_builtin",
        **{CONF_BUILTIN_CASTING: False},
    )
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    events: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_START, lambda e: events.append(e.data))

    with (
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
        ) as show,
        patch(
            "custom_components.spinjam.coordinator.async_end_cast",
            new_callable=AsyncMock,
        ) as end,
    ):
        await coordinator.async_start()
        assert coordinator.cast_active is True
        show.assert_not_awaited()
        await coordinator.async_stop()
        assert coordinator.cast_active is False
        end.assert_not_awaited()

    assert events and events[-1]["display"] == "media_player.living_room_tv"
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_cast_clears_when_display_goes_off(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cast_drop")
    entry.add_to_hass(hass)
    hass.states.async_set("media_player.living_room_tv", "playing", {})
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = "media_player.living_room_tv"
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await coordinator.async_start()
    assert coordinator.cast_active is True

    hass.states.async_set("media_player.living_room_tv", STATE_OFF, {})
    await hass.async_block_till_done()
    assert coordinator.cast_active is False
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_tracking_off_holds_and_stops_polling(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {
            "media_title": "Song A",
            "media_artist": "Artist A",
            "media_position": 10,
        },
    )
    entry = _entry(unique_id=f"{DOMAIN}_track", **{CONF_DISPLAYS: []})
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    await coordinator.async_refresh()
    assert coordinator.data.active is not None
    assert coordinator.data.active.title == "Song A"
    assert coordinator.update_interval is not None

    await coordinator.async_set_tracking(False)
    assert coordinator.tracking_enabled is False
    assert coordinator.update_interval is None
    assert coordinator._unsub_state is None  # noqa: SLF001
    assert coordinator.data.active is not None
    assert coordinator.data.active.title == "Song A"

    # Source changes must not update held snapshot while tracking is off.
    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {
            "media_title": "Song B",
            "media_artist": "Artist B",
            "media_position": 20,
        },
    )
    await hass.async_block_till_done()
    # Even a manual refresh while tracking off returns the held snapshot.
    await coordinator.async_refresh()
    assert coordinator.data.active.title == "Song A"

    await coordinator.async_set_tracking(True)
    assert coordinator.tracking_enabled is True
    assert coordinator.update_interval is not None
    await coordinator.async_refresh()
    assert coordinator.data.active.title == "Song B"
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_tracking_off_leaves_cast_alone(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_track_cast")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await coordinator.async_start()
    assert coordinator.cast_active is True
    await coordinator.async_set_tracking(False)
    assert coordinator.cast_active is True
    await coordinator.async_shutdown()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_recast_on_startup_option(hass: HomeAssistant) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_recast_boot",
        **{CONF_RECAST_ON_STARTUP: True},
    )
    entry.add_to_hass(hass)
    mock_restore_cache(hass, [State("switch.spinjam_cast", STATE_ON)])

    with (
        patch.object(
            SpinJamCoordinator,
            "_client",
            return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
        ),
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
            return_value=True,
        ) as show,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert show.await_count >= 1
    cast_state = hass.states.get("switch.spinjam_cast")
    assert cast_state is not None
    assert cast_state.state == STATE_ON
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_no_recast_on_startup_by_default(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_no_recast_boot")
    entry.add_to_hass(hass)
    mock_restore_cache(hass, [State("switch.spinjam_cast", STATE_ON)])

    with (
        patch.object(
            SpinJamCoordinator,
            "_client",
            return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
        ),
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
            return_value=True,
        ) as show,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    show.assert_not_awaited()
    cast_state = hass.states.get("switch.spinjam_cast")
    assert cast_state is not None
    assert cast_state.state == STATE_OFF
    tracking = hass.states.get("switch.spinjam_tracking")
    assert tracking is not None
    assert tracking.state == STATE_ON
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_options_schema_includes_builtin_casting() -> None:
    pytest.importorskip("homeassistant")
    from custom_components.spinjam.config_flow import _schema
    from custom_components.spinjam.const import CONF_BUILTIN_CASTING, CONF_RECAST_ON_STARTUP

    schema = _schema(options=True)
    data = schema(
        {
            "name": "SpinJam",
            "source_players": ["media_player.living_room"],
            "displays": ["media_player.living_room_tv"],
            "lyrics_enabled": True,
            "sync_offset_ms": 0,
            "lyric_offset_ms": 0,
            "builtin_casting": False,
            "dashboard_path": "spinjam",
            "view_path": "now",
            "recast_while_playing": True,
            "recast_interval": 45,
            "recast_on_startup": True,
        }
    )
    assert data[CONF_BUILTIN_CASTING] is False
    assert data[CONF_RECAST_ON_STARTUP] is True


def test_cast_switch_is_restore_entity() -> None:
    from custom_components.spinjam.switch import SpinJamCastSwitch, SpinJamTrackingSwitch

    assert issubclass(SpinJamCastSwitch, RestoreEntity)
    assert issubclass(SpinJamTrackingSwitch, RestoreEntity)
