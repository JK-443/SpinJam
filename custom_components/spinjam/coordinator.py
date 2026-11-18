"""SpinJam update coordinator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
import time
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
from .artwork import ArtworkResolver
from .const import (
    ARTWORK_DISK_CACHE_DIR,
    ARTWORK_DISK_CACHE_FILE,
    ATTR_ALBUM_LOCK,
    ATTR_ARTWORK_HD,
    ATTR_ARTWORK_NEXT,
    ATTR_ARTWORK_SOURCE,
    ATTR_DISPLAYS,
    ATTR_LYRIC_CURRENT,
    ATTR_LYRIC_LINES,
    ATTR_LYRIC_NEXT,
    ATTR_LYRIC_OFFSET_MS,
    ATTR_LYRICS_ENABLED,
    ATTR_LYRICS_SOURCE,
    ATTR_LYRICS_STATUS,
    ATTR_SELECTED_DISPLAY,
    ATTR_SYNC_OFFSET_MS,
    CAST_LAUNCH_GRACE_SEC,
    CONF_BUILTIN_CASTING,
    CONF_DASHBOARD_PATH,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAYS,
    CONF_FALLBACK_PROVIDERS,
    CONF_HD_ARTWORK,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_POWER_OFF_DISPLAY_ON_STOP,
    CONF_PREFETCH,
    CONF_RECAST_INTERVAL,
    CONF_RECAST_WHILE_PLAYING,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_UPDATE_INTERVAL,
    CONF_VIEW_PATH,
    CONF_VINYL_PLAYER,
    DEFAULT_BUILTIN_CASTING,
    DEFAULT_FALLBACK_PROVIDERS,
    DEFAULT_HD_ARTWORK,
    DEFAULT_LYRIC_OFFSET_MS,
    DEFAULT_LYRICS_ENABLED,
    DEFAULT_POWER_OFF_DISPLAY_ON_STOP,
    DEFAULT_PREFETCH,
    DEFAULT_SYNC_OFFSET_MS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_SPINJAM_START,
    EVENT_SPINJAM_STOP,
    LOVELACE_APP_NAMES,
    LYRICS_ERROR_RETRY_SEC,
    LYRICS_STATUS_DISABLED,
    LYRICS_STATUS_ERROR,
    LYRICS_STATUS_INSTRUMENTAL,
    LYRICS_STATUS_PLAIN,
    LYRICS_STATUS_SYNCED,
    LYRIC_LINES_ATTR_MAX,
    LYRIC_LINES_WINDOW_BEFORE,
    MQTT_CMD_CLEAR,
    MQTT_CMD_IDENTIFY,
    MQTT_CMD_SELECT_ALBUM,
    MQTT_CMD_SYNC_OFFSET,
)
from .frontend import card_file_hash
from .lyrics import (
    LrcLibClient,
    LyricsCache,
    LyricsLookup,
    LyricsResult,
    line_at,
    lines_payload,
    lyrics_kind,
    normalize_fallback_providers,
)
from .next_track import async_resolve_next_track
from .source import ActiveSource, select_active_source, snapshot_from_state

if TYPE_CHECKING:
    from .number import SpinJamLyricOffsetNumber
    from .select import SpinJamDisplaySelect
    from .switch import SpinJamCastSwitch, SpinJamLyricsSwitch, SpinJamTrackingSwitch

_LOGGER = logging.getLogger(__name__)


def _coerce_lookup(outcome: Any) -> tuple[str, LyricsResult | None, str | None]:
    """Accept LyricsLookup plus the legacy LyricsResult | None mock shape."""
    if isinstance(outcome, LyricsLookup):
        return outcome.status, outcome.result, outcome.source
    if isinstance(outcome, LyricsResult):
        return lyrics_kind(outcome), outcome, outcome.source
    return "not_found", None, None


@dataclass
class _TrackLyrics:
    """In-flight or settled lookup for one track signature."""

    key: str
    status: str | None
    result: LyricsResult | None
    source: str | None
    error_at: float | None = None


@dataclass
class SpinJamData:
    active: ActiveSource | None = None
    lyric_current: str | None = None
    lyric_next: str | None = None
    lyric_lines: list[dict[str, Any]] | None = None
    lyrics: LyricsResult | None = None
    lyrics_status: str | None = None
    lyrics_source: str | None = None
    album_lock: str | None = None
    sync_offset_ms: int = 0
    lyric_offset_ms: int = 0
    position_updated_at: datetime | None = None
    tracking_enabled: bool = False
    cast_active: bool = False
    artwork_hd: str | None = None
    artwork_source: str | None = None
    artwork_next: str | None = None
    lyrics_enabled: bool = True


class SpinJamCoordinator(DataUpdateCoordinator[SpinJamData]):
    """Aggregate configured media players into one now-playing view."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        options = {**entry.data, **entry.options}
        interval = float(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        self._poll_interval = timedelta(seconds=max(0.5, interval))
        # Tracking starts off after HA restart (Cast sessions do not survive).
        # The cast/tracking switches align this during async_added_to_hass.
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.data = SpinJamData(
            sync_offset_ms=int(options.get(CONF_SYNC_OFFSET_MS, DEFAULT_SYNC_OFFSET_MS)),
            lyric_offset_ms=int(
                options.get(CONF_LYRIC_OFFSET_MS, DEFAULT_LYRIC_OFFSET_MS)
            ),
            tracking_enabled=False,
            lyrics_enabled=True,
        )
        self._lyrics_client: LrcLibClient | None = None
        self._track_lyrics: _TrackLyrics | None = None
        self._lyrics_task: asyncio.Task[Any] | None = None
        self._lyrics_task_key: str | None = None
        self._artwork: ArtworkResolver | None = None
        self._unsub_state: Any = None
        self._tracked: list[str] = []
        self._last_artwork_key: str | None = None
        self.display_select: SpinJamDisplaySelect | None = None
        self.selected_display: str | None = None
        self.cast_switch: SpinJamCastSwitch | None = None
        self.tracking_switch: SpinJamTrackingSwitch | None = None
        self.lyrics_switch: SpinJamLyricsSwitch | None = None
        self.lyric_offset_number: SpinJamLyricOffsetNumber | None = None
        self._cast_active = False
        self._cast_display: str | None = None
        self._unsub_recast: Any = None
        self._unsub_cast_display: Any = None
        self._tracking_enabled = False
        # Runtime lyrics UI/fetch gate (switch.spinjam_lyrics); restored on add.
        self._lyrics_display_enabled = True
        self._ending_cast = False
        self._cast_launch_until: datetime | None = None
        self._cast_start_task: asyncio.Task[Any] | None = None
        self._prefetch_task: asyncio.Task[Any] | None = None
        self._prefetch_key: str | None = None
        # Last SpinJam card JS version cast to each display (Cast caches resources).
        self._cast_card_version_by_display: dict[str, str] = {}
        self._last_publish_fingerprint: tuple[Any, ...] | None = None
        # Position attribute publish throttle (avoid 1 Hz media_position writes).
        self._last_pos_write_mono: float | None = None
        self._last_pos_write_value: float | None = None
        self._awaiting_mpua_after_track: datetime | None = None

    def _client(self) -> LrcLibClient:
        if self._lyrics_client is None:
            self._lyrics_client = LrcLibClient(async_get_clientsession(self.hass))
        return self._lyrics_client

    def _cancel_lyrics_task(self) -> None:
        task = self._lyrics_task
        self._lyrics_task = None
        self._lyrics_task_key = None
        if task is not None and not task.done():
            task.cancel()

    def _fallback_providers(self) -> list[str]:
        raw = self._options().get(CONF_FALLBACK_PROVIDERS, DEFAULT_FALLBACK_PROVIDERS)
        return normalize_fallback_providers(raw)

    def _schedule_lyrics(self, key: str, active: ActiveSource) -> None:
        """Start at most one lookup for this track. The coordinator does not await it."""
        if (
            self._lyrics_task is not None
            and not self._lyrics_task.done()
            and self._lyrics_task_key == key
        ):
            return
        self._cancel_lyrics_task()
        providers = self._fallback_providers()
        self._lyrics_task_key = key
        self._lyrics_task = self.hass.async_create_task(
            self._run_lyrics(
                key,
                active.artist or "",
                active.title or "",
                active.album,
                active.duration,
                providers,
            )
        )

    def _sync_lyrics_state(self, active: ActiveSource | None) -> None:
        if not self.lyrics_enabled or active is None or not active.artist or not active.title:
            self._cancel_lyrics_task()
            if not self.lyrics_enabled:
                self._track_lyrics = _TrackLyrics(
                    key="",
                    status=LYRICS_STATUS_DISABLED,
                    result=None,
                    source=None,
                )
            else:
                self._track_lyrics = None
            return

        key = LyricsCache.key(active.artist, active.title, active.album, active.duration)
        current = self._track_lyrics
        if current is not None and current.key == key:
            if current.status == LYRICS_STATUS_ERROR:
                erred_at = current.error_at or 0.0
                if time.monotonic() - erred_at >= LYRICS_ERROR_RETRY_SEC:
                    self._schedule_lyrics(key, active)
                return
            if current.status is None and (
                self._lyrics_task is None or self._lyrics_task.done()
            ):
                self._schedule_lyrics(key, active)
            return

        self._track_lyrics = _TrackLyrics(key=key, status=None, result=None, source=None)
        self._schedule_lyrics(key, active)

    def _lyric_fields(
        self, active: ActiveSource | None, lyric_offset: int
    ) -> dict[str, Any]:
        """Lyric attributes for publish. Position comes from the live source."""
        empty: dict[str, Any] = {
            "lyric_current": None,
            "lyric_next": None,
            "lyric_lines": None,
            "lyrics": None,
            "lyrics_status": None,
            "lyrics_source": None,
        }
        if not self.lyrics_enabled:
            empty["lyrics_status"] = LYRICS_STATUS_DISABLED
            return empty
        if active is None or not active.artist or not active.title:
            return empty

        state = self._track_lyrics
        key = LyricsCache.key(active.artist, active.title, active.album, active.duration)
        if state is None or state.key != key:
            return empty

        lyrics = state.result
        status = state.status
        source = state.source
        lyric_current = None
        lyric_next = None
        lyric_lines = None
        lyric_pos = None
        if active.position is not None:
            # Positive lyric_offset_ms = lyrics appear later → look earlier in LRC.
            lyric_pos = max(0.0, float(active.position) - (lyric_offset / 1000.0))

        if lyrics is not None and status == LYRICS_STATUS_PLAIN:
            lyric_lines = [
                {"text": line.text} for line in lyrics.lines[:LYRIC_LINES_ATTR_MAX]
            ]
        elif lyrics is not None and status == LYRICS_STATUS_SYNCED and lyrics.lines:
            if lyric_pos is not None:
                lyric_current, lyric_next = line_at(lyrics.lines, lyric_pos)
            lyric_lines = lines_payload(
                lyrics.lines,
                position=lyric_pos,
                max_lines=LYRIC_LINES_ATTR_MAX,
                before=LYRIC_LINES_WINDOW_BEFORE,
            )
        keep = status in (
            LYRICS_STATUS_SYNCED,
            LYRICS_STATUS_PLAIN,
            LYRICS_STATUS_INSTRUMENTAL,
        )
        return {
            "lyric_current": lyric_current,
            "lyric_next": lyric_next,
            "lyric_lines": lyric_lines,
            "lyrics": lyrics if keep else None,
            "lyrics_status": status,
            "lyrics_source": source if keep else None,
        }

    def _publish_lyrics_state(self) -> None:
        if self.data is None:
            return
        # Highlight from the last published position; the next poll uses the live one.
        fields = self._lyric_fields(self.data.active, self.data.lyric_offset_ms)
        updated = replace(self.data, **fields)
        self._last_publish_fingerprint = self._data_fingerprint(updated)
        self.async_set_updated_data(updated)

    async def _run_lyrics(
        self,
        key: str,
        artist: str,
        title: str,
        album: str | None,
        duration: float | None,
        providers: list[str],
    ) -> None:
        try:
            outcome = await self._client().fetch(
                artist=artist,
                title=title,
                album=album,
                duration=duration,
                fallback_providers=providers,
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 — surface as error, do not cache
            _LOGGER.debug("Lyrics lookup failed for %s - %s: %s", artist, title, err)
            outcome = LyricsLookup(LYRICS_STATUS_ERROR)
        if not self._tracking_enabled or not self.lyrics_enabled:
            return
        if self._track_lyrics is None or self._track_lyrics.key != key:
            return
        status, result, source = _coerce_lookup(outcome)
        self._track_lyrics = _TrackLyrics(
            key=key,
            status=status,
            result=result,
            source=source,
            error_at=time.monotonic() if status == LYRICS_STATUS_ERROR else None,
        )
        self._publish_lyrics_state()

    def _artwork_resolver(self) -> ArtworkResolver:
        if self._artwork is None:
            from pathlib import Path

            disk = Path(self.hass.config.path(ARTWORK_DISK_CACHE_DIR, ARTWORK_DISK_CACHE_FILE))
            self._artwork = ArtworkResolver(
                async_get_clientsession(self.hass), disk_path=disk
            )
        return self._artwork

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
    def lyrics_config_enabled(self) -> bool:
        """Config-flow option: allow LRCLIB fetching at all."""
        return bool(self._options().get(CONF_LYRICS_ENABLED, DEFAULT_LYRICS_ENABLED))

    @property
    def lyrics_enabled(self) -> bool:
        """Runtime lyrics on (switch); card + fetch gate."""
        return self._lyrics_display_enabled and self.lyrics_config_enabled

    @property
    def hd_artwork_enabled(self) -> bool:
        return bool(self._options().get(CONF_HD_ARTWORK, DEFAULT_HD_ARTWORK))

    @property
    def prefetch_enabled(self) -> bool:
        return bool(self._options().get(CONF_PREFETCH, DEFAULT_PREFETCH))

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
        self._cancel_lyrics_task()
        self._async_cancel_cast_start_task()
        self._async_cancel_prefetch()
        self._async_stop_recast()
        self._async_unwatch_cast_display()
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    def _async_cancel_prefetch(self) -> None:
        task = self._prefetch_task
        self._prefetch_task = None
        self._prefetch_key = None
        if task is not None and not task.done():
            task.cancel()

    def _async_cancel_cast_start_task(self) -> None:
        task = self._cast_start_task
        self._cast_start_task = None
        if task is not None and not task.done():
            task.cancel()

    def _warn_if_sources_look_like_arc(self, display: str) -> None:
        """Log when a configured source looks HDMI/ARC-linked after a Cast wake."""
        from .source import is_passthrough_source, is_tv_placeholder_track

        for entity_id in self.source_players:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            source = state.attributes.get("source")
            title = state.attributes.get("media_title")
            artist = state.attributes.get("media_artist")
            if is_passthrough_source(source) or is_tv_placeholder_track(title, artist):
                _LOGGER.warning(
                    "Source %s looks like TV/HDMI/ARC input (source=%s title=%s) "
                    "after casting to %s — SpinJam ignores passthrough inputs; "
                    "consider removing linked soundbars from source_players",
                    entity_id,
                    source,
                    title,
                    display,
                )

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
            artwork_hd=None,
            artwork_source=None,
            artwork_next=None,
            lyrics_enabled=self.lyrics_enabled,
            lyrics_status=None if self.lyrics_enabled else LYRICS_STATUS_DISABLED,
            lyrics_source=None,
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
            data.lyrics_status,
            data.lyrics_source,
            data.sync_offset_ms,
            data.lyric_offset_ms,
            data.album_lock,
            data.tracking_enabled,
            data.cast_active,
            data.artwork_hd,
            data.artwork_source,
            data.artwork_next,
            data.lyrics_enabled,
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
            self._cancel_lyrics_task()
            self._track_lyrics = None
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

        prev_active = self.data.active if self.data else None
        hold = prev_active if prev_active and prev_active.playing else None
        live_active = select_active_source(
            self._collect_snapshots(),
            priority=self.source_players,
            vinyl_entity_id=self.vinyl_player,
            sync_offset_ms=sync_offset,
            hold=hold,
        )
        # Throttle media_position attribute writes; keep a live estimate for lyrics.
        active = self._throttle_position_publish(live_active, prev_active)

        artwork_hd = self.data.artwork_hd if self.data else None
        artwork_source = self.data.artwork_source if self.data else None
        artwork_next = self.data.artwork_next if self.data else None

        # Start the lookup before artwork so a fast cache hit can land during that await.
        self._sync_lyrics_state(live_active)

        if live_active and self.hd_artwork_enabled and (live_active.artist or live_active.title):
            art_key = f"{live_active.artist}|{live_active.album}|{live_active.title}"
            if art_key != self._last_artwork_key:
                try:
                    art = await self._artwork_resolver().resolve(
                        artist=live_active.artist,
                        title=live_active.title,
                        album=live_active.album,
                        duration=live_active.duration,
                        entity_picture=live_active.art_url,
                    )
                except Exception:  # noqa: BLE001 — never block now-playing on art lookup
                    _LOGGER.debug("HD artwork resolve failed", exc_info=True)
                    art = None
                self._last_artwork_key = art_key
                if art is not None:
                    artwork_hd = art.url
                    artwork_source = art.source
                else:
                    artwork_hd = live_active.art_url
                    artwork_source = "entity_picture" if live_active.art_url else None
            elif not artwork_hd and live_active.art_url:
                artwork_hd = live_active.art_url
                artwork_source = artwork_source or "entity_picture"
        elif not self.hd_artwork_enabled:
            artwork_hd = live_active.art_url if live_active else None
            artwork_source = "entity_picture" if artwork_hd else None
            self._last_artwork_key = None
        else:
            artwork_hd = None
            artwork_source = None
            self._last_artwork_key = None

        # Keep select options in sync after options reload.
        if self.display_select is not None:
            self.display_select._sync_options_from_coordinator()  # noqa: SLF001

        position_updated_at = self._position_updated_at_for_publish(active, prev_active)

        if live_active and self.prefetch_enabled:
            self._schedule_prefetch(live_active)
        else:
            self._async_cancel_prefetch()
            artwork_next = None

        # Re-read after awaits so a lookup that finished during artwork is included.
        lyric_fields = self._lyric_fields(live_active, lyric_offset)

        return self._publish_data(
            SpinJamData(
                active=active,
                album_lock=self.data.album_lock,
                sync_offset_ms=sync_offset,
                lyric_offset_ms=lyric_offset,
                position_updated_at=position_updated_at,
                tracking_enabled=True,
                cast_active=self._cast_active,
                artwork_hd=artwork_hd,
                artwork_source=artwork_source,
                artwork_next=artwork_next,
                lyrics_enabled=self.lyrics_enabled,
                **lyric_fields,
            )
        )

    def _same_track(self, left: ActiveSource | None, right: ActiveSource | None) -> bool:
        if left is None or right is None:
            return False
        return (
            left.entity_id == right.entity_id
            and left.title == right.title
            and left.artist == right.artist
        )

    def _throttle_position_publish(
        self, active: ActiveSource | None, prev: ActiveSource | None
    ) -> ActiveSource | None:
        """Limit media_position attribute churn; wait for fresh m_p_u_a on track change."""
        if active is None:
            self._last_pos_write_mono = None
            self._last_pos_write_value = None
            self._awaiting_mpua_after_track = None
            return None

        track_changed = not self._same_track(prev, active)
        play_changed = prev is not None and prev.playing != active.playing

        if track_changed:
            # Hold the first position until the source reports a new m_p_u_a.
            prev_mpua = prev.position_updated_at if prev else None
            self._awaiting_mpua_after_track = prev_mpua
            if active.position is None or active.position_updated_at is None:
                return replace(active, position=None)
            if prev_mpua is not None and active.position_updated_at <= prev_mpua:
                return replace(active, position=None)
            self._awaiting_mpua_after_track = None
            self._last_pos_write_mono = time.monotonic()
            self._last_pos_write_value = active.position
            return active

        if self._awaiting_mpua_after_track is not None:
            if (
                active.position is None
                or active.position_updated_at is None
                or active.position_updated_at <= self._awaiting_mpua_after_track
            ):
                return replace(active, position=None)
            self._awaiting_mpua_after_track = None
            self._last_pos_write_mono = time.monotonic()
            self._last_pos_write_value = active.position
            return active

        if active.position is None:
            return active

        if play_changed:
            self._last_pos_write_mono = time.monotonic()
            self._last_pos_write_value = active.position
            return active

        # Jump > 1s vs last published position (seek / skip).
        if (
            self._last_pos_write_value is not None
            and abs(active.position - self._last_pos_write_value) > 1.0
        ):
            # Account for wall time since last write so normal playback isn't a "jump".
            elapsed = 0.0
            if self._last_pos_write_mono is not None:
                elapsed = time.monotonic() - self._last_pos_write_mono
            expected = self._last_pos_write_value + (
                elapsed if active.playing else 0.0
            )
            if abs(active.position - expected) > 1.0:
                self._last_pos_write_mono = time.monotonic()
                self._last_pos_write_value = active.position
                return active

        # Periodic drift correction at most every 30s.
        if (
            self._last_pos_write_mono is None
            or (time.monotonic() - self._last_pos_write_mono) >= 30.0
        ):
            self._last_pos_write_mono = time.monotonic()
            self._last_pos_write_value = active.position
            return active

        # Hold the last published position so fingerprints stay stable mid-track.
        if prev is not None and self._same_track(prev, active) and prev.position is not None:
            return replace(active, position=prev.position)
        return replace(active, position=None)

    def _position_updated_at_for_publish(
        self, active: ActiveSource | None, prev: ActiveSource | None
    ) -> datetime | None:
        """Publish a new position clock only when media_position itself is published."""
        if active is None or active.position is None:
            return None
        if (
            prev is not None
            and self._same_track(prev, active)
            and prev.position is not None
            and active.position == prev.position
            and self.data
            and self.data.position_updated_at is not None
        ):
            # Reuse prior publish timestamp when holding the same position value.
            return self.data.position_updated_at
        return datetime.now(timezone.utc)

    async def _async_prefetch_for_active(self, active: ActiveSource) -> str | None:
        """Resolve and cache next-track assets; return next HD art URL if any."""
        nxt = await async_resolve_next_track(self.hass, active.entity_id)
        if nxt is None or not (nxt.artist or nxt.title):
            return None
        art_url = None
        if self.hd_artwork_enabled:
            art = await self._artwork_resolver().resolve(
                artist=nxt.artist,
                title=nxt.title,
                album=nxt.album,
                duration=nxt.duration,
                entity_picture=nxt.art_url,
            )
            if art is not None:
                art_url = art.url
        if self.lyrics_enabled and nxt.artist and nxt.title:
            await self._client().fetch(
                artist=nxt.artist,
                title=nxt.title,
                album=nxt.album,
                duration=nxt.duration,
                fallback_providers=self._fallback_providers(),
            )
        return art_url

    def _apply_artwork_next(self, art_url: str) -> None:
        held = self.data
        if held is None or held.artwork_next == art_url:
            return
        updated = SpinJamData(
            active=held.active,
            lyric_current=held.lyric_current,
            lyric_next=held.lyric_next,
            lyric_lines=held.lyric_lines,
            lyrics=held.lyrics,
            album_lock=held.album_lock,
            sync_offset_ms=held.sync_offset_ms,
            lyric_offset_ms=held.lyric_offset_ms,
            position_updated_at=held.position_updated_at,
            tracking_enabled=held.tracking_enabled,
            cast_active=self._cast_active,
            artwork_hd=held.artwork_hd,
            artwork_source=held.artwork_source,
            artwork_next=art_url,
            lyrics_enabled=held.lyrics_enabled,
            lyrics_status=held.lyrics_status,
            lyrics_source=held.lyrics_source,
        )
        self.async_set_updated_data(updated)
        self._last_publish_fingerprint = self._data_fingerprint(updated)

    def _schedule_prefetch(self, active: ActiveSource) -> None:
        """Background-resolve next-track HD art (+ lyrics) when the source exposes it."""
        key = f"{active.entity_id}|{active.artist}|{active.title}"
        # Avoid cancelling an in-flight prefetch for the same track on every poll.
        if self._prefetch_key == key and self._prefetch_task is not None:
            if not self._prefetch_task.done():
                return
            if self.data and self.data.artwork_next:
                return
        self._async_cancel_prefetch()
        self._prefetch_key = key

        async def _job() -> None:
            try:
                art_url = await self._async_prefetch_for_active(active)
                if not art_url:
                    return
                if not (
                    self.data
                    and self.data.active
                    and self.data.active.entity_id == active.entity_id
                    and self.data.active.title == active.title
                    and self.data.active.artist == active.artist
                ):
                    return
                self._apply_artwork_next(art_url)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Prefetch next-track assets failed", exc_info=True)
            finally:
                if self._prefetch_task is asyncio.current_task():
                    self._prefetch_task = None

        self._prefetch_task = self.hass.async_create_task(_job())

    async def async_set_lyrics_enabled(self, enabled: bool) -> None:
        """Toggle lyrics fetch/display (live; no Cast restart)."""
        enabled = bool(enabled)
        if self._lyrics_display_enabled == enabled:
            return
        self._lyrics_display_enabled = enabled
        if self.lyrics_switch is not None and self.lyrics_switch.hass is not None:
            self.lyrics_switch.async_write_ha_state()
        if not enabled:
            self._track_lyrics = None
            self._cancel_lyrics_task()
            held = self.data
            updated = replace(
                held,
                lyric_current=None,
                lyric_next=None,
                lyric_lines=None,
                lyrics=None,
                lyrics_status=LYRICS_STATUS_DISABLED,
                lyrics_source=None,
                lyrics_enabled=False,
            )
            self.async_set_updated_data(updated)
            self._last_publish_fingerprint = self._data_fingerprint(self.data)
        elif self._tracking_enabled:
            await self.async_request_refresh()
        else:
            held = self.data
            status = (
                None
                if held.lyrics_status == LYRICS_STATUS_DISABLED
                else held.lyrics_status
            )
            updated = replace(held, lyrics_enabled=True, lyrics_status=status)
            self.async_set_updated_data(updated)
            self._last_publish_fingerprint = self._data_fingerprint(self.data)

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
            self._cancel_lyrics_task()
            self._track_lyrics = None
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
            self.async_set_updated_data(replace(self.data, sync_offset_ms=offset_ms))

    async def async_set_lyric_offset(self, offset_ms: int) -> None:
        """Set lyric display offset (ms; positive = lyrics later). Live, no reload."""
        offset_ms = max(-5000, min(5000, int(offset_ms)))
        self.data.lyric_offset_ms = offset_ms
        self._persist_live_option(CONF_LYRIC_OFFSET_MS, offset_ms)
        if self.lyric_offset_number is not None and self.lyric_offset_number.hass:
            self.lyric_offset_number._attr_native_value = float(offset_ms)  # noqa: SLF001
            self.lyric_offset_number.async_write_ha_state()

        fields = self._lyric_fields(self.data.active, offset_ms)
        updated = replace(self.data, lyric_offset_ms=offset_ms, **fields)
        self.async_set_updated_data(updated)
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
        """Select a display, cast (master on), enable tracking, fire ``spinjam_start``.

        Builtin cast wake/launch/verify runs in a background task so the Cast
        switch returns immediately (optimistically on). Failure reverts the switch.
        """
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

        # Optimistic on — background task reverts on failure.
        self._async_cancel_cast_start_task()
        self._async_set_cast_active(True, target)
        self.hass.bus.async_fire(EVENT_SPINJAM_START, {"display": target})
        await self.async_request_refresh()

        if do_builtin:
            self._cast_start_task = self._async_create_cast_start_task(
                self._async_cast_start_job(
                    target,
                    dashboard_path=str(opts[CONF_DASHBOARD_PATH]),
                    view_path=str(opts[CONF_VIEW_PATH]),
                    opts=opts,
                )
            )
        else:
            self._async_stop_recast()

        return target

    def _async_create_cast_start_task(self, coro: Any) -> asyncio.Task[Any]:
        """Schedule wake/launch/verify off the switch turn_on path."""
        name = f"{DOMAIN}_cast_start"
        if hasattr(self.entry, "async_create_background_task"):
            return self.entry.async_create_background_task(self.hass, coro, name)
        if hasattr(self.hass, "async_create_background_task"):
            return self.hass.async_create_background_task(coro, name)
        return self.hass.async_create_task(coro)

    async def _async_cast_start_job(
        self,
        target: str,
        *,
        dashboard_path: str,
        view_path: str,
        opts: dict[str, Any],
    ) -> None:
        """Background wake → cast → verify; revert switch on failure."""
        try:
            ok = await self._async_cast_lovelace_view(
                target,
                dashboard_path=dashboard_path,
                view_path=view_path,
            )
            if not ok:
                _LOGGER.warning(
                    "SpinJam cast to %s failed — leaving switch.spinjam_cast off",
                    target,
                )
                if self._cast_active and self._cast_display == target:
                    self._async_stop_recast()
                    self._async_set_cast_active(False)
                return
            if self._cast_active and self._cast_display == target:
                self._async_schedule_recast(opts)
                self._warn_if_sources_look_like_arc(target)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("SpinJam cast start job failed for %s", target)
            if self._cast_active and self._cast_display == target:
                self._async_stop_recast()
                self._async_set_cast_active(False)
        finally:
            if self._cast_start_task is asyncio.current_task():
                self._cast_start_task = None

    async def async_stop(self) -> None:
        """End Cast, stop recast, disable tracking, and clear now-playing."""
        self._async_cancel_cast_start_task()
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
        self._cancel_lyrics_task()
        self._track_lyrics = None
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
            ATTR_LYRICS_STATUS: self.data.lyrics_status,
            ATTR_LYRICS_SOURCE: self.data.lyrics_source,
            ATTR_ALBUM_LOCK: self.data.album_lock,
            ATTR_DISPLAYS: list(self.displays),
            ATTR_SELECTED_DISPLAY: self.selected_display,
            ATTR_ARTWORK_HD: self.data.artwork_hd,
            ATTR_ARTWORK_SOURCE: self.data.artwork_source,
            ATTR_ARTWORK_NEXT: self.data.artwork_next,
            ATTR_LYRICS_ENABLED: self.lyrics_enabled,
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
