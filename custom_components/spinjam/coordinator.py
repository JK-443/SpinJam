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

from .cast import async_end_cast, async_show_now_playing, cast_options
from .const import (
    ATTR_ALBUM_LOCK,
    ATTR_DISPLAYS,
    ATTR_LYRIC_CURRENT,
    ATTR_LYRIC_LINES,
    ATTR_LYRIC_NEXT,
    ATTR_LYRIC_OFFSET_MS,
    ATTR_SELECTED_DISPLAY,
    ATTR_SYNC_OFFSET_MS,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAYS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_RECAST_INTERVAL,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_UPDATE_INTERVAL,
    CONF_VIEW_PATH,
    CONF_VINYL_PLAYER,
    DEFAULT_LYRIC_OFFSET_MS,
    DEFAULT_LYRICS_ENABLED,
    DEFAULT_SYNC_OFFSET_MS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
    MQTT_CMD_CLEAR,
    MQTT_CMD_IDENTIFY,
    MQTT_CMD_SELECT_ALBUM,
    MQTT_CMD_SYNC_OFFSET,
)
from .lyrics import LrcLibClient, LyricsResult, line_at
from .source import ActiveSource, select_active_source, snapshot_from_state

if TYPE_CHECKING:
    from .select import SpinJamDisplaySelect

_LOGGER = logging.getLogger(__name__)

# Cap lyric payload size for state attributes (TV card still scrolls).
_MAX_LYRIC_LINES_ATTR = 120


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


class SpinJamCoordinator(DataUpdateCoordinator[SpinJamData]):
    """Aggregate configured media players into one now-playing view."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        options = {**entry.data, **entry.options}
        interval = float(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(0.5, interval)),
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
        self._cast_active = False
        self._cast_display: str | None = None
        self._unsub_recast: Any = None

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
        return int(self._options().get(CONF_LYRIC_OFFSET_MS, DEFAULT_LYRIC_OFFSET_MS))

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
        entities = list(dict.fromkeys([*self.source_players, self.vinyl_player or ""]))
        entities = [e for e in entities if e]
        self._tracked = entities
        if not entities:
            return

        @callback
        def _on_state(event: Event) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_state = async_track_state_change_event(self.hass, entities, _on_state)

    async def async_shutdown(self) -> None:
        self._async_stop_recast()
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

    @staticmethod
    def _lines_payload(lyrics: LyricsResult | None) -> list[dict[str, Any]] | None:
        if not lyrics or not lyrics.lines:
            return None
        lines = lyrics.lines[:_MAX_LYRIC_LINES_ATTR]
        return [{"t": round(line.start, 3), "text": line.text} for line in lines]

    async def _async_update_data(self) -> SpinJamData:
        options = self._options()
        sync_offset = int(options.get(CONF_SYNC_OFFSET_MS, self.data.sync_offset_ms))
        lyric_offset = int(options.get(CONF_LYRIC_OFFSET_MS, DEFAULT_LYRIC_OFFSET_MS))
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
            lyric_lines = self._lines_payload(lyrics)
            if lyrics and active.position is not None:
                lyric_pos = active.position + (lyric_offset / 1000.0)
                lyric_current, lyric_next = line_at(lyrics.lines, lyric_pos)
        else:
            self._last_lyrics_key = None

        # Keep select options in sync after options reload.
        if self.display_select is not None:
            self.display_select._sync_options_from_coordinator()  # noqa: SLF001

        return SpinJamData(
            active=active,
            lyric_current=lyric_current,
            lyric_next=lyric_next,
            lyric_lines=lyric_lines,
            lyrics=lyrics,
            album_lock=self.data.album_lock,
            sync_offset_ms=sync_offset,
            lyric_offset_ms=lyric_offset,
            position_updated_at=datetime.now(timezone.utc) if active else None,
        )

    async def async_set_sync_offset(self, offset_ms: int) -> None:
        self.data.sync_offset_ms = int(offset_ms)
        options = {**self.entry.options, CONF_SYNC_OFFSET_MS: int(offset_ms)}
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self._async_mqtt_publish(MQTT_CMD_SYNC_OFFSET, str(offset_ms))
        await self.async_request_refresh()

    async def async_identify(self) -> None:
        await self._async_mqtt_publish(MQTT_CMD_IDENTIFY, "press")

    async def async_select_album(self, album: str) -> None:
        self.data.album_lock = album
        await self._async_mqtt_publish(MQTT_CMD_SELECT_ALBUM, album)
        await self.async_request_refresh()

    async def async_clear_lock(self) -> None:
        self.data.album_lock = None
        await self._async_mqtt_publish(MQTT_CMD_CLEAR, "clear")
        await self.async_request_refresh()

    async def async_start(self, display: str | None = None) -> str:
        """Select a display, cast the now-playing view, and fire ``spinjam_start``."""
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

        opts = cast_options(self._options())
        await async_show_now_playing(
            self.hass,
            entity_id=target,
            dashboard_path=str(opts[CONF_DASHBOARD_PATH]),
            view_path=str(opts[CONF_VIEW_PATH]),
        )
        self._cast_active = True
        self._cast_display = target
        self._async_schedule_recast(opts)

        self.hass.bus.async_fire(EVENT_SPINJAM_START, {"display": target})
        await self.async_request_refresh()
        return target

    async def async_stop(self) -> None:
        """End the Cast session and fire ``spinjam_stop``."""
        self._async_stop_recast()
        display = self._cast_display or self.selected_display
        if display and self._cast_active:
            await async_end_cast(self.hass, display)
        self._cast_active = False
        payload: dict[str, Any] = {}
        if display:
            payload["display"] = display
        self._cast_display = None
        self.hass.bus.async_fire(EVENT_SPINJAM_STOP, payload)

    def _async_schedule_recast(self, opts: dict[str, Any]) -> None:
        self._async_stop_recast()
        if not opts.get(CONF_RECAST_WHILE_PLAYING):
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
        if not self._cast_active or not self._cast_display:
            return
        active = self.data.active
        if active is None or not active.playing:
            return
        opts = cast_options(self._options())
        await async_show_now_playing(
            self.hass,
            entity_id=self._cast_display,
            dashboard_path=str(opts[CONF_DASHBOARD_PATH]),
            view_path=str(opts[CONF_VIEW_PATH]),
        )

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
