"""v0.5.3: LovelaceData resources, passthrough sources, startup tracking, non-blocking cast."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam.const import (
    CONF_DISPLAYS,
    CONF_HD_ARTWORK,
    CONF_LYRICS_ENABLED,
    CONF_PREFETCH,
    CONF_RECAST_ON_STARTUP,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DOMAIN,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.frontend import (
    CARD_URL_PATH,
    async_register_lovelace_resource,
    lovelace_resources,
)
from custom_components.spinjam.source import (
    SourceSnapshot,
    is_passthrough_source,
    is_tv_placeholder_track,
    select_active_source,
)

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.speaker_a"],
        CONF_DISPLAYS: ["media_player.example_tv"],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_RECAST_WHILE_PLAYING: False,
        CONF_RECAST_ON_STARTUP: False,
        CONF_HD_ARTWORK: False,
        CONF_PREFETCH: False,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_v053"),
        version=2,
    )


class _FakeResources:
    loaded = True

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        item = {"id": f"id_{len(self.items)}", "type": "module", "url": data["url"]}
        self.items.append(item)
        self.created.append(item)
        return item

    async def async_update_item(self, item_id, data):
        self.updated.append((item_id, data))
        for item in self.items:
            if item["id"] == item_id:
                item["url"] = data["url"]
                item["type"] = "module"
                return item
        raise KeyError(item_id)


# --- 1) Lovelace resources ---


@pytest.mark.asyncio
async def test_lovelace_resources_from_lovelace_data_object() -> None:
    resources = _FakeResources()
    hass = MagicMock()
    hass.data = {"lovelace": SimpleNamespace(resources=resources, mode="storage")}
    assert lovelace_resources(hass) is resources
    url = f"{CARD_URL_PATH}?v=abc123"
    assert await async_register_lovelace_resource(hass, url) is True
    assert len(resources.created) == 1
    assert resources.items[0]["url"] == url


@pytest.mark.asyncio
async def test_lovelace_resources_from_dict_form() -> None:
    resources = _FakeResources()
    hass = MagicMock()
    hass.data = {"lovelace": {"resources": resources, "mode": "storage"}}
    assert await async_register_lovelace_resource(hass, f"{CARD_URL_PATH}?v=one") is True
    assert len(resources.created) == 1


@pytest.mark.asyncio
async def test_lovelace_resource_updates_existing_by_path() -> None:
    resources = _FakeResources()
    resources.items = [
        {"id": "res_1", "type": "module", "url": f"{CARD_URL_PATH}?v=oldhash"}
    ]
    hass = MagicMock()
    hass.data = {"lovelace": SimpleNamespace(resources=resources)}
    new_url = f"{CARD_URL_PATH}?v=newhash"
    assert await async_register_lovelace_resource(hass, new_url) is True
    assert resources.created == []
    assert resources.updated and resources.updated[-1][0] == "res_1"
    assert resources.items[0]["url"] == new_url


@pytest.mark.asyncio
async def test_lovelace_missing_logs_and_skips() -> None:
    hass = MagicMock()
    hass.data = {}
    assert await async_register_lovelace_resource(hass, f"{CARD_URL_PATH}?v=x") is False


# --- 2) Source filtering ---


def test_passthrough_source_variants() -> None:
    assert is_passthrough_source("TV")
    assert is_passthrough_source("hdmi")
    assert is_passthrough_source("HDMI 1")
    assert is_passthrough_source("Optical")
    assert is_passthrough_source("eARC")
    assert is_passthrough_source("Line-in")
    assert not is_passthrough_source("Spotify")
    assert not is_passthrough_source(None)


def test_tv_placeholder_track() -> None:
    assert is_tv_placeholder_track("TV", None)
    assert is_tv_placeholder_track("tv", "")
    assert not is_tv_placeholder_track("TV", "Some Artist")
    assert not is_tv_placeholder_track("Real Song", None)


def test_select_ignores_tv_hdmi_and_placeholder() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.speaker_a",
            state="playing",
            source="TV",
            title="TV",
            artist=None,
        ),
        SourceSnapshot(
            entity_id="media_player.speaker_b",
            state="playing",
            source="Spotify",
            title="Song",
            artist="Artist",
        ),
    ]
    active = select_active_source(
        snaps,
        priority=["media_player.speaker_a", "media_player.speaker_b"],
        vinyl_entity_id=None,
    )
    assert active is not None
    assert active.entity_id == "media_player.speaker_b"


def test_select_ignores_title_tv_even_on_spotify_source() -> None:
    snaps = [
        SourceSnapshot(
            entity_id="media_player.speaker_a",
            state="playing",
            source="Spotify",
            title="TV",
            artist=None,
        ),
    ]
    assert (
        select_active_source(
            snaps, priority=["media_player.speaker_a"], vinyl_entity_id=None
        )
        is None
    )


# --- 3) Startup tracking ---


@pytest.mark.asyncio
async def test_tracking_starts_off_when_cast_off_after_restart(
    hass: HomeAssistant,
) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_track_boot")
    entry.add_to_hass(hass)
    # Previously ON tracking must not come back while Cast is off.
    mock_restore_cache(
        hass,
        [
            State("switch.spinjam_cast", STATE_OFF),
            State("switch.spinjam_tracking", STATE_ON),
        ],
    )

    with patch.object(
        SpinJamCoordinator,
        "_client",
        return_value=AsyncMock(fetch=AsyncMock(return_value=None)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    cast_state = hass.states.get("switch.spinjam_cast")
    assert cast_state is not None and cast_state.state == STATE_OFF
    # A restored tracking switch must not come back; Cast off keeps tracking off.
    assert hass.states.get("switch.spinjam_tracking") is None
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.tracking_enabled is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# --- 4) Non-blocking cast ---


@pytest.mark.asyncio
async def test_cast_start_returns_before_wake_completes(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_nonblock")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_wake(_hass, _entity_id, **_kwargs):
        started.set()
        await release.wait()
        return True

    with (
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            side_effect=_slow_wake,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_wait_for_lovelace_app",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        target = await coordinator.async_start()
        # Returned while wake still blocked.
        assert target == "media_player.example_tv"
        assert coordinator.cast_active is True
        assert started.is_set()
        assert coordinator._cast_start_task is not None  # noqa: SLF001
        release.set()
        await hass.async_block_till_done()

    assert coordinator.cast_active is True
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_cast_stop_cancels_in_flight_start(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cancel_start")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    release = asyncio.Event()

    async def _slow_wake(_hass, _entity_id, **_kwargs):
        await release.wait()
        return True

    with (
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            side_effect=_slow_wake,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_end_cast",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator.async_start()
        task = coordinator._cast_start_task  # noqa: SLF001
        assert task is not None
        await coordinator.async_stop()
        assert coordinator.cast_active is False
        # Cancellation is delivered when the event loop next runs the task.
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled() or task.done()
        release.set()
        await hass.async_block_till_done()

    await coordinator.async_shutdown()
