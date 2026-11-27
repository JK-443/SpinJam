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
CONF_LYRIC_NUDGE_MS = "lyric_nudge_ms"
CONF_SCALE_LYRICS = "scale_lyrics"
CONF_LYRICS_ENABLED = "lyrics_enabled"
CONF_FALLBACK_PROVIDERS = "fallback_providers"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DASHBOARD_PATH = "dashboard_path"
CONF_VIEW_PATH = "view_path"
CONF_RECAST_WHILE_PLAYING = "recast_while_playing"
CONF_RECAST_INTERVAL = "recast_interval"
CONF_BUILTIN_CASTING = "builtin_casting"
CONF_RECAST_ON_STARTUP = "recast_on_startup"
CONF_POWER_OFF_DISPLAY_ON_STOP = "power_off_display_on_stop"
CONF_HD_ARTWORK = "hd_artwork"
CONF_PREFETCH = "prefetch"
CONF_TIZEN_APP_ID = "tizen_app_id"
CONF_FRAME_ART_MODE = "frame_art_mode"

DEFAULT_NAME = "SpinJam Now Playing"
DEFAULT_SYNC_OFFSET_MS = 0
DEFAULT_LYRIC_OFFSET_MS = 0
DEFAULT_LYRIC_NUDGE_MS = 250
DEFAULT_SCALE_LYRICS = False
DEFAULT_LYRICS_ENABLED = True
# lyrics.ovh on, QQ Music off. Saved list order is the lookup order.
DEFAULT_FALLBACK_PROVIDERS = ("lyricsovh",)
DEFAULT_UPDATE_INTERVAL = 1.0
DEFAULT_DASHBOARD_PATH = "spinjam-tv"
DEFAULT_VIEW_PATH = "now"
LEGACY_DASHBOARD_PATH = "spinjam"
DEFAULT_RECAST_WHILE_PLAYING = True
DEFAULT_RECAST_INTERVAL = 45.0
DEFAULT_BUILTIN_CASTING = True
DEFAULT_RECAST_ON_STARTUP = False
DEFAULT_POWER_OFF_DISPLAY_ON_STOP = False
DEFAULT_HD_ARTWORK = True
DEFAULT_PREFETCH = True
DEFAULT_TIZEN_APP_ID = ""
DEFAULT_FRAME_ART_MODE = False

# Options keys that can change live without reloading the config entry.
LIVE_OPTIONS_KEYS = frozenset({CONF_SYNC_OFFSET_MS, CONF_LYRIC_OFFSET_MS})

# Cast media_player.app_name when the HA Lovelace receiver is running.
LOVELACE_APP_NAMES = frozenset({"Home Assistant Lovelace"})

CAST_WAKE_TIMEOUT_SEC = 10.0
CAST_LOVELACE_TIMEOUT_SEC = 15.0
CAST_LAUNCH_GRACE_SEC = 20.0

ATTR_LYRIC_CURRENT = "lyric_current"
ATTR_LYRIC_NEXT = "lyric_next"
ATTR_LYRIC_LINES = "lyric_lines"
ATTR_LYRIC_OFFSET_MS = "lyric_offset_ms"
ATTR_LYRICS_STATUS = "lyrics_status"
ATTR_LYRICS_SOURCE = "lyrics_source"
ATTR_LYRICS_DURATION = "lyrics_duration"
ATTR_LYRICS_DURATION_DELTA = "lyrics_duration_delta"
ATTR_ACTIVE_SOURCE = "active_source"
ATTR_SELECTED_SOURCE = "selected_source"
ATTR_SOURCE_KIND = "source_kind"
ATTR_DISPLAYS = "displays"
ATTR_SELECTED_DISPLAY = "selected_display"
ATTR_SYNC_OFFSET_MS = "sync_offset_ms"
ATTR_ALBUM_LOCK = "album_lock"
ATTR_ARTWORK_HD = "artwork_hd"
ATTR_ARTWORK_SOURCE = "artwork_source"
ATTR_ARTWORK_NEXT = "artwork_next"
ATTR_LYRICS_ENABLED = "lyrics_enabled"

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

# Input / passthrough sources that are not real music now-playing (e.g. HDMI ARC
# flipping a soundbar to "TV" when the Cast display wakes).
IGNORED_PASSTHROUGH_SOURCES = frozenset(
    {
        *LINE_IN_SOURCES,
        "tv",
        "television",
        "hdmi",
        "hdmi1",
        "hdmi2",
        "hdmi3",
        "hdmi4",
        "hdmi 1",
        "hdmi 2",
        "hdmi 3",
        "hdmi 4",
        "hdmi-1",
        "hdmi-2",
        "optical",
        "opt",
        "toslink",
        "spdif",
        "s/pdif",
        "arc",
        "earc",
        "e-arc",
        "e_arc",
        "hdmi arc",
        "hdmi-arc",
        "hdmi earc",
    }
)

MQTT_CMD_IDENTIFY = "spinjam/cmd/identify"
MQTT_CMD_SYNC_OFFSET = "spinjam/cmd/sync_offset_ms"
MQTT_CMD_CLEAR = "spinjam/cmd/clear"
MQTT_CMD_SELECT_ALBUM = "spinjam/cmd/select_album"

LRCLIB_API = "https://lrclib.net/api/get"
LRCLIB_SEARCH_API = "https://lrclib.net/api/search"
QQMUSIC_SEARCH_API = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQMUSIC_LYRIC_API = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
LYRICSOVH_API = "https://api.lyrics.ovh/v1"
LYRICS_CACHE_SIZE = 64
LYRICS_REQUEST_TIMEOUT = 6.0
LYRICS_BUDGET_SEC = 12.0
LYRICS_NOT_FOUND_TTL_SEC = 6 * 60 * 60
LYRICS_ERROR_RETRY_SEC = 5 * 60
LYRICS_PROVIDER_FAIL_LIMIT = 5
LYRICS_PROVIDER_SKIP_SEC = 60 * 60
LYRICS_DURATION_TOLERANCE_SEC = 3.0

LYRICS_PROVIDER_LRCLIB = "lrclib"
LYRICS_PROVIDER_QQMUSIC = "qqmusic"
LYRICS_PROVIDER_LYRICSOVH = "lyricsovh"

LYRICS_STATUS_SYNCED = "synced"
LYRICS_STATUS_PLAIN = "plain"
LYRICS_STATUS_INSTRUMENTAL = "instrumental"
LYRICS_STATUS_NOT_FOUND = "not_found"
LYRICS_STATUS_ERROR = "error"
LYRICS_STATUS_DISABLED = "disabled"

SELECT_DISPLAY_ENTITY_ID = "select.spinjam_display"
SELECT_SOURCE_ENTITY_ID = "select.spinjam_source"
SWITCH_CAST_ENTITY_ID = "switch.spinjam_cast"
# Retired in 0.7.0. Kept so upgrades can drop the registry entry and the tile.
SWITCH_TRACKING_ENTITY_ID = "switch.spinjam_tracking"
LEGACY_TRACKING_UNIQUE_ID = "spinjam_tracking"
SWITCH_LYRICS_ENTITY_ID = "switch.spinjam_lyrics"
NUMBER_LYRIC_OFFSET_ENTITY_ID = "number.spinjam_lyric_offset"
BUTTON_LYRICS_EARLIER_ENTITY_ID = "button.spinjam_lyrics_earlier"
BUTTON_LYRICS_LATER_ENTITY_ID = "button.spinjam_lyrics_later"
BUTTON_LYRIC_DELAY_RESET_ENTITY_ID = "button.spinjam_reset_lyric_delay"
SENSOR_LYRIC_DELAY_ENTITY_ID = "sensor.spinjam_lyric_delay"

# Device page, primary entities then the configuration category.
# Cast, Display, Source, Lyrics, Now Playing; configuration: Lyric offset.
DEVICE_PAGE_TRANSLATION_KEYS = (
    ("switch", "cast", "Cast"),
    ("select", "display", "Display"),
    ("select", "source", "Source"),
    ("switch", "lyrics", "Lyrics"),
    ("media_player", "now_playing", "Now Playing"),
    ("number", "lyric_offset", "Lyric delay"),
    ("button", "lyrics_earlier", "Lyrics earlier"),
    ("button", "lyrics_later", "Lyrics later"),
    ("button", "reset_lyric_delay", "Reset lyric delay"),
    ("sensor", "lyric_delay", "Current delay"),
)

ARTWORK_DISK_CACHE_DIR = "spinjam"
ARTWORK_DISK_CACHE_FILE = "artwork_cache.json"

# lyric_lines attribute: hard cap; window keeps context around the current line.
LYRIC_LINES_ATTR_MAX = 120
LYRIC_LINES_WINDOW_BEFORE = 40
