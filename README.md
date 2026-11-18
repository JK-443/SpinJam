# SpinJam

<p align="center">
  <img src="images/logo-1024.png" alt="SpinJam" width="220" />
</p>

**General now-playing for Home Assistant.** SpinJam aggregates Music Assistant, Sonos, and a vinyl MQTT capture node into one unified `media_player`, with optional synced lyrics and Cast to a TV. Vinyl recognition runs on a dedicated Pi — never on the HA host.

## Pieces

| Path | What |
| --- | --- |
| [`custom_components/spinjam`](custom_components/spinjam) | HACS-installable HA integration (brain + TV card) |
| [`spinjam/`](spinjam) | Vinyl capture/recognition MQTT node (Pi) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design |
| [`docs/TV_CAST.md`](docs/TV_CAST.md) | TV now-playing card + Cast setup |
| [`docs/BRANDING.md`](docs/BRANDING.md) | Logo / brand images (local `brand/` + HACS) |
| [`docs/PHASE0_HARDWARE.md`](docs/PHASE0_HARDWARE.md) | Port OUT → UCA202 cabling |
| [`docs/FIXTURE_MODE.md`](docs/FIXTURE_MODE.md) | Test vinyl node without USB hardware |
| [`images/`](images/) | Logo pack (`logo-1024.png`, icons, source) |

```
Music Assistant / Sonos media_players ──┐
                                        ├─► HA SpinJam ─► media_player.spinjam_now_playing
Vinyl Pi (Shazam → MQTT) ───────────────┘         │
                                                  ├─ Lyrics (LRCLIB, then fallbacks)
                                                  └─ cast.show_lovelace_view → TV
```

When a configured Sonos/Port player’s source is **Line-in**, SpinJam uses the vinyl MQTT player instead of Port metadata.

## Install the HA integration

### Option A — HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories  
2. URL: `https://github.com/JK-443/SpinJam`, category **Integration**  
3. Download **SpinJam**, then restart Home Assistant  
4. Settings → Devices & services → Add Integration → **SpinJam**  
5. Select source media players (priority order), e.g.:
   - `media_player.turntable` (Music Assistant)
   - Sonos rooms (`media_player.living_room`, `media_player.kitchen`, …)
   - Optional vinyl: `media_player.spinjam_turntable` (after the capture node is up)
6. Optionally select **Displays** (Google Cast targets), e.g. `media_player.example_tv`
7. Enable lyrics; leave sync / lyric offsets at `0` until you calibrate

The TV card ships with the integration (`/spinjam/spinjam-lyrics-card.js?v=…`, modes `details` / `lyrics`) — no separate frontend install. With lyrics off, the Cast view is one full-width stage instead of two panels. `spinjam-now-playing-card` remains a deprecated alias.

### Option B — Manual

Copy `custom_components/spinjam` into your HA `config/custom_components/spinjam`, restart, then add the integration as above.

### Cast the now-playing view (one-time)

1. Ensure **Google Cast** is set up and HA has an HTTPS **External URL**.  
2. Call `spinjam.create_dashboard` (or manually create Lovelace path `spinjam-tv` with panel view `now` — HA requires a hyphen in the path). Full steps: [`docs/TV_CAST.md`](docs/TV_CAST.md).  
3. Configure SpinJam options: Cast displays + dashboard/view paths (defaults `spinjam-tv` / `now`).  
4. Use `switch.spinjam_cast`, or `spinjam.start` / `spinjam.stop` (or automate on Port Line-in).

### Controls

| Entity | Role |
| --- | --- |
| `switch.spinjam_cast` | **On/off.** On = wake + cast + tracking (`spinjam.start`); off = quit Cast, tracking off, clear now-playing (`spinjam.stop`). Tracking is derived from Cast. The old `switch.spinjam_tracking` entity is removed on upgrade. |
| `select.spinjam_display` | Which configured Cast display to use. |
| `select.spinjam_source` | **Source.** `Automatic` (default) ranks configured players (playing over paused, sticky within a track). Any other option follows only that player, including the vinyl player when one is configured. Restored across restarts. |
| `switch.spinjam_lyrics` | On (default) fetches/shows the two-panel lyrics layout. Off switches live to one full-width stage (blurred cover, centred art, title, artist, album, slim progress) and sets `lyrics_status` to `disabled`. No Cast restart. |

Options: **Built-in casting** (default on) — when off, start/stop and the Cast switch only fire `spinjam_start` / `spinjam_stop` so you can cast from your own automations without double-casting. **Recast on startup** (default off) — only then will a previously-on Cast switch re-cast after an HA restart. **Fallback lyrics providers** (default lyrics.ovh) run in list order after LRCLIB misses. QQ Music is an unofficial endpoint, for personal use, and is off until selected. It can return synced lyrics; lyrics.ovh returns plain text.

### Lyrics lookup

1. LRCLIB `/api/get`, then `/api/search` (artist + title, duration within 3 s, prefer synced).
2. The same calls again with a cleaned title (remaster, featured artist, live, version, radio edit), then a free-text search.
3. Each selected fallback, in order. A miss is cached for 6 hours. Timeouts and server errors are not cached.

`media_player.spinjam_now_playing` exposes `lyrics_status` (`synced`, `plain`, `instrumental`, `not_found`, `error`, `disabled`) and `lyrics_source` (`lrclib`, `qqmusic`, `lyricsovh`). Plain lyrics are static centred text. The TV card shows a dim footer (`Lyrics: LRCLIB`, `Lyrics: QQ Music`, `Lyrics: lyrics.ovh`). Lookups run in the background and do not block now-playing updates.

### Try it

1. Play a track on any configured Music Assistant or Sonos player.  
2. Open Developer Tools → States → `media_player.spinjam_now_playing`.  
3. Confirm artist/title/album/art; with lyrics enabled, check `lyric_current` / `lyric_next` / `lyric_lines`.  
4. Services: `spinjam.identify`, `spinjam.set_sync_offset`, `spinjam.select_album`, `spinjam.clear_lock`, `spinjam.start`, `spinjam.stop`.
5. Device page order: Cast, Display, Source, Lyrics, Now Playing. Configuration: Lyric offset (`number.spinjam_lyric_offset`).
6. Attributes include `displays`, `selected_display`, `selected_source` (`Automatic` or a `media_player` entity id), `active_source`, `lyric_offset_ms`, `lyrics_duration`, `lyrics_duration_delta`, `lyric_lines` (optional `words`), `lyrics_status`, `lyrics_source`, `tracking_enabled`, `cast_active`, `artwork_hd`, `artwork_source`, `artwork_next`, `lyrics_enabled`.

## Vinyl capture node (optional source)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml   # mqtt.host = Mosquitto
spinjam -c config.yaml --no-shazam --no-realtime   # fixture mode
```

Live ALSA + Shazam after UCA202: see Phase 0 docs. Optional AudD / ACRCloud fallback keys go under `identify:` in `config.yaml`.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
# Optional full HA integration tests:
pip install -e ".[ha]"
pytest -q
```

## Roadmap

- **Album lock:** Discogs tracklists + vinyl position confirm
- **Polish:** art caching, scrobble

## Licence

MIT
