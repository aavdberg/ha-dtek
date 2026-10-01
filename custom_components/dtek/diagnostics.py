"""Diagnostics support for DTEK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .models import DtekConfigEntry

REDACTED = "**REDACTED**"

# Credentials and identifiers that must never leave the instance in a
# diagnostics download. `entry.data` is copied wholesale, so anything sensitive
# has to be listed here explicitly.
REDACTED_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "phone",
        "account",
        "eic",
        "house_number",
    }
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry with PII redacted."""
    coordinator = entry.runtime_data.coordinator

    entry_data = {key: REDACTED if key in REDACTED_ENTRY_KEYS and value else value for key, value in entry.data.items()}

    state_info: dict[str, Any] = {}
    if coordinator.data:
        state_info = {
            "group": coordinator.data.group,
            "power_expected": coordinator.data.power_expected,
            "has_current_outage": coordinator.data.current_outage is not None,
            "has_next_outage": coordinator.data.next_outage is not None,
            "total_events_count": len(coordinator.data.events),
            "flags": coordinator.data.flags,
            "last_updated": coordinator.data.last_updated.isoformat(),
        }

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": entry_data,
            "options": dict(entry.options),
        },
        "dso": entry.runtime_data.dso,
        "coordinator": state_info,
    }
