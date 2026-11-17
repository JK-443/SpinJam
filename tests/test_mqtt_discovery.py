from __future__ import annotations

import json

from spinjam.config import AppConfig, DeviceConfig, MqttConfig, SyncConfig
from spinjam.mqtt_ha import (
    NowPlaying,
    discovery_messages,
    media_player_attributes,
    media_player_state_payload,
)


def _config() -> AppConfig:
    return AppConfig(
        mqtt=MqttConfig(
            host="192.168.1.10",
            topic_prefix="spinjam",
            discovery_prefix="homeassistant",
            availability_topic="spinjam/status",
        ),
        device=DeviceConfig(
            name="SpinJam Turntable",
            identifiers=["spinjam_turntable"],
        ),
        sync=SyncConfig(offset_ms=0),
    )


def test_discovery_topics_and_core_fields() -> None:
    msgs = discovery_messages(_config())
    topics = [t for t, _, _ in msgs]
    assert "homeassistant/media_player/spinjam_turntable/config" in topics
    assert "homeassistant/sensor/spinjam_turntable_status/config" in topics
    assert "homeassistant/sensor/spinjam_turntable_level/config" in topics
    assert "homeassistant/number/spinjam_turntable_sync_offset/config" in topics
    assert "homeassistant/button/spinjam_turntable_identify/config" in topics

    by_topic = {t: p for t, p, _ in msgs}
    mp = by_topic["homeassistant/media_player/spinjam_turntable/config"]
    assert mp["unique_id"] == "spinjam_turntable"
    assert mp["state_topic"] == "spinjam/media_player/state"
    assert mp["json_attributes_topic"] == "spinjam/media_player/attributes"
    assert mp["availability_topic"] == "spinjam/status"
    assert mp["device"]["identifiers"] == ["spinjam_turntable"]
    assert mp["command_topic"] == "spinjam/cmd/media_player"

    status = by_topic["homeassistant/sensor/spinjam_turntable_status/config"]
    assert status["state_topic"] == "spinjam/status/detail"

    offset = by_topic["homeassistant/number/spinjam_turntable_sync_offset/config"]
    assert offset["command_topic"] == "spinjam/cmd/sync_offset_ms"
    assert offset["state_topic"] == "spinjam/sync/offset_ms"
    assert offset["min"] == -2000
    assert offset["max"] == 2000

    identify = by_topic["homeassistant/button/spinjam_turntable_identify/config"]
    assert identify["command_topic"] == "spinjam/cmd/identify"

    # All discovery retained
    assert all(retain for _, _, retain in msgs)

    # Payloads must be JSON-serializable (HA discovery)
    for _, payload, _ in msgs:
        json.dumps(payload)


def test_media_player_state_and_attributes() -> None:
    idle = NowPlaying(playing=False)
    assert media_player_state_payload(idle) == "idle"

    playing = NowPlaying(
        artist="Radiohead",
        title="Everything In Its Right Place",
        album="Kid A",
        art_url="https://example.com/art.jpg",
        playing=True,
        position_seconds=32.5,
        provider="shazam",
        source="auto",
    )
    assert media_player_state_payload(playing) == "playing"
    attrs = media_player_attributes(playing, status="locked", level_db=-12.34)
    assert attrs["media_artist"] == "Radiohead"
    assert attrs["media_title"] == "Everything In Its Right Place"
    assert attrs["media_album_name"] == "Kid A"
    assert attrs["entity_picture"] == "https://example.com/art.jpg"
    assert attrs["media_position"] == 32.5
    assert attrs["spinjam_status"] == "locked"
    assert attrs["provider"] == "shazam"
    assert attrs["level_db"] == -12.3
