"""Frontend card hash must be computed off the event loop and cached."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.spinjam import frontend as frontend_mod


@pytest.mark.asyncio
async def test_async_get_card_file_hash_uses_executor_and_caches() -> None:
    frontend_mod._card_hash = None  # noqa: SLF001
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value="abc123def456")

    first = await frontend_mod.async_get_card_file_hash(hass)
    second = await frontend_mod.async_get_card_file_hash(hass)

    assert first == "abc123def456"
    assert second == first
    hass.async_add_executor_job.assert_awaited_once()
    assert frontend_mod.card_file_hash() == "abc123def456"
    frontend_mod._card_hash = None  # noqa: SLF001


@pytest.mark.asyncio
async def test_async_setup_frontend_hashes_via_executor() -> None:
    frontend_mod._card_hash = None  # noqa: SLF001
    hass = MagicMock()
    hass.data = {}
    hass.http = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value="deadbeefcafe")

    with (
        patch.object(
            frontend_mod, "_async_register_static", new_callable=AsyncMock, return_value=True
        ),
        patch(
            "homeassistant.components.frontend.add_extra_js_url",
            create=True,
        ),
    ):
        url = await frontend_mod.async_setup_frontend(hass)

    assert url == "/spinjam/spinjam-lyrics-card.js?v=deadbeefcafe"
    assert hass.data[f"{frontend_mod.DOMAIN}_card_version"] == "deadbeefcafe"
    hass.async_add_executor_job.assert_awaited()
    frontend_mod._card_hash = None  # noqa: SLF001
