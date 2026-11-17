"""Live offsets (no reload), cast wake/verify, tracking linkage, resources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam.const import (
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_VIEW_PATH,
    DOMAIN,
    LOVELACE_APP_NAMES,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.frontend import (
    CARD_URL_PATH,
    async_register_lovelace_resource,
)
from custom_components.spinjam import _async_update_listener

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _entry(**overrides):
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.living_room"],
        CONF_DISPLAYS: ["media_player.example_tv"],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_LYRIC_OFFSET_MS: 0,
        CONF_RECAST_WHILE_PLAYING: False,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={
            k: data[k]
            for k in (
                CONF_LYRIC_OFFSET_MS,
                CONF_SYNC_OFFSET_MS,
                CONF_DASHBOARD_PATH,
                CONF_VIEW_PATH,
            )
            if k in data
        },
        title=data[CONF_NAME],
        unique_id=overrides.get("unique_id", f"{DOMAIN}_live"),
        version=2,
    )


def _cast_success_patches():
    return (
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            new_callable=AsyncMock,
            return_value=True,
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
    )


@pytest.mark.asyncio
async def test_lyric_offset_live_no_reload(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_offset_live")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][f"{entry.entry_id}_options"] = dict(entry.options)

    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    hass.data[DOMAIN][entry.entry_id] = coordinator

    reload = AsyncMock()
    with patch.object(hass.config_entries, "async_reload", reload):
        await coordinator.async_set_lyric_offset(1500)
        await _async_update_listener(hass, entry)

    assert coordinator.data.lyric_offset_ms == 1500
    assert entry.options[CONF_LYRIC_OFFSET_MS] == 1500
    reload.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_sync_offset_live_no_reload(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_sync_live")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][f"{entry.entry_id}_options"] = dict(entry.options)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    hass.data[DOMAIN][entry.entry_id] = coordinator

    reload = AsyncMock()
    with patch.object(hass.config_entries, "async_reload", reload):
        await coordinator.async_set_sync_offset(250)
        await _async_update_listener(hass, entry)

    assert coordinator.data.sync_offset_ms == 250
    assert entry.options[CONF_SYNC_OFFSET_MS] == 250
    reload.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_non_offset_options_still_reload(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_reload_other")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][f"{entry.entry_id}_options"] = dict(entry.options)

    reload = AsyncMock()
    with patch.object(hass.config_entries, "async_reload", reload):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_VIEW_PATH: "other"}
        )
        await _async_update_listener(hass, entry)
    reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_cast_failure_leaves_switch_off(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_cast_fail")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_wait_for_lovelace_app",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        await coordinator.async_start()
        await hass.async_block_till_done()

    assert coordinator.cast_active is False
    assert coordinator.tracking_enabled is True
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_cast_off_clears_tracking_and_idle(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {"media_title": "Song", "media_artist": "Artist", "media_position": 5},
    )
    entry = _entry(unique_id=f"{DOMAIN}_cast_off_clear")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    await coordinator.async_set_tracking(True)
    await coordinator.async_refresh()
    assert coordinator.data.active is not None

    wake, show, wait = _cast_success_patches()
    with (
        wake,
        show,
        wait,
        patch(
            "custom_components.spinjam.coordinator.async_end_cast",
            new_callable=AsyncMock,
            return_value=True,
        ) as end,
    ):
        await coordinator.async_start()
        await hass.async_block_till_done()
        assert coordinator.cast_active is True
        await coordinator.async_stop()

    end.assert_awaited()
    assert coordinator.cast_active is False
    assert coordinator.tracking_enabled is False
    assert coordinator.data.active is None
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_tracking_off_stops_cast(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_track_stops_cast")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    wake, show, wait = _cast_success_patches()
    with (
        wake,
        show,
        wait,
        patch(
            "custom_components.spinjam.coordinator.async_end_cast",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator.async_start()
        await hass.async_block_till_done()
        assert coordinator.cast_active is True
        await coordinator.async_set_tracking(False)

    assert coordinator.cast_active is False
    assert coordinator.tracking_enabled is False
    assert coordinator.data.active is None
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_display_watcher_ignores_off_during_grace(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_grace")
    entry.add_to_hass(hass)
    hass.states.async_set(
        "media_player.example_tv",
        "playing",
        {"app_name": next(iter(LOVELACE_APP_NAMES))},
    )
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = "media_player.example_tv"
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    wake, show, wait = _cast_success_patches()
    with wake, show, wait:
        await coordinator.async_start()
        await hass.async_block_till_done()
    assert coordinator.cast_active is True

    hass.states.async_set("media_player.example_tv", STATE_OFF, {})
    await hass.async_block_till_done()
    assert coordinator.cast_active is True  # grace window

    # After grace, unavailable ends the session.
    coordinator._cast_launch_until = datetime.now(timezone.utc) - timedelta(seconds=1)  # noqa: SLF001
    with patch(
        "custom_components.spinjam.coordinator.async_end_cast",
        new_callable=AsyncMock,
        return_value=True,
    ):
        hass.states.async_set("media_player.example_tv", STATE_UNAVAILABLE, {})
        await hass.async_block_till_done()
    assert coordinator.cast_active is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_display_watcher_ends_on_other_app(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_other_app")
    entry.add_to_hass(hass)
    hass.states.async_set(
        "media_player.example_tv",
        "playing",
        {"app_name": next(iter(LOVELACE_APP_NAMES))},
    )
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = "media_player.example_tv"
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    wake, show, wait = _cast_success_patches()
    with wake, show, wait:
        await coordinator.async_start()
        await hass.async_block_till_done()
    coordinator._cast_launch_until = datetime.now(timezone.utc) - timedelta(seconds=1)  # noqa: SLF001

    with patch(
        "custom_components.spinjam.coordinator.async_end_cast",
        new_callable=AsyncMock,
        return_value=True,
    ):
        hass.states.async_set(
            "media_player.example_tv", "playing", {"app_name": "YouTube"}
        )
        await hass.async_block_till_done()
    assert coordinator.cast_active is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_lovelace_resource_create_and_update() -> None:
    hass = MagicMock()
    created: list[dict] = []
    updated: list[tuple[str, dict]] = []

    class FakeResources:
        loaded = True

        def async_items(self):
            return list(created)

        async def async_create_item(self, data):
            item = {"id": f"id_{len(created)}", "type": "module", "url": data["url"]}
            created.append(item)
            return item

        async def async_update_item(self, item_id, data):
            updated.append((item_id, data))
            for item in created:
                if item["id"] == item_id:
                    item["url"] = data["url"]
                    return item
            raise KeyError(item_id)

    hass.data = {"lovelace": {"resources": FakeResources()}}
    url1 = f"{CARD_URL_PATH}?v=aaa"
    url2 = f"{CARD_URL_PATH}?v=bbb"
    assert await async_register_lovelace_resource(hass, url1) is True
    assert len(created) == 1
    assert await async_register_lovelace_resource(hass, url2) is True
    assert len(created) == 1
    assert updated and updated[-1][1]["url"] == url2


@pytest.mark.asyncio
async def test_lovelace_yaml_mode_skips() -> None:
    hass = MagicMock()

    class YamlResources:
        def async_items(self):
            return []

    hass.data = {"lovelace": {"resources": YamlResources()}}
    assert await async_register_lovelace_resource(hass, f"{CARD_URL_PATH}?v=x") is False


@pytest.mark.asyncio
async def test_media_player_skips_unchanged_writes(hass: HomeAssistant) -> None:
    from custom_components.spinjam.media_player import SpinJamMediaPlayer

    hass.states.async_set(
        "media_player.living_room",
        "playing",
        {"media_title": "TV Audio", "media_artist": "Cable"},  # no media_position
    )
    entry = _entry(unique_id=f"{DOMAIN}_throttle", **{CONF_DISPLAYS: []})
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    await coordinator.async_set_tracking(True)
    await coordinator.async_refresh()
    player = SpinJamMediaPlayer(coordinator, entry)
    player.hass = hass
    player.async_write_ha_state = MagicMock()  # type: ignore[method-assign]

    player._handle_coordinator_update()  # noqa: SLF001
    assert player.async_write_ha_state.call_count == 1

    # Second update with same fingerprint (no media_position clock bump) → skip.
    await coordinator.async_refresh()
    player._handle_coordinator_update()  # noqa: SLF001
    assert player.async_write_ha_state.call_count == 1
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_cast_wake_called_on_start(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_wake")
    entry.add_to_hass(hass)
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = coordinator.displays[0]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            new_callable=AsyncMock,
            return_value=True,
        ) as wake,
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
        await coordinator.async_start()
        await hass.async_block_till_done()

    wake.assert_awaited_once()
    assert coordinator.cast_active is True
    assert coordinator.tracking_enabled is True
    await coordinator.async_shutdown()
