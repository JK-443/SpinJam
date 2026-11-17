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

The card JS is auto-registered at `/spinjam/spinjam-lyrics-card.js?v=<hash>`.
Cast receivers cache Lovelace resources for the session — when the card hash
changes, `spinjam.start` quits the Cast app before casting so the new JS loads.

### 3. Configure SpinJam displays

Settings → Devices & services → SpinJam → Configure:

- **Displays:** Google Cast targets only, e.g. `media_player.example_tv`
- **Built-in casting:** on (default). When off, start/stop and `switch.spinjam_cast` only fire `spinjam_start` / `spinjam_stop` (no `cast.show_lovelace_view`) so you can cast from your own automations without double-casting. Events always fire either way.
- **Cast dashboard path:** `spinjam-tv` (default; must contain a hyphen)
- **Cast view path:** `now` (default)
- **Re-cast while playing:** on (default) — recovers dropped Cast sessions
- **Recast on startup:** off (default). Cast sessions do not survive HA restart; leave this off unless you want SpinJam to call start again when the Cast switch was previously on.
- **Lyric display offset (ms):** positive = lyrics appear **later** (see below)

## Entities

| Entity | Behaviour |
| --- | --- |
| `select.spinjam_display` | Which configured display to use |
| `switch.spinjam_cast` | On → same as `spinjam.start`; off → `spinjam.stop`. State = active SpinJam cast session (also clears if the display goes off/unavailable while built-in casting is on). |
| `switch.spinjam_tracking` | Off pauses source following and the ~1 s poll; now-playing **holds** last metadata (does not clear). **Does not** stop an active Cast. Restored across restarts; defaults to on. |
| `number.spinjam_lyric_offset` | Lyric display offset in ms (**positive = lyrics later**). Live — no reload. Restored. Range −5000…5000, step 50. The TV card reads this by default via `offset_entity`. |

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
| `lyrics` | Centred, fading, karaoke-sweep lyrics (optional `show_header` / `show_progress` / `font_scale`) |

Timing uses a **shared clock**: `media_position + (last_updated − media_position_updated_at)`, then advanced with `performance.now()` — the TV’s `Date.now()` is never compared to HA.

`lyric_lines` may include per-line `words: [{t, text}]` from LRCLIB enhanced tags. Attributes are capped (~120 lines) and **windowed** around the current position so long tracks stay light on a Pi 4.

Cast renders at **1080p** even on 4K TVs; the layout is tuned for that.

## Stop behaviour

`spinjam.stop` calls `media_player.turn_off` on the active Cast entity. That
ends the Cast session on Google TV / Chromecast without needing Browser Mod.

## Known limitations

- Dashboard/view must exist before the first `spinjam.start` (use `spinjam.create_dashboard` or create manually; path needs a hyphen).
- Cast requires HTTPS external URL; local HTTP-only setups will not work.
- Displays should be Google Cast entities; other `media_player` platforms are skipped for built-in casting.
- Re-cast briefly reloads the Lovelace view (possible flash every N seconds).
- `lyric_lines` is capped (~120 lines) to keep state attributes light on Pi 4.
- Bravia / Google TV power policies may still sleep the panel after idle.
- Album art URLs must be reachable from the Cast device (same as HA frontend).
