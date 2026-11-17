"""Constants for SpinJam."""

from __future__ import annotations

DOMAIN = "spinjam"

CONF_SOURCE_PLAYERS = "source_players"
CONF_VINYL_PLAYER = "vinyl_player"
CONF_DISPLAYS = "displays"
# Legacy single-display key (pre multi-display); read for migration only.
CONF_DISPLAY_ENTITY = "display_entity"
CONF_SYNC_OFFSET_MS = "sync_offset_ms"
CONF_LYRIC_OFFSET_MS = "lyric_offset_ms"
CONF_LYRICS_ENABLED = "lyrics_enabled"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DASHBOARD_PATH = "dashboard_path"
CONF_VIEW_PATH = "view_path"
CONF_RECAST_WHILE_PLAYING = "recast_while_playing"
CONF_RECAST_INTERVAL = "recast_interval"
CONF_BUILTIN_CASTING = "builtin_casting"
CONF_RECAST_ON_STARTUP = "recast_on_startup"

DEFAULT_NAME = "SpinJam Now Playing"
DEFAULT_SYNC_OFFSET_MS = 0
DEFAULT_LYRIC_OFFSET_MS = 0
DEFAULT_LYRICS_ENABLED = True
DEFAULT_UPDATE_INTERVAL = 1.0
DEFAULT_DASHBOARD_PATH = "spinjam-tv"
DEFAULT_VIEW_PATH = "now"
LEGACY_DASHBOARD_PATH = "spinjam"
DEFAULT_RECAST_WHILE_PLAYING = True
DEFAULT_RECAST_INTERVAL = 45.0
DEFAULT_BUILTIN_CASTING = True
DEFAULT_RECAST_ON_STARTUP = False

ATTR_LYRIC_CURRENT = "lyric_current"
ATTR_LYRIC_NEXT = "lyric_next"
ATTR_LYRIC_LINES = "lyric_lines"
ATTR_LYRIC_OFFSET_MS = "lyric_offset_ms"
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
SERVICE_CREATE_DASHBOARD = "create_dashboard"

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
SWITCH_CAST_ENTITY_ID = "switch.spinjam_cast"
SWITCH_TRACKING_ENTITY_ID = "switch.spinjam_tracking"
NUMBER_LYRIC_OFFSET_ENTITY_ID = "number.spinjam_lyric_offset"

# lyric_lines attribute: hard cap; window keeps context around the current line.
LYRIC_LINES_ATTR_MAX = 120
LYRIC_LINES_WINDOW_BEFORE = 40
