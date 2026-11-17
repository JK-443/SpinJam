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

# Populated once via executor (or sync fallback in unit tests).
_card_hash: str | None = None


def _compute_card_file_hash() -> str:
    """Read card bytes and return a short sha256 (blocking — run in executor)."""
    path = WWW_DIR / CARD_FILENAME
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def card_file_hash() -> str:
    """Return the cached card content hash.

    Prefer ``async_get_card_file_hash`` on the event loop so the first read runs
    in an executor. Sync fallback exists for unit tests that never set up the
    frontend.
    """
    global _card_hash
    if _card_hash is None:
        _card_hash = _compute_card_file_hash()
    return _card_hash


async def async_get_card_file_hash(hass: HomeAssistant) -> str:
    """Compute (once) and cache the card hash off the event loop."""
    global _card_hash
    if _card_hash is None:
        _card_hash = await hass.async_add_executor_job(_compute_card_file_hash)
    return _card_hash


def card_resource_url(version: str | None = None) -> str:
    """Lovelace module URL including ``?v=<hash>``."""
    return f"/{DOMAIN}/{CARD_FILENAME}?v={version or card_file_hash()}"


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

    version = await async_get_card_file_hash(hass)
    url = card_resource_url(version)
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("add_extra_js_url skipped: %s", err)

    hass.data[key] = True
    hass.data[f"{DOMAIN}_card_url"] = url
    hass.data[f"{DOMAIN}_card_version"] = version
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
