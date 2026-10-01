"""The DTEK Outages integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DtekApiClient
from .const import (
    CONF_ACCOUNT,
    CONF_CITY,
    CONF_DSO,
    CONF_EIC,
    CONF_GROUP,
    CONF_HOUSE_NUMBER,
    CONF_PASSWORD,
    CONF_PHONE,
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
    phone = entry.data.get(CONF_PHONE)
    account = entry.data.get(CONF_ACCOUNT)
    eic = entry.data.get(CONF_EIC)
    password = entry.data.get(CONF_PASSWORD)

    base_url = SUPPORTED_DSOS.get(dso, {}).get("base_url", "https://www.dtek-dnem.com.ua")
    session = async_get_clientsession(hass)
    client = DtekApiClient(session=session, base_url=base_url)

    cabinet_token = None
    if phone and password:
        try:
            user = await client.async_cabinet_authenticate(phone=phone, password=password)
            cabinet_token = user.token
            if not account and user.primary_account:
                account = user.primary_account
            if not eic and user.primary_eic:
                eic = user.primary_eic
        except Exception as err:
            _LOGGER.warning("Could not authenticate to DTEK cabinet during setup: %s", err)

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
        cabinet_token=cabinet_token,
        cabinet_account=account,
        cabinet_eic=eic,
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
        phone=phone,
        account=account,
        eic=eic,
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
