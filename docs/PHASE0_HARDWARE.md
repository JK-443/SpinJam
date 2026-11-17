# Phase 0 — Hardware & Port prep

This document is the shopping / cabling checklist before live ALSA capture. Phase 1 software can be tested **without** this hardware using file/fixture mode.

## Bill of materials

| Item | Qty | Notes |
| --- | --- | --- |
| Behringer UCA202 (or UCA222 / UFO202) | 1 | RCA in → USB; class-compliant “USB Audio CODEC” on Linux |
| RCA stereo cable | 1 | Sonos Port **OUT** → UCA202 **INPUT** |
| Capture Pi | 1 | **Interim:** Pi Zero 2 W + solid 2.5 A+ PSU. **Target:** freed Pi 4 4GB |
| MicroSD (16 GB+) | 1 | Raspberry Pi OS Lite 64-bit recommended |
| Ethernet (optional but preferred) | 1 | Especially for Zero 2 W Wi‑Fi + USB audio contention |

Do **not** plug the UCA202 into the current HAOS Pi (memory-starved; recognition stays off-box).

## Sonos Port settings

Example Port at `192.168.1.50` (name it whatever you like in Sonos, e.g. “Turntable”):

1. Connect turntable **line-level** to Port **IN** (existing).
2. Connect Port **analog OUT** → UCA202 INPUT with RCA.
3. In the Sonos app → Port settings:
   - **Line-Out Level = Fixed** (capture level stays stable).
   - Set **Line-In audio delay** as low as you can live with (Sonos floor ~75 ms; factory defaults can be ~2 s). Lower delay = tighter speaker timing; SpinJam captures **after** this buffer when using Port OUT, so lyrics later sync to what you hear.
4. Confirm Port OUT only carries audio while line-in is playing (expected — use as an implicit “armed” signal).

### Fallback

If Port OUT must stay free later, use an RCA **Y-splitter on Port OUT** (not preferred on Port IN unless OUT is unavailable). Pre-Port split ahead of Port IN is the last resort and **adds** Sonos buffer skew relative to speakers — then use `sync_offset_ms` to compensate.

### Digital option (later)

Port has **coaxial digital OUT** (not Toslink). Only pursue SPDIF→USB if analog is noisy; UCA202 is analog-only.

## Capture node OS notes

### Pi Zero 2 W

USB audio + onboard Wi‑Fi can starve each other with the default USB driver. If Wi‑Fi drops when the UCA202 streams, add to `/boot/firmware/config.txt` (or `/boot/config.txt`) and reboot:

```
dtoverlay=dwc2,dr_mode=host
```

Use a proper PSU; brownouts look like random Wi‑Fi death.

### Pi 4 (target)

No special USB overlay usually required. Prefer Ethernet to the same LAN as Mosquitto / HA.

## Verify the audio chain (once UCA202 arrives)

On the capture Pi:

```bash
arecord -l
# Expect something like: card 1: CODEC [USB Audio CODEC], device 0

arecord -D plughw:1,0 -f S16_LE -r 44100 -c 2 -d 5 /tmp/port-out-test.wav
```

Start Port line-in playback, then check levels:

```bash
# Rough level meter while playing
arecord -D plughw:1,0 -f S16_LE -r 44100 -c 2 -t raw - | \
  python3 -c "import sys,struct,math; d=sys.stdin.buffer.read(44100*2*2);
s=struct.unpack('<'+'h'*(len(d)//2),d); m=sum(x*x for x in s)/len(s);
print('dBFS', 20*math.log10(math.sqrt(m)/32768) if m else -120)"
```

Music should land roughly **−20 to −5 dBFS**. Silence near **≤ −40 dBFS**. Adjust Port Fixed out / UCA input switch if needed, then tune `silence.threshold_db` in `config.yaml` (default `-35`).

## MQTT / HA prep (no code on HA yet)

- Mosquitto already installed — note host IP, port, and any user/password for `config.yaml`.
- Phase 2 will add Lovelace + Cast automations. Phase 1 only needs MQTT discovery enabled in HA (default when MQTT integration is configured).

## Without hardware (today)

Use file/fixture mode — see [FIXTURE_MODE.md](FIXTURE_MODE.md) and the README.
