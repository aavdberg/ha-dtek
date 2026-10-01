"""API client module for DTEK integration."""

from __future__ import annotations

from .client import (
    DTEK_TIMEZONE,
    DtekApiClient,
    ensure_dtek_timezone,
    find_house_info,
    normalize_house_number,
    parse_house_outage,
)
from .exceptions import (
    DtekAddressNotFoundError,
    DtekAuthError,
    DtekConnectionError,
    DtekCsrfError,
    DtekError,
    DtekRateLimitError,
    DtekResponseError,
)
from .models import (
    DtekAddressLookupResult,
    DtekCabinetProfile,
    DtekCabinetUser,
    DtekHouseInfo,
    DtekOutageEvent,
    DtekState,
)

__all__ = [
    "DTEK_TIMEZONE",
    "DtekAddressLookupResult",
    "DtekAddressNotFoundError",
    "DtekApiClient",
    "DtekAuthError",
    "DtekCabinetProfile",
    "DtekCabinetUser",
    "DtekConnectionError",
    "DtekCsrfError",
    "DtekError",
    "DtekHouseInfo",
    "DtekOutageEvent",
    "DtekRateLimitError",
    "DtekResponseError",
    "DtekState",
    "ensure_dtek_timezone",
    "find_house_info",
    "normalize_house_number",
    "parse_house_outage",
]
