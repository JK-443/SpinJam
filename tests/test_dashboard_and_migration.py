"""Tests for dashboard path validation, migration, and non-cast display skip."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.spinjam.const import (
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    DEFAULT_DASHBOARD_PATH,
    DOMAIN,
    LEGACY_DASHBOARD_PATH,
)
from custom_components.spinjam.dashboard import (
    DETAILS_CARD,
    LYRICS_CARD,
    async_create_spinjam_dashboard,
    upgrade_controls_cards,
    spinjam_tv_view_config,
    validate_dashboard_url_path,
)
from custom_components.spinjam import async_migrate_entry
from custom_components.spinjam.coordinator import SpinJamCoordinator

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_dashboard_path_requires_hyphen() -> None:
    assert validate_dashboard_url_path("spinjam-tv") == "spinjam-tv"
    assert validate_dashboard_url_path("my-cast-view") == "my-cast-view"
    with pytest.raises(vol.Invalid):
        validate_dashboard_url_path("spinjam")
    with pytest.raises(vol.Invalid):
        validate_dashboard_url_path("SpinJam-TV")
    with pytest.raises(vol.Invalid):
        validate_dashboard_url_path("bad_path")


def test_upgrade_controls_cards_is_idempotent() -> None:
    user = {"type": "markdown", "content": "A note added on the controls view"}
    cards = [
        {"type": "tile", "entity": "switch.spinjam_cast", "name": "My cast"},
        {"type": "tile", "entity": "switch.spinjam_tracking", "name": "Tracking"},
        {"type": "tile", "entity": "switch.spinjam_lyrics", "name": "Lyrics"},
        {"type": "tile", "entity": "switch.spinjam_lyrics", "name": "Lyrics again"},
        user,
        {
            "type": "entities",
            "entities": ["switch.spinjam_tracking", "light.example_lamp"],
        },
    ]
    once = upgrade_controls_cards(cards)
    twice = upgrade_controls_cards(once)
    assert twice == once
    entities = [card.get("entity") for card in once]
    assert "switch.spinjam_tracking" not in entities
    assert entities.count("switch.spinjam_lyrics") == 1
    assert "select.spinjam_display" in entities
    assert "select.spinjam_source" in entities
    assert once[0]["name"] == "My cast"
    assert user in once
    nested = next(card for card in once if card.get("type") == "entities")
    assert nested["entities"] == ["light.example_lamp"]
    assert "switch.spinjam_cast" not in [
        item for item in nested["entities"]
    ]


@pytest.mark.asyncio
async def test_create_dashboard_upgrades_in_place_twice(hass: HomeAssistant) -> None:
    class _Store:
        def __init__(self) -> None:
            self.config = {
                "views": [
                    {
                        "title": "Now",
                        "path": "now",
                        "cards": [{"type": "markdown", "content": "keep the now view"}],
                    },
                    {
                        "title": "Controls",
                        "path": "controls",
                        "cards": [
                            {
                                "type": "tile",
                                "entity": "switch.spinjam_tracking",
                                "name": "Tracking",
                            },
                            {
                                "type": "tile",
                                "entity": "switch.spinjam_cast",
                                "name": "My cast",
                            },
                            {"type": "markdown", "content": "user note"},
                        ],
                    },
                ]
            }

        async def async_load(self, force: bool = False) -> dict:
            _ = force
            return self.config

        async def async_save(self, config: dict) -> None:
            self.config = config

    store = _Store()
    hass.data["lovelace"] = {
        "dashboards": {"spinjam-tv": store},
        "dashboards_collection": AsyncMock(),
    }
    first = await async_create_spinjam_dashboard(hass, dashboard_path="spinjam-tv")
    assert first["created"] is False
    controls = next(view for view in store.config["views"] if view["path"] == "controls")
    entities = [card.get("entity") for card in controls["cards"]]
    assert "switch.spinjam_tracking" not in entities
    assert entities.count("switch.spinjam_cast") == 1
    assert controls["cards"][0]["name"] == "My cast"
    assert any(card.get("content") == "user note" for card in controls["cards"])
    now = next(view for view in store.config["views"] if view["path"] == "now")
    assert now["cards"][0]["content"] == "keep the now view"
    snapshot = [dict(card) for card in controls["cards"]]

    second = await async_create_spinjam_dashboard(hass, dashboard_path="spinjam-tv")
    assert second["created"] is False
    controls_again = next(
        view for view in store.config["views"] if view["path"] == "controls"
    )
    assert controls_again["cards"] == snapshot


def test_tv_view_layout_details_left_lyrics_right() -> None:
    view = spinjam_tv_view_config("now")
    assert view["type"] == "panel"
    assert view["path"] == "now"
    stack = view["cards"][0]
    assert stack["type"] == "horizontal-stack"
    left, right = stack["cards"]
    assert left["type"] == "custom:spinjam-lyrics-card"
    assert left["mode"] == "details"
    assert right["mode"] == "lyrics"
    assert left["offset_entity"] == "number.spinjam_lyric_offset"
    assert right["offset_entity"] == DETAILS_CARD["offset_entity"] == LYRICS_CARD["offset_entity"]


@pytest.mark.asyncio
async def test_migrate_v2_negates_lyric_offset_and_dashboard(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_LYRICS_ENABLED: True,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_LYRIC_OFFSET_MS: -1500,
            CONF_DASHBOARD_PATH: LEGACY_DASHBOARD_PATH,
        },
        options={CONF_LYRIC_OFFSET_MS: -1500, CONF_DASHBOARD_PATH: LEGACY_DASHBOARD_PATH},
        version=1,
        unique_id=f"{DOMAIN}_migrate",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.spinjam.dashboard.dashboard_exists",
        return_value=False,
    ):
        assert await async_migrate_entry(hass, entry) is True

    assert entry.version == 3
    assert entry.data[CONF_LYRIC_OFFSET_MS] == 1500
    assert entry.options[CONF_LYRIC_OFFSET_MS] == 1500
    assert entry.data[CONF_DASHBOARD_PATH] == DEFAULT_DASHBOARD_PATH
    assert entry.options[CONF_DASHBOARD_PATH] == DEFAULT_DASHBOARD_PATH


@pytest.mark.asyncio
async def test_migrate_keeps_legacy_dashboard_if_exists(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_LYRIC_OFFSET_MS: 0,
            CONF_DASHBOARD_PATH: LEGACY_DASHBOARD_PATH,
        },
        options={},
        version=1,
        unique_id=f"{DOMAIN}_migrate_keep",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.spinjam.dashboard.dashboard_exists",
        return_value=True,
    ):
        assert await async_migrate_entry(hass, entry) is True

    assert entry.data[CONF_DASHBOARD_PATH] == LEGACY_DASHBOARD_PATH


@pytest.mark.asyncio
async def test_start_skips_non_cast_display(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_DISPLAYS: ["media_player.example_tv"],
            CONF_LYRICS_ENABLED: False,
            CONF_SYNC_OFFSET_MS: 0,
            CONF_DASHBOARD_PATH: DEFAULT_DASHBOARD_PATH,
        },
        unique_id=f"{DOMAIN}_non_cast",
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player",
        "sonos",
        "example_tv_unique",
        suggested_object_id="example_tv",
    )

    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.selected_display = "media_player.example_tv"
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
    ) as show:
        await coordinator.async_start("media_player.example_tv")
        await hass.async_block_till_done()

    show.assert_not_awaited()
    assert coordinator.cast_active is True
    await coordinator.async_shutdown()
    await hass.async_stop()
