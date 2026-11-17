from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

import paho.mqtt.client as mqtt

from spinjam.config import AppConfig, DeviceConfig, MqttConfig

log = logging.getLogger(__name__)

CommandHandler = Callable[[str, dict[str, Any] | str | None], None]


@dataclass(frozen=True)
class NowPlaying:
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    art_url: str | None = None
    playing: bool = False
    position_seconds: float | None = None
    duration_seconds: float | None = None
    source: str = "auto"
    provider: str | None = None


def device_payload(device: DeviceConfig) -> dict[str, Any]:
    return {
        "identifiers": device.identifiers,
        "name": device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
    }


def discovery_messages(config: AppConfig) -> list[tuple[str, dict[str, Any], bool]]:
    """Return (topic, payload, retain) HA MQTT discovery configs."""
    mqtt_cfg = config.mqtt
    prefix = mqtt_cfg.topic_prefix.rstrip("/")
    disc = mqtt_cfg.discovery_prefix.rstrip("/")
    avail = mqtt_cfg.availability_topic
    device = device_payload(config.device)
    object_id = "spinjam_turntable"
    state_topic = f"{prefix}/media_player/state"
    attr_topic = f"{prefix}/media_player/attributes"
    cmd_topic = f"{prefix}/cmd/media_player"

    messages: list[tuple[str, dict[str, Any], bool]] = []

    messages.append(
        (
            f"{disc}/media_player/{object_id}/config",
            {
                "name": config.device.name,
                "unique_id": object_id,
                "object_id": object_id,
                "state_topic": state_topic,
                "json_attributes_topic": attr_topic,
                "availability_topic": avail,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                "command_topic": cmd_topic,
                "device_class": "receiver",
            },
            True,
        )
    )

    messages.append(
        (
            f"{disc}/sensor/{object_id}_status/config",
            {
                "name": "SpinJam Status",
                "unique_id": f"{object_id}_status",
                "object_id": f"{object_id}_status",
                "state_topic": f"{prefix}/status/detail",
                "availability_topic": avail,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                "icon": "mdi:album",
            },
            True,
        )
    )

    messages.append(
        (
            f"{disc}/sensor/{object_id}_level/config",
            {
                "name": "SpinJam Level",
                "unique_id": f"{object_id}_level",
                "object_id": f"{object_id}_level",
                "state_topic": f"{prefix}/audio/level_db",
                "unit_of_measurement": "dB",
                "availability_topic": avail,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                "icon": "mdi:volume-high",
                "state_class": "measurement",
            },
            True,
        )
    )

    messages.append(
        (
            f"{disc}/number/{object_id}_sync_offset/config",
            {
                "name": "SpinJam Sync Offset",
                "unique_id": f"{object_id}_sync_offset",
                "object_id": f"{object_id}_sync_offset",
                "command_topic": f"{prefix}/cmd/sync_offset_ms",
                "state_topic": f"{prefix}/sync/offset_ms",
                "availability_topic": avail,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                "min": -2000,
                "max": 2000,
                "step": 10,
                "unit_of_measurement": "ms",
                "icon": "mdi:timer-sync",
            },
            True,
        )
    )

    messages.append(
        (
            f"{disc}/button/{object_id}_identify/config",
            {
                "name": "SpinJam Identify Now",
                "unique_id": f"{object_id}_identify",
                "object_id": f"{object_id}_identify",
                "command_topic": f"{prefix}/cmd/identify",
                "availability_topic": avail,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
                "icon": "mdi:microphone",
            },
            True,
        )
    )

    return messages


def media_player_state_payload(np: NowPlaying) -> str:
    return "playing" if np.playing and (np.title or np.artist) else ("idle" if not np.playing else "playing")


def media_player_attributes(np: NowPlaying, *, status: str, level_db: float | None = None) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "source": np.source,
        "spinjam_status": status,
        "provider": np.provider,
    }
    if np.artist:
        attrs["media_artist"] = np.artist
    if np.title:
        attrs["media_title"] = np.title
    if np.album:
        attrs["media_album_name"] = np.album
    if np.art_url:
        attrs["entity_picture"] = np.art_url
    if np.duration_seconds is not None:
        attrs["media_duration"] = np.duration_seconds
    if np.position_seconds is not None:
        attrs["media_position"] = np.position_seconds
    if level_db is not None:
        attrs["level_db"] = round(level_db, 1)
    return attrs


class MqttHaClient:
    def __init__(self, config: AppConfig, on_command: CommandHandler | None = None) -> None:
        self.config = config
        self.mqtt_cfg: MqttConfig = config.mqtt
        self.on_command = on_command
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.mqtt_cfg.client_id,
        )
        if self.mqtt_cfg.username:
            self._client.username_pw_set(self.mqtt_cfg.username, self.mqtt_cfg.password or "")
        self._client.will_set(self.mqtt_cfg.availability_topic, "offline", retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._connected = False

    def connect(self) -> None:
        log.info("Connecting MQTT %s:%s", self.mqtt_cfg.host, self.mqtt_cfg.port)
        self._client.connect(self.mqtt_cfg.host, self.mqtt_cfg.port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        try:
            self.publish(self.mqtt_cfg.availability_topic, "offline", retain=True)
        except Exception:
            pass
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
        _ = userdata, flags, properties
        rc = getattr(reason_code, "value", reason_code)
        try:
            rc_int = int(rc)
        except (TypeError, ValueError):
            rc_int = 0 if str(reason_code) in {"Success", "0"} else 1
        if rc_int != 0:
            log.error("MQTT connect failed: %s", reason_code)
            return
        log.info("MQTT connected")
        self._connected = True
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        client.subscribe(f"{prefix}/cmd/#")
        self.publish_discovery()
        self.publish(self.mqtt_cfg.availability_topic, "online", retain=True)
        self.publish(f"{prefix}/sync/offset_ms", str(self.config.sync.offset_ms), retain=True)

    def _on_message(self, client, userdata, msg) -> None:  # noqa: ANN001
        _ = client, userdata
        topic = msg.topic
        payload_raw = msg.payload.decode("utf-8", errors="replace").strip()
        parsed: dict[str, Any] | str | None
        if not payload_raw:
            parsed = None
        else:
            try:
                parsed = json.loads(payload_raw)
            except json.JSONDecodeError:
                parsed = payload_raw
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        if not topic.startswith(f"{prefix}/cmd/"):
            return
        command = topic[len(f"{prefix}/cmd/") :]
        log.info("MQTT command %s: %r", command, parsed)
        if self.on_command:
            self.on_command(command, parsed)

    def publish(self, topic: str, payload: str | dict[str, Any], retain: bool = False) -> None:
        body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        self._client.publish(topic, body, qos=0, retain=retain)

    def publish_discovery(self) -> None:
        for topic, payload, retain in discovery_messages(self.config):
            self.publish(topic, payload, retain=retain)
            log.debug("Published discovery %s", topic)

    def publish_status(self, status: str) -> None:
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        self.publish(f"{prefix}/status/detail", status, retain=True)

    def publish_level(self, level_db: float) -> None:
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        self.publish(f"{prefix}/audio/level_db", f"{level_db:.1f}")

    def publish_now_playing(self, np: NowPlaying, *, status: str, level_db: float | None = None) -> None:
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        self.publish(f"{prefix}/media_player/state", media_player_state_payload(np), retain=True)
        self.publish(
            f"{prefix}/media_player/attributes",
            media_player_attributes(np, status=status, level_db=level_db),
            retain=True,
        )

    def publish_sync_offset(self, offset_ms: int) -> None:
        prefix = self.mqtt_cfg.topic_prefix.rstrip("/")
        self.publish(f"{prefix}/sync/offset_ms", str(offset_ms), retain=True)
