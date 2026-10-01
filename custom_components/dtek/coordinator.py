"""DataUpdateCoordinator for DTEK Outages integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DtekApiClient,
    DtekConnectionError,
    DtekError,
    DtekRateLimitError,
    DtekState,
)
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DtekDataUpdateCoordinator(DataUpdateCoordinator[DtekState]):
    """Class to manage fetching DTEK outage data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DtekApiClient,
        group: str,
        city: str | None = None,
        street: str | None = None,
        house_number: str | None = None,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"DTEK ({group})",
            update_interval=update_interval,
        )
        self.client = client
        self.group = group
        self.city = city
        self.street = street
        self.house_number = house_number

    async def _async_update_data(self) -> DtekState:
        """Fetch latest data from DTEK portal."""
        try:
            flags: dict[str, bool] = {}
            if self.city and self.street:
                lookup_result = await self.client.async_get_home_numbers(
                    city=self.city,
                    street=self.street,
                )
                flags = {
                    "show_cur_outage_param": lookup_result.show_cur_outage_param,
                    "show_cur_schedule": lookup_result.show_cur_schedule,
                    "show_table_schedule": lookup_result.show_table_schedule,
                    "show_table_plan": lookup_result.show_table_plan,
                    "show_table_fact": lookup_result.show_table_fact,
                    "show_user_group": lookup_result.show_user_group,
                }
                # If house_number was provided, verify if group updated
                if self.house_number and self.house_number in lookup_result.houses:
                    house_info = lookup_result.houses[self.house_number]
                    if house_info.group and house_info.group != self.group:
                        _LOGGER.info("DTEK queue updated from %s to %s", self.group, house_info.group)
                        self.group = house_info.group

            # Fetch schedule events
            events = await self.client.async_get_schedule(
                group=self.group,
                city=self.city,
                street=self.street,
                house=self.house_number,
            )

            now = datetime.now()
            current_outage = None
            next_outage = None

            # Filter and sort upcoming events
            upcoming = [e for e in events if e.end > now]
            upcoming.sort(key=lambda e: e.start)

            for event in upcoming:
                if event.start <= now < event.end:
                    current_outage = event
                    break

            for event in upcoming:
                if event.start > now:
                    next_outage = event
                    break

            power_expected = current_outage is None

            return DtekState(
                group=self.group,
                power_expected=power_expected,
                current_outage=current_outage,
                next_outage=next_outage,
                events=events,
                last_updated=now,
                flags=flags,
            )

        except DtekRateLimitError as err:
            raise UpdateFailed(f"DTEK rate limit hit: {err}") from err
        except DtekConnectionError as err:
            raise UpdateFailed(f"Cannot connect to DTEK portal: {err}") from err
        except DtekError as err:
            raise UpdateFailed(f"DTEK API error: {err}") from err
