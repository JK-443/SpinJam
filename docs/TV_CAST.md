# TV now-playing + Cast

SpinJam casts a full-screen now-playing Lovelace view to a Google Cast /
Google TV `media_player` (e.g. `media_player.example_tv`) when you call
`spinjam.start` or turn on `switch.spinjam_cast`. `spinjam.stop` / Cast switch
off ends the session.

Browser Mod and Fully Kiosk are **not** required.

## One-time Home Assistant setup

Home Assistant **requires a hyphen** in new dashboard URL paths (e.g.
`spinjam-tv`, not `spinjam`). SpinJam defaults to `spinjam-tv` / `now`.

### 1. Prerequisites

1. **Google Cast** integration enabled; your TV appears as a Cast `media_player`
   (entity registry platform `cast`). Non-cast displays are skipped at start
   with a warning.
2. Home Assistant reachable over **HTTPS** with a valid **External URL**
   (Settings → System → Network). Cast cannot load HTTP-only dashboards.
3. SpinJam installed (HACS or manual). The custom card is registered at
   `/spinjam/spinjam-lyrics-card.js?v=<hash>` automatically — no separate frontend
   install.

### 2. Create the dashboard + view

**Preferred — one-shot service (storage mode):**

```yaml
service: spinjam.create_dashboard
# optional:
# data:
#   dashboard_path: spinjam-tv
#   view_path: now
```

This creates a storage-mode **panel** view (`panel: true`) with **one** card
(`mode: cast`). Lyrics on is the split art/lyrics layout inside that card;
lyrics off is the full-bleed stage. A Controls view (Cast, Display, Source,
Lyrics) is included. Running it again, or setting up when the dashboard
already exists, upgrades a generated two-card Cast view to that single card
and updates the Controls tiles. Cards you added are left in place. The change
is logged. A new card hash makes the next cast quit and relaunch so the
receiver loads it.

**Manual UI:**

1. Settings → Dashboards → **Add dashboard**
2. Title: `SpinJam`, URL path: `spinjam-tv` (must include a hyphen; must match options `dashboard_path`)
3. Open the dashboard → edit → add a view:
   - Title: `Now`
   - Path: `now` (must match options `view_path`)
   - Type: **Panel**
4. Add one card that fills the panel:

```yaml
type: panel
panel: true
cards:
  - type: custom:spinjam-lyrics-card
    entity: media_player.spinjam_now_playing
    mode: cast
    offset_entity: number.spinjam_lyric_offset
```

`custom:spinjam-now-playing-card` remains registered as a **deprecated alias**
(details mode) so older dashboards keep working.

**YAML mode alternative:** add a dashboard that loads
[`docs/lovelace/spinjam.yaml`](lovelace/spinjam.yaml) (copy into your config
and reference it from `lovelace:` / dashboards config).

The card JS is registered as a **Lovelace module resource** at
`/spinjam/spinjam-lyrics-card.js?v=<hash>` (storage mode; YAML mode needs a
manual resource) and the same URL is passed to `add_extra_js_url` so browsers
don’t load two copies. Cast receivers only see Lovelace resources — without
that registration the TV card stays blank. Cast also caches resources for the
session; when the card hash changes, `spinjam.start` quits the Cast app before
casting so the new JS loads.

### 3. Configure SpinJam displays

Settings → Devices & services → SpinJam → Configure:

- **Displays:** Google Cast targets only, e.g. `media_player.example_tv`
- **Built-in casting:** on (default). When off, start/stop and `switch.spinjam_cast` only fire `spinjam_start` / `spinjam_stop` (no `cast.show_lovelace_view`) so you can cast from your own automations without double-casting. Events always fire either way.
- **Cast dashboard path:** `spinjam-tv` (default; must contain a hyphen)
- **Cast view path:** `now` (default)
- **Re-cast while playing:** on (default) — recovers dropped Cast sessions
- **Recast on startup:** off (default). Cast sessions do not survive HA restart; leave this off unless you want SpinJam to call start again when the Cast switch was previously on.
- **Power off display when stopping:** off (default). `media_player.turn_off` on the Cast entity quits the app but usually leaves a Chromecast-built-in TV on; enable this to also power off via the device’s `remote.*` entity when available.
- **Lyric display offset (ms):** positive = lyrics appear **later** (see below)

## Entities

Device page order: **Cast**, **Display**, **Source**, **Lyrics**, **Now Playing**. Under Configuration: **Lyric offset**.

| Entity | Behaviour |
| --- | --- |
| `switch.spinjam_cast` | On → wake display if needed, cast Lovelace, enable tracking (`spinjam.start`). Off → quit Cast app, disable tracking, clear now-playing to idle (`spinjam.stop`). Tracking follows this switch. |
| `select.spinjam_display` | Which configured display to use. Options are friendly names; a restored entity id still selects the same display. |
| `select.spinjam_source` | `Automatic` (default) or one configured player by friendly name, plus the vinyl player when configured. A fixed choice is the only now-playing source. Restored across restarts. Options refresh when sources change. |
| `switch.spinjam_lyrics` | Off stops lyric fetches and switches the TV card live to one full-width stage. On restores the two-panel lyrics layout. Restored; default on. No Cast restart. |
| `number.spinjam_lyric_offset` | **Lyric delay** in ms (**higher = lyrics appear later**). Configuration entity. Live — no reload. Restored. Range −5000…5000, step 100. |
| `button.spinjam_lyrics_earlier` / `button.spinjam_lyrics_later` | Move the delay by the configured step (default 250 ms). Clamped to the number range. Live. |
| `button.spinjam_reset_lyric_delay` | Restore the delay from the last options load. |
| `sensor.spinjam_lyric_delay` | Signed readout such as `+2.0 s (later)`. |

### Now-playing attributes (art + lyrics)

| Attribute | Meaning |
| --- | --- |
| `artwork_hd` | High-res cover URL (iTunes / Cover Art Archive / player picture) |
| `artwork_source` | `itunes`, `coverartarchive`, or `entity_picture` |
| `artwork_next` | Prefetched next-track HD URL when the queue exposes a next item |
| `lyrics_enabled` | Mirrors `switch.spinjam_lyrics` (and config lyrics option) for the card |
| `selected_source` | `Automatic`, or the entity id chosen on `select.spinjam_source` |
| `active_source` | Entity id actually providing now-playing, or null when idle |
| `lyrics_status` | `synced`, `plain`, `instrumental`, `not_found`, `error`, or `disabled` (full-width stage) |
| `lyrics_source` | `lrclib`, `qqmusic`, or `lyricsovh` when a provider returned lyrics |
| `lyrics_duration` | Length of the chosen lyrics (provider duration, or the last stamp when the file ends early) |
| `lyrics_duration_delta` | `lyrics_duration` minus the player duration. Negative means the lyrics run short |

Options **High-resolution album art** and **Prefetch** (defaults on) can disable those features. **Fallback lyrics providers** (default lyrics.ovh) run after LRCLIB. QQ Music is an unofficial endpoint, for personal use, and stays off until selected.

## Usage

```yaml
service: switch.turn_on
target:
  entity_id: switch.spinjam_cast
```

```yaml
service: spinjam.start
data:
  display: media_player.example_tv   # optional; uses select.spinjam_display
```

```yaml
service: spinjam.stop
# or switch.turn_off on switch.spinjam_cast
```

### Example: start when Port goes Line-in

```yaml
alias: SpinJam cast on vinyl Line-in
trigger:
  - platform: state
    entity_id: media_player.speaker_a
    attribute: source
    to: "Line-in"
action:
  - service: spinjam.start
    data:
      display: media_player.example_tv
mode: single
```

Stop when leaving Line-in (optional):

```yaml
alias: SpinJam stop when Line-in ends
trigger:
  - platform: state
    entity_id: media_player.speaker_a
    attribute: source
    from: "Line-in"
action:
  - service: spinjam.stop
mode: single
```

Events `spinjam_start` / `spinjam_stop` still fire if you want extra automations.

## Lyric sync latency

| Stage | Typical contribution |
| --- | --- |
| Source `media_position` + `media_position_updated_at` interpolation | ~0–200 ms once position is fresh |
| SpinJam coordinator tick (default `update_interval` 1.0 s) | up to ~1.0 s for attribute refresh |
| TV card local tick (500 ms) + position interpolation | ~0–500 ms visual; progress bar stays smooth |
| Cast / Chromecast Lovelace websocket | ~100–500 ms depending on LAN and TV |
| **Expected lyric highlight lag (stream sources)** | **~0.5–2.0 s** before calibration |
| Vinyl fingerprint → first metadata | separate (seconds); not lyric sync |

Calibration:

1. `sync_offset_ms` — corrects **playback position** (cable / Sonos buffer skew).
2. `number.spinjam_lyric_offset` / options `lyric_offset_ms` — shifts **lyric highlighting only** (positive = lyrics later). Prefer the number entity for live nudges on the TV.

Tune with a known track until the highlighted line matches what you hear.
`spinjam.set_sync_offset` still updates playback sync live.

## What the card shows

Official card: `custom:spinjam-lyrics-card`. On a 16:9 Cast dashboard the Now view is a horizontal stack: details on the left, lyrics on the right. Toggling `switch.spinjam_lyrics` swaps that for a single full-width stage with a short fade. The Cast session is not restarted.

**Lyrics on (two panels).** Left: album art full-bleed, title, artist, and album over a bottom gradient, with a progress bar. Right: centred karaoke-sweep lyrics, or static centred text when `lyrics_status` is `plain`. A dim footer reads `Lyrics: LRCLIB`, `Lyrics: QQ Music`, or `Lyrics: lyrics.ovh`. `not_found` shows "Lyrics not available for this song"; `instrumental` shows "Instrumental".

**Lyrics off (one stage, 16:9).** The lyrics panel collapses and the details card fills the screen. The background is the cover, scaled up, heavily blurred, and slightly darkened. A large square cover sits in the centre (about 60% of the screen height, rounded corners, soft shadow). Under it: the title (largest), the artist, the album in smaller dim type, then a slim progress bar with elapsed and total times. HD art still crossfades in over the low-res picture, and the next cover is preloaded. With no artwork, the background is a neutral grey gradient and the square is a placeholder. The progress clock does not step backward within a track.

Timing uses a **shared clock**: `media_position + (last_updated − media_position_updated_at)`, then advanced with `performance.now()` — the TV’s `Date.now()` is never compared to HA.

`lyric_lines` may include per-line `words: [{t, text}]` from LRCLIB enhanced tags. Attributes are capped (~120 lines) and **windowed** around the current position so long tracks stay light on a Pi 4.

Cast renders at **1080p** even on 4K TVs; the layout is tuned for that.

## Stop behaviour

`spinjam.stop` calls `media_player.turn_off` on the active Cast entity (quits
the Lovelace/Cast app; the TV panel usually stays on). Optional **power off
display when stopping** uses the paired `remote.*` entity when present.

## Known limitations

- Dashboard/view must exist before the first `spinjam.start` (use `spinjam.create_dashboard` or create manually; path needs a hyphen).
- Cast requires HTTPS external URL; local HTTP-only setups will not work.
- Displays should be Google Cast entities; other `media_player` platforms are skipped for built-in casting.
- Re-cast briefly reloads the Lovelace view (possible flash every N seconds).
- `lyric_lines` is capped (~120 lines) to keep state attributes light on Pi 4.
- Bravia / Google TV power policies may still sleep the panel after idle.
- Album art URLs must be reachable from the Cast device (same as HA frontend).
