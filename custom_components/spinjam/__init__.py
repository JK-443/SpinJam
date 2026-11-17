"""The SpinJam Home Assistant integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_DASHBOARD_PATH,
    CONF_LYRIC_OFFSET_MS,
    CONF_VIEW_PATH,
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_VIEW_PATH,
    DOMAIN,
    LEGACY_DASHBOARD_PATH,
    SERVICE_CLEAR_LOCK,
    SERVICE_CREATE_DASHBOARD,
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

PLATFORMS = ["media_player", "select", "switch", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SpinJam from a config entry."""
    from homeassistant.const import Platform

    from .coordinator import SpinJamCoordinator
    from .frontend import async_setup_frontend

    await async_setup_frontend(hass)

    coordinator = SpinJamCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry,
        [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SWITCH, Platform.NUMBER],
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to the latest version."""
    from .dashboard import dashboard_exists

    version = entry.version
    data = dict(entry.data)
    options = dict(entry.options)

    if version < 2:
        # v2: lyric_offset sign flip (positive = lyrics later) → negate stored values.
        for bag in (data, options):
            if CONF_LYRIC_OFFSET_MS in bag:
                try:
                    bag[CONF_LYRIC_OFFSET_MS] = -int(bag[CONF_LYRIC_OFFSET_MS])
                except (TypeError, ValueError):
                    bag[CONF_LYRIC_OFFSET_MS] = 0

        # Legacy default dashboard path "spinjam" is invalid in HA UI (needs hyphen).
        # Migrate only when that dashboard does not already exist.
        for bag in (data, options):
            path = bag.get(CONF_DASHBOARD_PATH)
            if path == LEGACY_DASHBOARD_PATH and not dashboard_exists(
                hass, LEGACY_DASHBOARD_PATH
            ):
                bag[CONF_DASHBOARD_PATH] = DEFAULT_DASHBOARD_PATH
                _LOGGER.info(
                    "Migrated dashboard_path from %s to %s",
                    LEGACY_DASHBOARD_PATH,
                    DEFAULT_DASHBOARD_PATH,
                )

        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
        _LOGGER.info("Migrated SpinJam config entry to version 2")

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    import voluptuous as vol
    from homeassistant.core import ServiceCall
    from homeassistant.helpers import config_validation as cv

    from .coordinator import SpinJamCoordinator
    from .dashboard import async_create_spinjam_dashboard, validate_dashboard_url_path

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

    async def handle_create_dashboard(call: ServiceCall) -> None:
        from homeassistant.exceptions import ServiceValidationError

        coordinator = await _coord()
        opts: dict[str, Any] = {}
        if coordinator is not None:
            opts = {**coordinator.entry.data, **coordinator.entry.options}
        path = call.data.get(CONF_DASHBOARD_PATH) or opts.get(
            CONF_DASHBOARD_PATH, DEFAULT_DASHBOARD_PATH
        )
        view = call.data.get(CONF_VIEW_PATH) or opts.get(
            CONF_VIEW_PATH, DEFAULT_VIEW_PATH
        )
        try:
            path = validate_dashboard_url_path(path)
        except vol.Invalid as err:
            raise ServiceValidationError(str(err)) from err
        result = await async_create_spinjam_dashboard(
            hass, dashboard_path=path, view_path=view
        )
        if coordinator is not None:
            hass.config_entries.async_update_entry(
                coordinator.entry,
                options={
                    **coordinator.entry.options,
                    CONF_DASHBOARD_PATH: result["dashboard_path"],
                    CONF_VIEW_PATH: result["view_path"],
                },
            )
        _LOGGER.info(
            "SpinJam dashboard ready at %s/%s (created=%s)",
            result["dashboard_path"],
            result["view_path"],
            result["created"],
        )

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
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_DASHBOARD,
        handle_create_dashboard,
        schema=vol.Schema(
            {
                vol.Optional(CONF_DASHBOARD_PATH): cv.string,
                vol.Optional(CONF_VIEW_PATH): cv.string,
            }
        ),
    )
