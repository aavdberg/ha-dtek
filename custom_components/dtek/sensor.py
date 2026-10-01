"""Sensor platform for DTEK integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DtekState
from .const import DOMAIN, MANUFACTURER, OUTAGE_TYPE_NONE
from .coordinator import DtekDataUpdateCoordinator

if TYPE_CHECKING:
    from .models import DtekConfigEntry


@dataclass(frozen=True, kw_only=True)
class DtekSensorEntityDescription(SensorEntityDescription):
    """Class describing DTEK sensor entities."""

    value_fn: Callable[[DtekState], Any]


SENSOR_DESCRIPTIONS: tuple[DtekSensorEntityDescription, ...] = (
    DtekSensorEntityDescription(
        key="next_outage",
        translation_key="next_outage",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-alert-outline",
        value_fn=lambda state: state.next_outage.start if state.next_outage else None,
    ),
    DtekSensorEntityDescription(
        key="restore_time",
        translation_key="restore_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        value_fn=lambda state: state.current_outage.end if state.current_outage else None,
    ),
    DtekSensorEntityDescription(
        key="outage_reason",
        translation_key="outage_reason",
        icon="mdi:information-outline",
        value_fn=lambda state: (
            state.current_outage.description
            if state.current_outage
            else (state.next_outage.description if state.next_outage else OUTAGE_TYPE_NONE)
        ),
    ),
    DtekSensorEntityDescription(
        key="group",
        translation_key="group",
        icon="mdi:numeric",
        value_fn=lambda state: state.group,
    ),
)

# Entities below are only available when a Personal Cabinet account is linked.
# They are created on demand: a field the cabinet does not expose for an account
# would otherwise surface as a permanently "unknown" entity.
CABINET_SENSOR_DESCRIPTIONS: tuple[DtekSensorEntityDescription, ...] = (
    DtekSensorEntityDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:cash-multiple",
        native_unit_of_measurement="UAH",
        value_fn=lambda state: state.balance,
    ),
    DtekSensorEntityDescription(
        key="customer_name",
        translation_key="customer_name",
        icon="mdi:account",
        value_fn=lambda state: state.customer_name,
    ),
    DtekSensorEntityDescription(
        key="eic",
        translation_key="eic",
        icon="mdi:identifier",
        value_fn=lambda state: state.eic,
    ),
    DtekSensorEntityDescription(
        key="address",
        translation_key="address",
        icon="mdi:map-marker",
        value_fn=lambda state: state.address,
    ),
    DtekSensorEntityDescription(
        key="object_type",
        translation_key="object_type",
        icon="mdi:home-city-outline",
        value_fn=lambda state: state.object_type,
    ),
    DtekSensorEntityDescription(
        key="contract_capacity",
        translation_key="contract_capacity",
        icon="mdi:transmission-tower",
        value_fn=lambda state: state.contract_capacity,
    ),
    DtekSensorEntityDescription(
        key="meter_serial",
        translation_key="meter_serial",
        icon="mdi:counter",
        value_fn=lambda state: state.meter_serial,
    ),
    DtekSensorEntityDescription(
        key="meter_type",
        translation_key="meter_type",
        icon="mdi:information",
        value_fn=lambda state: state.meter_type,
    ),
)

# Sensors that earlier releases created but for which no DTEK endpoint exists at
# all. These can never return, so their registry entries are removed. Cabinet
# sensors are deliberately NOT treated this way: a missing value may simply be a
# temporarily failing endpoint, and discarding the entity would lose its history.
OBSOLETE_SENSOR_KEYS: frozenset[str] = frozenset({"day_reading", "night_reading"})


@callback
def _async_remove_obsolete_entities(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Remove registry entries for sensors the integration no longer provides."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        if entity.unique_id.removeprefix(prefix) in OBSOLETE_SENSOR_KEYS:
            registry.async_remove(entity.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DTEK sensor entities."""
    coordinator = entry.runtime_data.coordinator
    account = entry.runtime_data.account
    group = entry.runtime_data.group

    _async_remove_obsolete_entities(hass, entry)

    def _build(description: DtekSensorEntityDescription) -> DtekSensor:
        return DtekSensor(
            coordinator=coordinator,
            description=description,
            entry_id=entry.entry_id,
            group=group,
            account=account,
        )

    async_add_entities([_build(description) for description in SENSOR_DESCRIPTIONS])

    if not entry.runtime_data.cabinet_enabled:
        return

    # A cabinet field that is absent right now may just be a temporarily failing
    # endpoint, so entities are added the first time a value actually appears
    # rather than being decided once from the initial snapshot.
    known_keys: set[str] = set()

    @callback
    def _async_add_available_cabinet_sensors() -> None:
        state = coordinator.data
        if state is None:
            return
        new_entities = [
            _build(description)
            for description in CABINET_SENSOR_DESCRIPTIONS
            if description.key not in known_keys and description.value_fn(state) is not None
        ]
        if not new_entities:
            return
        known_keys.update(entity.entity_description.key for entity in new_entities)
        async_add_entities(new_entities)

    _async_add_available_cabinet_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_available_cabinet_sensors))


class DtekSensor(CoordinatorEntity[DtekDataUpdateCoordinator], SensorEntity):
    """Representation of a DTEK sensor."""

    entity_description: DtekSensorEntityDescription

    def __init__(
        self,
        coordinator: DtekDataUpdateCoordinator,
        description: DtekSensorEntityDescription,
        entry_id: str,
        group: str,
        account: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_has_entity_name = True

        device_name = f"DTEK Account {account}" if account else f"DTEK Grid ({group})"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": f"Queue {group}",
        }

    @property
    def native_value(self) -> datetime | str | None:
        """Return the value of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
