"""SpinJam display and audio-source select entities."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SELECT_DISPLAY_ENTITY_ID, SELECT_SOURCE_ENTITY_ID
from .coordinator import SpinJamCoordinator
from .source import (
    SOURCE_AUTOMATIC,
    SourceChoice,
    build_source_choices,
    configured_source_entity_ids,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    display = SpinJamDisplaySelect(coordinator, entry)
    source = SpinJamSourceSelect(coordinator, entry)
    async_add_entities([display, source])
    coordinator.display_select = display
    coordinator.source_select = source


def _friendly_name(hass: HomeAssistant | None, entity_id: str) -> str | None:
    if hass is None:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    name = state.attributes.get("friendly_name") or state.name
    if not name or name == entity_id:
        return None
    return str(name)


class SpinJamDisplaySelect(CoordinatorEntity[SpinJamCoordinator], RestoreEntity, SelectEntity):
    """Choose which configured display SpinJam should cast to."""

    _attr_has_entity_name = True
    _attr_translation_key = "display"
    _attr_name = "Display"
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


class SpinJamSourceSelect(CoordinatorEntity[SpinJamCoordinator], RestoreEntity, SelectEntity):
    """Choose which audio player SpinJam monitors.

    ``Automatic`` keeps the configured ranking (playing over paused, sticky
    within a track). Any other option follows only that player.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "source"
    _attr_name = "Source"
    _attr_icon = "mdi:speaker-multiple"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = "spinjam_source"
        self.entity_id = SELECT_SOURCE_ENTITY_ID
        self._by_label: dict[str, str | None] = {SOURCE_AUTOMATIC: None}
        self._label_by_entity: dict[str, str] = {}
        self._attr_options = [SOURCE_AUTOMATIC]
        self._attr_current_option = SOURCE_AUTOMATIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }

    def _choices(self) -> list[SourceChoice]:
        entity_ids = configured_source_entity_ids(
            self.coordinator.source_players,
            self.coordinator.vinyl_player,
        )
        players = [(entity_id, _friendly_name(self.hass, entity_id)) for entity_id in entity_ids]
        return build_source_choices(players)

    def _rebuild_maps(self) -> None:
        choices = self._choices()
        self._by_label = {choice.label: choice.entity_id for choice in choices}
        self._label_by_entity = {
            choice.entity_id: choice.label
            for choice in choices
            if choice.entity_id
        }
        self._attr_options = [choice.label for choice in choices]

    def _apply_current(self, preferred_entity: str | None, preferred_label: str | None) -> None:
        if preferred_entity and preferred_entity in self._label_by_entity:
            self._attr_current_option = self._label_by_entity[preferred_entity]
        elif preferred_label in self._attr_options:
            self._attr_current_option = preferred_label
        else:
            self._attr_current_option = SOURCE_AUTOMATIC
        entity_id = self._by_label.get(self._attr_current_option)
        self.coordinator.selected_source_entity_id = entity_id

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"source_entity_id": self.coordinator.selected_source_entity_id}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._rebuild_maps()
        last = await self.async_get_last_state()
        preferred_entity = None
        preferred_label = None
        if last is not None:
            preferred_label = last.state
            if last.attributes:
                preferred_entity = last.attributes.get("source_entity_id") or None
        self._apply_current(preferred_entity, preferred_label)
        self.async_write_ha_state()
        if self.coordinator.selected_source_entity_id:
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.sync_options(from_coordinator=True)
        super()._handle_coordinator_update()

    def sync_options(self, *, from_coordinator: bool = False) -> None:
        """Rebuild options from the current source / vinyl configuration."""
        previous = self._attr_current_option
        previous_entity = self.coordinator.selected_source_entity_id
        self._rebuild_maps()
        self._apply_current(previous_entity, previous)
        changed = (
            self._attr_current_option != previous
            or self.coordinator.selected_source_entity_id != previous_entity
        )
        if self.hass is not None and changed:
            self.async_write_ha_state()
            if not from_coordinator:
                self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def async_select_option(self, option: str) -> None:
        self._rebuild_maps()
        if option not in self._attr_options:
            return
        self._attr_current_option = option
        self.coordinator.selected_source_entity_id = self._by_label.get(option)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
