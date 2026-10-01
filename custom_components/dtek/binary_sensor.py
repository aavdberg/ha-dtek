"""Binary sensor platform for DTEK integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DtekDataUpdateCoordinator

if TYPE_CHECKING:
    from .models import DtekConfigEntry

POWER_EXPECTED_DESCRIPTION = BinarySensorEntityDescription(
    key="power_expected",
    translation_key="power_expected",
    device_class=BinarySensorDeviceClass.POWER,
    icon="mdi:power-plug",
)

OUTAGE_ACTIVE_DESCRIPTION = BinarySensorEntityDescription(
    key="outage_active",
    translation_key="outage_active",
    device_class=BinarySensorDeviceClass.POWER,
    icon="mdi:power-plug-off",
)

PLANNED_MAINTENANCE_DESCRIPTION = BinarySensorEntityDescription(
    key="planned_maintenance",
    translation_key="planned_maintenance",
    icon="mdi:wrench-clock",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DTEK binary sensor entities."""
    coordinator = entry.runtime_data.coordinator
    account = entry.runtime_data.account
    group = entry.runtime_data.group

    async_add_entities(
        [
            DtekBinarySensor(
                coordinator=coordinator,
                description=POWER_EXPECTED_DESCRIPTION,
                entry_id=entry.entry_id,
                group=group,
                account=account,
                is_on_fn=lambda state: state.power_expected,
            ),
            DtekBinarySensor(
                coordinator=coordinator,
                description=OUTAGE_ACTIVE_DESCRIPTION,
                entry_id=entry.entry_id,
                group=group,
                account=account,
                is_on_fn=lambda state: not state.power_expected,
            ),
            DtekBinarySensor(
                coordinator=coordinator,
                description=PLANNED_MAINTENANCE_DESCRIPTION,
                entry_id=entry.entry_id,
                group=group,
                account=account,
                is_on_fn=lambda state: (
                    state.current_outage is not None and state.current_outage.outage_type == "planned"
                ),
            ),
        ]
    )


class DtekBinarySensor(CoordinatorEntity[DtekDataUpdateCoordinator], BinarySensorEntity):
    """Binary sensor representing DTEK grid status."""

    def __init__(
        self,
        coordinator: DtekDataUpdateCoordinator,
        description: BinarySensorEntityDescription,
        entry_id: str,
        group: str,
        account: str | None = None,
        is_on_fn: Callable[[Any], bool] | None = None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._is_on_fn = is_on_fn
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
    def is_on(self) -> bool:
        """Return True if condition is met."""
        if self.coordinator.data is None:
            return False
        if self._is_on_fn:
            return bool(self._is_on_fn(self.coordinator.data))
        return self.coordinator.data.power_expected

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        current = self.coordinator.data.current_outage
        return {
            "group": self.coordinator.data.group,
            "current_outage_type": current.outage_type if current else None,
            "current_outage_description": current.description if current else None,
        }
