"""Config flow and Options flow for DTEK Outages integration."""

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
)
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
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    SUPPORTED_DSOS,
)

_LOGGER = logging.getLogger(__name__)

CONF_SETUP_MODE = "setup_mode"
SETUP_MODE_ADDRESS = "address"
SETUP_MODE_CABINET = "cabinet"
SETUP_MODE_MANUAL = "manual"


class DtekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DTEK Outages."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._dso: str = DEFAULT_DSO
        self._city: str | None = None
        self._street: str | None = None
        self._house_number: str | None = None
        self._group: str | None = None

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
            if setup_mode == SETUP_MODE_MANUAL:
                return await self.async_step_manual_group()
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
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
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
                matched_house = None
                normalized_input = (
                    self._house_number.replace(" ", "").replace("/", "").lower().replace("b", "б").replace("a", "а")
                )

                for house_key, house_info in lookup.houses.items():
                    norm_key = house_key.replace(" ", "").replace("/", "").lower().replace("b", "б").replace("a", "а")
                    if norm_key == normalized_input or house_key == self._house_number:
                        matched_house = house_info
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
            client = DtekApiClient(session=session, base_url=base_url)

            try:
                user = await client.async_cabinet_authenticate(phone=phone, password=password)
                account = user.primary_account or "default"
                eic = user.primary_eic or ""
                group = "GPV1.1"

                # If EIC is available, try to resolve exact GPV schedule
                if eic:
                    sched = await client.async_get_cabinet_powertrack_schedule(
                        token=user.token,
                        eic=eic,
                        account=account,
                    )
                    if isinstance(sched, dict) and sched.get("data", {}).get("gpv"):
                        group = str(sched["data"]["gpv"])

                # Auto-detect address details from cabinet objects if available
                objects = await client.async_get_cabinet_objects_info(
                    token=user.token,
                    account=account,
                )
                city = None
                street = None
                house = None
                if objects and isinstance(objects, list):
                    first_obj = objects[0]
                    if isinstance(first_obj, dict):
                        city = first_obj.get("city")
                        street = first_obj.get("street")
                        house = first_obj.get("house") or first_obj.get("house_num")

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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

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

        return self.async_show_form(step_id="init", data_schema=schema)
