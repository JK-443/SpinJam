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
from .frontend import lovelace_value

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

# One card owns lyrics-on (split) and lyrics-off (full-bleed stage).
CAST_CARD = {
    "type": "custom:spinjam-lyrics-card",
    "entity": "media_player.spinjam_now_playing",
    "mode": "cast",
    "offset_entity": NUMBER_LYRIC_OFFSET_ENTITY_ID,
}

SPINJAM_TV_CARD_TYPES = frozenset(
    {
        "custom:spinjam-lyrics-card",
        "custom:spinjam-now-playing-card",
    }
)

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


# A tile, button, or button-card for any of these already is the lyric-delay
# control, including when it sits inside a section or a stack.
_LYRIC_DELAY_ENTITIES = frozenset(
    {
        NUMBER_LYRIC_OFFSET_ENTITY_ID,
        BUTTON_LYRICS_EARLIER_ENTITY_ID,
        BUTTON_LYRICS_LATER_ENTITY_ID,
        BUTTON_LYRIC_DELAY_RESET_ENTITY_ID,
        SENSOR_LYRIC_DELAY_ENTITY_ID,
    }
)

_NESTED_CARD_KEYS = ("cards", "sections")

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


def _lovelace_dashboards(hass: HomeAssistant) -> Any:
    """Dashboards mapping from ``LovelaceData`` or a legacy dict."""
    return lovelace_value(hass, "dashboards")


def _dashboard_store(dashboards: Any, url_path: str) -> Any:
    if dashboards is None:
        return None
    getter = getattr(dashboards, "get", None)
    if callable(getter):
        return getter(url_path)
    try:
        return dashboards[url_path]
    except (KeyError, TypeError, IndexError):
        return None


def dashboard_exists(hass: HomeAssistant, url_path: str) -> bool:
    """Return True if a Lovelace dashboard is registered for url_path."""
    dashboards = _lovelace_dashboards(hass)
    if dashboards is None:
        return False
    try:
        return url_path in dashboards
    except TypeError:
        return False


def spinjam_tv_view_config(view_path: str) -> dict[str, Any]:
    """Full-screen panel: one card for the split lyrics layout and the stage."""
    return {
        "title": "Now",
        "path": view_path,
        "type": "panel",
        "panel": True,
        "cards": [dict(CAST_CARD)],
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


def _collect_entities(node: Any, found: set[str] | None = None) -> set[str]:
    """Entity ids on this card and inside stacks, grids, and sections."""
    found = found if found is not None else set()
    if isinstance(node, list):
        for item in node:
            _collect_entities(item, found)
        return found
    if not isinstance(node, dict):
        return found
    entity = node.get("entity")
    if isinstance(entity, str):
        found.add(entity)
    entities = node.get("entities")
    if isinstance(entities, list):
        for item in entities:
            if isinstance(item, str):
                found.add(item)
            else:
                _collect_entities(item, found)
    for key in _NESTED_CARD_KEYS:
        if isinstance(node.get(key), list):
            _collect_entities(node[key], found)
    return found


def _upgrade_card_list(cards: list[Any], seen_managed: set[str]) -> list[Any]:
    """Strip tracking and duplicate managed tiles, walking nested cards."""
    result: list[Any] = []
    for card in cards:
        if not isinstance(card, dict):
            result.append(card)
            continue
        stripped = _without_tracking(card)
        if stripped is None:
            continue
        if any(isinstance(stripped.get(key), list) for key in _NESTED_CARD_KEYS):
            stripped = dict(stripped)
            for key in _NESTED_CARD_KEYS:
                nested = stripped.get(key)
                if isinstance(nested, list):
                    stripped[key] = _upgrade_card_list(nested, seen_managed)
        entity = _card_entity(stripped)
        if entity in MANAGED_CONTROL_ENTITIES:
            if entity in seen_managed:
                continue
            seen_managed.add(entity)
        result.append(stripped)
    return result


def _append_target(view: dict[str, Any]) -> list[Any]:
    """Where new control tiles go: the card list, or the first section."""
    cards = view.get("cards")
    sections = view.get("sections")
    if isinstance(sections, list) and sections and not cards:
        for section in sections:
            if not isinstance(section, dict):
                continue
            if not isinstance(section.get("cards"), list):
                section["cards"] = []
            return section["cards"]
    if not isinstance(cards, list):
        view["cards"] = []
    return view["cards"]


def upgrade_controls_view(view: dict[str, Any]) -> dict[str, Any]:
    """Upgrade one Controls view, including sections and nested stacks.

    Cast, Display, Source, and Lyrics match by entity, so a tile already
    sitting in a section or a stack is not added again. An existing tile,
    button, or button-card for the lyric delay number or the delay buttons
    counts as the delay row.
    """
    view = dict(view)
    seen_managed: set[str] = set()
    if isinstance(view.get("cards"), list):
        view["cards"] = _upgrade_card_list(view["cards"], seen_managed)
    if isinstance(view.get("sections"), list):
        sections: list[Any] = []
        for section in view["sections"]:
            if not isinstance(section, dict):
                sections.append(section)
                continue
            section = dict(section)
            if isinstance(section.get("cards"), list):
                section["cards"] = _upgrade_card_list(section["cards"], seen_managed)
            sections.append(section)
        view["sections"] = sections
    present = _collect_entities(view)
    seen_managed.update(present & MANAGED_CONTROL_ENTITIES)
    dest = _append_target(view)
    for tile in REQUIRED_CONTROL_TILES:
        if tile["entity"] not in seen_managed:
            dest.append(dict(tile))
            seen_managed.add(tile["entity"])
    if not (present & _LYRIC_DELAY_ENTITIES):
        dest.append(lyric_delay_row())
    return view


def upgrade_controls_cards(cards: list[Any]) -> list[Any]:
    """Remove the tracking tile, append missing SpinJam tiles, drop duplicates.

    Cards the user added (anything that is not a SpinJam control entity) are
    left in place, including their position relative to tiles that stay.
    Nested stacks and grids are walked the same way as a sections view.
    """
    return list(upgrade_controls_view({"cards": list(cards)}).get("cards") or [])


def _controls_view_index(views: list[Any]) -> int | None:
    for index, view in enumerate(views):
        if isinstance(view, dict) and view.get("path") == "controls":
            return index
    for index, view in enumerate(views):
        if isinstance(view, dict) and str(view.get("title") or "").lower() == "controls":
            return index
    return None


def _is_spinjam_tv_card(card: Any) -> bool:
    return isinstance(card, dict) and card.get("type") in SPINJAM_TV_CARD_TYPES


def _is_cast_card(card: Any) -> bool:
    return (
        isinstance(card, dict)
        and card.get("type") == "custom:spinjam-lyrics-card"
        and card.get("mode") == "cast"
    )


def _is_generated_pair(cards: Any) -> bool:
    """The old left/right Cast row: exactly two SpinJam TV cards."""
    if not isinstance(cards, list) or len(cards) != 2:
        return False
    return all(_is_spinjam_tv_card(card) for card in cards)


def _leaf_cards(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_leaf_cards(item))
        return found
    if not isinstance(node, dict):
        return found
    nested = False
    for key in ("cards", "sections"):
        if isinstance(node.get(key), list):
            nested = True
            found.extend(_leaf_cards(node[key]))
    if not nested and node.get("type"):
        found.append(node)
    return found


def _replace_pair_containers(node: Any, notes: list[str]) -> Any:
    """Replace a stack/grid that is only the old two-card row. Leave other cards."""
    if isinstance(node, list):
        return [_replace_pair_containers(item, notes) for item in node]
    if not isinstance(node, dict):
        return node
    cards = node.get("cards")
    if isinstance(cards, list) and _is_generated_pair(cards):
        if node.get("type") in {"horizontal-stack", "vertical-stack", "stack"}:
            notes.append("replaced a two-card SpinJam stack with one full-screen card")
            return dict(CAST_CARD)
        notes.append(
            "replaced a two-card SpinJam row with one full-screen card; left other cards alone"
        )
        return {**node, "cards": [dict(CAST_CARD)]}
    updated = dict(node)
    if isinstance(cards, list):
        updated["cards"] = [_replace_pair_containers(item, notes) for item in cards]
    if isinstance(node.get("sections"), list):
        updated["sections"] = [
            _replace_pair_containers(item, notes) for item in node["sections"]
        ]
    return updated


def _panel_cast_view(view: dict[str, Any]) -> dict[str, Any]:
    kept = {key: value for key, value in view.items() if key not in ("cards", "sections", "type")}
    kept["type"] = "panel"
    kept["panel"] = True
    kept["cards"] = [dict(CAST_CARD)]
    return kept


def upgrade_cast_view(view: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Turn a generated two-card Cast view into one full-screen panel card.

    A view that is only that pair (nested in a stack, grid, or sections) becomes
    ``type: panel`` / ``panel: true`` with a single ``mode: cast`` card.
    Other cards in the same view stay put.
    """
    if not isinstance(view, dict):
        return view, []
    cards = view.get("cards")
    if (
        isinstance(cards, list)
        and len(cards) == 1
        and _is_cast_card(cards[0])
        and not view.get("sections")
        and view.get("type") == "panel"
        and view.get("panel") is True
    ):
        return view, []

    leaves = _leaf_cards(view)
    spinjam = [card for card in leaves if _is_spinjam_tv_card(card)]
    others = [card for card in leaves if not _is_spinjam_tv_card(card)]
    if len(spinjam) == 2 and not others and _is_generated_pair(spinjam):
        return _panel_cast_view(view), [
            "replaced the two-card cast layout with one full-screen card"
        ]
    if len(spinjam) == 1 and _is_cast_card(spinjam[0]) and not others:
        if view.get("type") == "panel" and view.get("panel") is True and not view.get("sections"):
            return view, []
        updated = _panel_cast_view(view)
        return updated, ["marked the cast view as a full-screen panel"]

    notes: list[str] = []
    replaced = _replace_pair_containers(view, notes)
    return replaced if isinstance(replaced, dict) else view, notes


def upgrade_cast_views(views: list[Any]) -> tuple[list[Any], list[str]]:
    updated: list[Any] = []
    notes: list[str] = []
    for view in views:
        if not isinstance(view, dict):
            updated.append(view)
            continue
        new_view, view_notes = upgrade_cast_view(view)
        path = new_view.get("path") or new_view.get("title") or "view"
        notes.extend(f"{path}: {note}" for note in view_notes)
        updated.append(new_view)
    return updated, notes


def upgrade_dashboard_config(config: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the Cast view and the Controls view in place."""
    raw_views = config.get("views")
    views = list(raw_views) if isinstance(raw_views, list) else []
    views, cast_notes = upgrade_cast_views(views)
    index = _controls_view_index(views)
    if index is None:
        views.append(spinjam_controls_view_config())
    else:
        views[index] = upgrade_controls_view(views[index])
    for note in cast_notes:
        _LOGGER.info("SpinJam dashboard layout: %s", note)
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

    dashboards = _lovelace_dashboards(hass)
    collection = lovelace_value(hass, "dashboards_collection")
    if dashboards is None or collection is None:
        _LOGGER.info(
            "SpinJam dashboard create skipped: Lovelace dashboards are not available"
        )
        raise HomeAssistantError(
            "Lovelace is not available — enable the Lovelace/default dashboard system first"
        )

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

    store = _dashboard_store(dashboards, path)
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
    dashboards = _lovelace_dashboards(hass)
    if dashboards is None:
        _LOGGER.info(
            "SpinJam dashboard upgrade skipped: Lovelace dashboards are not available"
        )
        return False
    if not dashboard_exists(hass, path):
        return False
    store = _dashboard_store(dashboards, path)
    if store is None:
        _LOGGER.info(
            "SpinJam dashboard upgrade skipped: no config store for %s", path
        )
        return False
    loaded = await _async_load_dashboard_config(store)
    if not loaded or not loaded.get("views"):
        return False
    config = upgrade_dashboard_config(loaded)
    await store.async_save(config)
    return True
