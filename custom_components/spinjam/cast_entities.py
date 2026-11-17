"""Helpers for identifying Google Cast display entities."""

from __future__ import annotations

import logging
from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

CastCheck = Literal["cast", "not_cast", "unknown"]


def cast_platform_status(hass: HomeAssistant, entity_id: str) -> CastCheck:
    """Return whether ``entity_id`` is registered under the cast integration.

    ``unknown`` means no registry entry (common in unit tests) — callers should
    not hard-fail in that case.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None:
        return "unknown"
    if entry.platform == "cast":
        return "cast"
    return "not_cast"


def filter_cast_displays(
    hass: HomeAssistant, entity_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Split displays into (usable, skipped_non_cast).

    Unknown registry entries are treated as usable so tests and edge cases work.
    """
    usable: list[str] = []
    skipped: list[str] = []
    for entity_id in entity_ids:
        status = cast_platform_status(hass, entity_id)
        if status == "not_cast":
            skipped.append(entity_id)
        else:
            usable.append(entity_id)
    return usable, skipped


def non_cast_displays(hass: HomeAssistant, entity_ids: list[str]) -> list[str]:
    """Return entity ids that are known non-cast platforms."""
    return [
        entity_id
        for entity_id in entity_ids
        if cast_platform_status(hass, entity_id) == "not_cast"
    ]
