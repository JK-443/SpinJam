"""SpinJam display target select entity."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SELECT_DISPLAY_ENTITY_ID
from .coordinator import SpinJamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    entity = SpinJamDisplaySelect(coordinator, entry)
    async_add_entities([entity])
    coordinator.display_select = entity


class SpinJamDisplaySelect(CoordinatorEntity[SpinJamCoordinator], RestoreEntity, SelectEntity):
    """Choose which configured display SpinJam should cast to."""

    _attr_has_entity_name = False
    _attr_name = "SpinJam Display"
    _attr_icon = "mdi:television"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = "spinjam_display"
        self.entity_id = SELECT_DISPLAY_ENTITY_ID
        self._attr_options = list(coordinator.displays)
        self._attr_current_option: str | None = (
            self._attr_options[0] if self._attr_options else None
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
        options = list(self.coordinator.displays)
        self._attr_options = options
        if last and last.state in options:
            self._attr_current_option = last.state
        elif options:
            if self._attr_current_option not in options:
                self._attr_current_option = options[0]
        else:
            self._attr_current_option = None
        self.coordinator.selected_display = self._attr_current_option

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_options_from_coordinator()
        super()._handle_coordinator_update()

    def _sync_options_from_coordinator(self) -> None:
        options = list(self.coordinator.displays)
        self._attr_options = options
        if not options:
            self._attr_current_option = None
        elif self._attr_current_option not in options:
            self._attr_current_option = options[0]
        self.coordinator.selected_display = self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        self._attr_current_option = option
        self.coordinator.selected_display = option
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
