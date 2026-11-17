# SpinJam architecture

SpinJam is a **general now-playing system**. Vinyl is one source among Music Assistant, Sonos, and other `media_player` entities.

## Components

| Piece | Runs where | Role |
| --- | --- | --- |
| `custom_components/spinjam` | Home Assistant (HACS) | Brain: pick active source, unify metadata, LRCLIB lyrics, services, Cast |
| `spinjam/` Python service | Capture Pi (Zero 2 W / Pi 4) | Vinyl audio capture + Shazam/(optional ACR/AudD) → MQTT media_player |
| Lovelace card + Cast | HA → TV Cast targets | `spinjam-now-playing-card` + `cast.show_lovelace_view` on `spinjam.start` |

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
5. `spinjam.stop` / Cast switch off ends Cast via `media_player.turn_off` when built-in casting is on, and always fires `spinjam_stop`. External Cast end (display off/unavailable) clears the logical session and the Cast switch.
6. `switch.spinjam_tracking` (default on, RestoreEntity): off pauses source watchers and the ~1 s poll; now-playing **holds** the last snapshot. Tracking off does not stop Cast.
7. Legacy single `display_entity` config is migrated into a one-item `displays` list when present.
8. The Lovelace dashboard/view is a **one-time manual setup** (integrations cannot reliably create dashboards in all HA modes). Card JS is served from the integration static path.

## Memory constraints

HA runs on a Pi 4 that is (or was) memory-starved. The integration must stay light:

- No Shazam/ACR on the HA host
- `aiohttp` via Home Assistant’s shared session only
- Small in-memory LRU for lyrics (and art URLs are passed through, not downloaded)
- Event-driven updates + a low-frequency lyric tick while playing
- Vanilla JS TV card (no Lit); `lyric_lines` attribute capped for state size
