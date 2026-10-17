"""Tests for config entry setup helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.dtek import _async_persist_discovered_data, async_setup_entry
from custom_components.dtek.api import DtekApiClient, DtekRateLimitError


def test_persist_discovered_data_updates_stale_values() -> None:
    """Stale queue group and empty address fields are refreshed."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"group": "GPV1.1", "eic": "", "city": "", "account": "12345678"}

    _async_persist_discovered_data(
        hass,
        entry,
        {
            "group": "GPV1.2",
            "eic": "62Z1234567890123",
            "city": "с-ще Тестове",
            "account": "12345678",
        },
    )

    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["data"]["group"] == "GPV1.2"
    assert kwargs["data"]["eic"] == "62Z1234567890123"
    assert kwargs["data"]["city"] == "с-ще Тестове"


def test_persist_discovered_data_skips_when_unchanged() -> None:
    """No write happens when nothing new was discovered."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"group": "GPV1.2", "eic": "62Z1234567890123"}

    _async_persist_discovered_data(hass, entry, {"group": "GPV1.2", "eic": None, "city": None})

    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_setup_retries_skip_all_requests_during_portal_cooldown() -> None:
    """A new client on setup/reload shares the cooldown before cabinet login."""
    session = MagicMock(spec=aiohttp.ClientSession)
    response = MagicMock()
    response.status = 403
    response.__aenter__.return_value = response
    session.get.return_value = response
    with pytest.raises(DtekRateLimitError):
        await DtekApiClient(session).async_ensure_csrf_token()

    hass = MagicMock()
    hass.session = session
    entry = MagicMock()
    entry.data = {"dso": "dtek-dnem", "phone": "test_phone", "password": "test_password"}
    entry.options = {}
    for _ in range(3):
        with pytest.raises(ConfigEntryNotReady, match="portal requests paused"):
            await async_setup_entry(hass, entry)

    assert session.get.call_count == 1
    session.post.assert_not_called()
    hass.config_entries.async_forward_entry_setups.assert_not_called()
