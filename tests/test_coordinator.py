"""Unit tests for DtekDataUpdateCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dtek.api.models import (
    DtekAddressLookupResult,
    DtekHouseInfo,
    DtekOutageEvent,
)
from custom_components.dtek.coordinator import DtekDataUpdateCoordinator


@pytest.mark.asyncio
async def test_coordinator_update_data_with_address() -> None:
    """Test coordinator updating data with address information."""
    hass = MagicMock()
    client = MagicMock()

    # Mock get_home_numbers
    lookup = DtekAddressLookupResult(
        result=True,
        show_cur_outage_param=True,
        show_cur_schedule=True,
        show_table_schedule=True,
        show_table_plan=False,
        show_table_fact=True,
        show_user_group=True,
        houses={
            "1": DtekHouseInfo(
                house_num="1",
                group="GPV1.2",
                sub_type_reason=["GPV1.2"],
            )
        },
    )
    client.async_get_home_numbers = AsyncMock(return_value=lookup)

    # Mock get_schedule with an upcoming outage
    now = datetime.now()
    event = DtekOutageEvent(
        start=now + timedelta(hours=2),
        end=now + timedelta(hours=5),
        outage_type="planned",
        description="Planned maintenance",
        group="GPV1.2",
    )
    client.async_get_schedule = AsyncMock(return_value=[event])

    coordinator = DtekDataUpdateCoordinator(
        hass=hass,
        client=client,
        group="GPV1.2",
        city="м. Дніпро",
        street="вул. Центральна",
        house_number="1",
    )

    state = await coordinator._async_update_data()

    assert state.group == "GPV1.2"
    assert state.power_expected is True
    assert state.current_outage is None
    assert state.next_outage is not None
    assert state.next_outage.description == "Planned maintenance"
    assert len(state.events) == 1
    assert state.flags["show_cur_outage_param"] is True


@pytest.mark.asyncio
async def test_coordinator_active_outage_power_expected_false() -> None:
    """Test power_expected is False when current outage is active."""
    hass = MagicMock()
    client = MagicMock()
    client.async_get_home_numbers = AsyncMock()

    now = datetime.now()
    active_outage = DtekOutageEvent(
        start=now - timedelta(minutes=30),
        end=now + timedelta(hours=2),
        outage_type="emergency",
        description="Transformer repair",
        group="GPV1.2",
    )
    client.async_get_schedule = AsyncMock(return_value=[active_outage])

    coordinator = DtekDataUpdateCoordinator(
        hass=hass,
        client=client,
        group="GPV1.2",
    )

    state = await coordinator._async_update_data()

    assert state.power_expected is False
    assert state.current_outage is not None
    assert state.current_outage.description == "Transformer repair"


@pytest.mark.asyncio
async def test_coordinator_cabinet_balance_update() -> None:
    """Test coordinator updates balance when cabinet account info is provided."""
    hass = MagicMock()
    client = MagicMock()
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_cabinet_balance = AsyncMock(return_value=-42.50)

    coordinator = DtekDataUpdateCoordinator(
        hass=hass,
        client=client,
        group="GPV1.2",
        cabinet_token="mock_token",
        cabinet_account="12345678",
    )

    state = await coordinator._async_update_data()

    assert state.balance == -42.50
    assert state.cabinet_authenticated is True
