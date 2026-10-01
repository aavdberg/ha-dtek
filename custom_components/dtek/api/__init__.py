"""API client module for DTEK integration."""

from __future__ import annotations

from .client import DtekApiClient
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
    DtekCabinetUser,
    DtekHouseInfo,
    DtekOutageEvent,
    DtekState,
)

__all__ = [
    "DtekAddressLookupResult",
    "DtekAddressNotFoundError",
    "DtekApiClient",
    "DtekAuthError",
    "DtekCabinetUser",
    "DtekConnectionError",
    "DtekCsrfError",
    "DtekError",
    "DtekHouseInfo",
    "DtekOutageEvent",
    "DtekRateLimitError",
    "DtekResponseError",
    "DtekState",
]
