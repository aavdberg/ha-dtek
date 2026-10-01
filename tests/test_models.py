"""Unit tests for DTEK API models."""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.dtek.api.models import (
    DtekAddressLookupResult,
    DtekHouseInfo,
    DtekOutageEvent,
    DtekState,
)


def test_house_info_creation() -> None:
    """Test creating DtekHouseInfo with defaults and values."""
    house = DtekHouseInfo(
        house_num="1",
        group="GPV1.2",
        sub_type_reason=["GPV1.2"],
    )
    assert house.house_num == "1"
    assert house.group == "GPV1.2"
    assert house.sub_type_reason == ["GPV1.2"]
    assert house.outage_type == ""


def test_address_lookup_result() -> None:
    """Test DtekAddressLookupResult parsing."""
    lookup = DtekAddressLookupResult(
        result=True,
        show_cur_outage_param=True,
        show_cur_schedule=True,
        show_table_schedule=True,
        show_table_plan=False,
        show_table_fact=True,
        show_user_group=True,
    )
    assert lookup.result is True
    assert lookup.show_cur_outage_param is True
    assert lookup.show_table_plan is False
    assert lookup.houses == {}


def test_outage_event_is_active() -> None:
    """Test is_active calculation for DtekOutageEvent."""
    now = datetime.now()
    active_event = DtekOutageEvent(
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=2),
        outage_type="planned",
        description="Line maintenance",
        group="GPV1.2",
    )
    assert active_event.is_active is True

    past_event = DtekOutageEvent(
        start=now - timedelta(hours=3),
        end=now - timedelta(hours=1),
        outage_type="planned",
        description="Repairs",
    )
    assert past_event.is_active is False

    future_event = DtekOutageEvent(
        start=now + timedelta(hours=1),
        end=now + timedelta(hours=4),
        outage_type="stabilization_schedule",
        description="Scheduled outage",
    )
    assert future_event.is_active is False


def test_dtek_state_defaults() -> None:
    """Test DtekState default values."""
    state = DtekState(group="GPV1.2")
    assert state.group == "GPV1.2"
    assert state.power_expected is True
    assert state.current_outage is None
    assert state.next_outage is None
    assert state.events == []
