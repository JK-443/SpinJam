"""Constants for SpinJam."""

from __future__ import annotations

DOMAIN = "spinjam"

CONF_SOURCE_PLAYERS = "source_players"
CONF_VINYL_PLAYER = "vinyl_player"
CONF_DISPLAYS = "displays"
# Legacy single-display key (pre multi-display); read for migration only.
CONF_DISPLAY_ENTITY = "display_entity"
CONF_SYNC_OFFSET_MS = "sync_offset_ms"
CONF_LYRICS_ENABLED = "lyrics_enabled"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_NAME = "SpinJam Now Playing"
DEFAULT_SYNC_OFFSET_MS = 0
DEFAULT_LYRICS_ENABLED = True
DEFAULT_UPDATE_INTERVAL = 1.0

ATTR_LYRIC_CURRENT = "lyric_current"
ATTR_LYRIC_NEXT = "lyric_next"
ATTR_LYRIC_LINES = "lyric_lines"
ATTR_ACTIVE_SOURCE = "active_source"
ATTR_SOURCE_KIND = "source_kind"
ATTR_DISPLAYS = "displays"
ATTR_SELECTED_DISPLAY = "selected_display"
ATTR_SYNC_OFFSET_MS = "sync_offset_ms"
ATTR_ALBUM_LOCK = "album_lock"

SERVICE_IDENTIFY = "identify"
SERVICE_SET_SYNC_OFFSET = "set_sync_offset"
SERVICE_SELECT_ALBUM = "select_album"
SERVICE_CLEAR_LOCK = "clear_lock"
SERVICE_START = "start"
SERVICE_STOP = "stop"

EVENT_SPINJAM_START = "spinjam_start"
EVENT_SPINJAM_STOP = "spinjam_stop"

SOURCE_KIND_STREAM = "stream"
SOURCE_KIND_VINYL = "vinyl"
SOURCE_KIND_LINE_IN = "line_in"

LINE_IN_SOURCES = frozenset(
    {
        "line-in",
        "line_in",
        "line in",
        "linein",
        "audio line-in",
    }
)

MQTT_CMD_IDENTIFY = "spinjam/cmd/identify"
MQTT_CMD_SYNC_OFFSET = "spinjam/cmd/sync_offset_ms"
MQTT_CMD_CLEAR = "spinjam/cmd/clear"
MQTT_CMD_SELECT_ALBUM = "spinjam/cmd/select_album"

LRCLIB_API = "https://lrclib.net/api/get"
LYRICS_CACHE_SIZE = 64

SELECT_DISPLAY_ENTITY_ID = "select.spinjam_display"
