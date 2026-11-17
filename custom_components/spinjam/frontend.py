"""Serve the SpinJam Lovelace card and register a frontend resource."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WWW_DIR = Path(__file__).parent / "www"
CARD_FILENAME = "spinjam-now-playing-card.js"
STATIC_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register static path + Lovelace module resource (once).

    Soft-fails when ``http`` / ``frontend`` are not fully available (unit tests).
    HACS users get the card automatically — no separate frontend install.
    """
    key = f"{DOMAIN}_frontend"
    if hass.data.get(key):
        return

    if not hasattr(hass, "http") or hass.http is None:
        _LOGGER.debug("HTTP not ready; skipping SpinJam frontend registration")
        return

    registered = await _async_register_static(hass)
    if not registered:
        return

    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, STATIC_URL_PATH)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("add_extra_js_url skipped: %s", err)

    hass.data[key] = True
    _LOGGER.debug("Registered SpinJam frontend at %s", STATIC_URL_PATH)


async def _async_register_static(hass: HomeAssistant) -> bool:
    """Register ``/spinjam`` static files (HA 2024+ paths API, with fallback)."""
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    f"/{DOMAIN}",
                    str(WWW_DIR),
                    cache_headers=False,
                )
            ]
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("async_register_static_paths failed (%s); trying legacy", err)

    try:
        hass.http.async_register_static_path(
            f"/{DOMAIN}", str(WWW_DIR), cache_headers=False
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register SpinJam static path: %s", err)
        return False
