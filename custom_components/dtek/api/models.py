"""Data models for DTEK API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class DtekHouseInfo:
    """Information about a specific house number from getHomeNum."""

    house_num: str
    group: str | None = None
    sub_type: str = ""
    start_date: str = ""
    end_date: str = ""
    outage_type: str = ""
    sub_type_reason: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class DtekAddressLookupResult:
    """Parsed result from method=getHomeNum."""

    result: bool
    show_cur_outage_param: bool = False
    show_cur_schedule: bool = False
    show_table_schedule: bool = False
    show_table_plan: bool = False
    show_table_fact: bool = False
    show_user_group: bool = False
    houses: dict[str, DtekHouseInfo] = field(default_factory=dict)
    resolved_city: str | None = None
    resolved_street: str | None = None


@dataclass(slots=True, frozen=True)
class DtekOutageEvent:
    """An individual outage or maintenance interval."""

    start: datetime
    end: datetime
    outage_type: str
    description: str
    group: str | None = None

    @property
    def is_active(self) -> bool:
        """Return true if this outage is currently happening."""
        now = datetime.now(self.start.tzinfo)
        return self.start <= now < self.end


@dataclass(slots=True, frozen=True)
class DtekCabinetUser:
    """Authenticated user info from ok.dtek cabinet."""

    token: str
    phone: str
    accounts: list[str] = field(default_factory=list)
    eic_codes: list[str] = field(default_factory=list)
    primary_account: str | None = None
    primary_eic: str | None = None
    customer_name: str | None = None
    city: str | None = None
    street: str | None = None
    house_number: str | None = None
    meter_serial: str | None = None
    meter_type: str | None = None


@dataclass(slots=True)
class DtekState:
    """Aggregated state for a configured DTEK location."""

    group: str
    power_expected: bool = True
    current_outage: DtekOutageEvent | None = None
    next_outage: DtekOutageEvent | None = None
    events: list[DtekOutageEvent] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    flags: dict[str, bool] = field(default_factory=dict)
    balance: float | None = None
    day_reading: float | None = None
    night_reading: float | None = None
    customer_name: str | None = None
    eic: str | None = None
    meter_serial: str | None = None
    meter_type: str | None = None
    contract_capacity: str | None = None
    cabinet_authenticated: bool = False
