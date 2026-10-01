"""Unit tests for DtekDataUpdateCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dtek.api.models import (
    DtekAddressLookupResult,
    DtekCabinetProfile,
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
async def test_coordinator_cabinet_profile_update() -> None:
    """Test coordinator enriches state from the cabinet profile."""
    hass = MagicMock()
    client = MagicMock()
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_home_numbers = AsyncMock(return_value=MagicMock(houses={}))
    client.async_get_cabinet_profile = AsyncMock(
        return_value=DtekCabinetProfile(
            account="12345678",
            customer_name="Іван Іванов",
            eic="62Z1234567890123",
            address="с-ще Тестове, вул. Тестова буд. 1 Б",
            object_type="Житловий будинок",
            contract_capacity="40.2 kW",
            city="с-ще Тестове",
            street="вул. Тестова",
            house_number="1Б",
            meter_serial="987654",
            meter_type="MTX 1A",
            balance=-42.50,
            group="GPV1.2",
        )
    )

    coordinator = DtekDataUpdateCoordinator(
        hass=hass,
        client=client,
        group="GPV1.1",
        cabinet_token="mock_token",
        cabinet_account="12345678",
    )

    state = await coordinator._async_update_data()

    assert state.balance == -42.50
    assert state.customer_name == "Іван Іванов"
    assert state.eic == "62Z1234567890123"
    assert state.meter_serial == "987654"
    assert state.meter_type == "MTX 1A"
    assert state.contract_capacity == "40.2 kW"
    assert state.object_type == "Житловий будинок"
    assert state.cabinet_authenticated is True
    # The cabinet is authoritative for the queue group and the address.
    assert state.group == "GPV1.2"
    assert coordinator.city == "с-ще Тестове"
    assert coordinator.house_number == "1Б"


@pytest.mark.asyncio
async def test_coordinator_without_cabinet_leaves_fields_empty() -> None:
    """Without cabinet credentials no cabinet calls are made."""
    hass = MagicMock()
    client = MagicMock()
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_cabinet_profile = AsyncMock()

    coordinator = DtekDataUpdateCoordinator(hass=hass, client=client, group="GPV1.2")

    state = await coordinator._async_update_data()

    client.async_get_cabinet_profile.assert_not_awaited()
    assert state.balance is None
    assert state.customer_name is None
    assert state.meter_serial is None
    assert state.cabinet_authenticated is False
