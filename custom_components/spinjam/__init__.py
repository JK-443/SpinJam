"""The SpinJam Home Assistant integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    DOMAIN,
    SERVICE_CLEAR_LOCK,
    SERVICE_IDENTIFY,
    SERVICE_SELECT_ALBUM,
    SERVICE_SET_SYNC_OFFSET,
    SERVICE_START,
    SERVICE_STOP,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SpinJam from a config entry."""
    from homeassistant.const import Platform

    from .coordinator import SpinJamCoordinator

    coordinator = SpinJamCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.MEDIA_PLAYER, Platform.SELECT]
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import SpinJamCoordinator

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SpinJamCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    import voluptuous as vol
    from homeassistant.core import ServiceCall
    from homeassistant.helpers import config_validation as cv

    from .coordinator import SpinJamCoordinator

    if hass.services.has_service(DOMAIN, SERVICE_IDENTIFY):
        return

    async def _coord() -> SpinJamCoordinator | None:
        entries = hass.data.get(DOMAIN) or {}
        if not entries:
            return None
        return next(iter(entries.values()))

    async def handle_identify(call: ServiceCall) -> None:
        _ = call
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_identify()

    async def handle_sync_offset(call: ServiceCall) -> None:
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_set_sync_offset(int(call.data["offset_ms"]))

    async def handle_select_album(call: ServiceCall) -> None:
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_select_album(call.data["album"])

    async def handle_clear_lock(call: ServiceCall) -> None:
        _ = call
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_clear_lock()

    async def handle_start(call: ServiceCall) -> None:
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_start(call.data.get("display"))

    async def handle_stop(call: ServiceCall) -> None:
        _ = call
        coordinator = await _coord()
        if coordinator:
            await coordinator.async_stop()

    hass.services.async_register(DOMAIN, SERVICE_IDENTIFY, handle_identify)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SYNC_OFFSET,
        handle_sync_offset,
        schema=vol.Schema(
            {
                vol.Required("offset_ms"): vol.All(
                    vol.Coerce(int), vol.Range(-2000, 2000)
                )
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SELECT_ALBUM,
        handle_select_album,
        schema=vol.Schema({vol.Required("album"): cv.string}),
    )
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_LOCK, handle_clear_lock)
    hass.services.async_register(
        DOMAIN,
        SERVICE_START,
        handle_start,
        schema=vol.Schema({vol.Optional("display"): cv.entity_id}),
    )
    hass.services.async_register(DOMAIN, SERVICE_STOP, handle_stop)
