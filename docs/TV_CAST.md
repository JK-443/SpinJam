# TV now-playing + Cast

SpinJam casts a full-screen now-playing Lovelace view to a Google Cast /
Google TV `media_player` (e.g. `media_player.living_room_tv`) when you call
`spinjam.start`. `spinjam.stop` ends the session.

Browser Mod and Fully Kiosk are **not** required.

## One-time Home Assistant setup

HA does not let custom integrations reliably auto-create Lovelace dashboards
across YAML and storage modes, so create the dashboard once:

### 1. Prerequisites

1. **Google Cast** integration enabled; your TV appears as a `media_player`.
2. Home Assistant reachable over **HTTPS** with a valid **External URL**
   (Settings → System → Network). Cast cannot load HTTP-only dashboards.
3. SpinJam installed (HACS or manual). The custom card is registered at
   `/spinjam/spinjam-now-playing-card.js` automatically — no separate frontend
   install.

### 2. Create the dashboard + view

**UI (storage mode):**

1. Settings → Dashboards → **Add dashboard**
2. Title: `SpinJam`, URL path: `spinjam` (must match options `dashboard_path`)
3. Open the dashboard → edit → add a view:
   - Title: `Now`
   - Path: `now` (must match options `view_path`)
   - Type: **Panel** (one card fills the screen)
4. Add card → Manual YAML:

```yaml
type: custom:spinjam-now-playing-card
entity: media_player.spinjam_now_playing
```

**YAML mode alternative:** add a dashboard that loads
[`docs/lovelace/spinjam.yaml`](lovelace/spinjam.yaml) (copy into your config
and reference it from `lovelace:` / dashboards config).

### 3. Configure SpinJam displays

Settings → Devices & services → SpinJam → Configure:

- **Displays:** e.g. `media_player.living_room_tv`
- **Cast dashboard path:** `spinjam` (default)
- **Cast view path:** `now` (default)
- **Re-cast while playing:** on (default) — recovers dropped Cast sessions
- **Lyric display offset (ms):** fine-tune highlight timing (see below)

## Usage

```yaml
service: spinjam.start
data:
  display: media_player.living_room_tv   # optional; uses select.spinjam_display
```

```yaml
service: spinjam.stop
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
      display: media_player.living_room_tv
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
2. `lyric_offset_ms` — shifts **lyric highlighting only** (positive = lyrics later).

Tune with a known track until the highlighted line matches what you hear.
Both are in SpinJam options; `spinjam.set_sync_offset` still updates playback sync live.

## What the card shows

- Idle: “SPINJAM / Waiting for music…” when nothing is playing
- Playing/paused: large album art, title, artist, album, progress bar
- Synced LRCLIB lyrics with current line highlighted and auto-scroll
- Driven by `media_player.spinjam_now_playing` (`lyric_lines`, position attrs)

Cast renders at **1080p** even on 4K TVs; the layout is tuned for that.

## Stop behaviour

`spinjam.stop` calls `media_player.turn_off` on the active Cast entity. That
ends the Cast session on Google TV / Chromecast without needing Browser Mod.

## Known limitations

- Dashboard/view must exist before the first `spinjam.start` (one-time setup).
- Cast requires HTTPS external URL; local HTTP-only setups will not work.
- Re-cast briefly reloads the Lovelace view (possible flash every N seconds).
- `lyric_lines` is capped (~120 lines) to keep state attributes light on Pi 4.
- Bravia / Google TV power policies may still sleep the panel after idle.
- Album art URLs must be reachable from the Cast device (same as HA frontend).
