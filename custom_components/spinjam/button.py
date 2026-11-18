"""Buttons that nudge or reset the lyric delay."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUTTON_LYRIC_DELAY_RESET_ENTITY_ID,
    BUTTON_LYRICS_EARLIER_ENTITY_ID,
    BUTTON_LYRICS_LATER_ENTITY_ID,
    DOMAIN,
)
from .coordinator import SpinJamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SpinJamLyricsEarlierButton(coordinator, entry),
            SpinJamLyricsLaterButton(coordinator, entry),
            SpinJamResetLyricDelayButton(coordinator, entry),
        ]
    )


class _SpinJamButton(CoordinatorEntity[SpinJamCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }


class SpinJamLyricsEarlierButton(_SpinJamButton):
    """Decrease the lyric delay so lines appear sooner."""

    _attr_translation_key = "lyrics_earlier"
    _attr_name = "Lyrics earlier"
    _attr_icon = "mdi:chevron-double-up"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_lyrics_earlier"
        self.entity_id = BUTTON_LYRICS_EARLIER_ENTITY_ID

    async def async_press(self) -> None:
        await self.coordinator.async_nudge_lyric_offset(-self.coordinator.lyric_nudge_ms)


class SpinJamLyricsLaterButton(_SpinJamButton):
    """Increase the lyric delay so lines appear later."""

    _attr_translation_key = "lyrics_later"
    _attr_name = "Lyrics later"
    _attr_icon = "mdi:chevron-double-down"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_lyrics_later"
        self.entity_id = BUTTON_LYRICS_LATER_ENTITY_ID

    async def async_press(self) -> None:
        await self.coordinator.async_nudge_lyric_offset(self.coordinator.lyric_nudge_ms)


class SpinJamResetLyricDelayButton(_SpinJamButton):
    """Restore the lyric delay from when the entry was last loaded."""

    _attr_translation_key = "reset_lyric_delay"
    _attr_name = "Reset lyric delay"
    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_reset_lyric_delay"
        self.entity_id = BUTTON_LYRIC_DELAY_RESET_ENTITY_ID

    async def async_press(self) -> None:
        await self.coordinator.async_reset_lyric_offset()
