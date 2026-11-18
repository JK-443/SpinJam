"""SpinJam Cast, tracking, and lyrics switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_RECAST_ON_STARTUP,
    DEFAULT_RECAST_ON_STARTUP,
    DOMAIN,
    SWITCH_CAST_ENTITY_ID,
    SWITCH_LYRICS_ENTITY_ID,
    SWITCH_TRACKING_ENTITY_ID,
)
from .coordinator import SpinJamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SpinJamCoordinator = hass.data[DOMAIN][entry.entry_id]
    cast_switch = SpinJamCastSwitch(coordinator, entry)
    tracking_switch = SpinJamTrackingSwitch(coordinator, entry)
    lyrics_switch = SpinJamLyricsSwitch(coordinator, entry)
    async_add_entities([cast_switch, tracking_switch, lyrics_switch])
    coordinator.cast_switch = cast_switch
    coordinator.tracking_switch = tracking_switch
    coordinator.lyrics_switch = lyrics_switch


class _SpinJamSwitchBase(CoordinatorEntity[SpinJamCoordinator], RestoreEntity, SwitchEntity):
    """Shared device info for SpinJam switches."""

    _attr_has_entity_name = False

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
    """Master SpinJam on/off (cast + tracking). Same as spinjam.start / stop."""

    _attr_name = "SpinJam"
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


class SpinJamTrackingSwitch(_SpinJamSwitchBase):
    """Pause or resume source following / polling for now-playing.

    Turning tracking off while Cast is active also stops Cast (clears
    now-playing). Turning tracking on does not start Cast — use the SpinJam
    master switch (``switch.spinjam_cast``) for that.
    """

    _attr_name = "SpinJam Tracking"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: SpinJamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = "spinjam_tracking"
        self.entity_id = SWITCH_TRACKING_ENTITY_ID

    @property
    def is_on(self) -> bool:
        return self.coordinator.tracking_enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # After HA restart Cast is off unless recast_on_startup already fired.
        # Match cast: do not restore tracking ON while Cast is off.
        if self.coordinator.cast_active:
            await self.coordinator.async_set_tracking(True)
        else:
            await self.coordinator.async_set_tracking(False)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_set_tracking(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _ = kwargs
        await self.coordinator.async_set_tracking(False)
        self.async_write_ha_state()


class SpinJamLyricsSwitch(_SpinJamSwitchBase):
    """Show/hide lyrics on the TV card (cover-art layout when off).

    Persisted across restarts. Default on. Live — no Cast restart.
    """

    _attr_name = "SpinJam Lyrics"
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
