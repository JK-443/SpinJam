"""Serve the SpinJam Lovelace card and register a frontend resource."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WWW_DIR = Path(__file__).parent / "www"
CARD_FILENAME = "spinjam-lyrics-card.js"
CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"

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
    return f"{CARD_URL_PATH}?v={version or card_file_hash()}"


def _resource_path(url: str) -> str:
    """Strip query/fragment so version bumps match the same resource."""
    return urlsplit(url).path


async def async_register_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Create or update a storage-mode Lovelace module resource for the card.

    Cast receivers load only Lovelace resources (not ``add_extra_js_url`` alone).
    YAML-mode Lovelace cannot be mutated — log and skip.
    """
    lovelace = hass.data.get("lovelace")
    if not isinstance(lovelace, dict) or "resources" not in lovelace:
        _LOGGER.debug("Lovelace resources unavailable; skipping module registration")
        return False

    resources = lovelace["resources"]
    # YAML collection has no create/update — storage collection does.
    if not hasattr(resources, "async_create_item"):
        _LOGGER.info(
            "Lovelace is in YAML mode — add `%s` as a module resource manually "
            "(Cast will not see add_extra_js_url)",
            url,
        )
        return False

    try:
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not load Lovelace resources: %s", err)
        return False

    items = list(resources.async_items() or [])
    target_path = _resource_path(url)
    existing = next(
        (
            item
            for item in items
            if _resource_path(str(item.get("url") or "")) == target_path
        ),
        None,
    )
    try:
        if existing is not None:
            item_id = existing["id"]
            if existing.get("url") == url and existing.get("type") == "module":
                _LOGGER.debug("Lovelace resource already current: %s", url)
                return True
            await resources.async_update_item(
                item_id, {"res_type": "module", "url": url}
            )
            _LOGGER.info("Updated Lovelace resource %s → %s", item_id, url)
        else:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Created Lovelace resource %s", url)
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register Lovelace resource %s: %s", url, err)
        return False


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
    await async_register_lovelace_resource(hass, url)

    try:
        from homeassistant.components.frontend import add_extra_js_url

        # Same URL as the Lovelace resource so browsers/Cast don't double-load
        # divergent versions.
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
