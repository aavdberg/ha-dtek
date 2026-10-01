"""Binary sensor platform for DTEK Outages integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DTEK binary sensor entities."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            DtekPowerExpectedBinarySensor(
                coordinator=coordinator,
                description=POWER_EXPECTED_DESCRIPTION,
                entry_id=entry.entry_id,
                group=entry.runtime_data.group,
            )
        ]
    )


class DtekPowerExpectedBinarySensor(CoordinatorEntity[DtekDataUpdateCoordinator], BinarySensorEntity):
    """Binary sensor representing whether electricity is expected to be ON."""

    def __init__(
        self,
        coordinator: DtekDataUpdateCoordinator,
        description: BinarySensorEntityDescription,
        entry_id: str,
        group: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": f"DTEK Grid ({group})",
            "manufacturer": MANUFACTURER,
            "model": f"Queue {group}",
        }

    @property
    def is_on(self) -> bool:
        """Return True if power is expected, False if outage is active."""
        if self.coordinator.data is None:
            return True
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
