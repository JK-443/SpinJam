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
    NUMBER_LYRIC_OFFSET_ENTITY_ID,
    SELECT_DISPLAY_ENTITY_ID,
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

CONTROLS_TILES = [
    {
        "type": "tile",
        "entity": SWITCH_CAST_ENTITY_ID,
        "name": "SpinJam",
        "icon": "mdi:cast",
    },
    {
        "type": "tile",
        "entity": SWITCH_TRACKING_ENTITY_ID,
        "name": "Tracking",
        "icon": "mdi:radar",
    },
    {
        "type": "tile",
        "entity": SWITCH_LYRICS_ENTITY_ID,
        "name": "Lyrics",
        "icon": "mdi:microphone-variant",
    },
    {
        "type": "tile",
        "entity": SELECT_DISPLAY_ENTITY_ID,
        "name": "Display",
        "icon": "mdi:television",
    },
    {
        "type": "tile",
        "entity": NUMBER_LYRIC_OFFSET_ENTITY_ID,
        "name": "Lyric offset",
        "icon": "mdi:timer-outline",
    },
]


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
    """Masonry view of SpinJam control tiles (cast / tracking / lyrics / …)."""
    return {
        "title": "Controls",
        "path": "controls",
        "type": "masonry",
        "cards": [dict(tile) for tile in CONTROLS_TILES],
    }


async def async_create_spinjam_dashboard(
    hass: HomeAssistant,
    *,
    dashboard_path: str | None = None,
    view_path: str | None = None,
    title: str = "SpinJam",
) -> dict[str, Any]:
    """Create (or update) a storage-mode SpinJam panel dashboard.

    Uses Lovelace's ``DashboardsCollection`` the same way HA creates the map
    dashboard. Safe to call repeatedly: existing dashboards are updated in place.
    Layout: details card left, lyrics card right; plus a Controls view with tiles.
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

    config = {
        "views": [spinjam_tv_view_config(view), spinjam_controls_view_config()],
    }
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
