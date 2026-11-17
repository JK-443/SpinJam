"""SpinJam update coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cast import (
    async_end_cast,
    async_power_off_display,
    async_show_now_playing,
    async_wait_for_lovelace_app,
    async_wake_display,
    cast_options,
)
from .cast_entities import cast_platform_status
from .const import (
    ATTR_ALBUM_LOCK,
    ATTR_DISPLAYS,
    ATTR_LYRIC_CURRENT,
    ATTR_LYRIC_LINES,
    ATTR_LYRIC_NEXT,
    ATTR_LYRIC_OFFSET_MS,
    ATTR_SELECTED_DISPLAY,
    ATTR_SYNC_OFFSET_MS,
    CAST_LAUNCH_GRACE_SEC,
    CONF_BUILTIN_CASTING,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_POWER_OFF_DISPLAY_ON_STOP,
    CONF_RECAST_INTERVAL,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_UPDATE_INTERVAL,
    CONF_VIEW_PATH,
    CONF_VINYL_PLAYER,
    DEFAULT_BUILTIN_CASTING,
    DEFAULT_LYRIC_OFFSET_MS,
    DEFAULT_LYRICS_ENABLED,
    DEFAULT_POWER_OFF_DISPLAY_ON_STOP,
    DEFAULT_SYNC_OFFSET_MS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
    LOVELACE_APP_NAMES,
    MQTT_CMD_CLEAR,
    MQTT_CMD_IDENTIFY,
    MQTT_CMD_SELECT_ALBUM,
    MQTT_CMD_SYNC_OFFSET,
)
from .frontend import card_file_hash
from .lyrics import LrcLibClient, LyricsResult, line_at, lines_payload
from .source import ActiveSource, select_active_source, snapshot_from_state

if TYPE_CHECKING:
    from .number import SpinJamLyricOffsetNumber
    from .select import SpinJamDisplaySelect
    from .switch import SpinJamCastSwitch, SpinJamTrackingSwitch

_LOGGER = logging.getLogger(__name__)


@dataclass
class SpinJamData:
    active: ActiveSource | None = None
    lyric_current: str | None = None
    lyric_next: str | None = None
    lyric_lines: list[dict[str, Any]] | None = None
    lyrics: LyricsResult | None = None
    album_lock: str | None = None
    sync_offset_ms: int = 0
    lyric_offset_ms: int = 0
    position_updated_at: datetime | None = None
    tracking_enabled: bool = True
    cast_active: bool = False


class SpinJamCoordinator(DataUpdateCoordinator[SpinJamData]):
    """Aggregate configured media players into one now-playing view."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        options = {**entry.data, **entry.options}
        interval = float(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        self._poll_interval = timedelta(seconds=max(0.5, interval))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._poll_interval,
        )
        self.data = SpinJamData(
            sync_offset_ms=int(options.get(CONF_SYNC_OFFSET_MS, DEFAULT_SYNC_OFFSET_MS)),
            lyric_offset_ms=int(
                options.get(CONF_LYRIC_OFFSET_MS, DEFAULT_LYRIC_OFFSET_MS)
            ),
        )
        self._lyrics_client: LrcLibClient | None = None
        self._unsub_state: Any = None
        self._tracked: list[str] = []
        self._last_lyrics_key: str | None = None
        self.display_select: SpinJamDisplaySelect | None = None
        self.selected_display: str | None = None
        self.cast_switch: SpinJamCastSwitch | None = None
        self.tracking_switch: SpinJamTrackingSwitch | None = None
        self.lyric_offset_number: SpinJamLyricOffsetNumber | None = None
        self._cast_active = False
        self._cast_display: str | None = None
        self._unsub_recast: Any = None
        self._unsub_cast_display: Any = None
        self._tracking_enabled = True
        self._ending_cast = False
        self._cast_launch_until: datetime | None = None
        # Last SpinJam card JS version cast to each display (Cast caches resources).
        self._cast_card_version_by_display: dict[str, str] = {}
        self._last_publish_fingerprint: tuple[Any, ...] | None = None

    def _client(self) -> LrcLibClient:
        if self._lyrics_client is None:
            self._lyrics_client = LrcLibClient(async_get_clientsession(self.hass))
        return self._lyrics_client

    def _options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def source_players(self) -> list[str]:
        return list(self._options().get(CONF_SOURCE_PLAYERS, []))

    @property
    def vinyl_player(self) -> str | None:
        return self._options().get(CONF_VINYL_PLAYER) or None

    @property
    def displays(self) -> list[str]:
        """Configured display media_players (priority/order preserved).

        Migrates legacy ``display_entity`` into a one-item list when ``displays``
        is missing or empty.
        """
        options = self._options()
        raw = options.get(CONF_DISPLAYS)
        if isinstance(raw, str) and raw:
            return [raw]
        if isinstance(raw, list) and raw:
            return [str(item) for item in raw if item]
        legacy = options.get(CONF_DISPLAY_ENTITY)
        if legacy:
            return [str(legacy)]
        return []

    @property
    def lyrics_enabled(self) -> bool:
        return bool(self._options().get(CONF_LYRICS_ENABLED, DEFAULT_LYRICS_ENABLED))

    @property
    def lyric_offset_ms(self) -> int:
        return int(self.data.lyric_offset_ms)

    @property
    def builtin_casting(self) -> bool:
        return bool(self._options().get(CONF_BUILTIN_CASTING, DEFAULT_BUILTIN_CASTING))

    @property
    def power_off_display_on_stop(self) -> bool:
        return bool(
            self._options().get(
                CONF_POWER_OFF_DISPLAY_ON_STOP, DEFAULT_POWER_OFF_DISPLAY_ON_STOP
            )
        )

    @property
    def cast_active(self) -> bool:
        return self._cast_active

    @property
    def tracking_enabled(self) -> bool:
        return self._tracking_enabled

    async def async_setup(self) -> None:
        self._async_watch_sources()
        if self.displays and self.selected_display is None:
            self.selected_display = self.displays[0]
        await self.async_refresh()

    @callback
    def _async_watch_sources(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if not self._tracking_enabled:
            self._tracked = []
            return
        entities = list(dict.fromkeys([*self.source_players, self.vinyl_player or ""]))
        entities = [e for e in entities if e]
        self._tracked = entities
        if not entities:
            return

        @callback
        def _on_state(event: Event) -> None:
            if not self._tracking_enabled:
                return
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_state = async_track_state_change_event(self.hass, entities, _on_state)

    async def async_shutdown(self) -> None:
        self._async_stop_recast()
        self._async_unwatch_cast_display()
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    def _collect_snapshots(self):
        snaps = []
        for entity_id in dict.fromkeys([*self.source_players, self.vinyl_player or ""]):
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            attrs = dict(state.attributes)
            attrs["last_changed"] = state.last_changed
            snaps.append(snapshot_from_state(entity_id, state.state, attrs))
        return snaps

    def _idle_data(self, *, tracking_enabled: bool | None = None) -> SpinJamData:
        return SpinJamData(
            active=None,
            lyric_current=None,
            lyric_next=None,
            lyric_lines=None,
            lyrics=None,
            album_lock=self.data.album_lock if self.data else None,
            sync_offset_ms=self.data.sync_offset_ms if self.data else 0,
            lyric_offset_ms=self.data.lyric_offset_ms if self.data else 0,
            position_updated_at=None,
            tracking_enabled=(
                self._tracking_enabled if tracking_enabled is None else tracking_enabled
            ),
            cast_active=self._cast_active,
        )

    def _data_fingerprint(self, data: SpinJamData) -> tuple[Any, ...]:
        active = data.active
        return (
            None
            if active is None
            else (
                active.entity_id,
                active.playing,
                active.title,
                active.artist,
                active.album,
                active.art_url,
                active.duration,
                active.position,
                active.kind,
            ),
            data.lyric_current,
            data.lyric_next,
            None if data.lyric_lines is None else len(data.lyric_lines),
            data.sync_offset_ms,
            data.lyric_offset_ms,
            data.album_lock,
            data.tracking_enabled,
            data.cast_active,
            # Only fingerprint position clock when we have a media_position.
            data.position_updated_at if active and active.position is not None else None,
            self.selected_display,
            tuple(self.displays),
        )

    def _publish_data(self, data: SpinJamData) -> SpinJamData:
        """Publish coordinator data only when the public fingerprint changes."""
        fingerprint = self._data_fingerprint(data)
        if fingerprint == self._last_publish_fingerprint and self.data is not None:
            return self.data
        self._last_publish_fingerprint = fingerprint
        return data

    async def _async_update_data(self) -> SpinJamData:
        # Tracking off: idle / no metadata (avoid stale "playing").
        if not self._tracking_enabled:
            return self._publish_data(self._idle_data(tracking_enabled=False))

        options = self._options()
        # Prefer live in-memory offsets (options persist without reload).
        sync_offset = int(self.data.sync_offset_ms)
        lyric_offset = int(self.data.lyric_offset_ms)
        # Keep in sync if options were changed via the UI (after a real reload).
        if CONF_SYNC_OFFSET_MS in options:
            sync_offset = int(options.get(CONF_SYNC_OFFSET_MS, sync_offset))
        if CONF_LYRIC_OFFSET_MS in options:
            lyric_offset = int(options.get(CONF_LYRIC_OFFSET_MS, lyric_offset))

        active = select_active_source(
            self._collect_snapshots(),
            priority=self.source_players,
            vinyl_entity_id=self.vinyl_player,
            sync_offset_ms=sync_offset,
        )

        lyrics: LyricsResult | None = None
        lyric_current = None
        lyric_next = None
        lyric_lines = None

        if active and self.lyrics_enabled and active.artist and active.title:
            key = f"{active.artist}|{active.title}|{active.album}|{active.duration}"
            if key != self._last_lyrics_key or self.data.lyrics is None:
                lyrics = await self._client().fetch(
                    artist=active.artist,
                    title=active.title,
                    album=active.album,
                    duration=active.duration,
                )
                self._last_lyrics_key = key
            else:
                lyrics = self.data.lyrics
            lyric_pos = None
            if active.position is not None:
                # Positive lyric_offset_ms = lyrics appear later → look earlier in LRC.
                lyric_pos = max(0.0, active.position - (lyric_offset / 1000.0))
                if lyrics:
                    lyric_current, lyric_next = line_at(lyrics.lines, lyric_pos)
            if lyrics:
                from .const import LYRIC_LINES_ATTR_MAX, LYRIC_LINES_WINDOW_BEFORE

                lyric_lines = lines_payload(
                    lyrics.lines,
                    position=lyric_pos,
                    max_lines=LYRIC_LINES_ATTR_MAX,
                    before=LYRIC_LINES_WINDOW_BEFORE,
                )
        else:
            self._last_lyrics_key = None

        # Keep select options in sync after options reload.
        if self.display_select is not None:
            self.display_select._sync_options_from_coordinator()  # noqa: SLF001

        # Only refresh the position clock when the source exposes media_position.
        # Sources like TV audio would otherwise force a state write every second.
        if active and active.position is not None:
            position_updated_at = datetime.now(timezone.utc)
        elif active:
            prev = self.data.active if self.data else None
            same_track = (
                prev is not None
                and prev.entity_id == active.entity_id
                and prev.title == active.title
                and prev.artist == active.artist
            )
            position_updated_at = (
                self.data.position_updated_at if same_track else None
            )
        else:
            position_updated_at = None

        return self._publish_data(
            SpinJamData(
                active=active,
                lyric_current=lyric_current,
                lyric_next=lyric_next,
                lyric_lines=lyric_lines,
                lyrics=lyrics,
                album_lock=self.data.album_lock,
                sync_offset_ms=sync_offset,
                lyric_offset_ms=lyric_offset,
                position_updated_at=position_updated_at,
                tracking_enabled=True,
                cast_active=self._cast_active,
            )
        )

    async def async_set_tracking(
        self, enabled: bool, *, from_cast_stop: bool = False
    ) -> None:
        """Enable or pause source following / coordinator polling.

        Tracking off while a Cast session is active also stops Cast (master
        linkage). Tracking on does **not** start Cast. When off, now-playing
        clears to idle (no stale metadata).
        """
        enabled = bool(enabled)
        if not enabled and self._cast_active and not from_cast_stop:
            await self.async_stop()
            return
        if self._tracking_enabled == enabled:
            return
        self._tracking_enabled = enabled
        if enabled:
            self.update_interval = self._poll_interval
            self._async_watch_sources()
            await self.async_request_refresh()
        else:
            self.update_interval = None
            if self._unsub_state:
                self._unsub_state()
                self._unsub_state = None
            self._tracked = []
            self._last_lyrics_key = None
            self.async_set_updated_data(self._idle_data(tracking_enabled=False))
            self._last_publish_fingerprint = self._data_fingerprint(self.data)
        if self.tracking_switch is not None and self.tracking_switch.hass is not None:
            self.tracking_switch.async_write_ha_state()

    def _persist_live_option(self, key: str, value: int) -> None:
        """Write an offset into options without triggering a full reload."""
        options = {**self.entry.options, key: value}
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def async_set_sync_offset(self, offset_ms: int) -> None:
        offset_ms = max(-2000, min(2000, int(offset_ms)))
        self.data.sync_offset_ms = offset_ms
        self._persist_live_option(CONF_SYNC_OFFSET_MS, offset_ms)
        await self._async_mqtt_publish(MQTT_CMD_SYNC_OFFSET, str(offset_ms))
        if self._tracking_enabled:
            await self.async_request_refresh()
        else:
            self.async_set_updated_data(
                SpinJamData(
                    active=self.data.active,
                    lyric_current=self.data.lyric_current,
                    lyric_next=self.data.lyric_next,
                    lyric_lines=self.data.lyric_lines,
                    lyrics=self.data.lyrics,
                    album_lock=self.data.album_lock,
                    sync_offset_ms=offset_ms,
                    lyric_offset_ms=self.data.lyric_offset_ms,
                    position_updated_at=self.data.position_updated_at,
                    tracking_enabled=self.data.tracking_enabled,
                    cast_active=self._cast_active,
                )
            )

    async def async_set_lyric_offset(self, offset_ms: int) -> None:
        """Set lyric display offset (ms; positive = lyrics later). Live, no reload."""
        offset_ms = max(-5000, min(5000, int(offset_ms)))
        self.data.lyric_offset_ms = offset_ms
        self._persist_live_option(CONF_LYRIC_OFFSET_MS, offset_ms)
        if self.lyric_offset_number is not None and self.lyric_offset_number.hass:
            self.lyric_offset_number._attr_native_value = float(offset_ms)  # noqa: SLF001
            self.lyric_offset_number.async_write_ha_state()

        held = self.data
        lyric_current = held.lyric_current
        lyric_next = held.lyric_next
        if held.lyrics and held.active and held.active.position is not None:
            lyric_pos = max(0.0, held.active.position - (offset_ms / 1000.0))
            lyric_current, lyric_next = line_at(held.lyrics.lines, lyric_pos)

        self.async_set_updated_data(
            SpinJamData(
                active=held.active,
                lyric_current=lyric_current,
                lyric_next=lyric_next,
                lyric_lines=held.lyric_lines,
                lyrics=held.lyrics,
                album_lock=held.album_lock,
                sync_offset_ms=held.sync_offset_ms,
                lyric_offset_ms=offset_ms,
                position_updated_at=held.position_updated_at,
                tracking_enabled=held.tracking_enabled,
                cast_active=self._cast_active,
            )
        )
        self._last_publish_fingerprint = self._data_fingerprint(self.data)

    async def async_identify(self) -> None:
        await self._async_mqtt_publish(MQTT_CMD_IDENTIFY, "press")

    async def async_select_album(self, album: str) -> None:
        self.data.album_lock = album
        await self._async_mqtt_publish(MQTT_CMD_SELECT_ALBUM, album)
        if self._tracking_enabled:
            await self.async_request_refresh()

    async def async_clear_lock(self) -> None:
        self.data.album_lock = None
        await self._async_mqtt_publish(MQTT_CMD_CLEAR, "clear")
        if self._tracking_enabled:
            await self.async_request_refresh()

    async def async_start(self, display: str | None = None) -> str:
        """Select a display, cast (master on), enable tracking, fire ``spinjam_start``."""
        configured = self.displays
        if not configured:
            raise ServiceValidationError(
                "No displays configured for SpinJam. Add media_player entities under Displays."
            )
        target = display or self.selected_display or configured[0]
        if target not in configured:
            raise ServiceValidationError(
                f"{target} is not a configured SpinJam display. Choose one of: {', '.join(configured)}"
            )
        if self.display_select is not None:
            await self.display_select.async_select_option(target)
        else:
            self.selected_display = target

        # Casting always enables tracking (master on).
        await self.async_set_tracking(True)

        opts = cast_options(self._options())
        do_builtin = self.builtin_casting
        if do_builtin:
            status = cast_platform_status(self.hass, target)
            if status == "not_cast":
                _LOGGER.warning(
                    "Display %s is not a Google Cast entity (platform != cast); "
                    "skipping cast.show_lovelace_view — spinjam_start will still fire",
                    target,
                )
                do_builtin = False

        if do_builtin:
            ok = await self._async_cast_lovelace_view(
                target,
                dashboard_path=str(opts[CONF_DASHBOARD_PATH]),
                view_path=str(opts[CONF_VIEW_PATH]),
            )
            if not ok:
                _LOGGER.warning(
                    "SpinJam cast to %s failed — leaving switch.spinjam_cast off",
                    target,
                )
                self._async_set_cast_active(False)
                if self.cast_switch is not None and self.cast_switch.hass is not None:
                    self.cast_switch.async_write_ha_state()
                return target
            self._async_schedule_recast(opts)
        else:
            self._async_stop_recast()

        self._async_set_cast_active(True, target)
        self.hass.bus.async_fire(EVENT_SPINJAM_START, {"display": target})
        await self.async_request_refresh()
        return target

    async def async_stop(self) -> None:
        """End Cast, stop recast, disable tracking, and clear now-playing."""
        self._async_stop_recast()
        display = self._cast_display or self.selected_display
        was_active = self._cast_active
        self._ending_cast = True
        try:
            if (
                display
                and was_active
                and self.builtin_casting
                and cast_platform_status(self.hass, display) != "not_cast"
            ):
                await async_end_cast(self.hass, display)
                if self.power_off_display_on_stop:
                    await async_power_off_display(self.hass, display)
            self._async_set_cast_active(False)
        finally:
            self._ending_cast = False

        await self.async_set_tracking(False, from_cast_stop=True)
        self._last_lyrics_key = None
        self.async_set_updated_data(self._idle_data(tracking_enabled=False))
        self._last_publish_fingerprint = self._data_fingerprint(self.data)

        payload: dict[str, Any] = {}
        if display:
            payload["display"] = display
        self.hass.bus.async_fire(EVENT_SPINJAM_STOP, payload)

    def _async_set_cast_active(self, active: bool, display: str | None = None) -> None:
        self._cast_active = active
        if active:
            self._cast_display = display
            self._async_watch_cast_display()
        else:
            self._async_unwatch_cast_display()
            self._cast_display = None
            self._cast_launch_until = None
        if self.data is not None:
            self.data.cast_active = active
        if self.cast_switch is not None and self.cast_switch.hass is not None:
            self.cast_switch.async_write_ha_state()

    def _mark_cast_launch(self) -> None:
        self._cast_launch_until = datetime.now(timezone.utc) + timedelta(
            seconds=CAST_LAUNCH_GRACE_SEC
        )

    def _async_watch_cast_display(self) -> None:
        self._async_unwatch_cast_display()
        if not self._cast_display or not self.builtin_casting:
            return

        @callback
        def _on_display(event: Event) -> None:
            if self._ending_cast or not self._cast_active:
                return
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            # Ignore brief off/standby flaps while the Cast app (re)launches.
            now = datetime.now(timezone.utc)
            if self._cast_launch_until and now < self._cast_launch_until:
                return
            if new_state.state == STATE_UNAVAILABLE:
                _LOGGER.debug(
                    "Cast display %s unavailable — clearing SpinJam cast session",
                    self._cast_display,
                )
                self.hass.async_create_task(self.async_stop())
                return
            app = new_state.attributes.get("app_name")
            if app and str(app) not in LOVELACE_APP_NAMES:
                _LOGGER.debug(
                    "Cast display %s app_name=%s — ending SpinJam session",
                    self._cast_display,
                    app,
                )
                self.hass.async_create_task(self.async_stop())

        self._unsub_cast_display = async_track_state_change_event(
            self.hass, [self._cast_display], _on_display
        )

    def _async_unwatch_cast_display(self) -> None:
        if self._unsub_cast_display:
            self._unsub_cast_display()
            self._unsub_cast_display = None

    def _async_schedule_recast(self, opts: dict[str, Any]) -> None:
        self._async_stop_recast()
        if not self.builtin_casting or not opts.get(CONF_RECAST_WHILE_PLAYING):
            return
        interval = max(15.0, float(opts.get(CONF_RECAST_INTERVAL) or 45.0))

        @callback
        def _tick(_now: datetime) -> None:
            self.hass.async_create_task(self._async_recast_tick())

        self._unsub_recast = async_track_time_interval(
            self.hass, _tick, timedelta(seconds=interval)
        )

    def _async_stop_recast(self) -> None:
        if self._unsub_recast:
            self._unsub_recast()
            self._unsub_recast = None

    async def _async_recast_tick(self) -> None:
        if not self.builtin_casting or not self._cast_active or not self._cast_display:
            return
        active = self.data.active
        if active is None or not active.playing:
            return
        opts = cast_options(self._options())
        ok = await self._async_cast_lovelace_view(
            self._cast_display,
            dashboard_path=str(opts[CONF_DASHBOARD_PATH]),
            view_path=str(opts[CONF_VIEW_PATH]),
        )
        if not ok:
            _LOGGER.warning("SpinJam re-cast to %s failed", self._cast_display)

    async def _async_cast_lovelace_view(
        self,
        entity_id: str,
        *,
        dashboard_path: str,
        view_path: str,
    ) -> bool:
        """Wake, cast, and verify Lovelace — quit first when card JS changed."""
        version = card_file_hash()
        last = self._cast_card_version_by_display.get(entity_id)
        if last is not None and last != version:
            _LOGGER.info(
                "SpinJam card version changed (%s → %s) on %s — quitting Cast app before re-cast",
                last,
                version,
                entity_id,
            )
            await async_end_cast(self.hass, entity_id)

        self._mark_cast_launch()
        if not await async_wake_display(self.hass, entity_id):
            return False

        shown = await async_show_now_playing(
            self.hass,
            entity_id=entity_id,
            dashboard_path=dashboard_path,
            view_path=view_path,
            blocking=True,
        )
        if not shown:
            return False

        if not await async_wait_for_lovelace_app(self.hass, entity_id):
            return False

        self._cast_card_version_by_display[entity_id] = version
        self._mark_cast_launch()
        return True

    async def _async_mqtt_publish(self, topic: str, payload: str) -> None:
        try:
            await self.hass.services.async_call(
                "mqtt",
                "publish",
                {"topic": topic, "payload": payload, "qos": 0, "retain": False},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 — mqtt may be missing during tests
            _LOGGER.debug("MQTT publish skipped for %s", topic)

    def as_attributes(self) -> dict[str, Any]:
        active = self.data.active
        attrs: dict[str, Any] = {
            ATTR_SYNC_OFFSET_MS: self.data.sync_offset_ms,
            ATTR_LYRIC_OFFSET_MS: self.data.lyric_offset_ms,
            ATTR_LYRIC_CURRENT: self.data.lyric_current,
            ATTR_LYRIC_NEXT: self.data.lyric_next,
            ATTR_LYRIC_LINES: self.data.lyric_lines,
            ATTR_ALBUM_LOCK: self.data.album_lock,
            ATTR_DISPLAYS: list(self.displays),
            ATTR_SELECTED_DISPLAY: self.selected_display,
            "tracking_enabled": self._tracking_enabled,
            "cast_active": self._cast_active,
            "builtin_casting": self.builtin_casting,
        }
        if active:
            attrs["active_source"] = active.entity_id
            attrs["source_kind"] = active.kind
            if active.artist:
                attrs["media_artist"] = active.artist
            if active.title:
                attrs["media_title"] = active.title
            if active.album:
                attrs["media_album_name"] = active.album
            if active.art_url:
                attrs["entity_picture"] = active.art_url
            if active.duration is not None:
                attrs["media_duration"] = active.duration
            if active.position is not None:
                attrs["media_position"] = active.position
        return attrs
