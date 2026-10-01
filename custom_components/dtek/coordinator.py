"""DataUpdateCoordinator for DTEK integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DtekApiClient,
    DtekCabinetProfile,
    DtekConnectionError,
    DtekError,
    DtekOutageEvent,
    DtekRateLimitError,
    DtekState,
    find_house_info,
    parse_house_outage,
)
from .const import CABINET_DEFAULT_SITE, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _merge_events(
    house_events: list[DtekOutageEvent],
    schedule_events: list[DtekOutageEvent],
) -> list[DtekOutageEvent]:
    """Combine both outage sources, dropping duplicate windows."""
    merged: list[DtekOutageEvent] = []
    seen: set[tuple[datetime, datetime, str]] = set()
    for event in [*house_events, *schedule_events]:
        key = (event.start, event.end, event.outage_type)
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
    merged.sort(key=lambda event: event.start)
    return merged


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
        cabinet_token: str | None = None,
        cabinet_account: str | None = None,
        cabinet_eic: str | None = None,
        cabinet_customer_name: str | None = None,
        cabinet_site: str = CABINET_DEFAULT_SITE,
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
        self.cabinet_token = cabinet_token
        self.cabinet_account = cabinet_account
        self.cabinet_eic = cabinet_eic
        self.cabinet_customer_name = cabinet_customer_name
        self.cabinet_site = cabinet_site

    async def _async_fetch_cabinet_profile(self) -> DtekCabinetProfile | None:
        """Fetch cabinet details, keeping the update alive if the cabinet is down."""
        if not (self.cabinet_token and self.cabinet_account):
            return None
        try:
            return await self.client.async_get_cabinet_profile(
                token=self.cabinet_token,
                account=self.cabinet_account,
                site=self.cabinet_site,
            )
        except DtekError as err:
            _LOGGER.debug("Could not refresh DTEK cabinet profile: %s", err)
            return None

    async def _async_update_data(self) -> DtekState:
        """Fetch latest data from DTEK portal."""
        try:
            profile = await self._async_fetch_cabinet_profile()

            if profile:
                # The cabinet is authoritative for the queue group and address.
                if profile.group:
                    if profile.group != self.group:
                        _LOGGER.info("DTEK queue updated from %s to %s", self.group, profile.group)
                    self.group = profile.group
                if profile.eic:
                    self.cabinet_eic = profile.eic
                # The registered address can change (or be corrected) on DTEK's
                # side, so every component the cabinet supplies replaces the
                # stored one instead of only filling in blanks.
                if profile.city:
                    self.city = profile.city
                if profile.street:
                    self.street = profile.street
                if profile.house_number:
                    self.house_number = profile.house_number

            flags: dict[str, bool] = {}
            house_events: list[DtekOutageEvent] = []
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
                house_info = find_house_info(lookup_result.houses, self.house_number)
                if house_info is not None:
                    if not (profile and profile.group) and house_info.group and house_info.group != self.group:
                        _LOGGER.info("DTEK queue updated from %s to %s", self.group, house_info.group)
                        self.group = house_info.group

                    # getHomeNum is the only live source of outage windows; the
                    # legacy schedule methods are retired on the Dnipro portal.
                    house_outage = parse_house_outage(house_info)
                    if house_outage is not None:
                        house_events.append(house_outage)
                else:
                    _LOGGER.debug(
                        "House %s not present in DTEK address list for %s, %s",
                        self.house_number,
                        self.city,
                        self.street,
                    )

            # Fetch schedule events
            events = await self.client.async_get_schedule(
                group=self.group,
                city=self.city,
                street=self.street,
                house=self.house_number,
            )
            events = _merge_events(house_events, events)

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
                balance=profile.balance if profile else None,
                customer_name=(profile.customer_name if profile else None) or self.cabinet_customer_name,
                eic=(profile.eic if profile else None) or self.cabinet_eic,
                meter_serial=profile.meter_serial if profile else None,
                meter_type=profile.meter_type if profile else None,
                contract_capacity=profile.contract_capacity if profile else None,
                address=profile.address if profile else None,
                object_type=profile.object_type if profile else None,
                cabinet_authenticated=bool(self.cabinet_token),
            )

        except DtekRateLimitError as err:
            raise UpdateFailed(f"DTEK rate limit hit: {err}") from err
        except DtekConnectionError as err:
            raise UpdateFailed(f"Cannot connect to DTEK portal: {err}") from err
        except DtekError as err:
            raise UpdateFailed(f"DTEK API error: {err}") from err
