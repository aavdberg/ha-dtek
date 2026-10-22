"""Unit tests for DTEK entity platforms (binary sensor, sensor, calendar)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dtek.api.client import DTEK_TIMEZONE
from custom_components.dtek.api.exceptions import DtekConnectionError
from custom_components.dtek.api.models import DtekCabinetProfile, DtekOutageEvent, DtekState
from custom_components.dtek.binary_sensor import (
    OUTAGE_ACTIVE_DESCRIPTION,
    PLANNED_MAINTENANCE_DESCRIPTION,
    POWER_EXPECTED_DESCRIPTION,
    DtekBinarySensor,
)
from custom_components.dtek.calendar import DtekOutageCalendarEntity
from custom_components.dtek.coordinator import DtekDataUpdateCoordinator, UpdateFailed
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


@pytest.mark.asyncio
async def test_entity_availability_during_partial_update_and_recovery() -> None:
    """Only cabinet entities remain available during a public outage-source failure."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DtekState(
        group="GPV1.2", power_expected=None, outage_data_available=False, meter_serial="test_meter"
    )
    outage_sensors = [DtekSensor(coordinator, desc, "test_entry", "GPV1.2") for desc in SENSOR_DESCRIPTIONS]
    cabinet_sensor = DtekSensor(coordinator, CABINET_SENSOR_DESCRIPTIONS[6], "test_entry", "GPV1.2")
    binaries = [
        DtekBinarySensor(coordinator, desc, "test_entry", "GPV1.2")
        for desc in (POWER_EXPECTED_DESCRIPTION, OUTAGE_ACTIVE_DESCRIPTION, PLANNED_MAINTENANCE_DESCRIPTION)
    ]
    calendar = DtekOutageCalendarEntity(coordinator, "test_entry", "GPV1.2")
    assert all(not entity.available and entity.native_value is None for entity in outage_sensors)
    assert all(not entity.available and entity.is_on is None for entity in binaries)
    assert cabinet_sensor.available is True
    assert cabinet_sensor.native_value == "test_meter"
    assert calendar.available is False
    assert calendar.event is None
    now = datetime.now()
    with pytest.raises(HomeAssistantError, match="outage data is unavailable"):
        await calendar.async_get_events(MagicMock(), now, now + timedelta(days=1))

    coordinator.data = DtekState(group="GPV1.2", meter_serial="test_meter")
    assert all(entity.available for entity in [*outage_sensors, *binaries, calendar, cabinet_sensor])
    assert await calendar.async_get_events(MagicMock(), now, now + timedelta(days=1)) == []

    coordinator.last_update_success = False
    assert all(not entity.available for entity in [*outage_sensors, *binaries, calendar, cabinet_sensor])
    assert all(entity.is_on is None for entity in binaries)
    assert all(entity.native_value is None for entity in [*outage_sensors, cabinet_sensor])
    with pytest.raises(HomeAssistantError, match="outage data is unavailable"):
        await calendar.async_get_events(MagicMock(), now, now + timedelta(days=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("cabinet_enabled", [False, True])
@pytest.mark.parametrize("had_events", [False, True])
async def test_calendar_rejects_retained_state_after_failed_refresh(cabinet_enabled: bool, had_events: bool) -> None:
    """A last-known successful state is not a current schedule after both sources fail."""
    now = datetime.now(DTEK_TIMEZONE)
    event = DtekOutageEvent(
        start=now + timedelta(hours=1),
        end=now + timedelta(hours=2),
        outage_type="planned",
        description="Test outage",
    )
    client = MagicMock()
    client.async_get_schedule = AsyncMock(
        side_effect=[[event] if had_events else [], DtekConnectionError("public portal down")]
    )
    client.async_get_cabinet_profile = AsyncMock(
        side_effect=[DtekCabinetProfile(meter_serial="test_meter"), DtekConnectionError("cabinet down")]
    )
    coordinator = DtekDataUpdateCoordinator(
        hass=MagicMock(),
        client=client,
        group="GPV1.2",
        cabinet_token="test_token" if cabinet_enabled else None,
        cabinet_account="test_account" if cabinet_enabled else None,
    )
    coordinator.data = await coordinator._async_update_data()
    coordinator.last_update_success = True
    calendar = DtekOutageCalendarEntity(coordinator, "test_entry", "GPV1.2")
    assert calendar.available is True
    with pytest.raises(UpdateFailed, match="Cannot connect"):
        await coordinator._async_update_data()
    # HA retains data but marks the coordinator update as failed.
    coordinator.last_update_success = False
    assert coordinator.data.outage_data_available is True
    assert calendar.available is False
    assert calendar.event is None
    with pytest.raises(HomeAssistantError, match="outage data is unavailable"):
        await calendar.async_get_events(MagicMock(), now, now + timedelta(days=1))


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

    available = [desc.key for desc in CABINET_SENSOR_DESCRIPTIONS if desc.value_fn(coordinator.data) is not None]

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


def _make_entry(coordinator: Any, cabinet_enabled: bool = True) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data.coordinator = coordinator
    entry.runtime_data.account = "12345678"
    entry.runtime_data.group = "GPV1.2"
    entry.runtime_data.cabinet_enabled = cabinet_enabled
    return entry


def _registry_entry(entity_id: str, unique_id: str) -> MagicMock:
    entity = MagicMock()
    entity.entity_id = entity_id
    entity.domain = "sensor"
    entity.unique_id = unique_id
    entity.config_entry_id = "test_entry"
    return entity


@pytest.mark.asyncio
async def test_setup_entry_removes_only_obsolete_sensors() -> None:
    """Sensors without any DTEK endpoint are purged; cabinet ones are kept."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.dtek.sensor import async_setup_entry

    hass = MagicMock()
    hass.entity_registry = None
    registry = er.async_get(hass)
    for entity_id, unique_id in (
        ("sensor.dtek_day_meter_reading", "test_entry_day_reading"),
        ("sensor.dtek_night_meter_reading", "test_entry_night_reading"),
        ("sensor.dtek_account_balance", "test_entry_balance"),
        ("sensor.dtek_queue_group", "test_entry_group"),
    ):
        registry.entities[entity_id] = _registry_entry(entity_id, unique_id)

    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2", customer_name="Тестенко Т.Т.")

    added: list[Any] = []
    await async_setup_entry(hass, _make_entry(coordinator), lambda e: added.extend(e))

    remaining = set(registry.entities)
    assert "sensor.dtek_day_meter_reading" not in remaining
    assert "sensor.dtek_night_meter_reading" not in remaining
    # A cabinet endpoint can fail transiently, so its entity must survive.
    assert "sensor.dtek_account_balance" in remaining
    assert "sensor.dtek_queue_group" in remaining

    created = {sensor.entity_description.key for sensor in added}
    assert "customer_name" in created
    assert "balance" not in created


@pytest.mark.asyncio
async def test_cabinet_sensor_added_when_value_appears_later() -> None:
    """Meter sensors are registered immediately; other fields are added when available."""
    from custom_components.dtek.coordinator import DtekDataUpdateCoordinator
    from custom_components.dtek.sensor import async_setup_entry

    hass = MagicMock()
    hass.entity_registry = None

    coordinator = DtekDataUpdateCoordinator(hass=hass, client=MagicMock(), group="GPV1.2")
    coordinator.data = DtekState(group="GPV1.2")

    added: list[Any] = []
    await async_setup_entry(hass, _make_entry(coordinator), lambda e: added.extend(e))

    initial_keys = {s.entity_description.key for s in added}
    assert initial_keys == {d.key for d in SENSOR_DESCRIPTIONS} | {"meter_serial", "meter_type"}

    # The cabinet endpoint recovers on a later refresh.
    coordinator.data = DtekState(group="GPV1.2", balance=-12.5, customer_name="Тестенко Т.Т.")
    coordinator.async_notify_listeners()

    created = {sensor.entity_description.key for sensor in added}
    assert "balance" in created
    assert "customer_name" in created
    assert "meter_serial" in created
    assert "meter_type" in created

    # A further refresh must not duplicate the entities.
    coordinator.async_notify_listeners()
    keys = [sensor.entity_description.key for sensor in added]
    assert len(keys) == len(set(keys))
    assert keys.count("meter_serial") == 1
    assert keys.count("meter_type") == 1


@pytest.mark.asyncio
async def test_no_cabinet_sensors_without_account() -> None:
    """Address-only entries never get cabinet entities."""
    from custom_components.dtek.sensor import async_setup_entry

    hass = MagicMock()
    hass.entity_registry = None

    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2", customer_name="Тестенко Т.Т.")

    added: list[Any] = []
    await async_setup_entry(hass, _make_entry(coordinator, cabinet_enabled=False), lambda e: added.extend(e))

    assert {s.entity_description.key for s in added} == {d.key for d in SENSOR_DESCRIPTIONS}
