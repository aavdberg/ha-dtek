"""The DTEK integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DtekApiClient, DtekAuthError, DtekError
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
    cabinet_base_url_for_dso,
    cabinet_site_for_dso,
)
from .coordinator import DtekDataUpdateCoordinator
from .models import DtekConfigEntry, DtekRuntimeData

_LOGGER = logging.getLogger(__name__)


def _async_persist_discovered_data(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    discovered: dict[str, str | None],
) -> None:
    """Write values resolved at runtime back to the config entry.

    The Personal Cabinet is authoritative for the queue group, EIC code and
    address. Entries created before those lookups existed keep stale or empty
    values, so they are refreshed here instead of on every coordinator update.
    """
    updates = {key: value for key, value in discovered.items() if value and entry.data.get(key) != value}
    if not updates:
        return
    _LOGGER.debug("Updating DTEK config entry with resolved values: %s", sorted(updates))
    hass.config_entries.async_update_entry(entry, data={**entry.data, **updates})


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
    cabinet_site = cabinet_site_for_dso(dso)
    session = async_get_clientsession(hass)
    client = DtekApiClient(
        session=session,
        base_url=base_url,
        cabinet_base_url=cabinet_base_url_for_dso(dso),
    )

    cabinet_token = None
    cabinet_customer_name = None
    cabinet_enabled = bool(phone and password)
    if cabinet_enabled:
        try:
            user = await client.async_cabinet_authenticate(
                phone=phone,
                password=password,
                site=cabinet_site,
            )
            cabinet_token = user.token
            cabinet_customer_name = user.customer_name
            if not account and user.primary_account:
                account = user.primary_account
            if not eic and user.primary_eic:
                eic = user.primary_eic
        except DtekAuthError as err:
            # Stored credentials are no longer valid; prompt the user to
            # reauthenticate instead of loading a permanently broken entry.
            raise ConfigEntryAuthFailed(f"DTEK Personal Cabinet rejected the stored credentials: {err}") from err
        except DtekError as err:
            # Transient connectivity problem: let Home Assistant retry setup
            # rather than leaving the cabinet permanently unauthenticated.
            raise ConfigEntryNotReady(f"Could not reach the DTEK Personal Cabinet: {err}") from err

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
        cabinet_customer_name=cabinet_customer_name,
        cabinet_site=cabinet_site,
        update_interval=scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    _async_persist_discovered_data(
        hass,
        entry,
        {
            CONF_GROUP: coordinator.group,
            CONF_CITY: coordinator.city,
            CONF_STREET: coordinator.street,
            CONF_HOUSE_NUMBER: coordinator.house_number,
            CONF_EIC: coordinator.cabinet_eic,
            CONF_ACCOUNT: account,
        },
    )

    entry.runtime_data = DtekRuntimeData(
        client=client,
        coordinator=coordinator,
        dso=dso,
        group=coordinator.group,
        city=coordinator.city,
        street=coordinator.street,
        house_number=coordinator.house_number,
        phone=phone,
        account=account,
        eic=coordinator.cabinet_eic,
        cabinet_enabled=cabinet_enabled,
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
