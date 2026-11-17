# SpinJam

**General now-playing for Home Assistant.** SpinJam aggregates Music Assistant, Sonos, and a vinyl MQTT capture node into one unified `media_player`, with optional LRCLIB synced lyrics and Cast to a TV. Vinyl recognition runs on a dedicated Pi — never on the HA host.

## Pieces

| Path | What |
| --- | --- |
| [`custom_components/spinjam`](custom_components/spinjam) | HACS-installable HA integration (brain + TV card) |
| [`spinjam/`](spinjam) | Vinyl capture/recognition MQTT node (Pi) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design |
| [`docs/TV_CAST.md`](docs/TV_CAST.md) | TV now-playing card + Cast setup |
| [`docs/PHASE0_HARDWARE.md`](docs/PHASE0_HARDWARE.md) | Port OUT → UCA202 cabling |
| [`docs/FIXTURE_MODE.md`](docs/FIXTURE_MODE.md) | Test vinyl node without USB hardware |

```
Music Assistant / Sonos media_players ──┐
                                        ├─► HA SpinJam ─► media_player.spinjam_now_playing
Vinyl Pi (Shazam → MQTT) ───────────────┘         │
                                                  ├─ LRCLIB lyrics (cached)
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
6. Optionally select **Displays** (Cast / Google TV targets), e.g. `media_player.living_room_tv`
7. Enable lyrics; leave sync / lyric offsets at `0` until you calibrate

The TV card ships with the integration (`/spinjam/spinjam-now-playing-card.js`) — no separate frontend install.

### Option B — Manual

Copy `custom_components/spinjam` into your HA `config/custom_components/spinjam`, restart, then add the integration as above.

### Cast the now-playing view (one-time)

1. Ensure **Google Cast** is set up and HA has an HTTPS **External URL**.  
2. Create a Lovelace dashboard path `spinjam` with a panel view path `now` using `custom:spinjam-now-playing-card` (full steps: [`docs/TV_CAST.md`](docs/TV_CAST.md)).  
3. Configure SpinJam options: displays + dashboard/view paths (defaults match above).  
4. Call `spinjam.start` / `spinjam.stop` (or automate on Port Line-in).

### Try it

1. Play a track on any configured Music Assistant or Sonos player.  
2. Open Developer Tools → States → `media_player.spinjam_now_playing`.  
3. Confirm artist/title/album/art; with lyrics enabled, check `lyric_current` / `lyric_next` / `lyric_lines`.  
4. Services: `spinjam.identify`, `spinjam.set_sync_offset`, `spinjam.select_album`, `spinjam.clear_lock`, `spinjam.start`, `spinjam.stop`.
5. Attributes include `displays`, `selected_display`, `lyric_offset_ms`.

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
