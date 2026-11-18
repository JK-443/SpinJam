"""Cast the SpinJam Lovelace view to a display media_player."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CAST_LOVELACE_TIMEOUT_SEC,
    CAST_WAKE_TIMEOUT_SEC,
    LOVELACE_APP_NAMES,
)

_LOGGER = logging.getLogger(__name__)

_OFF_LIKE = frozenset({STATE_OFF, "standby", STATE_UNAVAILABLE, STATE_UNKNOWN})


def remote_entity_for_media_player(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return a ``remote.*`` entity on the same device as ``entity_id``, if any."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None or entry.device_id is None:
        return None
    for candidate in er.async_entries_for_device(registry, entry.device_id):
        if candidate.domain == "remote" and not candidate.disabled:
            return candidate.entity_id
    return None


def _is_closed_transport(err: BaseException) -> bool:
    """True when pychromecast/websocket closed while a write was in flight."""
    current: BaseException | None = err
    seen: list[int] = []
    while current is not None and id(current) not in seen:
        seen.append(id(current))
        message = str(current).lower()
        if "closing transport" in message or "closed transport" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


async def _async_service_call(
    hass: HomeAssistant,
    domain: str,
    service: str,
    data: dict[str, Any],
    *,
    blocking: bool,
) -> None:
    """Call a service, retrying once when the Cast socket is already closing."""
    for attempt in (1, 2):
        try:
            await hass.services.async_call(domain, service, data, blocking=blocking)
            return
        except Exception as err:
            if attempt == 1 and _is_closed_transport(err):
                _LOGGER.debug(
                    "%s.%s hit a closed transport; retrying once: %s",
                    domain,
                    service,
                    err,
                )
                continue
            raise


def _is_display_on(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    return state is not None and state.state not in _OFF_LIKE


def lovelace_app_active(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True when the Cast entity reports the HA Lovelace app."""
    state = hass.states.get(entity_id)
    if state is None or state.state in _OFF_LIKE:
        return False
    app = state.attributes.get("app_name")
    if not app:
        return False
    return str(app) in LOVELACE_APP_NAMES


async def async_wake_display(
    hass: HomeAssistant,
    entity_id: str,
    *,
    timeout: float = CAST_WAKE_TIMEOUT_SEC,
) -> bool:
    """Wake a Cast display that is off/standby; wait until it reports on."""
    if _is_display_on(hass, entity_id):
        return True

    if hass.services.has_service("media_player", "turn_on"):
        try:
            await _async_service_call(
                hass,
                "media_player",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("media_player.turn_on failed for %s: %s", entity_id, err)

    remote_id = remote_entity_for_media_player(hass, entity_id)
    if remote_id and hass.services.has_service("remote", "turn_on"):
        try:
            await hass.services.async_call(
                "remote",
                "turn_on",
                {"entity_id": remote_id},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("remote.turn_on failed for %s: %s", remote_id, err)

    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        if _is_display_on(hass, entity_id):
            return True
        await asyncio.sleep(0.5)
    _LOGGER.warning("Display %s did not come on within %.0fs", entity_id, timeout)
    return False


async def async_wait_for_lovelace_app(
    hass: HomeAssistant,
    entity_id: str,
    *,
    timeout: float = CAST_LOVELACE_TIMEOUT_SEC,
) -> bool:
    """Wait until ``app_name`` is the Home Assistant Lovelace Cast receiver."""
    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        if lovelace_app_active(hass, entity_id):
            return True
        await asyncio.sleep(0.5)
    state = hass.states.get(entity_id)
    app = None if state is None else state.attributes.get("app_name")
    _LOGGER.warning(
        "Cast on %s did not reach Lovelace app within %.0fs (app_name=%s)",
        entity_id,
        timeout,
        app,
    )
    return False


async def async_show_now_playing(
    hass: HomeAssistant,
    *,
    entity_id: str,
    dashboard_path: str,
    view_path: str,
    blocking: bool = True,
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
        await _async_service_call(
            hass,
            "cast",
            "show_lovelace_view",
            {
                "entity_id": entity_id,
                "dashboard_path": dashboard_path,
                "view_path": view_path,
            },
            blocking=blocking,
        )
    except Exception as err:  # noqa: BLE001 — Cast may be offline
        _LOGGER.warning("Failed to cast SpinJam view to %s: %s", entity_id, err)
        return False
    _LOGGER.debug(
        "Casting SpinJam %s/%s to %s", dashboard_path, view_path, entity_id
    )
    return True


async def async_end_cast(hass: HomeAssistant, entity_id: str) -> bool:
    """Quit the Cast / Lovelace app on the display.

    ``media_player.turn_off`` on Chromecast-built-in TVs typically leaves the
    panel powered on and only exits the Cast app — preferred for stop.
    """
    if not hass.services.has_service("media_player", "turn_off"):
        return False
    try:
        await _async_service_call(
            hass,
            "media_player",
            "turn_off",
            {"entity_id": entity_id},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed to end Cast on %s: %s", entity_id, err)
        return False
    _LOGGER.debug("Ended Cast session on %s", entity_id)
    return True


async def async_power_off_display(hass: HomeAssistant, entity_id: str) -> bool:
    """Power off the TV panel (remote preferred; falls back to media_player)."""
    remote_id = remote_entity_for_media_player(hass, entity_id)
    if remote_id and hass.services.has_service("remote", "turn_off"):
        try:
            await hass.services.async_call(
                "remote",
                "turn_off",
                {"entity_id": remote_id},
                blocking=True,
            )
            return True
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("remote.turn_off failed for %s: %s", remote_id, err)
    if hass.services.has_service("media_player", "turn_off"):
        try:
            await hass.services.async_call(
                "media_player",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to power off %s: %s", entity_id, err)
    return False


def cast_options(entry_options: dict[str, Any]) -> dict[str, Any]:
    """Extract cast-related options with defaults (imported lazily to avoid cycles)."""
    from .const import (
        CONF_DASHBOARD_PATH,
        CONF_POWER_OFF_DISPLAY_ON_STOP,
        CONF_RECAST_INTERVAL,
        CONF_RECAST_WHILE_PLAYING,
        CONF_VIEW_PATH,
        DEFAULT_DASHBOARD_PATH,
        DEFAULT_POWER_OFF_DISPLAY_ON_STOP,
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
        CONF_POWER_OFF_DISPLAY_ON_STOP: bool(
            entry_options.get(
                CONF_POWER_OFF_DISPLAY_ON_STOP, DEFAULT_POWER_OFF_DISPLAY_ON_STOP
            )
        ),
    }
