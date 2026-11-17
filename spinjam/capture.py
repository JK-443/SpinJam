from __future__ import annotations

import logging
import subprocess
import time
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from spinjam.config import CaptureConfig

log = logging.getLogger(__name__)


class AudioSource(ABC):
    """Yields PCM16 little-endian frames of approximately frame_ms duration."""

    @abstractmethod
    def frames(self, frame_ms: int) -> Iterator[bytes]:
        raise NotImplementedError

    def close(self) -> None:
        return None


class FileAudioSource(AudioSource):
    """Replay a WAV fixture. Supports looping and optional realtime pacing."""

    def __init__(
        self,
        path: str | Path,
        *,
        loop: bool = True,
        realtime: bool = True,
        target_channels: int = 2,
        target_rate: int = 44100,
    ) -> None:
        self.path = Path(path)
        self.loop = loop
        self.realtime = realtime
        self.target_channels = target_channels
        self.target_rate = target_rate
        if not self.path.exists():
            raise FileNotFoundError(f"Fixture WAV not found: {self.path}")

    def _open(self) -> wave.Wave_read:
        wf = wave.open(str(self.path), "rb")
        if wf.getsampwidth() != 2:
            wf.close()
            raise ValueError(f"Only 16-bit PCM WAV is supported (got {wf.getsampwidth() * 8}-bit)")
        if wf.getframerate() != self.target_rate:
            log.warning(
                "Fixture sample rate %s != configured %s; proceeding without resampling",
                wf.getframerate(),
                self.target_rate,
            )
        return wf

    def frames(self, frame_ms: int) -> Iterator[bytes]:
        bytes_per_frame = None
        while True:
            wf = self._open()
            try:
                channels = wf.getnchannels()
                rate = wf.getframerate()
                frames_per_chunk = max(1, int(rate * frame_ms / 1000))
                bytes_per_frame = frames_per_chunk * channels * 2
                while True:
                    data = wf.readframes(frames_per_chunk)
                    if not data:
                        break
                    if len(data) < bytes_per_frame:
                        data = data + b"\x00" * (bytes_per_frame - len(data))
                    # Downmix/upmix channel count if needed (simple duplicate / take L)
                    if channels != self.target_channels:
                        data = _remix_pcm16(data, channels, self.target_channels)
                    if self.realtime:
                        time.sleep(frame_ms / 1000.0)
                    yield data
            finally:
                wf.close()
            if not self.loop:
                break


class AlsaAudioSource(AudioSource):
    """Capture from ALSA via `arecord` (works on Pi OS without extra Python audio deps)."""

    def __init__(
        self,
        device: str,
        *,
        sample_rate: int = 44100,
        channels: int = 2,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._proc: subprocess.Popen[bytes] | None = None

    def frames(self, frame_ms: int) -> Iterator[bytes]:
        frames_per_chunk = max(1, int(self.sample_rate * frame_ms / 1000))
        bytes_per_chunk = frames_per_chunk * self.channels * 2
        cmd = [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-t",
            "raw",
            "-",
        ]
        log.info("Starting ALSA capture: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert self._proc.stdout is not None
        try:
            while True:
                data = self._proc.stdout.read(bytes_per_chunk)
                if not data:
                    stderr = b""
                    if self._proc.stderr is not None:
                        stderr = self._proc.stderr.read()
                    raise RuntimeError(
                        f"arecord ended unexpectedly (code={self._proc.poll()}): {stderr.decode(errors='replace')}"
                    )
                if len(data) < bytes_per_chunk:
                    data = data + b"\x00" * (bytes_per_chunk - len(data))
                yield data
        finally:
            self.close()

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


def _remix_pcm16(data: bytes, src_ch: int, dst_ch: int) -> bytes:
    import struct

    count = len(data) // 2
    samples = list(struct.unpack("<" + "h" * count, data[: count * 2]))
    frames = len(samples) // src_ch
    out: list[int] = []
    for i in range(frames):
        frame = samples[i * src_ch : (i + 1) * src_ch]
        if dst_ch == 1:
            out.append(int(sum(frame) / len(frame)))
        elif src_ch == 1:
            out.extend([frame[0]] * dst_ch)
        else:
            # Take first dst_ch channels, pad if needed
            take = frame[:dst_ch]
            while len(take) < dst_ch:
                take.append(take[-1] if take else 0)
            out.extend(take)
    return struct.pack("<" + "h" * len(out), *out)


class RingBuffer:
    """Keep the last N seconds of PCM for identification clips."""

    def __init__(self, sample_rate: int, channels: int, seconds: float) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_bytes = int(sample_rate * channels * 2 * seconds)
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)
        if len(self._buf) > self.max_bytes:
            overflow = len(self._buf) - self.max_bytes
            del self._buf[:overflow]

    def snapshot(self, seconds: float | None = None) -> bytes:
        if seconds is None:
            return bytes(self._buf)
        want = int(self.sample_rate * self.channels * 2 * seconds)
        if want >= len(self._buf):
            return bytes(self._buf)
        return bytes(self._buf[-want:])

    def __len__(self) -> int:
        return len(self._buf)


def build_audio_source(config: CaptureConfig) -> AudioSource:
    mode = config.mode.lower().strip()
    if mode == "file":
        return FileAudioSource(
            config.file_path,
            loop=config.file_loop,
            realtime=config.file_realtime,
            target_channels=config.channels,
            target_rate=config.sample_rate,
        )
    if mode == "alsa":
        return AlsaAudioSource(
            config.alsa_device,
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
    raise ValueError(f"Unknown capture.mode: {config.mode!r} (expected 'alsa' or 'file')")
