"""DataUpdateCoordinator for DTEK integration."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DTEK_TIMEZONE,
    DtekApiClient,
    DtekAuthError,
    DtekCabinetProfile,
    DtekConnectionError,
    DtekError,
    DtekOutageEvent,
    DtekRateLimitError,
    DtekState,
    ensure_dtek_timezone,
    find_house_info,
    parse_house_outage,
)
from .const import CABINET_DEFAULT_SITE, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

_CABINET_METADATA_FIELDS = (
    "customer_name",
    "eic",
    "address",
    "object_type",
    "contract_capacity",
    "contract_date",
    "city",
    "street",
    "house_number",
    "meter_serial",
    "meter_type",
)


def _merge_events(
    house_events: list[DtekOutageEvent],
    schedule_events: list[DtekOutageEvent],
) -> list[DtekOutageEvent]:
    """Combine both outage sources, dropping duplicate windows."""
    merged: list[DtekOutageEvent] = []
    seen: set[tuple[datetime, datetime, str]] = set()
    for event in [*house_events, *schedule_events]:
        # Normalise first so a naive timestamp cannot poison the comparisons
        # below, and so duplicates are detected across both sources.
        event = replace(
            event,
            start=ensure_dtek_timezone(event.start),
            end=ensure_dtek_timezone(event.end),
        )
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
        self._last_cabinet_profile: DtekCabinetProfile | None = None
        self._cabinet_refresh_succeeded = False

    async def _async_fetch_cabinet_profile(self) -> DtekCabinetProfile | None:
        """Fetch cabinet details, keeping the update alive if the cabinet is down."""
        self._cabinet_refresh_succeeded = False
        if not (self.cabinet_token and self.cabinet_account):
            return None
        try:
            profile = await self.client.async_get_cabinet_profile(
                token=self.cabinet_token,
                account=self.cabinet_account,
                site=self.cabinet_site,
            )
            self._cabinet_refresh_succeeded = profile is not None and any(
                getattr(profile, name) is not None for name in (*_CABINET_METADATA_FIELDS, "balance")
            )
        except DtekAuthError as err:
            raise ConfigEntryAuthFailed("DTEK cabinet session expired; please reauthenticate") from err
        except DtekError as err:
            _LOGGER.warning("Could not refresh DTEK cabinet profile: %s", err)
            profile = None

        if self._last_cabinet_profile is not None:
            retained = {
                name: getattr(self._last_cabinet_profile, name)
                for name in _CABINET_METADATA_FIELDS
                if (profile is None or getattr(profile, name) is None)
                and getattr(self._last_cabinet_profile, name) is not None
            }
            if retained:
                _LOGGER.debug("Retaining last-known DTEK cabinet metadata for missing fields: %s", ", ".join(retained))
                profile = replace(profile or DtekCabinetProfile(), **retained)

        self._last_cabinet_profile = profile
        return profile

    async def _async_update_data(self) -> DtekState:
        """Fetch latest data from DTEK portal."""
        profile = await self._async_fetch_cabinet_profile()
        if profile:
            if profile.group:
                if profile.group != self.group:
                    _LOGGER.info("DTEK queue updated from %s to %s", self.group, profile.group)
                self.group = profile.group
            if profile.eic:
                self.cabinet_eic = profile.eic
            if profile.city:
                self.city = profile.city
            if profile.street:
                self.street = profile.street
            if profile.house_number:
                self.house_number = profile.house_number

        outage_data_available = True
        try:
            flags, events = await self._async_fetch_outages(profile)
        except DtekError as err:
            if not self._cabinet_refresh_succeeded:
                if isinstance(err, DtekRateLimitError):
                    raise UpdateFailed(f"DTEK rate limit hit: {err}") from err
                if isinstance(err, DtekConnectionError):
                    raise UpdateFailed(f"Cannot connect to DTEK portal: {err}") from err
                raise UpdateFailed(f"DTEK API error: {err}") from err
            _LOGGER.warning("DTEK outage data unavailable; cabinet data remains available (%s)", type(err).__name__)
            outage_data_available = False
            flags, events = {}, []

        now = datetime.now(DTEK_TIMEZONE)
        current_outage = None
        next_outage = None

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

        return DtekState(
            group=self.group,
            power_expected=(current_outage is None) if outage_data_available else None,
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
            outage_data_available=outage_data_available,
        )

    async def _async_fetch_outages(
        self, profile: DtekCabinetProfile | None
    ) -> tuple[dict[str, bool], list[DtekOutageEvent]]:
        """Fetch public outage data independently from cabinet metadata."""
        self.client.raise_if_portal_cooling_down()
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
            house_info = find_house_info(lookup_result.houses, self.house_number)
            if house_info is not None:
                if not (profile and profile.group) and house_info.group and house_info.group != self.group:
                    _LOGGER.info("DTEK queue updated from %s to %s", self.group, house_info.group)
                    self.group = house_info.group
                house_outage = parse_house_outage(house_info)
                if house_outage is not None:
                    house_events.append(house_outage)
            else:
                _LOGGER.debug("Configured house not present in DTEK address list")

        events = await self.client.async_get_schedule(
            group=self.group,
            city=self.city,
            street=self.street,
            house=self.house_number,
        )
        return flags, _merge_events(house_events, events)
