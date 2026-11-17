"""Cast the SpinJam Lovelace view to a display media_player."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_show_now_playing(
    hass: HomeAssistant,
    *,
    entity_id: str,
    dashboard_path: str,
    view_path: str,
) -> bool:
    """Cast a Lovelace dashboard view via HA Cast.

    Uses ``cast.show_lovelace_view``. Requires the Cast integration, a
    reachable HTTPS ``external_url``, and a pre-created dashboard/view.
    """
    if not hass.services.has_service("cast", "show_lovelace_view"):
        _LOGGER.warning(
            "cast.show_lovelace_view is unavailable — enable the Google Cast "
            "integration before using spinjam.start"
        )
        return False
    try:
        await hass.services.async_call(
            "cast",
            "show_lovelace_view",
            {
                "entity_id": entity_id,
                "dashboard_path": dashboard_path,
                "view_path": view_path,
            },
            blocking=False,
        )
    except Exception as err:  # noqa: BLE001 — Cast may be offline
        _LOGGER.warning("Failed to cast SpinJam view to %s: %s", entity_id, err)
        return False
    _LOGGER.debug(
        "Casting SpinJam %s/%s to %s", dashboard_path, view_path, entity_id
    )
    return True


async def async_end_cast(hass: HomeAssistant, entity_id: str) -> bool:
    """End a Cast session on the display.

    ``media_player.turn_off`` is the safest cross-device quit for Cast /
    Google TV entities (avoids quitting unrelated apps via media_stop alone).
    """
    if not hass.services.has_service("media_player", "turn_off"):
        return False
    try:
        await hass.services.async_call(
            "media_player",
            "turn_off",
            {"entity_id": entity_id},
            blocking=False,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed to end Cast on %s: %s", entity_id, err)
        return False
    _LOGGER.debug("Ended Cast session on %s", entity_id)
    return True


def cast_options(entry_options: dict[str, Any]) -> dict[str, Any]:
    """Extract cast-related options with defaults (imported lazily to avoid cycles)."""
    from .const import (
        CONF_DASHBOARD_PATH,
        CONF_RECAST_INTERVAL,
        CONF_RECAST_WHILE_PLAYING,
        CONF_VIEW_PATH,
        DEFAULT_DASHBOARD_PATH,
        DEFAULT_RECAST_INTERVAL,
        DEFAULT_RECAST_WHILE_PLAYING,
        DEFAULT_VIEW_PATH,
    )

    return {
        CONF_DASHBOARD_PATH: entry_options.get(
            CONF_DASHBOARD_PATH, DEFAULT_DASHBOARD_PATH
        ),
        CONF_VIEW_PATH: entry_options.get(CONF_VIEW_PATH, DEFAULT_VIEW_PATH),
        CONF_RECAST_WHILE_PLAYING: bool(
            entry_options.get(
                CONF_RECAST_WHILE_PLAYING, DEFAULT_RECAST_WHILE_PLAYING
            )
        ),
        CONF_RECAST_INTERVAL: float(
            entry_options.get(CONF_RECAST_INTERVAL, DEFAULT_RECAST_INTERVAL)
        ),
    }
