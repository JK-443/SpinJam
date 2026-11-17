"""Unified SpinJam now-playing media player."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACTIVE_SOURCE,
    ATTR_ALBUM_LOCK,
    ATTR_DISPLAYS,
    ATTR_LYRIC_CURRENT,
    ATTR_LYRIC_LINES,
    ATTR_LYRIC_NEXT,
    ATTR_LYRIC_OFFSET_MS,
    ATTR_SELECTED_DISPLAY,
    ATTR_SOURCE_KIND,
    ATTR_SYNC_OFFSET_MS,
    DOMAIN,
)
from .coordinator import SpinJamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpinJamMediaPlayer(coordinator, entry)])


class SpinJamMediaPlayer(CoordinatorEntity[SpinJamCoordinator], MediaPlayerEntity):
    """Expose aggregated now-playing as a single media_player."""

    _attr_has_entity_name = False
    _attr_name = "SpinJam Now Playing"
    _attr_supported_features = MediaPlayerEntityFeature(0)
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "spinjam_now_playing"
        self.entity_id = "media_player.spinjam_now_playing"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }

    @property
    def state(self) -> MediaPlayerState:
        active = self.coordinator.data.active
        if active is None:
            return MediaPlayerState.IDLE
        return MediaPlayerState.PLAYING if active.playing else MediaPlayerState.PAUSED

    @property
    def media_title(self) -> str | None:
        active = self.coordinator.data.active
        return active.title if active else None

    @property
    def media_artist(self) -> str | None:
        active = self.coordinator.data.active
        return active.artist if active else None

    @property
    def media_album_name(self) -> str | None:
        active = self.coordinator.data.active
        return active.album if active else None

    @property
    def media_image_url(self) -> str | None:
        active = self.coordinator.data.active
        return active.art_url if active else None

    @property
    def media_duration(self) -> int | None:
        active = self.coordinator.data.active
        if not active or active.duration is None:
            return None
        return int(active.duration)

    @property
    def media_position(self) -> float | None:
        active = self.coordinator.data.active
        if not active or active.position is None:
            return None
        return float(active.position)

    @property
    def media_position_updated_at(self) -> datetime | None:
        return self.coordinator.data.position_updated_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        active = data.active
        attrs: dict[str, Any] = {
            ATTR_LYRIC_CURRENT: data.lyric_current,
            ATTR_LYRIC_NEXT: data.lyric_next,
            ATTR_LYRIC_LINES: data.lyric_lines,
            ATTR_SYNC_OFFSET_MS: data.sync_offset_ms,
            ATTR_LYRIC_OFFSET_MS: data.lyric_offset_ms,
            ATTR_ALBUM_LOCK: data.album_lock,
            ATTR_DISPLAYS: list(self.coordinator.displays),
            ATTR_SELECTED_DISPLAY: self.coordinator.selected_display,
        }
        if active:
            attrs[ATTR_ACTIVE_SOURCE] = active.entity_id
            attrs[ATTR_SOURCE_KIND] = active.kind
        return attrs
