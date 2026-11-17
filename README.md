# SpinJam

Vinyl capture and recognition node for Home Assistant. Taps the **Sonos Port line-out** (Fixed), identifies the playing track, and publishes a `media_player` plus sensors to HA over **MQTT**. Recognition runs on a dedicated Pi — not on the HA host.

Phase 1 delivers the capture/recognition service, MQTT discovery, silence FSM, Shazam (optional), and a **file/fixture mode** so you can test before the UCA202 arrives.

## Architecture (Phase 1)

```
Turntable → Sonos Port IN → Sonos speakers
                 ↓
            Port OUT (Fixed) → UCA202 → Pi (SpinJam)
                                           ↓ MQTT
                                      Mosquitto → HA
```

Docs:

- [Phase 0 hardware & Port prep](docs/PHASE0_HARDWARE.md)
- [Fixture / file mode](docs/FIXTURE_MODE.md)

## Quick start (no USB hardware)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python3 scripts/generate_fixture_wav.py
cp config.example.yaml config.yaml
# set mqtt.host to your Mosquitto broker (or leave 127.0.0.1 for local broker)

pytest -q
spinjam -c config.yaml --no-shazam --no-realtime
```

With a broker, HA should auto-discover **SpinJam Turntable** (`media_player.spinjam_turntable`) when MQTT discovery is enabled.

### Commands (MQTT)

| Topic | Payload | Effect |
| --- | --- | --- |
| `spinjam/cmd/identify` | any | Force a recognition pass |
| `spinjam/cmd/sync_offset_ms` | `0` or `{"value": 50}` | Set lyric/position offset (ms) |
| `spinjam/cmd/clear` | any | Clear now-playing metadata |

## Live capture (after UCA202)

1. Follow [Phase 0](docs/PHASE0_HARDWARE.md): Port OUT Fixed → UCA202 → Pi.
2. `arecord -l` and set `capture.alsa_device` (often `plughw:1,0`).
3. In `config.yaml`:

```yaml
capture:
  mode: alsa
  alsa_device: "plughw:1,0"
identify:
  use_shazam: true
```

4. Install as a service (Pi OS):

```bash
sudo mkdir -p /opt/spinjam
sudo rsync -a --exclude .venv ./ /opt/spinjam/
cd /opt/spinjam && sudo python3 -m venv .venv && sudo .venv/bin/pip install -e .
sudo cp deploy/spinjam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spinjam
```

Pi Zero 2 W: see USB/Wi‑Fi note in Phase 0 docs (`dtoverlay=dwc2,dr_mode=host`).

## MQTT entities (discovery)

- `media_player.spinjam_turntable` — artist / title / album / art URL attributes
- `sensor.spinjam_turntable_status` — `idle` / `music` / `gap` / `identifying` / `locked`
- `sensor.spinjam_turntable_level` — input level dBFS
- `number.spinjam_turntable_sync_offset` — ms offset for later lyrics sync
- `button.spinjam_turntable_identify` — identify now

## Tests

```bash
pytest -q
```

Covers silence FSM transitions and HA MQTT discovery payload shape.

## Roadmap

- **Phase 2:** HA Lovelace `spinjam-now` view + Bravia Cast automations
- **Phase 3:** Manual album select + Discogs tracklist lock
- **Phase 4:** LRCLIB synced lyrics
- **Phase 5:** AudD/ACR fallback, polish

## Licence

MIT
