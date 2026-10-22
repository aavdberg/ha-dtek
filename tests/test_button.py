"""Tests for the DTEK refresh button."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dtek.button import DtekRefreshButton, async_setup_entry
from custom_components.dtek.const import DOMAIN, PLATFORMS


@pytest.mark.asyncio
async def test_refresh_button_requests_coordinator_refresh() -> None:
    """Pressing the button asks the coordinator to fetch data now."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    button = DtekRefreshButton(coordinator, "entry_id", "12345", "GPV1.2")

    await button.async_press()

    coordinator.async_request_refresh.assert_awaited_once_with()
    assert button._attr_unique_id == "entry_id_refresh_data"
    assert button._attr_device_info["identifiers"] == {(DOMAIN, "entry_id")}


@pytest.mark.asyncio
async def test_refresh_button_is_added_for_every_entry() -> None:
    """The force-refresh control is present with or without a cabinet account."""
    for account in (None, "12345"):
        entry = MagicMock()
        entry.entry_id = "entry_id"
        entry.runtime_data.account = account
        entry.runtime_data.group = "GPV1.2"
        entry.runtime_data.coordinator = MagicMock()
        added = []

        await async_setup_entry(MagicMock(), entry, added.extend)

        assert len(added) == 1
        assert isinstance(added[0], DtekRefreshButton)


def test_button_platform_is_forwarded() -> None:
    """Home Assistant loads the button platform for each config entry."""
    assert "button" in PLATFORMS
