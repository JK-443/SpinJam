# Fixture / file capture mode

Until a Behringer UCA202 (or similar) is available, SpinJam can run end-to-end on any machine (including CI) using a WAV fixture.

## What it does

- `capture.mode: file` reads a 16-bit PCM WAV (`fixtures/sample_music.wav` by default).
- Optional `file_loop: true` repeats forever.
- `file_realtime: true` sleeps per frame to simulate wall-clock audio; set `false` (or pass `--no-realtime`) for fast CI.
- With `identify.use_shazam: false` (or `--no-shazam`), a **FixtureIdentifier** returns a canned track when the buffer is loud enough — no network Shazam required.
- MQTT discovery and state publish the same way as live mode (point `mqtt.host` at Mosquitto, or use unit tests that build payloads without a broker).

## Generate / refresh the fixture WAV

```bash
python3 scripts/generate_fixture_wav.py
```

This writes `fixtures/sample_music.wav`: silence → tone (music) → silence (gap) → tone → long silence (idle). That sequence exercises the silence FSM.

## Run against MQTT without USB audio

```bash
cp config.example.yaml config.yaml
# edit mqtt.host / credentials
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
spinjam -c config.yaml --no-shazam --no-realtime
```

Or:

```bash
spinjam -c config.yaml --file fixtures/sample_music.wav --no-shazam --no-realtime --mqtt-host mqtt.example.local
```

Watch HA → MQTT devices for **SpinJam Turntable**, or subscribe:

```bash
mosquitto_sub -h <broker> -t 'spinjam/#' -v
mosquitto_sub -h <broker> -t 'homeassistant/+/spinjam_turntable/#' -v
```

## Switch to live UCA202 later

```yaml
capture:
  mode: alsa
  alsa_device: "plughw:1,0"   # from arecord -l
identify:
  use_shazam: true
```

Keep the same MQTT settings. No HA reinstall required — discovery topics stay stable.
