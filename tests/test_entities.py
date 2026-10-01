"""Unit tests for DTEK entity platforms (binary sensor, sensor, calendar)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.dtek.api.models import DtekOutageEvent, DtekState
from custom_components.dtek.binary_sensor import (
    POWER_EXPECTED_DESCRIPTION,
    DtekPowerExpectedBinarySensor,
)
from custom_components.dtek.calendar import DtekOutageCalendarEntity
from custom_components.dtek.sensor import SENSOR_DESCRIPTIONS, DtekSensor


def test_power_expected_binary_sensor() -> None:
    """Test binary sensor state."""
    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2", power_expected=True)

    binary_sensor = DtekPowerExpectedBinarySensor(
        coordinator=coordinator,
        description=POWER_EXPECTED_DESCRIPTION,
        entry_id="test_entry",
        group="GPV1.2",
    )

    assert binary_sensor.is_on is True
    assert binary_sensor.unique_id == "test_entry_power_expected"

    # Outage active
    coordinator.data = DtekState(group="GPV1.2", power_expected=False)
    assert binary_sensor.is_on is False


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
