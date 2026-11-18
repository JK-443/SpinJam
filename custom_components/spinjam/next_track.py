"""Resolve the upcoming track from source-player attributes or Music Assistant."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# Attribute names seen on Music Assistant / generic media players.
_TITLE_KEYS = (
    "media_next_title",
    "next_media_title",
    "next_track_title",
    "queue_next_title",
    "next_title",
)
_ARTIST_KEYS = (
    "media_next_artist",
    "next_media_artist",
    "next_track_artist",
    "queue_next_artist",
    "next_artist",
)
_ALBUM_KEYS = (
    "media_next_album",
    "next_media_album_name",
    "next_track_album",
    "queue_next_album",
    "next_album",
)
_DURATION_KEYS = (
    "media_next_duration",
    "next_media_duration",
    "next_track_duration",
    "queue_next_duration",
)
_ART_KEYS = (
    "media_next_entity_picture",
    "next_entity_picture",
    "queue_next_entity_picture",
)


@dataclass(frozen=True)
class NextTrackInfo:
    artist: str | None
    title: str | None
    album: str | None = None
    duration: float | None = None
    art_url: str | None = None
    source: str = "attributes"


def _first_str(attrs: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_float(attrs: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = attrs.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def next_from_attributes(attrs: dict[str, Any]) -> NextTrackInfo | None:
    """Pick next-item metadata from player state attributes when present."""
    # Nested dict forms used by some queues.
    for nest_key in ("next_track", "queue_next", "media_next", "next_item"):
        nested = attrs.get(nest_key)
        if isinstance(nested, dict):
            title = (
                nested.get("media_title")
                or nested.get("title")
                or nested.get("name")
            )
            artist = (
                nested.get("media_artist")
                or nested.get("artist")
                or nested.get("artists")
            )
            if isinstance(artist, list):
                artist = ", ".join(str(a) for a in artist if a)
            album = nested.get("media_album_name") or nested.get("album")
            if title or artist:
                duration = nested.get("media_duration") or nested.get("duration")
                try:
                    duration_f = float(duration) if duration is not None else None
                except (TypeError, ValueError):
                    duration_f = None
                art = nested.get("entity_picture") or nested.get("image_url")
                return NextTrackInfo(
                    artist=str(artist).strip() if artist else None,
                    title=str(title).strip() if title else None,
                    album=str(album).strip() if album else None,
                    duration=duration_f,
                    art_url=str(art) if art else None,
                    source="attributes",
                )

    title = _first_str(attrs, _TITLE_KEYS)
    artist = _first_str(attrs, _ARTIST_KEYS)
    if not title and not artist:
        return None
    return NextTrackInfo(
        artist=artist,
        title=title,
        album=_first_str(attrs, _ALBUM_KEYS),
        duration=_first_float(attrs, _DURATION_KEYS),
        art_url=_first_str(attrs, _ART_KEYS),
        source="attributes",
    )


def _parse_ma_queue_payload(payload: Any) -> NextTrackInfo | None:
    """Extract the upcoming item from a Music Assistant get_queue result."""
    if payload is None:
        return None
    data = payload
    if isinstance(payload, dict) and "queue" in payload:
        data = payload["queue"]
    items = None
    current_index = None
    if isinstance(data, dict):
        items = (
            data.get("items")
            or data.get("queue_items")
            or data.get("tracks")
            or data.get("media_items")
        )
        current_index = data.get("current_index", data.get("current_item_id"))
        current = data.get("current_item") or data.get("current")
        nxt = data.get("next_item") or data.get("next")
        if isinstance(nxt, dict):
            return _item_dict_to_next(nxt, source="music_assistant")
        if isinstance(current, dict) and isinstance(items, list):
            # Prefer explicit next; else item after current.
            pass
    if isinstance(data, list):
        items = data
    if not isinstance(items, list) or not items:
        return None

    start = 0
    if isinstance(current_index, int) and current_index >= 0:
        start = current_index + 1
    for item in items[start:]:
        if not isinstance(item, dict):
            continue
        info = _item_dict_to_next(item, source="music_assistant")
        if info is not None:
            return info
    return None


def _item_dict_to_next(item: dict[str, Any], *, source: str) -> NextTrackInfo | None:
    media = item.get("media_item") if isinstance(item.get("media_item"), dict) else item
    title = media.get("name") or media.get("title") or media.get("media_title")
    artist = media.get("artist") or media.get("artists") or media.get("media_artist")
    if isinstance(artist, list):
        artist = ", ".join(
            (a.get("name") if isinstance(a, dict) else str(a)) for a in artist if a
        )
    elif isinstance(artist, dict):
        artist = artist.get("name")
    album = media.get("album")
    if isinstance(album, dict):
        album = album.get("name")
    album = album or media.get("media_album_name")
    duration = media.get("duration") or media.get("media_duration")
    try:
        duration_f = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_f = None
    image = media.get("image") or media.get("entity_picture")
    if isinstance(image, dict):
        image = image.get("path") or image.get("url")
    if not title and not artist:
        return None
    return NextTrackInfo(
        artist=str(artist).strip() if artist else None,
        title=str(title).strip() if title else None,
        album=str(album).strip() if album else None,
        duration=duration_f,
        art_url=str(image) if image else None,
        source=source,
    )


async def async_resolve_next_track(
    hass: HomeAssistant, entity_id: str
) -> NextTrackInfo | None:
    """Resolve next track from attributes, then Music Assistant get_queue if present."""
    state = hass.states.get(entity_id)
    if state is not None:
        from_attrs = next_from_attributes(dict(state.attributes))
        if from_attrs is not None:
            return from_attrs

    if not hass.services.has_service("music_assistant", "get_queue"):
        return None

    try:
        result = await hass.services.async_call(
            "music_assistant",
            "get_queue",
            {"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, TypeError, ValueError) as err:
        _LOGGER.debug("music_assistant.get_queue unavailable for %s: %s", entity_id, err)
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("music_assistant.get_queue failed for %s: %s", entity_id, err)
        return None

    # HA return_response may nest under entity_id.
    if isinstance(result, dict) and entity_id in result:
        return _parse_ma_queue_payload(result[entity_id])
    return _parse_ma_queue_payload(result)
