"""The DTEK Outages integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DtekApiClient
from .const import (
    CONF_CITY,
    CONF_DSO,
    CONF_GROUP,
    CONF_HOUSE_NUMBER,
    CONF_STREET,
    CONF_UPDATE_INTERVAL,
    DEFAULT_DSO,
    DEFAULT_SCAN_INTERVAL,
    PLATFORMS,
    SUPPORTED_DSOS,
)
from .coordinator import DtekDataUpdateCoordinator
from .models import DtekConfigEntry, DtekRuntimeData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Set up DTEK Outages from a config entry."""
    dso = entry.data.get(CONF_DSO, DEFAULT_DSO)
    group = entry.data.get(CONF_GROUP, "GPV1.2")
    city = entry.data.get(CONF_CITY)
    street = entry.data.get(CONF_STREET)
    house_number = entry.data.get(CONF_HOUSE_NUMBER)

    base_url = SUPPORTED_DSOS.get(dso, {}).get("base_url", "https://www.dtek-dnem.com.ua")
    session = async_get_clientsession(hass)
    client = DtekApiClient(session=session, base_url=base_url)

    interval_minutes = entry.options.get(
        CONF_UPDATE_INTERVAL,
        int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60),
    )
    scan_interval = timedelta(minutes=interval_minutes)

    coordinator = DtekDataUpdateCoordinator(
        hass=hass,
        client=client,
        group=group,
        city=city,
        street=street,
        house_number=house_number,
        update_interval=scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = DtekRuntimeData(
        client=client,
        coordinator=coordinator,
        dso=dso,
        group=group,
        city=city,
        street=street,
        house_number=house_number,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
