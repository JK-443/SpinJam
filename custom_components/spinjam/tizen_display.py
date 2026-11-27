"""Launch and leave the SpinJam Tizen app on a Samsung TV media_player.

The entity id and the Tizen application id both come from the user. This
module does not pick a television or an app id of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .cast import async_power_off_display, async_wake_display

_LOGGER = logging.getLogger(__name__)


async def _async_play_media(
    hass: HomeAssistant,
    entity_id: str,
    *,
    media_content_type: str,
    media_content_id: str,
) -> bool:
    if not hass.services.has_service("media_player", "play_media"):
        _LOGGER.warning(
            "media_player.play_media is unavailable; cannot control %s",
            entity_id,
        )
        return False
    payload: dict[str, Any] = {
        "entity_id": entity_id,
        "media_content_type": media_content_type,
        "media_content_id": media_content_id,
    }
    try:
        await hass.services.async_call(
            "media_player",
            "play_media",
            payload,
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001 — TV may be offline or unpaired
        _LOGGER.warning(
            "media_player.play_media failed for %s (%s): %s",
            entity_id,
            media_content_type,
            err,
        )
        return False
    return True


async def async_launch_tizen_app(
    hass: HomeAssistant, entity_id: str, app_id: str
) -> bool:
    """Wake ``entity_id`` and launch ``app_id`` via the Samsung TV integration.

    ``app_id`` is the installed Tizen application id (certificate prefix plus
    the app name). An empty id is a configuration miss, not a default app.
    """
    app_id = str(app_id or "").strip()
    if not app_id:
        _LOGGER.warning(
            "Samsung display %s has no Tizen application id. "
            "Set it in SpinJam options after installing the TV app.",
            entity_id,
        )
        return False
    if not await async_wake_display(hass, entity_id):
        return False
    launched = await _async_play_media(
        hass,
        entity_id,
        media_content_type="app",
        media_content_id=app_id,
    )
    if launched:
        _LOGGER.debug("Launched Tizen app %s on %s", app_id, entity_id)
    return launched


async def async_exit_tizen_app(
    hass: HomeAssistant, entity_id: str, *, power_off: bool
) -> bool:
    """Leave the Tizen app without powering the panel off, unless asked.

    Samsung ``media_player.turn_off`` powers the television off. The Cast
    path uses that service because it only quits the Cast receiver. Here,
    Home (`KEY_HOME`) returns to the TV menu and leaves the panel on.
    ``power_off`` uses the shared remote / media_player power-off helper.
    """
    if power_off:
        return await async_power_off_display(hass, entity_id)
    left = await _async_play_media(
        hass,
        entity_id,
        media_content_type="channel",
        media_content_id="KEY_HOME",
    )
    if left:
        _LOGGER.debug("Sent Home to leave the Tizen app on %s", entity_id)
    return left
