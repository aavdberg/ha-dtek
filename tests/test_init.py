"""Tests for config entry setup helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.dtek import _async_persist_discovered_data, async_setup_entry
from custom_components.dtek.api import DtekApiClient, DtekRateLimitError
from custom_components.dtek.api.models import DtekCabinetProfile, DtekCabinetUser
from custom_components.dtek.coordinator import DtekDataUpdateCoordinator


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
    """Without a cabinet, setup/reload makes no requests during the public cooldown."""
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
    entry.data = {"dso": "dtek-dnem"}
    entry.options = {}
    for _ in range(3):
        with pytest.raises(ConfigEntryNotReady, match="portal requests paused"):
            await async_setup_entry(hass, entry)

    assert session.get.call_count == 1
    session.post.assert_not_called()
    hass.config_entries.async_forward_entry_setups.assert_not_called()


@pytest.mark.asyncio
async def test_setup_loads_cabinet_during_public_portal_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A working cabinet allows platforms to load with outage data unavailable."""
    client = MagicMock()
    client.raise_if_portal_cooling_down.side_effect = DtekRateLimitError("requests paused")
    client.async_cabinet_authenticate = AsyncMock(
        return_value=DtekCabinetUser(token="test_token", phone="test_phone", primary_account="test_account")
    )
    client.async_get_cabinet_profile = AsyncMock(return_value=DtekCabinetProfile(meter_serial="test_meter"))
    client.async_get_home_numbers = AsyncMock()
    client.async_get_schedule = AsyncMock()
    monkeypatch.setattr("custom_components.dtek.DtekApiClient", lambda **kwargs: client)

    async def first_refresh(coordinator: DtekDataUpdateCoordinator) -> None:
        coordinator.data = await coordinator._async_update_data()

    monkeypatch.setattr(DtekDataUpdateCoordinator, "async_config_entry_first_refresh", first_refresh)
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = MagicMock()
    entry.data = {"dso": "dtek-dnem", "phone": "test_phone", "password": "test_password"}
    entry.options = {}

    assert await async_setup_entry(hass, entry) is True
    assert entry.runtime_data.coordinator.data.meter_serial == "test_meter"
    assert entry.runtime_data.coordinator.data.outage_data_available is False
    client.async_cabinet_authenticate.assert_awaited_once()
    client.async_get_home_numbers.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
