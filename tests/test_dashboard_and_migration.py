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
    CAST_CARD,
    DETAILS_CARD,
    LYRICS_CARD,
    async_create_spinjam_dashboard,
    upgrade_cast_view,
    upgrade_controls_cards,
    upgrade_dashboard_config,
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


def _generated_pair() -> list[dict]:
    return [dict(DETAILS_CARD), dict(LYRICS_CARD)]


def test_tv_view_is_one_fullscreen_cast_card() -> None:
    view = spinjam_tv_view_config("now")
    assert view["type"] == "panel"
    assert view["panel"] is True
    assert view["path"] == "now"
    assert len(view["cards"]) == 1
    card = view["cards"][0]
    assert card["type"] == "custom:spinjam-lyrics-card"
    assert card["mode"] == "cast"
    assert card == CAST_CARD
    assert card["offset_entity"] == DETAILS_CARD["offset_entity"] == LYRICS_CARD["offset_entity"]


def test_cast_view_migration_replaces_two_card_stack(caplog: pytest.LogCaptureFixture) -> None:
    original = {
        "views": [
            {
                "title": "Now",
                "path": "now",
                "type": "panel",
                "cards": [
                    {"type": "horizontal-stack", "cards": _generated_pair()},
                ],
            }
        ]
    }
    with caplog.at_level("INFO"):
        once = upgrade_dashboard_config(original)
        twice = upgrade_dashboard_config(once)
    view = once["views"][0]
    assert view["type"] == "panel"
    assert view["panel"] is True
    assert view["cards"] == [CAST_CARD]
    assert "sections" not in view
    assert twice["views"][0] == view
    assert sum("full-screen card" in rec.message for rec in caplog.records) == 1


def test_cast_view_migration_keeps_user_cards(caplog: pytest.LogCaptureFixture) -> None:
    user = {"type": "markdown", "content": "A note on the cast view"}
    view = {
        "title": "Now",
        "path": "now",
        "type": "panel",
        "cards": [
            {"type": "horizontal-stack", "cards": _generated_pair()},
            user,
        ],
    }
    with caplog.at_level("INFO"):
        migrated, notes = upgrade_cast_view(view)
        again, notes_again = upgrade_cast_view(migrated)
    assert migrated["cards"][0] == CAST_CARD
    assert migrated["cards"][1] == user
    assert again["cards"] == migrated["cards"]
    assert notes_again == []
    assert notes
    assert any("left other cards alone" in note or "full-screen card" in note for note in notes)
    assert any("full-screen card" in rec.message for rec in caplog.records) or notes


def test_cast_view_migration_sections_become_a_panel() -> None:
    view = {
        "title": "Now",
        "path": "now",
        "icon": "mdi:album",
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": _generated_pair()},
        ],
    }
    migrated, notes = upgrade_cast_view(view)
    again, notes_again = upgrade_cast_view(migrated)
    assert migrated["type"] == "panel"
    assert migrated["panel"] is True
    assert migrated["icon"] == "mdi:album"
    assert "sections" not in migrated
    assert migrated["cards"] == [CAST_CARD]
    assert notes_again == []
    assert again == migrated
    assert notes


def test_cast_view_migration_ignores_unrelated_views() -> None:
    weather = {
        "title": "Weather",
        "path": "weather",
        "type": "masonry",
        "cards": [{"type": "weather-forecast", "entity": "weather.home"}],
    }
    migrated, notes = upgrade_cast_view(weather)
    assert notes == []
    assert migrated["cards"] == weather["cards"]
    assert migrated["title"] == "Weather"


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


def _entities(node) -> list[str]:
    found: list[str] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_entities(item))
        return found
    if isinstance(node, dict):
        entity = node.get("entity")
        if isinstance(entity, str):
            found.append(entity)
        for key in ("cards", "sections", "entities"):
            if isinstance(node.get(key), list):
                found.extend(_entities(node[key]))
    return found


def test_upgrade_controls_sections_is_idempotent() -> None:
    view = {
        "title": "Controls",
        "path": "controls",
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "tile",
                        "entity": "switch.spinjam_cast",
                        "name": "Cast",
                    },
                    {
                        "type": "horizontal-stack",
                        "cards": [
                            {
                                "type": "custom:button-card",
                                "entity": "button.spinjam_lyrics_earlier",
                                "name": "Earlier",
                            },
                            {
                                "type": "button",
                                "entity": "button.spinjam_lyrics_later",
                                "name": "Later",
                            },
                            {
                                "type": "tile",
                                "entity": "number.spinjam_lyric_offset",
                                "name": "Delay",
                            },
                        ],
                    },
                    {"type": "markdown", "content": "user note"},
                ],
            }
        ],
    }
    once = upgrade_dashboard_config({"views": [view]})
    twice = upgrade_dashboard_config(once)
    controls = once["views"][0]
    assert "cards" not in controls or not controls.get("cards")
    entities = _entities(controls)
    assert entities.count("switch.spinjam_cast") == 1
    assert entities.count("select.spinjam_display") == 1
    assert entities.count("select.spinjam_source") == 1
    assert entities.count("switch.spinjam_lyrics") == 1
    assert entities.count("button.spinjam_lyrics_earlier") == 1
    assert entities.count("number.spinjam_lyric_offset") == 1
    assert twice["views"][0] == controls
    section_cards = controls["sections"][0]["cards"]
    assert any(card.get("content") == "user note" for card in section_cards)
    assert not any(
        card.get("type") == "horizontal-stack"
        and card.get("cards")
        and card["cards"][0].get("entity") == "button.spinjam_lyrics_earlier"
        and len(card.get("cards") or []) == 3
        and card["cards"][1].get("entity") == "sensor.spinjam_lyric_delay"
        for card in section_cards
    )


class _LovelaceData:
    """Stand-in for HA's LovelaceData (not a dict)."""

    def __init__(self, dashboards: dict, collection: object | None = None) -> None:
        self.dashboards = dashboards
        self.dashboards_collection = collection
        self.resources = None


@pytest.mark.asyncio
async def test_upgrade_reads_lovelace_data_object(hass: HomeAssistant) -> None:
    from custom_components.spinjam.dashboard import async_upgrade_configured_dashboard

    class _Store:
        def __init__(self) -> None:
            self.config = {
                "views": [
                    {
                        "title": "Controls",
                        "path": "controls",
                        "cards": [
                            {"type": "tile", "entity": "switch.spinjam_cast", "name": "Cast"},
                        ],
                    }
                ]
            }

        async def async_load(self, force: bool = False) -> dict:
            _ = force
            return self.config

        async def async_save(self, config: dict) -> None:
            self.config = config

    store = _Store()
    hass.data["lovelace"] = _LovelaceData({"spinjam-tv": store}, object())
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_DASHBOARD_PATH: "spinjam-tv",
        },
        unique_id=f"{DOMAIN}_lovelace_data",
    )
    assert await async_upgrade_configured_dashboard(hass, entry) is True
    entities = [card.get("entity") for card in store.config["views"][0]["cards"]]
    assert "select.spinjam_display" in entities
    assert "select.spinjam_source" in entities
    again = [dict(card) for card in store.config["views"][0]["cards"]]
    assert await async_upgrade_configured_dashboard(hass, entry) is True
    assert store.config["views"][0]["cards"] == again


@pytest.mark.asyncio
async def test_upgrade_logs_when_lovelace_dashboards_missing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    from custom_components.spinjam.dashboard import async_upgrade_configured_dashboard

    hass.data["lovelace"] = object()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "SpinJam",
            CONF_SOURCE_PLAYERS: ["media_player.living_room"],
            CONF_DASHBOARD_PATH: "spinjam-tv",
        },
        unique_id=f"{DOMAIN}_lovelace_skip",
    )
    with caplog.at_level("INFO"):
        assert await async_upgrade_configured_dashboard(hass, entry) is False
    assert any(
        "dashboard upgrade skipped" in rec.message.lower()
        and rec.levelname == "INFO"
        for rec in caplog.records
    )
