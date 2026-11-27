"""Samsung TV launch, Tizen app id, and optional Frame Art Mode."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spinjam.cast_entities import (
    display_platform,
    unsupported_displays,
)
from custom_components.spinjam.config_flow import _validate_flow_input, displays_selector
from custom_components.spinjam.const import (
    CONF_DASHBOARD_PATH,
    CONF_DISPLAYS,
    CONF_FRAME_ART_MODE,
    CONF_LYRIC_NUDGE_MS,
    CONF_LYRIC_OFFSET_MS,
    CONF_LYRICS_ENABLED,
    CONF_POWER_OFF_DISPLAY_ON_STOP,
    CONF_RECAST_INTERVAL,
    CONF_SOURCE_PLAYERS,
    CONF_SYNC_OFFSET_MS,
    CONF_TIZEN_APP_ID,
    CONF_VIEW_PATH,
    DOMAIN,
    EVENT_SPINJAM_START,
)
from custom_components.spinjam.coordinator import SpinJamCoordinator
from custom_components.spinjam.frame_art import (
    image_file_type,
    push_cover_sync,
    samsungtv_host_and_token,
    warn_missing_library,
)
from custom_components.spinjam.tizen_display import (
    async_exit_tizen_app,
    async_launch_tizen_app,
)

APP_ID = "AbCdEfGhIj.Display"
FRAME = "media_player.example_frame"
CAST = "media_player.example_tv"


def _entry(**overrides) -> MockConfigEntry:
    data = {
        CONF_NAME: "SpinJam",
        CONF_SOURCE_PLAYERS: ["media_player.example_player"],
        CONF_DISPLAYS: [FRAME],
        CONF_LYRICS_ENABLED: False,
        CONF_SYNC_OFFSET_MS: 0,
        CONF_DASHBOARD_PATH: "spinjam-tv",
        CONF_VIEW_PATH: "now",
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        title="SpinJam",
        unique_id=overrides.get("unique_id", f"{DOMAIN}_tizen"),
    )


def _register(hass: HomeAssistant, entity_id: str, platform: str) -> None:
    object_id = entity_id.split(".", 1)[1]
    er.async_get(hass).async_get_or_create(
        "media_player",
        platform,
        f"{platform}_{object_id}",
        suggested_object_id=object_id,
    )


def _options(**extra: object) -> dict:
    base = {
        CONF_SYNC_OFFSET_MS: 0,
        CONF_LYRIC_OFFSET_MS: 0,
        CONF_DASHBOARD_PATH: "spinjam-tv",
        CONF_VIEW_PATH: "now",
        CONF_RECAST_INTERVAL: 45,
        CONF_LYRIC_NUDGE_MS: 250,
    }
    base.update(extra)
    return base


def test_image_file_type_recognises_jpeg_and_png() -> None:
    assert image_file_type(b"\xff\xd8\xff\x00") == "JPEG"
    assert image_file_type(b"\x89PNG\r\n\x1a\nrest") == "PNG"
    assert image_file_type(b"GIF89a") is None


def test_displays_selector_is_not_limited_to_cast() -> None:
    config = displays_selector().config
    domain = config.get("domain")
    assert domain == "media_player" or domain == ["media_player"]
    assert "integration" not in config


def test_tizen_app_id_must_look_like_an_installed_id() -> None:
    invalid = _validate_flow_input(
        _options(**{CONF_TIZEN_APP_ID: "not an id"}), options=True
    )
    assert invalid[CONF_TIZEN_APP_ID] == "invalid_tizen_app_id"
    assert _validate_flow_input(_options(**{CONF_TIZEN_APP_ID: APP_ID}), options=True) == {}
    payload = _options(**{CONF_TIZEN_APP_ID: "  "})
    assert _validate_flow_input(payload, options=True) == {}
    assert payload[CONF_TIZEN_APP_ID] == ""


class _Art:
    def __init__(self) -> None:
        self.uploaded = None
        self.selected = None
        self.mode = None
        self.deleted = None
        self.support = True

    def supported(self) -> bool:
        return self.support

    def upload(self, data: bytes, file_type: str = "JPEG", matte: str = "none") -> str:
        self.uploaded = (data, file_type, matte)
        return "MY-1"

    def select_image(self, content_id: str, show: bool = True) -> None:
        self.selected = (content_id, show)

    def set_artmode(self, on: bool) -> None:
        self.mode = on

    def delete(self, content_id: str) -> None:
        self.deleted = content_id


class _Client:
    def __init__(self, host: str, port: int = 8002, token: str | None = None, name: str = "") -> None:
        self.host = host
        self.port = port
        self.token = token
        self.name = name
        self.art_api = _Art()
        self.closed = False

    def art(self) -> _Art:
        return self.art_api

    def close(self) -> None:
        self.closed = True


def test_push_cover_uses_the_host_and_token_it_was_given() -> None:
    created: dict[str, _Client] = {}

    class _Recording(_Client):
        def __init__(
            self, host: str, port: int = 8002, token: str | None = None, name: str = ""
        ) -> None:
            super().__init__(host, port, token=token, name=name)
            created["client"] = self

    content_id = push_cover_sync(
        _Recording,
        "frame.example",
        "test-token",
        b"\xff\xd8\xff\x00",
        "JPEG",
        "MY-0",
    )
    client = created["client"]
    assert content_id == "MY-1"
    assert client.host == "frame.example"
    assert client.token == "test-token"
    assert client.art_api.deleted == "MY-0"
    assert client.art_api.mode is True
    assert client.closed is True


def test_push_cover_skips_when_art_mode_is_not_supported(caplog: pytest.LogCaptureFixture) -> None:
    class _Unsupported(_Client):
        def __init__(self, host: str, port: int = 8002, token: str | None = None, name: str = "") -> None:
            super().__init__(host, port, token=token, name=name)
            self.art_api.support = False

    with caplog.at_level("WARNING"):
        assert (
            push_cover_sync(_Unsupported, "frame.example", "test-token", b"\xff\xd8\xff", "JPEG", None)
            is None
        )
    assert any("did not report Art Mode" in rec.message for rec in caplog.records)


def test_missing_art_library_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    import custom_components.spinjam.frame_art as frame_art

    frame_art._MISSING_LIBRARY_LOGGED = False  # noqa: SLF001
    with caplog.at_level("WARNING"):
        warn_missing_library()
        warn_missing_library()
    warnings = [rec for rec in caplog.records if "samsungtvws" in rec.message]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"


@pytest.mark.asyncio
async def test_launch_uses_play_media_app() -> None:
    hass = MagicMock()
    hass.services.has_service.return_value = True
    hass.services.async_call = AsyncMock()
    with patch(
        "custom_components.spinjam.tizen_display.async_wake_display",
        new_callable=AsyncMock,
        return_value=True,
    ):
        ok = await async_launch_tizen_app(hass, FRAME, APP_ID)
    assert ok is True
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "play_media",
        {
            "entity_id": FRAME,
            "media_content_type": "app",
            "media_content_id": APP_ID,
        },
        blocking=True,
    )


@pytest.mark.asyncio
async def test_launch_without_an_app_id_does_not_call_the_tv() -> None:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    ok = await async_launch_tizen_app(hass, FRAME, "  ")
    assert ok is False
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_exit_sends_home_unless_power_off_is_requested() -> None:
    hass = MagicMock()
    hass.services.has_service.return_value = True
    hass.services.async_call = AsyncMock()
    assert await async_exit_tizen_app(hass, FRAME, power_off=False) is True
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "play_media",
        {
            "entity_id": FRAME,
            "media_content_type": "channel",
            "media_content_id": "KEY_HOME",
        },
        blocking=True,
    )
    with patch(
        "custom_components.spinjam.tizen_display.async_power_off_display",
        new_callable=AsyncMock,
        return_value=True,
    ) as power:
        assert await async_exit_tizen_app(hass, FRAME, power_off=True) is True
    power.assert_awaited_once()


@pytest.mark.asyncio
async def test_platforms_cast_and_samsung_are_displays(hass: HomeAssistant) -> None:
    _register(hass, CAST, "cast")
    _register(hass, FRAME, "samsungtv")
    _register(hass, "media_player.example_speaker", "sonos")
    assert display_platform(hass, CAST) == "cast"
    assert display_platform(hass, FRAME) == "samsungtv"
    assert display_platform(hass, "media_player.example_speaker") == "unsupported"
    assert display_platform(hass, "media_player.not_registered") == "unknown"
    assert unsupported_displays(
        hass, [CAST, FRAME, "media_player.example_speaker", "media_player.not_registered"]
    ) == ["media_player.example_speaker"]


@pytest.mark.asyncio
async def test_start_launches_the_tizen_app_for_a_samsung_tv(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_tizen_start", **{CONF_TIZEN_APP_ID: APP_ID})
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    events: list[dict] = []
    hass.bus.async_listen(EVENT_SPINJAM_START, lambda event: events.append(event.data))
    with (
        patch(
            "custom_components.spinjam.coordinator.async_launch_tizen_app",
            new_callable=AsyncMock,
            return_value=True,
        ) as launch,
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
        ) as show,
    ):
        target = await coordinator.async_start(FRAME)
        await hass.async_block_till_done()
    assert target == FRAME
    assert coordinator.cast_active is True
    launch.assert_awaited()
    assert launch.await_args.args[1:] == (FRAME, APP_ID)
    show.assert_not_awaited()
    assert events[-1]["display"] == FRAME
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_registered_cast_display_still_uses_lovelace(hass: HomeAssistant) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_cast_still",
        **{CONF_DISPLAYS: [CAST]},
    )
    entry.add_to_hass(hass)
    _register(hass, CAST, "cast")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    with (
        patch(
            "custom_components.spinjam.coordinator.async_launch_tizen_app",
            new_callable=AsyncMock,
        ) as launch,
        patch(
            "custom_components.spinjam.coordinator.async_wake_display",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
            return_value=True,
        ) as show,
        patch(
            "custom_components.spinjam.coordinator.async_wait_for_lovelace_app",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator.async_start(CAST)
        await hass.async_block_till_done()
    show.assert_awaited()
    launch.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_missing_tizen_app_id_turns_the_switch_back_off(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_tizen_missing_id")
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    with patch(
        "custom_components.spinjam.coordinator.async_show_now_playing",
        new_callable=AsyncMock,
    ) as show:
        await coordinator.async_start(FRAME)
        await hass.async_block_till_done()
    show.assert_not_awaited()
    assert coordinator.cast_active is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_stop_on_samsung_sends_home_and_does_not_end_cast(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_tizen_stop")
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = FRAME  # noqa: SLF001
    with (
        patch(
            "custom_components.spinjam.coordinator.async_exit_tizen_app",
            new_callable=AsyncMock,
            return_value=True,
        ) as leave,
        patch(
            "custom_components.spinjam.coordinator.async_end_cast",
            new_callable=AsyncMock,
        ) as end_cast,
    ):
        await coordinator.async_stop()
    leave.assert_awaited_once()
    assert leave.await_args.kwargs["power_off"] is False
    end_cast.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_samsung_stop_can_power_off_when_asked(hass: HomeAssistant) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_tizen_power",
        **{CONF_POWER_OFF_DISPLAY_ON_STOP: True},
    )
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = FRAME  # noqa: SLF001
    with patch(
        "custom_components.spinjam.coordinator.async_exit_tizen_app",
        new_callable=AsyncMock,
        return_value=True,
    ) as leave:
        await coordinator.async_stop()
    assert leave.await_args.kwargs["power_off"] is True
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_recast_interval_does_not_relaunch_samsung(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_tizen_recast", **{CONF_TIZEN_APP_ID: APP_ID})
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = FRAME  # noqa: SLF001
    with (
        patch(
            "custom_components.spinjam.coordinator.async_launch_tizen_app",
            new_callable=AsyncMock,
        ) as launch,
        patch(
            "custom_components.spinjam.coordinator.async_show_now_playing",
            new_callable=AsyncMock,
        ) as show,
    ):
        await coordinator._async_recast_tick()  # noqa: SLF001
    launch.assert_not_awaited()
    show.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_frame_art_stays_off_unless_the_option_is_on(hass: HomeAssistant) -> None:
    entry = _entry(unique_id=f"{DOMAIN}_art_off")
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    assert coordinator.frame_art_mode is False
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = FRAME  # noqa: SLF001
    with patch(
        "custom_components.spinjam.coordinator.async_push_cover",
        new_callable=AsyncMock,
    ) as push:
        await coordinator.async_set_lyrics_enabled(False)
        await hass.async_block_till_done()
    push.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_frame_art_uploads_when_lyrics_are_off_and_leaves_when_on(
    hass: HomeAssistant,
) -> None:
    entry = _entry(
        unique_id=f"{DOMAIN}_art_on",
        **{
            CONF_FRAME_ART_MODE: True,
            CONF_TIZEN_APP_ID: APP_ID,
            CONF_LYRICS_ENABLED: True,
        },
    )
    entry.add_to_hass(hass)
    _register(hass, FRAME, "samsungtv")
    coordinator = SpinJamCoordinator(hass, entry)
    coordinator._cast_active = True  # noqa: SLF001
    coordinator._cast_display = FRAME  # noqa: SLF001
    coordinator.data = replace(
        coordinator.data, artwork_hd="https://example.com/cover.jpg"
    )
    with (
        patch(
            "custom_components.spinjam.coordinator.async_fetch_artwork",
            new_callable=AsyncMock,
            return_value=(b"\xff\xd8\xff\x00", "JPEG"),
        ),
        patch(
            "custom_components.spinjam.coordinator.async_push_cover",
            new_callable=AsyncMock,
            return_value="MY-1",
        ) as push,
    ):
        await coordinator.async_set_lyrics_enabled(False)
        await hass.async_block_till_done()
    push.assert_awaited()
    assert push.await_args.args[1] == FRAME
    assert push.await_args.args[2] == b"\xff\xd8\xff\x00"
    assert coordinator._frame_art_active is True  # noqa: SLF001

    with (
        patch(
            "custom_components.spinjam.coordinator.async_set_artmode",
            new_callable=AsyncMock,
            return_value=True,
        ) as artmode,
        patch(
            "custom_components.spinjam.coordinator.async_launch_tizen_app",
            new_callable=AsyncMock,
            return_value=True,
        ) as launch,
    ):
        await coordinator.async_set_lyrics_enabled(True)
        await hass.async_block_till_done()
    artmode.assert_awaited()
    assert artmode.await_args.args[1:] == (FRAME, False)
    launch.assert_awaited()
    assert launch.await_args.args[1:] == (FRAME, APP_ID)
    assert coordinator._frame_art_active is False  # noqa: SLF001
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_art_host_comes_from_the_samsung_config_entry(hass: HomeAssistant) -> None:
    tv = MockConfigEntry(
        domain="samsungtv",
        data={"host": "frame.example", "token": "test-token"},
        unique_id="frame-entry",
    )
    tv.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player",
        "samsungtv",
        "example_frame_link",
        suggested_object_id="example_frame",
        config_entry=tv,
    )
    assert samsungtv_host_and_token(hass, FRAME) == ("frame.example", "test-token")

    bare = MockConfigEntry(
        domain="samsungtv",
        data={"host": "frame.example"},
        unique_id="frame-no-token",
    )
    bare.add_to_hass(hass)
    registry.async_get_or_create(
        "media_player",
        "samsungtv",
        "example_frame_notoken",
        suggested_object_id="example_frame_notoken",
        config_entry=bare,
    )
    assert samsungtv_host_and_token(hass, "media_player.example_frame_notoken") is None
