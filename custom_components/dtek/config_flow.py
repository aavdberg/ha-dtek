"""Config flow and Options flow for DTEK integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DtekAddressNotFoundError,
    DtekApiClient,
    DtekAuthError,
    DtekConnectionError,
    DtekError,
    find_house_info,
    normalize_house_number,
)
from .api.new_portal import DtekNewPortalClient
from .const import (
    CABINET_PORTAL_LEGACY,
    CABINET_PORTAL_NEW,
    CONF_ACCOUNT,
    CONF_CABINET_PORTAL,
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
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    SUPPORTED_DSOS,
    cabinet_base_url_for_dso,
    cabinet_site_for_dso,
)

_LOGGER = logging.getLogger(__name__)

CONF_SETUP_MODE = "setup_mode"
SETUP_MODE_ADDRESS = "address"
SETUP_MODE_CABINET = "cabinet"
SETUP_MODE_MANUAL = "manual"
SETUP_MODE_NEW_CABINET = "new_cabinet"


class _AbortCabinetStep(Exception):
    """Internal signal to redisplay the cabinet form with an error."""


class DtekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DTEK."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._dso: str = DEFAULT_DSO
        self._city: str | None = None
        self._street: str | None = None
        self._house_number: str | None = None
        self._group: str | None = None
        self._new_accounts: list[str] = []
        self._new_data: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - select DSO and setup mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._dso = user_input[CONF_DSO]
            setup_mode = user_input.get(CONF_SETUP_MODE, SETUP_MODE_ADDRESS)

            if setup_mode == SETUP_MODE_CABINET:
                return await self.async_step_cabinet()
            if setup_mode == SETUP_MODE_NEW_CABINET:
                if self._dso != "dtek-dnem":
                    errors["base"] = "new_portal_unsupported"
                else:
                    return await self.async_step_new_cabinet()
            if setup_mode == SETUP_MODE_MANUAL:
                return await self.async_step_manual_group()
            elif setup_mode != SETUP_MODE_NEW_CABINET:
                return await self.async_step_address()

        dso_options = {dso_id: info["name"] for dso_id, info in SUPPORTED_DSOS.items()}

        schema = vol.Schema(
            {
                vol.Required(CONF_DSO, default=DEFAULT_DSO): vol.In(dso_options),
                vol.Required(CONF_SETUP_MODE, default=SETUP_MODE_CABINET): vol.In(
                    {
                        SETUP_MODE_CABINET: "Personal Cabinet (ok.dtek) login [Recommended]",
                        SETUP_MODE_ADDRESS: "Automatic address lookup",
                        SETUP_MODE_MANUAL: "Manual group/queue entry",
                        SETUP_MODE_NEW_CABINET: "New Personal Cabinet (my.dtek) — Dnipro",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_new_cabinet(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Authenticate explicitly against the new Dnipro portal."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = DtekNewPortalClient(
                session=async_get_clientsession(self.hass), base_url=SUPPORTED_DSOS[self._dso]["base_url"]
            )
            try:
                user = await client.async_cabinet_authenticate(
                    phone=user_input[CONF_PHONE].strip(), password=user_input[CONF_PASSWORD], site="dnem"
                )
                if not user.accounts:
                    errors["base"] = "no_account"
                else:
                    self._new_accounts = user.accounts
                    self._new_data = {
                        CONF_DSO: self._dso,
                        CONF_PHONE: user_input[CONF_PHONE].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CABINET_PORTAL: CABINET_PORTAL_NEW,
                    }
                    return await self.async_step_new_account()
            except DtekAuthError:
                errors["base"] = "invalid_auth"
            except DtekConnectionError:
                errors["base"] = "cannot_connect"
            except DtekError:
                errors["base"] = "unknown"
            finally:
                await client.async_close()
        return self.async_show_form(
            step_id="new_cabinet",
            data_schema=vol.Schema({vol.Required(CONF_PHONE): str, vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_new_account(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Select an account without guessing an outage queue."""
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT]
            group = user_input.get(CONF_GROUP, "").strip().upper()
            if account not in self._new_accounts:
                errors["base"] = "no_account"
            else:
                client = DtekNewPortalClient(
                    session=async_get_clientsession(self.hass), base_url=SUPPORTED_DSOS[self._dso]["base_url"]
                )
                try:
                    user = await client.async_cabinet_authenticate(
                        phone=self._new_data[CONF_PHONE], password=self._new_data[CONF_PASSWORD], site="dnem"
                    )
                    if account not in user.accounts:
                        errors["base"] = "no_account"
                    else:
                        profile = await client.async_get_cabinet_profile(token=user.token, account=account)
                        group = profile.group or group
                        if not group and profile.city and profile.street and profile.house_number:
                            lookup = await client.async_get_home_numbers(city=profile.city, street=profile.street)
                            house = find_house_info(lookup.houses, profile.house_number)
                            if house is not None:
                                group = house.group
                        if not group:
                            errors["base"] = "no_group"
                        else:
                            await self.async_set_unique_id(f"{self._dso}_cabinet_{account}".lower())
                            self._abort_if_unique_id_configured()
                            return self.async_create_entry(
                                title=f"DTEK Account {account}",
                                data={
                                    **self._new_data,
                                    CONF_ACCOUNT: account,
                                    CONF_GROUP: group,
                                    CONF_EIC: profile.eic,
                                    CONF_CITY: profile.city,
                                    CONF_STREET: profile.street,
                                    CONF_HOUSE_NUMBER: profile.house_number,
                                },
                            )
                except DtekAuthError:
                    errors["base"] = "invalid_auth"
                except DtekConnectionError:
                    errors["base"] = "cannot_connect"
                except DtekError:
                    errors["base"] = "unknown"
                finally:
                    await client.async_close()
        return self.async_show_form(
            step_id="new_account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT): vol.In(self._new_accounts),
                    vol.Optional(CONF_GROUP): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Prompt for new credentials without changing account identity."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Validate replacement credentials for the linked account before reloading."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            dso = entry.data.get(CONF_DSO, DEFAULT_DSO)
            portal = entry.options.get(CONF_CABINET_PORTAL, entry.data.get(CONF_CABINET_PORTAL, CABINET_PORTAL_LEGACY))
            client_class = DtekNewPortalClient if portal == CABINET_PORTAL_NEW else DtekApiClient
            client = client_class(
                session=async_get_clientsession(self.hass),
                base_url=SUPPORTED_DSOS[dso]["base_url"],
                cabinet_base_url=cabinet_base_url_for_dso(dso),
            )
            try:
                user = await client.async_cabinet_authenticate(
                    phone=user_input[CONF_PHONE].strip(),
                    password=user_input[CONF_PASSWORD],
                    site=cabinet_site_for_dso(dso),
                )
                account = entry.data.get(CONF_ACCOUNT)
                if account not in user.accounts:
                    errors["base"] = "no_account"
                else:
                    await client.async_get_cabinet_profile(
                        token=user.token, account=account, site=cabinet_site_for_dso(dso)
                    )
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_PHONE: user_input[CONF_PHONE].strip(),
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
            except DtekAuthError:
                errors["base"] = "invalid_auth"
            except DtekConnectionError:
                errors["base"] = "cannot_connect"
            except DtekError:
                errors["base"] = "unknown"
            finally:
                if isinstance(client, DtekNewPortalClient):
                    await client.async_close()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PHONE): str, vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_address(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Step to enter city, street, and house number."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._city = user_input[CONF_CITY].strip()
            self._street = user_input[CONF_STREET].strip()
            self._house_number = user_input[CONF_HOUSE_NUMBER].strip()

            session = async_get_clientsession(self.hass)
            base_url = SUPPORTED_DSOS[self._dso]["base_url"]
            client = DtekApiClient(session=session, base_url=base_url)

            try:
                lookup = await client.async_get_home_numbers(
                    city=self._city,
                    street=self._street,
                )

                if lookup.resolved_city:
                    self._city = lookup.resolved_city
                if lookup.resolved_street:
                    self._street = lookup.resolved_street

                # Look for matching house number (handle formatting differences such as slashes or letters)
                matched_house = find_house_info(lookup.houses, self._house_number)
                if matched_house is not None:
                    # Store the portal's canonical key so later lookups match exactly.
                    target = normalize_house_number(self._house_number)
                    for house_key in lookup.houses:
                        if house_key == self._house_number or normalize_house_number(house_key) == target:
                            self._house_number = house_key
                            break

                if matched_house and matched_house.group:
                    self._group = matched_house.group
                elif matched_house:
                    # Found house but no explicit group tag
                    self._group = f"{self._dso}-default"
                else:
                    errors["base"] = "house_not_found"

                if not errors and self._group:
                    unique_id = f"{self._dso}_{self._city}_{self._street}_{self._house_number}".lower()
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    title = f"DTEK {self._city}, {self._street} {self._house_number} ({self._group})"
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_DSO: self._dso,
                            CONF_CITY: self._city,
                            CONF_STREET: self._street,
                            CONF_HOUSE_NUMBER: self._house_number,
                            CONF_GROUP: self._group,
                        },
                    )

            except DtekAddressNotFoundError:
                errors["base"] = "address_not_found"
            except DtekConnectionError:
                errors["base"] = "cannot_connect"
            except DtekError:
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_CITY, default=self._city or "м. Дніпро"): str,
                vol.Required(CONF_STREET, default=self._street or "вул. Центральна"): str,
                vol.Required(CONF_HOUSE_NUMBER, default=self._house_number or "1"): str,
            }
        )

        return self.async_show_form(
            step_id="address",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_cabinet(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Step to authenticate via DTEK Personal Cabinet."""
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()
            password = user_input[CONF_PASSWORD].strip()

            session = async_get_clientsession(self.hass)
            base_url = SUPPORTED_DSOS[self._dso]["base_url"]
            site = cabinet_site_for_dso(self._dso)
            client = DtekApiClient(
                session=session,
                base_url=base_url,
                cabinet_base_url=cabinet_base_url_for_dso(self._dso),
            )

            try:
                user = await client.async_cabinet_authenticate(
                    phone=phone,
                    password=password,
                    site=site,
                )
                # A login without an account cannot address any cabinet endpoint,
                # and substituting a placeholder would give every such user the
                # same bogus identity. Surface the problem instead.
                account = user.primary_account
                if not account:
                    errors["base"] = "no_account"
                    raise _AbortCabinetStep

                # The cabinet is authoritative: it yields the EIC, the registered
                # address and the exact GPV queue for this account.
                profile = await client.async_get_cabinet_profile(
                    token=user.token,
                    account=account,
                    site=site,
                )
                eic = profile.eic or user.primary_eic or ""
                # Guessing a queue would report another group's outages as the
                # user's own, so an unresolved queue aborts the setup.
                group = profile.group
                if not group:
                    errors["base"] = "no_group"
                    raise _AbortCabinetStep
                city = profile.city
                street = profile.street
                house = profile.house_number

                unique_id = f"{self._dso}_cabinet_{account}".lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = f"DTEK Account {account}"

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_DSO: self._dso,
                        CONF_PHONE: phone,
                        CONF_PASSWORD: password,
                        CONF_ACCOUNT: account,
                        CONF_EIC: eic,
                        CONF_GROUP: group,
                        CONF_CITY: city,
                        CONF_STREET: street,
                        CONF_HOUSE_NUMBER: house,
                    },
                )
            except _AbortCabinetStep:
                pass
            except DtekAuthError:
                errors["base"] = "invalid_auth"
            except DtekConnectionError:
                errors["base"] = "cannot_connect"
            except DtekError:
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_PHONE): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="cabinet",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual_group(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Step to enter group manually (e.g. GPV1.2)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            group = user_input[CONF_GROUP].strip().upper()
            unique_id = f"{self._dso}_{group}".lower()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            dso_name = SUPPORTED_DSOS[self._dso]["name"].split(" (")[0]
            title = f"DTEK {dso_name} ({group})"

            return self.async_create_entry(
                title=title,
                data={
                    CONF_DSO: self._dso,
                    CONF_GROUP: group,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_GROUP, default="GPV1.2"): str,
            }
        )

        return self.async_show_form(
            step_id="manual_group",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return DtekOptionsFlow(config_entry)


class DtekOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for DTEK."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            current_portal = self._config_entry.options.get(
                CONF_CABINET_PORTAL, self._config_entry.data.get(CONF_CABINET_PORTAL, CABINET_PORTAL_LEGACY)
            )
            portal = user_input.get(CONF_CABINET_PORTAL, current_portal)
            password = user_input.get(CONF_PASSWORD) or self._config_entry.data.get(CONF_PASSWORD)
            if portal == CABINET_PORTAL_NEW and (portal != current_portal or user_input.get(CONF_PASSWORD)):
                dso = self._config_entry.data.get(CONF_DSO, DEFAULT_DSO)
                if dso != "dtek-dnem":
                    errors["base"] = "new_portal_unsupported"
                elif not self._config_entry.data.get(CONF_PHONE) or not password:
                    errors["base"] = "no_account"
                else:
                    client = DtekNewPortalClient(
                        session=async_get_clientsession(self.hass), base_url=SUPPORTED_DSOS[dso]["base_url"]
                    )
                    try:
                        user = await client.async_cabinet_authenticate(
                            phone=self._config_entry.data[CONF_PHONE],
                            password=password,
                            site="dnem",
                        )
                        account = self._config_entry.data.get(CONF_ACCOUNT)
                        if account not in user.accounts:
                            errors["base"] = "no_account"
                        else:
                            await client.async_get_cabinet_profile(token=user.token, account=account)
                    except DtekAuthError:
                        errors["base"] = "invalid_auth"
                    except DtekConnectionError:
                        errors["base"] = "cannot_connect"
                    except DtekError:
                        errors["base"] = "unknown"
                    finally:
                        await client.async_close()
            if not errors:
                if portal == CABINET_PORTAL_NEW and user_input.get(CONF_PASSWORD):
                    self.hass.config_entries.async_update_entry(
                        self._config_entry, data={**self._config_entry.data, CONF_PASSWORD: password}
                    )
                return self.async_create_entry(
                    title="", data={key: value for key, value in user_input.items() if key != CONF_PASSWORD}
                )

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60),
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=current_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=MAX_SCAN_INTERVAL_MINUTES),
                ),
            }
        )
        if (
            self._config_entry.data.get(CONF_PHONE)
            and self._config_entry.data.get(CONF_DSO, DEFAULT_DSO) == "dtek-dnem"
        ):
            current_portal = self._config_entry.options.get(
                CONF_CABINET_PORTAL, self._config_entry.data.get(CONF_CABINET_PORTAL, CABINET_PORTAL_LEGACY)
            )
            schema = schema.extend(
                {
                    vol.Required(CONF_CABINET_PORTAL, default=current_portal): vol.In(
                        {
                            CABINET_PORTAL_LEGACY: "Legacy Personal Cabinet (ok.dtek)",
                            CABINET_PORTAL_NEW: "New Personal Cabinet (my.dtek)",
                        }
                    ),
                    vol.Optional(CONF_PASSWORD): str,
                }
            )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
