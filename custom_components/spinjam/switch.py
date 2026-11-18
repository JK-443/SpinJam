"""SpinJam Cast and lyrics switches.

Tracking is not an entity. Cast on starts tracking and the cast; Cast off
stops both. ``switch.spinjam_tracking`` is removed from the registry on
upgrade.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_RECAST_ON_STARTUP,
    DEFAULT_RECAST_ON_STARTUP,
    DOMAIN,
    LEGACY_TRACKING_UNIQUE_ID,
    SWITCH_CAST_ENTITY_ID,
    SWITCH_LYRICS_ENTITY_ID,
    SWITCH_TRACKING_ENTITY_ID,
)
from .coordinator import SpinJamCoordinator

_LOGGER = logging.getLogger(__name__)


def async_remove_legacy_tracking_switch(hass: HomeAssistant) -> str | None:
    """Mark the retired tracking switch unavailable, then drop it from the registry.

    Matches the old unique id and the default entity id. Safe to call more
    than once.
    """
    from homeassistant.helpers import entity_registry as er

    try:
        registry = er.async_get(hass)
    except Exception:  # noqa: BLE001 — registry is not ready in some unit tests
        return None

    found: list[str] = []
    direct = registry.async_get_entity_id("switch", DOMAIN, LEGACY_TRACKING_UNIQUE_ID)
    if direct:
        found.append(direct)
    entry = registry.async_get(SWITCH_TRACKING_ENTITY_ID)
    if entry is not None and (
        entry.unique_id == LEGACY_TRACKING_UNIQUE_ID or entry.platform == DOMAIN
    ):
        found.append(entry.entity_id)
    entities = getattr(registry, "entities", None)
    if isinstance(entities, dict):
        for item in entities.values():
            if getattr(item, "unique_id", None) == LEGACY_TRACKING_UNIQUE_ID and getattr(
                item, "domain", None
            ) == "switch":
                found.append(item.entity_id)

    removed: str | None = None
    for entity_id in dict.fromkeys(found):
        if hass.states.get(entity_id) is not None:
            hass.states.async_set(entity_id, STATE_UNAVAILABLE)
        registry.async_remove(entity_id)
        if hass.states.get(entity_id) is not None:
            hass.states.async_remove(entity_id)
        removed = entity_id
        _LOGGER.info("Removed retired SpinJam tracking switch %s", entity_id)
    return removed


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    cast_switch = SpinJamCastSwitch(coordinator, entry)
    lyrics_switch = SpinJamLyricsSwitch(coordinator, entry)
    async_add_entities([cast_switch, lyrics_switch])
    coordinator.cast_switch = cast_switch
    coordinator.lyrics_switch = lyrics_switch


class _SpinJamSwitchBase(CoordinatorEntity[SpinJamCoordinator], RestoreEntity, SwitchEntity):
    """Shared device info for SpinJam switches."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "SpinJam",
            "manufacturer": "SpinJam",
            "model": "now-playing",
        }


class SpinJamCastSwitch(_SpinJamSwitchBase):
    """Master on/off. On starts tracking and cast; off stops both.

    Same as ``spinjam.start`` / ``spinjam.stop``.
    """

    _attr_translation_key = "cast"
    _attr_name = "Cast"
    _attr_icon = "mdi:cast"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_cast"
        self.entity_id = SWITCH_CAST_ENTITY_ID
        self._restored_on = False

    @property
    def is_on(self) -> bool:
        return self.coordinator.cast_active

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._restored_on = bool(last and last.state == STATE_ON)
        options = {**self._entry.data, **self._entry.options}
        recast_on_startup = bool(
            options.get(CONF_RECAST_ON_STARTUP, DEFAULT_RECAST_ON_STARTUP)
        )
        # Cast sessions do not survive HA restart. Only re-start when opted in.
        if self._restored_on and recast_on_startup and self.coordinator.displays:
            await self.coordinator.async_start()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_start()

    async def async_turn_off(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_stop()


class SpinJamLyricsSwitch(_SpinJamSwitchBase):
    """Show or hide lyrics on the TV card.

    Off switches the Cast view to the full-width stage. Persisted across
    restarts. Default on. Live — no Cast restart.
    """

    _attr_translation_key = "lyrics"
    _attr_name = "Lyrics"
    _attr_icon = "mdi:microphone-variant"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_lyrics"
        self.entity_id = SWITCH_LYRICS_ENTITY_ID

    @property
    def is_on(self) -> bool:
        return self.coordinator._lyrics_display_enabled  # noqa: SLF001

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        # Default on when no prior state.
        enabled = True if last is None else last.state == STATE_ON
        await self.coordinator.async_set_lyrics_enabled(enabled)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_set_lyrics_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_set_lyrics_enabled(False)
        self.async_write_ha_state()
