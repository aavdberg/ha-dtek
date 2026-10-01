"""Unit tests for DTEK entity platforms (binary sensor, sensor, calendar)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.dtek.api.models import DtekOutageEvent, DtekState
from custom_components.dtek.binary_sensor import (
    OUTAGE_ACTIVE_DESCRIPTION,
    PLANNED_MAINTENANCE_DESCRIPTION,
    POWER_EXPECTED_DESCRIPTION,
    DtekBinarySensor,
)
from custom_components.dtek.calendar import DtekOutageCalendarEntity
from custom_components.dtek.sensor import SENSOR_DESCRIPTIONS, DtekSensor


def test_power_expected_binary_sensor() -> None:
    """Test binary sensor state."""
    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2", power_expected=True)

    binary_sensor = DtekBinarySensor(
        coordinator=coordinator,
        description=POWER_EXPECTED_DESCRIPTION,
        entry_id="test_entry",
        group="GPV1.2",
        is_on_fn=lambda s: s.power_expected,
    )

    assert binary_sensor.is_on is True
    assert binary_sensor.unique_id == "test_entry_power_expected"

    # Outage active
    coordinator.data = DtekState(group="GPV1.2", power_expected=False)
    assert binary_sensor.is_on is False

    # Outage active sensor
    active_sensor = DtekBinarySensor(
        coordinator=coordinator,
        description=OUTAGE_ACTIVE_DESCRIPTION,
        entry_id="test_entry",
        group="GPV1.2",
        is_on_fn=lambda s: not s.power_expected,
    )
    assert active_sensor.is_on is True

    # Planned maintenance sensor
    maint_sensor = DtekBinarySensor(
        coordinator=coordinator,
        description=PLANNED_MAINTENANCE_DESCRIPTION,
        entry_id="test_entry",
        group="GPV1.2",
        is_on_fn=lambda s: s.current_outage is not None and s.current_outage.outage_type == "planned",
    )
    assert maint_sensor.is_on is False


def test_dtek_sensors() -> None:
    """Test all sensor values."""
    now = datetime.now()
    next_outage = DtekOutageEvent(
        start=now + timedelta(hours=3),
        end=now + timedelta(hours=7),
        outage_type="planned",
        description="Substation maintenance",
    )
    coordinator = MagicMock()
    coordinator.data = DtekState(
        group="GPV1.2",
        power_expected=True,
        next_outage=next_outage,
    )

    sensors = {
        desc.key: DtekSensor(
            coordinator=coordinator,
            description=desc,
            entry_id="test_entry",
            group="GPV1.2",
        )
        for desc in SENSOR_DESCRIPTIONS
    }

    assert sensors["group"].native_value == "GPV1.2"
    assert sensors["next_outage"].native_value == next_outage.start
    assert sensors["restore_time"].native_value is None
    assert sensors["outage_reason"].native_value == "Substation maintenance"
    assert sensors["balance"].native_value is None
    assert sensors["customer_name"].native_value is None
    assert sensors["eic"].native_value is None
    assert sensors["meter_serial"].native_value is None


@pytest.mark.asyncio
async def test_calendar_events() -> None:
    """Test calendar entity upcoming and range events."""
    now = datetime.now()
    event1 = DtekOutageEvent(
        start=now + timedelta(days=1, hours=10),
        end=now + timedelta(days=1, hours=17),
        outage_type="planned",
        description="Network maintenance",
    )
    coordinator = MagicMock()
    coordinator.data = DtekState(
        group="GPV1.2",
        events=[event1],
        next_outage=event1,
    )

    calendar = DtekOutageCalendarEntity(
        coordinator=coordinator,
        entry_id="test_entry",
        group="GPV1.2",
    )

    # Next event
    current_cal_event = calendar.event
    assert current_cal_event is not None
    assert "Network maintenance" in current_cal_event.summary

    # Range events
    hass = MagicMock()
    events = await calendar.async_get_events(
        hass=hass,
        start_date=now,
        end_date=now + timedelta(days=2),
    )
    assert len(events) == 1
    assert "Network maintenance" in events[0].summary
