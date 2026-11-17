"""Tests for multi-display config, select, start/stop, and attributes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam.const import (
    ATTR_DISPLAYS,
    ATTR_SELECTED_DISPLAY,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAYS,
    CONF_LYRICS_ENABLED,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_DISPLAYS: [
            "media_player.living_room_tv",
            "media_player.bedroom_tv",
        ],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_displays"),
    )


@pytest.mark.asyncio
async def test_displays_and_legacy_migration(hass: HomeAssistant) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_legacy",
        **{CONF_DISPLAYS: [], CONF_DISPLAY_ENTITY: "media_player.living_room_tv"},
    )
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    assert coordinator.displays == ["media_player.living_room_tv"]

    entry2 = _entry(unique_id=f"{DOMAIN}_multi")
    entry2.add_to_hass(hass)
    coordinator2 = SpinJamCoordinator(hass, entry2)
    assert coordinator2.displays == [
        "media_player.living_room_tv",
        "media_player.bedroom_tv",
    ]


@pytest.mark.asyncio
async def test_missing_displays_key_still_works(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_LYRICS_ENABLED: False,
            CONF_SYNC_OFFSET_MS: 0,
        },
        unique_id=f"{DOMAIN}_no_displays",
    )
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    assert coordinator.displays == []
    assert coordinator.selected_display is None


@pytest.mark.asyncio
async def test_start_validates_display_and_fires_event(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_start")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    # Avoid starting the interval updater (debounce timers) for this unit test.
    coordinator.selected_display = coordinator.displays[0]
    assert coordinator.selected_display == "media_player.living_room_tv"

    events: list[dict] = []

    def _capture(event) -> None:
        events.append(event.data)

    hass.bus.async_listen(EVENT_SPINJAM_START, _capture)

    with pytest.raises(ServiceValidationError):
        await coordinator.async_start("media_player.not_configured_tv")

    # Skip refresh debounce in start by stubbing request_refresh.
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    target = await coordinator.async_start("media_player.bedroom_tv")
    assert target == "media_player.bedroom_tv"
    assert coordinator.selected_display == "media_player.bedroom_tv"
    await hass.async_block_till_done()
    assert events and events[-1]["display"] == "media_player.bedroom_tv"
    await hass.async_stop()


@pytest.mark.asyncio
async def test_stop_fires_event(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_stop")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    events: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_STOP, lambda e: events.append(e.data))
    await coordinator.async_stop()
    await hass.async_block_till_done()
    assert events and events[-1].get("display") == "media_player.living_room_tv"
    await hass.async_stop()


@pytest.mark.asyncio
async def test_media_player_exposes_display_attributes(hass: HomeAssistant) -> None:
    hass.states.async_set("media_player.living_room", "idle", {})
    entry = _entry(unique_id=f"{DOMAIN}_attrs")
    entry.add_to_hass(hass)

    with patch.object(
        SpinJamCoordinator,
        "_client",
        return_value=MagicMock(fetch=AsyncMock(return_value=None)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("media_player.spinjam_now_playing")
    assert state is not None
    assert state.attributes.get(ATTR_DISPLAYS) == [
        "media_player.living_room_tv",
        "media_player.bedroom_tv",
    ]
    assert state.attributes.get(ATTR_SELECTED_DISPLAY) == "media_player.living_room_tv"

    select_state = hass.states.get("select.spinjam_display")
    assert select_state is not None
    assert select_state.state == "media_player.living_room_tv"
    assert set(select_state.attributes.get("options", [])) == {
        "media_player.living_room_tv",
        "media_player.bedroom_tv",
    }

    assert hass.services.has_service(DOMAIN, "start")
    assert hass.services.has_service(DOMAIN, "stop")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_stop()


@pytest.mark.asyncio
async def test_schema_includes_displays() -> None:
    pytest.importorskip("homeassistant")
    from custom_components.spinjam.config_flow import _schema
    from custom_components.spinjam.const import CONF_DISPLAYS

    schema = _schema()
    data = schema(
        {
            "name": "SpinJam",
            "source_players": ["media_player.living_room"],
            "displays": ["media_player.living_room_tv"],
            "lyrics_enabled": True,
            "sync_offset_ms": 0,
        }
    )
    assert data[CONF_DISPLAYS] == ["media_player.living_room_tv"]
