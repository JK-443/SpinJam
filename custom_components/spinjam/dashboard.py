"""Lovelace dashboard helpers for SpinJam TV Cast."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_VIEW_PATH,
    DOMAIN,
    BUTTON_LYRIC_DELAY_RESET_ENTITY_ID,
    BUTTON_LYRICS_EARLIER_ENTITY_ID,
    BUTTON_LYRICS_LATER_ENTITY_ID,
    NUMBER_LYRIC_OFFSET_ENTITY_ID,
    SELECT_DISPLAY_ENTITY_ID,
    SELECT_SOURCE_ENTITY_ID,
    SENSOR_LYRIC_DELAY_ENTITY_ID,
    SWITCH_CAST_ENTITY_ID,
    SWITCH_LYRICS_ENTITY_ID,
    SWITCH_TRACKING_ENTITY_ID,
)

_LOGGER = logging.getLogger(__name__)

# HA Lovelace url_path: slug with at least one hyphen (Settings → Dashboards).
_URL_PATH_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")

DETAILS_CARD = {
    "type": "custom:spinjam-lyrics-card",
    "entity": "media_player.spinjam_now_playing",
    "mode": "details",
    "offset_entity": NUMBER_LYRIC_OFFSET_ENTITY_ID,
}

LYRICS_CARD = {
    "type": "custom:spinjam-lyrics-card",
    "entity": "media_player.spinjam_now_playing",
    "mode": "lyrics",
    "offset_entity": NUMBER_LYRIC_OFFSET_ENTITY_ID,
}

def _tile(entity: str, name: str, icon: str) -> dict[str, Any]:
    return {"type": "tile", "entity": entity, "name": name, "icon": icon}


# New dashboards: Cast, Display, Source, Lyrics, then the offset helper.
CONTROLS_TILES = [
    _tile(SWITCH_CAST_ENTITY_ID, "Cast", "mdi:cast"),
    _tile(SELECT_DISPLAY_ENTITY_ID, "Display", "mdi:television"),
    _tile(SELECT_SOURCE_ENTITY_ID, "Source", "mdi:speaker-multiple"),
    _tile(SWITCH_LYRICS_ENTITY_ID, "Lyrics", "mdi:microphone-variant"),
    _tile(NUMBER_LYRIC_OFFSET_ENTITY_ID, "Lyric delay", "mdi:timer-outline"),
    _tile(BUTTON_LYRIC_DELAY_RESET_ENTITY_ID, "Reset lyric delay", "mdi:restore"),
]


def lyric_delay_row() -> dict[str, Any]:
    """Earlier / signed delay / later, for the Controls view."""
    return {
        "type": "horizontal-stack",
        "cards": [
            {
                "type": "button",
                "entity": BUTTON_LYRICS_EARLIER_ENTITY_ID,
                "name": "Lyrics earlier",
                "icon": "mdi:chevron-double-up",
                "show_name": True,
                "show_icon": True,
            },
            {
                "type": "tile",
                "entity": SENSOR_LYRIC_DELAY_ENTITY_ID,
                "name": "Lyric delay",
                "icon": "mdi:timer-outline",
            },
            {
                "type": "button",
                "entity": BUTTON_LYRICS_LATER_ENTITY_ID,
                "name": "Lyrics later",
                "icon": "mdi:chevron-double-down",
                "show_name": True,
                "show_icon": True,
            },
        ],
    }


def _has_lyric_delay_row(cards: list[Any]) -> bool:
    for card in cards:
        if not isinstance(card, dict) or card.get("type") != "horizontal-stack":
            continue
        entities = {
            child.get("entity")
            for child in (card.get("cards") or [])
            if isinstance(child, dict)
        }
        if (
            BUTTON_LYRICS_EARLIER_ENTITY_ID in entities
            and BUTTON_LYRICS_LATER_ENTITY_ID in entities
        ):
            return True
    return False

# Added when missing on an existing dashboard. Lyric offset is kept if the
# user already has it and is not put back after they remove it.
REQUIRED_CONTROL_TILES = CONTROLS_TILES[:4]

MANAGED_CONTROL_ENTITIES = frozenset(
    {
        SWITCH_CAST_ENTITY_ID,
        SELECT_DISPLAY_ENTITY_ID,
        SELECT_SOURCE_ENTITY_ID,
        SWITCH_LYRICS_ENTITY_ID,
        NUMBER_LYRIC_OFFSET_ENTITY_ID,
        SWITCH_TRACKING_ENTITY_ID,
    }
)


def validate_dashboard_url_path(value: Any) -> str:
    """Validate a Lovelace dashboard url_path (must contain a hyphen)."""
    if value is None:
        raise vol.Invalid("Dashboard path is required")
    path = str(value).strip()
    if "-" not in path:
        raise vol.Invalid(
            "Dashboard path must contain a hyphen (e.g. spinjam-tv). "
            "Home Assistant rejects single-word dashboard URLs."
        )
    if not _URL_PATH_RE.match(path):
        raise vol.Invalid(
            "Dashboard path must be a lowercase slug with hyphens "
            f"(e.g. {DEFAULT_DASHBOARD_PATH})"
        )
    return path


def dashboard_exists(hass: HomeAssistant, url_path: str) -> bool:
    """Return True if a Lovelace dashboard is registered for url_path."""
    lovelace = hass.data.get("lovelace")
    if not isinstance(lovelace, dict):
        return False
    dashboards = lovelace.get("dashboards") or {}
    return url_path in dashboards


def spinjam_tv_view_config(view_path: str) -> dict[str, Any]:
    """Panel view: details (left) + lyrics (right) via horizontal-stack."""
    return {
        "title": "Now",
        "path": view_path,
        "type": "panel",
        "cards": [
            {
                "type": "horizontal-stack",
                "cards": [dict(DETAILS_CARD), dict(LYRICS_CARD)],
            }
        ],
    }


def spinjam_controls_view_config() -> dict[str, Any]:
    """Masonry view of SpinJam control tiles (Cast, Display, Source, Lyrics)."""
    return {
        "title": "Controls",
        "path": "controls",
        "type": "masonry",
        "cards": [dict(tile) for tile in CONTROLS_TILES] + [lyric_delay_row()],
    }


def _card_entity(card: Any) -> str | None:
    if isinstance(card, dict):
        entity = card.get("entity")
        if isinstance(entity, str):
            return entity
    return None


def _without_tracking(card: dict[str, Any]) -> dict[str, Any] | None:
    """Drop a tracking-only card, or strip that entity from an entities list."""
    entity = card.get("entity")
    entities = card.get("entities")
    if entity == SWITCH_TRACKING_ENTITY_ID and not entities and "cards" not in card:
        return None
    if isinstance(entities, list):
        kept: list[Any] = []
        removed = False
        for item in entities:
            if item == SWITCH_TRACKING_ENTITY_ID:
                removed = True
                continue
            if isinstance(item, dict) and item.get("entity") == SWITCH_TRACKING_ENTITY_ID:
                removed = True
                continue
            kept.append(item)
        if removed:
            if not kept:
                return None
            return {**card, "entities": kept}
    return card


def upgrade_controls_cards(cards: list[Any]) -> list[Any]:
    """Remove the tracking tile, append missing SpinJam tiles, drop duplicates.

    Cards the user added (anything that is not a SpinJam control entity) are
    left in place, including their position relative to tiles that stay.
    """
    result: list[Any] = []
    seen: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            result.append(card)
            continue
        stripped = _without_tracking(card)
        if stripped is None:
            continue
        entity = _card_entity(stripped)
        if entity in MANAGED_CONTROL_ENTITIES:
            if entity in seen:
                continue
            seen.add(entity)
        result.append(stripped)
    for tile in REQUIRED_CONTROL_TILES:
        if tile["entity"] not in seen:
            result.append(dict(tile))
            seen.add(tile["entity"])
    if not _has_lyric_delay_row(result):
        result.append(lyric_delay_row())
    return result


def _controls_view_index(views: list[Any]) -> int | None:
    for index, view in enumerate(views):
        if isinstance(view, dict) and view.get("path") == "controls":
            return index
    for index, view in enumerate(views):
        if isinstance(view, dict) and str(view.get("title") or "").lower() == "controls":
            return index
    return None


def upgrade_dashboard_config(config: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the Controls view in place. Other views are not rewritten."""
    raw_views = config.get("views")
    views = list(raw_views) if isinstance(raw_views, list) else []
    index = _controls_view_index(views)
    if index is None:
        views.append(spinjam_controls_view_config())
    else:
        view = dict(views[index])
        existing = view.get("cards")
        view["cards"] = upgrade_controls_cards(list(existing) if isinstance(existing, list) else [])
        views[index] = view
    updated = dict(config)
    updated["views"] = views
    return updated


async def _async_load_dashboard_config(store: Any) -> dict[str, Any] | None:
    loader = getattr(store, "async_load", None)
    loaded: Any = None
    if loader is not None:
        try:
            loaded = await loader(False)
        except TypeError:
            loaded = await loader()
    if not isinstance(loaded, dict):
        for attr in ("config", "data"):
            value = getattr(store, attr, None)
            if isinstance(value, dict):
                loaded = value
                break
    if isinstance(loaded, dict):
        return loaded
    return None


def _fresh_dashboard_config(view_path: str) -> dict[str, Any]:
    return {
        "views": [spinjam_tv_view_config(view_path), spinjam_controls_view_config()],
    }


async def async_create_spinjam_dashboard(
    hass: HomeAssistant,
    *,
    dashboard_path: str | None = None,
    view_path: str | None = None,
    title: str = "SpinJam",
) -> dict[str, Any]:
    """Create a storage-mode SpinJam dashboard, or upgrade one that already exists.

    A new dashboard is a panel (details left, lyrics right) plus Controls.
    An existing dashboard keeps user cards and the Now view. The Controls view
    gains any missing Cast / Display / Source / Lyrics tiles and loses the
    retired tracking tile. Safe to call repeatedly.
    """
    path = validate_dashboard_url_path(dashboard_path or DEFAULT_DASHBOARD_PATH)
    view = (view_path or DEFAULT_VIEW_PATH).strip() or DEFAULT_VIEW_PATH

    lovelace = hass.data.get("lovelace")
    if not isinstance(lovelace, dict) or "dashboards_collection" not in lovelace:
        raise HomeAssistantError(
            "Lovelace is not available — enable the Lovelace/default dashboard system first"
        )

    collection = lovelace["dashboards_collection"]
    created = False
    if not dashboard_exists(hass, path):
        try:
            await collection.async_create_item(
                {
                    "url_path": path,
                    "title": title,
                    "icon": "mdi:album",
                    "show_in_sidebar": True,
                    "require_admin": False,
                }
            )
            created = True
            _LOGGER.info("Created Lovelace dashboard %s", path)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not create dashboard {path}: {err}") from err

    store = lovelace["dashboards"].get(path)
    if store is None:
        raise HomeAssistantError(f"Dashboard {path} was not registered after create")

    if created:
        config = _fresh_dashboard_config(view)
    else:
        loaded = await _async_load_dashboard_config(store)
        if not loaded or not loaded.get("views"):
            config = _fresh_dashboard_config(view)
        else:
            config = upgrade_dashboard_config(loaded)
    try:
        await store.async_save(config)
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"Could not save dashboard config for {path}: {err}") from err

    return {
        "dashboard_path": path,
        "view_path": view,
        "created": created,
        "domain": DOMAIN,
    }


async def async_upgrade_configured_dashboard(hass: HomeAssistant, entry: Any) -> bool:
    """Upgrade an existing SpinJam dashboard. Does not create one.

    Called on setup and safe to repeat. Failures are logged and ignored so
    integration setup still succeeds when Lovelace is unavailable.
    """
    from .const import CONF_DASHBOARD_PATH

    options = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
    raw_path = options.get(CONF_DASHBOARD_PATH) or DEFAULT_DASHBOARD_PATH
    try:
        path = validate_dashboard_url_path(raw_path)
    except vol.Invalid:
        return False
    if not dashboard_exists(hass, path):
        return False
    lovelace = hass.data.get("lovelace")
    if not isinstance(lovelace, dict):
        return False
    store = (lovelace.get("dashboards") or {}).get(path)
    if store is None:
        return False
    loaded = await _async_load_dashboard_config(store)
    if not loaded or not loaded.get("views"):
        return False
    config = upgrade_dashboard_config(loaded)
    await store.async_save(config)
    return True
