"""Models and runtime data for DTEK integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import DtekApiClient
    from .coordinator import DtekDataUpdateCoordinator


@dataclass(slots=True)
class DtekRuntimeData:
    """Runtime data stored in entry.runtime_data."""

    client: DtekApiClient
    coordinator: DtekDataUpdateCoordinator
    dso: str
    group: str
    city: str | None = None
    street: str | None = None
    house_number: str | None = None


# Type alias for ConfigEntry with runtime data
type DtekConfigEntry = ConfigEntry[DtekRuntimeData]
