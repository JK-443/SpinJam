"""Serve the SpinJam Lovelace card and register a frontend resource."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WWW_DIR = Path(__file__).parent / "www"
CARD_FILENAME = "spinjam-lyrics-card.js"


def card_file_hash() -> str:
    """Return a short content hash for cache-busting Cast / browser loads."""
    path = WWW_DIR / CARD_FILENAME
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def card_resource_url() -> str:
    """Lovelace module URL including ``?v=<hash>``."""
    return f"/{DOMAIN}/{CARD_FILENAME}?v={card_file_hash()}"


async def async_setup_frontend(hass: HomeAssistant) -> str | None:
    """Register static path + Lovelace module resource (once).

    Soft-fails when ``http`` / ``frontend`` are not fully available (unit tests).
    Returns the versioned resource URL when registration succeeds.
    """
    key = f"{DOMAIN}_frontend"
    if hass.data.get(key):
        return hass.data.get(f"{DOMAIN}_card_url")

    if not hasattr(hass, "http") or hass.http is None:
        _LOGGER.debug("HTTP not ready; skipping SpinJam frontend registration")
        return None

    registered = await _async_register_static(hass)
    if not registered:
        return None

    url = card_resource_url()
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("add_extra_js_url skipped: %s", err)

    hass.data[key] = True
    hass.data[f"{DOMAIN}_card_url"] = url
    hass.data[f"{DOMAIN}_card_version"] = card_file_hash()
    _LOGGER.debug("Registered SpinJam frontend at %s", url)
    return url


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
