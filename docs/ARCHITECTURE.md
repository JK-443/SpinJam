# SpinJam architecture

SpinJam is a **general now-playing system**. Vinyl is one source among Music Assistant, Sonos, and other `media_player` entities.

## Components

| Piece | Runs where | Role |
| --- | --- | --- |
| `custom_components/spinjam` | Home Assistant (HACS) | Brain: pick active source, unify metadata, lyrics (LRCLIB then fallbacks), HD art, services, Cast |
| `spinjam/` Python service | Capture Pi (Zero 2 W / Pi 4) | Vinyl audio capture + Shazam/(optional ACR/AudD) → MQTT media_player |
| Lovelace card + Cast | HA → TV Cast targets | `spinjam-lyrics-card` (details + lyrics) + `cast.show_lovelace_view` on `spinjam.start` |

## Source rules

1. Configured media players are an **ordered priority list**.
2. Active source = any **playing** source beats paused; within a tier, list order wins. Paused only wins when nothing is playing.
3. If a Sonos/Port entity’s `source` is **Line-in**, use the vinyl MQTT player instead of Port metadata.
4. Streamed sources need **no** fingerprinting — lyric timing uses `media_position` + `media_position_updated_at` plus `sync_offset_ms`, then `lyric_offset_ms` for highlight fine-tuning.
5. Expected lyric highlight latency on Cast is roughly **0.5–2.0 s** before calibration; see [`TV_CAST.md`](TV_CAST.md).

## Displays + Cast

1. Config/options `displays` is an optional ordered list of Google Cast `media_player` entities (e.g. `media_player.example_tv`).
2. `select.spinjam_display` exposes those options; default is the first; last choice is restored after restart.
3. `spinjam.start` / `switch.spinjam_cast` on (optional `display`) validates against the list, updates the select, and fires `spinjam_start`. When **built-in casting** is on (default), also calls `cast.show_lovelace_view` with configurable `dashboard_path` / `view_path` (defaults `spinjam-tv` / `now`; path must include a hyphen). Non-cast platforms are skipped with a warning.
4. Optional re-cast while playing recovers dropped Cast sessions; optional **recast on startup** (default off) re-starts Cast after HA restart if the Cast switch was on.
5. `switch.spinjam_cast` is the **on/off**: on wakes the display if needed, casts with verification, and enables tracking; off quits Cast, disables tracking, and clears now-playing to idle. Tracking is derived state (no tracking switch). Upgrades remove `switch.spinjam_tracking` from the entity registry.
6. Cast receivers cache Lovelace resources once per session. SpinJam tracks the card JS hash last cast per display; when it changes, quit before re-cast. Display watcher ignores flaps for ~20 s around launches; session ends on `unavailable` or when `app_name` leaves the HA Lovelace app (not on brief `off`).
7. `spinjam.stop` / Cast switch off ends Cast via `media_player.turn_off` (app quit; TV usually stays on) when built-in casting is on; optional power-off uses `remote.turn_off`. Always fires `spinjam_stop`.
8. `select.spinjam_source` (RestoreEntity, default `Automatic`): Automatic uses the ranking above. A specific option monitors only that player (configured sources by friendly name, plus the vinyl player when set). Options refresh when integration options change. `selected_source` and `active_source` are attributes on `media_player.spinjam_now_playing`.
9. `switch.spinjam_lyrics` (default on, RestoreEntity): off stops lyric fetches and switches the TV card live from the two-panel layout to one full-width stage (no Cast restart). The stage is a blurred, darkened cover fill, a centred square (~60% of the height), title, artist, album, and a slim progress bar. State is exposed as `lyrics_enabled` on `media_player.spinjam_now_playing`.
10. `number.spinjam_lyric_offset` (friendly name Lyric delay) and `sync_offset_ms` update live without config-entry reload. Positive lyric delay means lyrics appear later. `sync_offset_ms` is added to the playhead and is not applied again by the card. Buttons `Lyrics earlier` / `Lyrics later` nudge by `lyric_nudge_ms` (default 250); `Reset lyric delay` restores the value from the last options load. The TV card defaults `offset_entity` to the number entity and shows a short toast when the delay changes.
11. Legacy single `display_entity` config is migrated into a one-item `displays` list when present.
12. Prefer `spinjam.create_dashboard` (panel: details left, lyrics right; Controls tiles for Cast, Display, Source, and Lyrics). Calling it again, or setting up when that dashboard already exists, upgrades the Controls view in place: missing tiles are added, the tracking tile is removed, and cards you added are left alone. Card JS is a Lovelace module resource at `/spinjam/spinjam-lyrics-card.js?v=<hash>` (plus the same URL via `add_extra_js_url`); `spinjam-now-playing-card` remains a deprecated alias.
13. HD album art (option `hd_artwork`, default on): on track change, SpinJam queries the iTunes Search API and rewrites `artworkUrl100` to a large size, falls back to MusicBrainz + Cover Art Archive (`front-1200`), then `entity_picture`. Results are scored and cached (memory + small on-disk LRU). Exposed as `artwork_hd` / `artwork_source`; the card crossfades from low-res once HD loads.
14. Prefetch (option `prefetch`, default on): when the active source exposes a next item (queue attributes or Music Assistant `get_queue`), SpinJam preloads next-track HD art and lyrics; the card preloads `artwork_next`. Degrades gracefully if MA is absent.
15. Lyrics fallback (option `fallback_providers`, default `lyricsovh`): after LRCLIB misses, try the selected providers in order. QQ Music is an unofficial endpoint for personal use and is off by default. Hits stay in the LRU. `not_found` expires after 6 hours. Network errors, timeouts, and HTTP 5xx are not cached. The lookup runs in a background task (6 s per request, 12 s per track) and publishes `lyrics_status` / `lyrics_source` when it finishes. `switch.spinjam_lyrics` off sets `lyrics_status` to `disabled` and the card uses the full-width stage.

## Memory constraints

HA runs on a Pi 4 that is (or was) memory-starved. The integration must stay light:

- No Shazam/ACR on the HA host
- `aiohttp` via Home Assistant’s shared session only
- Small in-memory LRU for lyrics and artwork URLs (URLs only — images are not downloaded on the HA host); optional tiny on-disk artwork URL cache under the config dir
- Event-driven updates + a low-frequency lyric tick while playing
- `media_position` attribute writes are throttled (track/play changes, >1 s seeks, or every 30 s) so Cast clients are not re-anchored every second; the TV card clock compensates for delivery delay and never steps lyrics/progress backward within a track
- Vanilla JS TV card (no Lit); `lyric_lines` capped (~120) and windowed around the current position; optional per-line `words` from LRCLIB enhanced tags; clock logic in `spinjam-playback-clock.js`
