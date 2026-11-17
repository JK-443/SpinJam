"""SpinJam lyric offset number entity."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_LYRIC_OFFSET_MS,
    DEFAULT_LYRIC_OFFSET_MS,
    DOMAIN,
    NUMBER_LYRIC_OFFSET_ENTITY_ID,
)
from .coordinator import SpinJamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    entity = SpinJamLyricOffsetNumber(coordinator, entry)
    async_add_entities([entity])
    coordinator.lyric_offset_number = entity


class SpinJamLyricOffsetNumber(
    CoordinatorEntity[SpinJamCoordinator], RestoreEntity, NumberEntity
):
    """Live lyric display offset in milliseconds (positive = lyrics later)."""

    _attr_has_entity_name = False
    _attr_name = "SpinJam Lyric Offset"
    _attr_icon = "mdi:tune-vertical"
    _attr_native_unit_of_measurement = "ms"
    _attr_native_min_value = -5000
    _attr_native_max_value = 5000
    _attr_native_step = 50
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = "spinjam_lyric_offset"
        self.entity_id = NUMBER_LYRIC_OFFSET_ENTITY_ID
        self._attr_native_value = float(
            coordinator.data.lyric_offset_ms
            if coordinator.data
            else DEFAULT_LYRIC_OFFSET_MS
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                await self.coordinator.async_set_lyric_offset(int(float(last.state)))
            except (TypeError, ValueError):
                pass
        self._attr_native_value = float(self.coordinator.data.lyric_offset_ms)
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = float(self.coordinator.data.lyric_offset_ms)
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_lyric_offset(int(round(value)))
        self._attr_native_value = float(self.coordinator.data.lyric_offset_ms)
        self.async_write_ha_state()
