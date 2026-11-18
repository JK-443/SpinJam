"""Readout of the lyric delay as signed seconds plus a direction word."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_LYRIC_DELAY_ENTITY_ID
from .coordinator import SpinJamCoordinator
from .lyric_delay import format_lyric_delay


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpinJamLyricDelaySensor(coordinator, entry)])


class SpinJamLyricDelaySensor(CoordinatorEntity[SpinJamCoordinator], SensorEntity):
    """``+2.0 s (later)`` style label for the controls row."""

    _attr_has_entity_name = True
    _attr_translation_key = "lyric_delay"
    _attr_name = "Current delay"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "spinjam_lyric_delay"
        self.entity_id = SENSOR_LYRIC_DELAY_ENTITY_ID
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }

    @property
    def native_value(self) -> str:
        return format_lyric_delay(self.coordinator.lyric_offset_ms)
