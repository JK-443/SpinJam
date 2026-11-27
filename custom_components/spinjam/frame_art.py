"""Optional Samsung Frame Art Mode.

Off unless the user turns the option on. The television host and websocket
token come from the Samsung TV config entry that owns the selected
media_player. ``samsungtvws`` (and its rename, ``samsungframetv``) is imported
only when an upload or art-mode change actually runs. Neither package is a
manifest requirement.

A missing library, a missing token, or a TV that does not support Art Mode
logs a warning and skips the upload. This does not start a pairing popup.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_ART_PORT = 8002
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_FETCH_TIMEOUT = ClientTimeout(total=10, connect=3, sock_read=8)
_MISSING_LIBRARY_LOGGED = False


def image_file_type(data: bytes) -> str | None:
    """Return ``JPEG`` or ``PNG`` when ``data`` looks like that image."""
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    return None


def load_tv_client() -> Any | None:
    """Return the SamsungTVWS class, or None when neither package is installed."""
    for module_name in ("samsungtvws", "samsungframetv"):
        try:
            module = __import__(module_name, fromlist=["SamsungTVWS"])
        except ImportError:
            continue
        client = getattr(module, "SamsungTVWS", None)
        if client is not None:
            return client
    return None


def warn_missing_library() -> None:
    """Log once that Art Mode was requested without the optional package."""
    global _MISSING_LIBRARY_LOGGED
    if _MISSING_LIBRARY_LOGGED:
        return
    _MISSING_LIBRARY_LOGGED = True
    _LOGGER.warning(
        "Frame Art Mode is on, but neither samsungtvws nor samsungframetv "
        "is installed; skipping album-art upload"
    )


def samsungtv_host_and_token(
    hass: HomeAssistant, entity_id: str
) -> tuple[str, str] | None:
    """Host and token from the samsungtv config entry that owns ``entity_id``.

    Both values are whatever that integration stored. No address is assumed.
    Returns None when the entity is not a Samsung TV entry, or when that
    entry has no host or no websocket token. A missing token means we will
    not open a new pairing prompt.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity = registry.async_get(entity_id)
    if entity is None or not entity.config_entry_id:
        return None
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.domain != "samsungtv":
        return None
    data = dict(entry.data or {})
    host = data.get("host")
    token = data.get("token")
    if not host or not token:
        return None
    return str(host), str(token)


def _absolute_artwork_url(hass: HomeAssistant, url: str) -> str | None:
    value = str(url or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        return None
    try:
        from homeassistant.helpers.network import get_url

        base = get_url(hass)
    except Exception:  # noqa: BLE001 — internal URL may be unset
        return None
    return str(base).rstrip("/") + value


def _close_client(tv: Any) -> None:
    closer = getattr(tv, "close", None)
    if not callable(closer):
        return
    try:
        closer()
    except Exception:  # noqa: BLE001 — closing a failed socket is best-effort
        _LOGGER.debug("Closing the Frame art connection failed", exc_info=True)


def _set_artmode(art: Any, on: bool) -> None:
    """Call set_artmode with a bool, then the older ``on`` / ``off`` strings."""
    try:
        art.set_artmode(on)
    except TypeError:
        art.set_artmode("on" if on else "off")


def _delete_previous(art: Any, content_id: str | None) -> None:
    if not content_id:
        return
    try:
        art.delete(content_id)
    except TypeError:
        art.delete([content_id])
    except Exception:  # noqa: BLE001 — leaving the previous upload is acceptable
        _LOGGER.debug("Could not remove the previous Frame upload", exc_info=True)


def _content_id(uploaded: Any) -> str | None:
    if uploaded is None:
        return None
    if isinstance(uploaded, dict):
        value = uploaded.get("content_id") or uploaded.get("id")
        return str(value) if value else None
    text = str(uploaded).strip()
    return text or None


def _open_art(client_cls: Any, host: str, token: str) -> Any:
    return client_cls(host, _ART_PORT, token=token, name="SpinJam")


def push_cover_sync(
    client_cls: Any,
    host: str,
    token: str,
    image: bytes,
    file_type: str,
    previous_id: str | None,
) -> str | None:
    """Upload ``image``, show it, and turn Art Mode on. Runs in an executor."""
    tv = _open_art(client_cls, host, token)
    try:
        art = tv.art()
        supported = art.supported()
        if supported is False or supported is None:
            _LOGGER.warning(
                "Frame Art Mode skipped: this Samsung TV did not report Art Mode support"
            )
            return None
        try:
            uploaded = art.upload(image, file_type=file_type, matte="none")
        except TypeError:
            uploaded = art.upload(image, file_type=file_type)
        content_id = _content_id(uploaded)
        if not content_id:
            _LOGGER.warning("Frame Art Mode upload did not return an art id")
            return None
        try:
            art.select_image(content_id, show=True)
        except TypeError:
            art.select_image(content_id)
        _set_artmode(art, True)
        if previous_id and previous_id != content_id:
            _delete_previous(art, previous_id)
        return content_id
    except Exception as err:  # noqa: BLE001 — TV socket, token, or art API
        _LOGGER.warning("Frame Art Mode upload failed: %s", err)
        return None
    finally:
        _close_client(tv)


def set_artmode_sync(client_cls: Any, host: str, token: str, on: bool) -> bool:
    """Turn Art Mode on or off. Runs in an executor."""
    tv = _open_art(client_cls, host, token)
    try:
        _set_artmode(tv.art(), on)
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Frame Art Mode switch failed: %s", err)
        return False
    finally:
        _close_client(tv)


async def async_fetch_artwork(
    hass: HomeAssistant, url: str
) -> tuple[bytes, str] | None:
    """Download album art. Returns image bytes and a JPEG/PNG file type."""
    absolute = _absolute_artwork_url(hass, url)
    if not absolute:
        _LOGGER.warning("Frame Art Mode skipped: album art URL is not fetchable")
        return None
    session = async_get_clientsession(hass)
    try:
        async with session.get(absolute, timeout=_FETCH_TIMEOUT) as response:
            if response.status != 200:
                _LOGGER.warning(
                    "Frame Art Mode skipped: album art request returned %s",
                    response.status,
                )
                return None
            data = await response.content.read(_MAX_IMAGE_BYTES + 1)
    except (ClientError, TimeoutError, OSError) as err:
        _LOGGER.warning(
            "Frame Art Mode skipped: could not download album art (%s)",
            type(err).__name__,
        )
        return None
    if len(data) > _MAX_IMAGE_BYTES:
        _LOGGER.warning("Frame Art Mode skipped: album art is too large")
        return None
    kind = image_file_type(data)
    if kind is None:
        _LOGGER.warning("Frame Art Mode skipped: album art is not JPEG or PNG")
        return None
    return data, kind


async def _async_with_tv(
    hass: HomeAssistant,
    entity_id: str,
    worker: Any,
) -> Any:
    client = load_tv_client()
    if client is None:
        warn_missing_library()
        return None
    connection = samsungtv_host_and_token(hass, entity_id)
    if connection is None:
        _LOGGER.warning(
            "Frame Art Mode skipped for %s: the Samsung TV integration "
            "has no stored websocket token",
            entity_id,
        )
        return None
    host, token = connection
    return await hass.async_add_executor_job(worker, client, host, token)


async def async_push_cover(
    hass: HomeAssistant,
    entity_id: str,
    image: bytes,
    file_type: str,
    previous_id: str | None,
) -> str | None:
    """Upload a cover to the Frame that owns ``entity_id`` and show it."""

    def _run(client: Any, host: str, token: str) -> str | None:
        return push_cover_sync(client, host, token, image, file_type, previous_id)

    return await _async_with_tv(hass, entity_id, _run)


async def async_set_artmode(hass: HomeAssistant, entity_id: str, on: bool) -> bool:
    """Turn Art Mode on or off for the Frame that owns ``entity_id``."""

    def _run(client: Any, host: str, token: str) -> bool:
        return set_artmode_sync(client, host, token, on)

    result = await _async_with_tv(hass, entity_id, _run)
    return bool(result)
