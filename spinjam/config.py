from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MqttConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "spinjam-capture"
    topic_prefix: str = "spinjam"
    discovery_prefix: str = "homeassistant"
    availability_topic: str = "spinjam/status"


@dataclass
class DeviceConfig:
    name: str = "SpinJam Turntable"
    manufacturer: str = "SpinJam"
    model: str = "capture-node"
    identifiers: list[str] = field(default_factory=lambda: ["spinjam_turntable"])


@dataclass
class CaptureConfig:
    mode: str = "file"  # alsa | file
    alsa_device: str = "plughw:1,0"
    sample_rate: int = 44100
    channels: int = 2
    file_path: str = "fixtures/sample_music.wav"
    file_loop: bool = True
    file_realtime: bool = True


@dataclass
class SilenceConfig:
    threshold_db: float = -35.0
    music_hold_ms: int = 400
    gap_hold_ms: int = 1500
    idle_hold_ms: int = 8000
    frame_ms: int = 100


@dataclass
class IdentifyConfig:
    enabled: bool = True
    clip_seconds: float = 5.0
    min_interval_seconds: float = 12.0
    auto_on_music: bool = True
    use_shazam: bool = True
    # Optional paid/fallback providers (tried after Shazam when configured)
    audd_api_token: str | None = None
    acr_host: str | None = None
    acr_access_key: str | None = None
    acr_access_secret: str | None = None


@dataclass
class SyncConfig:
    offset_ms: int = 0


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class AppConfig:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    silence: SilenceConfig = field(default_factory=SilenceConfig)
    identify: IdentifyConfig = field(default_factory=IdentifyConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _merge_dataclass(cls: type, data: dict[str, Any] | None) -> Any:
    if not data:
        return cls()
    valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in valid})


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return AppConfig(
        mqtt=_merge_dataclass(MqttConfig, raw.get("mqtt")),
        device=_merge_dataclass(DeviceConfig, raw.get("device")),
        capture=_merge_dataclass(CaptureConfig, raw.get("capture")),
        silence=_merge_dataclass(SilenceConfig, raw.get("silence")),
        identify=_merge_dataclass(IdentifyConfig, raw.get("identify")),
        sync=_merge_dataclass(SyncConfig, raw.get("sync")),
        logging=_merge_dataclass(LoggingConfig, raw.get("logging")),
    )