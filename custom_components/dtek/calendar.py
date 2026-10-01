"""Calendar platform for DTEK integration."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DtekDataUpdateCoordinator

if TYPE_CHECKING:
    from .models import DtekConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DTEK calendar entity."""
    coordinator = entry.runtime_data.coordinator
    account = entry.runtime_data.account
    group = entry.runtime_data.group

    async_add_entities(
        [
            DtekOutageCalendarEntity(
                coordinator=coordinator,
                entry_id=entry.entry_id,
                group=group,
                account=account,
            )
        ]
    )


class DtekOutageCalendarEntity(CoordinatorEntity[DtekDataUpdateCoordinator], CalendarEntity):
    """Calendar entity for DTEK power outages and planned maintenance."""

    def __init__(
        self,
        coordinator: DtekDataUpdateCoordinator,
        entry_id: str,
        group: str,
        account: str | None = None,
    ) -> None:
        """Initialize calendar entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_calendar"
        self._attr_has_entity_name = True
        self._attr_translation_key = "outages"
        self._attr_icon = "mdi:calendar-clock"

        device_name = f"DTEK Account {account}" if account else f"DTEK Grid ({group})"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": f"Queue {group}",
        }

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next or current upcoming event."""
        if self.coordinator.data is None:
            return None

        # Return current outage if active, else next outage
        active = self.coordinator.data.current_outage
        if active:
            return CalendarEvent(
                start=active.start,
                end=active.end,
                summary=f"DTEK Outage: {active.description}",
                description=f"Type: {active.outage_type}. Queue: {self.coordinator.data.group}",
            )

        upcoming = self.coordinator.data.next_outage
        if upcoming:
            return CalendarEvent(
                start=upcoming.start,
                end=upcoming.end,
                summary=f"DTEK Outage: {upcoming.description}",
                description=f"Type: {upcoming.outage_type}. Queue: {self.coordinator.data.group}",
            )

        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        if self.coordinator.data is None:
            return []

        events: list[CalendarEvent] = []
        for item in self.coordinator.data.events:
            if item.end > start_date and item.start < end_date:
                events.append(
                    CalendarEvent(
                        start=item.start,
                        end=item.end,
                        summary=f"DTEK Outage: {item.description}",
                        description=f"Type: {item.outage_type}. Queue: {self.coordinator.data.group}",
                    )
                )

        return events
