"""Unit tests for DTEK entity platforms (binary sensor, sensor, calendar)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
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
from custom_components.dtek.sensor import (
    CABINET_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    DtekSensor,
)


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
    # Cabinet-only entities are not part of the base set.
    assert "balance" not in sensors
    assert "customer_name" not in sensors
    assert "meter_serial" not in sensors


def test_cabinet_sensors_only_created_when_data_available() -> None:
    """Cabinet sensors are skipped for fields the account does not expose."""
    coordinator = MagicMock()
    coordinator.data = DtekState(
        group="GPV1.2",
        customer_name="Тестенко Т.Т.",
        eic="62Z1234567890123",
        meter_serial="04860803",
        balance=None,
    )

    available = [
        desc.key for desc in CABINET_SENSOR_DESCRIPTIONS if desc.value_fn(coordinator.data) is not None
    ]

    assert "customer_name" in available
    assert "eic" in available
    assert "meter_serial" in available
    # No billing figures for this account, so no permanently unknown entity.
    assert "balance" not in available
    assert "meter_type" not in available


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


@pytest.mark.asyncio
async def test_setup_entry_removes_stale_sensor_entities() -> None:
    """Sensors that DTEK no longer provides are purged from the registry."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.dtek.sensor import async_setup_entry

    hass = MagicMock()
    hass.entity_registry = None
    registry = er.async_get(hass)

    def _entry(entity_id: str, unique_id: str) -> MagicMock:
        entity = MagicMock()
        entity.entity_id = entity_id
        entity.domain = "sensor"
        entity.unique_id = unique_id
        entity.config_entry_id = "test_entry"
        return entity

    for entity_id, unique_id in (
        ("sensor.dtek_day_meter_reading", "test_entry_day_reading"),
        ("sensor.dtek_night_meter_reading", "test_entry_night_reading"),
        ("sensor.dtek_account_balance", "test_entry_balance"),
        ("sensor.dtek_customer_name", "test_entry_customer_name"),
        ("sensor.dtek_queue_group", "test_entry_group"),
    ):
        registry.entities[entity_id] = _entry(entity_id, unique_id)

    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2", customer_name="Тестенко Т.Т.")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data.coordinator = coordinator
    entry.runtime_data.account = "12345678"
    entry.runtime_data.group = "GPV1.2"
    entry.runtime_data.cabinet_enabled = True

    added: list[Any] = []
    await async_setup_entry(hass, entry, lambda entities: added.extend(entities))

    remaining = set(registry.entities)
    assert "sensor.dtek_day_meter_reading" not in remaining
    assert "sensor.dtek_night_meter_reading" not in remaining
    assert "sensor.dtek_account_balance" not in remaining
    # Entities that still have data are kept.
    assert "sensor.dtek_customer_name" in remaining
    assert "sensor.dtek_queue_group" in remaining

    created = {sensor.entity_description.key for sensor in added}
    assert "customer_name" in created
    assert "balance" not in created
