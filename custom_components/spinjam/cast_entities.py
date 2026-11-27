"""Helpers for identifying Cast and Samsung TV display entities."""

from __future__ import annotations

import logging
from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

CastCheck = Literal["cast", "not_cast", "unknown"]
DisplayPlatform = Literal["cast", "samsungtv", "unknown", "unsupported"]

PLATFORM_CAST = "cast"
PLATFORM_SAMSUNG_TV = "samsungtv"


def display_platform(hass: HomeAssistant, entity_id: str) -> DisplayPlatform:
    """Return how SpinJam can launch ``entity_id``.

    ``unknown`` means no registry entry (common in unit tests). Callers treat
    that like Cast so a missing registry does not block a session. ``unsupported``
    is a known platform that is neither Google Cast nor Samsung TV.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None:
        return "unknown"
    if entry.platform == PLATFORM_CAST:
        return "cast"
    if entry.platform == PLATFORM_SAMSUNG_TV:
        return "samsungtv"
    return "unsupported"


def cast_platform_status(hass: HomeAssistant, entity_id: str) -> CastCheck:
    """Return whether ``entity_id`` is registered under the cast integration.

    ``unknown`` means no registry entry (common in unit tests) — callers should
    not hard-fail in that case. Samsung TV entities are ``not_cast`` here;
    use :func:`display_platform` when Samsung TVs are valid displays.
    """
    kind = display_platform(hass, entity_id)
    if kind == "unknown":
        return "unknown"
    if kind == "cast":
        return "cast"
    return "not_cast"


def filter_cast_displays(
    hass: HomeAssistant, entity_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Split displays into (usable, skipped).

    Cast, Samsung TV, and unknown registry entries are usable. Other known
    platforms are skipped.
    """
    usable: list[str] = []
    skipped: list[str] = []
    for entity_id in entity_ids:
        if display_platform(hass, entity_id) == "unsupported":
            skipped.append(entity_id)
        else:
            usable.append(entity_id)
    return usable, skipped


def unsupported_displays(hass: HomeAssistant, entity_ids: list[str]) -> list[str]:
    """Return entity ids that are neither Cast nor Samsung TV."""
    return [
        entity_id
        for entity_id in entity_ids
        if display_platform(hass, entity_id) == "unsupported"
    ]


def non_cast_displays(hass: HomeAssistant, entity_ids: list[str]) -> list[str]:
    """Return displays SpinJam cannot launch (not Cast or Samsung TV)."""
    return unsupported_displays(hass, entity_ids)
