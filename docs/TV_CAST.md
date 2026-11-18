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

This creates a storage-mode **panel** dashboard with a horizontal stack:
**details** (art / title / artist / album / progress) on the left and **lyrics**
(centred, fading, karaoke sweep) on the right. Safe to run again (updates the
view config in place).

**Manual UI:**

1. Settings → Dashboards → **Add dashboard**
2. Title: `SpinJam`, URL path: `spinjam-tv` (must include a hyphen; must match options `dashboard_path`)
3. Open the dashboard → edit → add a view:
   - Title: `Now`
   - Path: `now` (must match options `view_path`)
   - Type: **Panel**
4. Add a horizontal-stack with two cards:

```yaml
type: horizontal-stack
cards:
  - type: custom:spinjam-lyrics-card
    entity: media_player.spinjam_now_playing
    mode: details
    offset_entity: number.spinjam_lyric_offset
  - type: custom:spinjam-lyrics-card
    entity: media_player.spinjam_now_playing
    mode: lyrics
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

| Entity | Behaviour |
| --- | --- |
| `select.spinjam_display` | Which configured display to use |
| `switch.spinjam_cast` (**master on/off**) | On → wake display if needed, cast Lovelace, enable tracking (`spinjam.start`). Off → quit Cast app, disable tracking, clear now-playing to idle (`spinjam.stop`). Preferred daily toggle. |
| `switch.spinjam_tracking` | Off pauses polling and clears now-playing; if Cast is active it also stops Cast. On resumes tracking only (does **not** start Cast). Restored across restarts; defaults to on. |
| `switch.spinjam_lyrics` | Off stops lyric fetches and switches the TV card live to a full-screen cover-art layout (blurred fill + centred art + slim progress). On restores lyrics. Restored; default on. No Cast restart. |
| `number.spinjam_lyric_offset` | Lyric display offset in ms (**positive = lyrics later**). Live — no reload. Restored. Range −5000…5000, step 50. The TV card reads this by default via `offset_entity`. |

### Now-playing attributes (art + lyrics)

| Attribute | Meaning |
| --- | --- |
| `artwork_hd` | High-res cover URL (iTunes / Cover Art Archive / player picture) |
| `artwork_source` | `itunes`, `coverartarchive`, or `entity_picture` |
| `artwork_next` | Prefetched next-track HD URL when the queue exposes a next item |
| `lyrics_enabled` | Mirrors `switch.spinjam_lyrics` (and config lyrics option) for the card |
| `lyrics_status` | `synced`, `plain`, `instrumental`, `not_found`, `error`, or `disabled` (cover layout) |
| `lyrics_source` | `lrclib`, `qqmusic`, or `lyricsovh` when a provider returned lyrics |

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
    entity_id: media_player.living_room_port
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
    entity_id: media_player.living_room_port
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

Official card: `custom:spinjam-lyrics-card`

| Mode | Content |
| --- | --- |
| `details` | Large album art, title, artist, album, progress over a gradient |
| `lyrics` | Centred karaoke-sweep lyrics, or static centred text when `lyrics_status` is `plain`. A dim footer reads `Lyrics: LRCLIB`, `Lyrics: QQ Music`, or `Lyrics: lyrics.ovh`. `not_found` shows "Lyrics not available for this song"; `instrumental` shows "Instrumental". |
| `cover` | Used when `switch.spinjam_lyrics` is off (`lyrics_status` `disabled`): full-screen art, no lyric sweep |

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
