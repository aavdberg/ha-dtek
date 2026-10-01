"""DTEK HTTP API client with session management, CSRF extraction, and retries."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import re
from typing import Any

import aiohttp

from .endpoints import (
    AJAX_PATH,
    METHOD_GET_CURRENT_SCHEDULE,
    METHOD_GET_FACT,
    METHOD_GET_HOME_NUM,
    METHOD_GET_PLAN,
    METHOD_GET_SCHEDULE,
    METHOD_GET_STREETS,
    PATH_CABINET_AUTH_PERSON,
    PATH_CABINET_BALANCE,
    PATH_CABINET_OBJECTS_INFO,
    PATH_CABINET_POWERTRACK,
    SHUTDOWNS_PATH,
)
from .exceptions import (
    DtekAddressNotFoundError,
    DtekAuthError,
    DtekConnectionError,
    DtekCsrfError,
    DtekRateLimitError,
    DtekResponseError,
)
from .models import DtekAddressLookupResult, DtekCabinetUser, DtekHouseInfo, DtekOutageEvent

_LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0

# Regex patterns for CSRF token
CSRF_META_PATTERN = re.compile(
    r'<meta\s+[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']|'
    r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']csrf-token["\']',
    re.IGNORECASE,
)
CSRF_JS_PATTERN = re.compile(r'["\']csrf-token["\']\s*:\s*["\']([^"\']+)["\']', re.IGNORECASE)

SETTLEMENT_PREFIX_PATTERN = re.compile(
    r"^(с-ще|смт|м\.|с\.|тг|селище|село|місто)\s*",
    re.IGNORECASE,
)
STREET_PREFIX_PATTERN = re.compile(
    r"^(вул\.|пров\.|просп\.|бульв\.|туп\.|узвіз|площа|пл\.|вулиця|провулок|проспект)\s*",
    re.IGNORECASE,
)


def resolve_settlement_and_street(
    input_city: str,
    input_street: str,
    streets_map: dict[str, list[str]],
) -> tuple[str, str] | None:
    """Resolve user input to exact DTEK settlement and street names."""
    clean_input_city = SETTLEMENT_PREFIX_PATTERN.sub("", input_city).strip().lower()
    clean_input_street = STREET_PREFIX_PATTERN.sub("", input_street).strip().lower()

    # Step 1: find candidate settlements
    candidate_cities: list[str] = []
    for c in streets_map:
        clean_c = SETTLEMENT_PREFIX_PATTERN.sub("", c).strip().lower()
        if clean_c == clean_input_city:
            candidate_cities.append(c)

    if not candidate_cities:
        for c in streets_map:
            clean_c = SETTLEMENT_PREFIX_PATTERN.sub("", c).strip().lower()
            if clean_input_city in clean_c:
                candidate_cities.append(c)

    # Step 2: match street in candidate settlements
    for c in candidate_cities:
        for s in streets_map.get(c, []):
            clean_s = STREET_PREFIX_PATTERN.sub("", s).strip().lower()
            if clean_s == clean_input_street:
                return c, s

    for c in candidate_cities:
        for s in streets_map.get(c, []):
            clean_s = STREET_PREFIX_PATTERN.sub("", s).strip().lower()
            if clean_input_street in clean_s:
                return c, s

    return None


class DtekApiClient:
    """API client for interacting with DTEK portals."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = "https://www.dtek-dnem.com.ua",
        cabinet_base_url: str = "https://ok.dtek-dnem.com.ua",
    ) -> None:
        """Initialize the DTEK API client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._cabinet_base_url = cabinet_base_url.rstrip("/")
        self._csrf_token: str | None = None
        self._streets_cache: dict[str, list[str]] | None = None
        self._cabinet_token: str | None = None

    @property
    def base_url(self) -> str:
        """Return current base URL."""
        return self._base_url

    async def async_ensure_csrf_token(self, force_refresh: bool = False) -> str:
        """Fetch the shutdowns page to obtain session cookies and CSRF token."""
        if self._csrf_token and not force_refresh:
            return self._csrf_token

        url = f"{self._base_url}{SHUTDOWNS_PATH}"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        try:
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 429:
                    raise DtekRateLimitError("Rate limit / WAF challenge encountered while obtaining CSRF token")
                if resp.status >= 400:
                    raise DtekConnectionError(f"Failed to fetch DTEK portal: HTTP {resp.status}")

                text = await resp.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise DtekConnectionError(f"Connection error while fetching DTEK portal: {err}") from err

        # Extract CSRF token
        match = CSRF_META_PATTERN.search(text)
        if match:
            self._csrf_token = match.group(1) or match.group(2)
        elif js_match := CSRF_JS_PATTERN.search(text):
            self._csrf_token = js_match.group(1)
        else:
            # Check cookies as fallback
            for cookie in self._session.cookie_jar:
                if "csrf" in cookie.key.lower() or "xsrf" in cookie.key.lower():
                    self._csrf_token = cookie.value
                    break
            if not self._csrf_token:
                raise DtekCsrfError("Could not find CSRF token in DTEK portal HTML or cookies")

        # Cache streets from HTML if embedded
        if not self._streets_cache:
            streets_match = re.search(r"DisconSchedule\.streets\s*=\s*(\{.*?\});", text)
            if streets_match:
                try:
                    import json

                    self._streets_cache = json.loads(streets_match.group(1))
                except Exception:
                    pass

        return self._csrf_token

    async def _async_post_ajax(
        self,
        data: dict[str, Any],
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """Send a stateful AJAX request with CSRF token and retries."""
        csrf_token = await self.async_ensure_csrf_token()

        url = f"{self._base_url}{AJAX_PATH}"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Origin": self._base_url,
            "Referer": f"{self._base_url}{SHUTDOWNS_PATH}",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        try:
            async with self._session.post(
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status == 429:
                    if retry_count < MAX_RETRIES:
                        backoff = (INITIAL_BACKOFF * (2**retry_count)) + random.uniform(0.1, 0.5)
                        _LOGGER.warning("DTEK rate limit hit, backing off for %.1f seconds", backoff)
                        await asyncio.sleep(backoff)
                        return await self._async_post_ajax(data, retry_count + 1)
                    raise DtekRateLimitError("DTEK rate limit exceeded after maximum retries")

                if resp.status in (401, 403, 419):
                    # CSRF token might have expired, try refreshing once
                    if retry_count == 0:
                        _LOGGER.debug("CSRF token expired or rejected (HTTP %d), refreshing token", resp.status)
                        await self.async_ensure_csrf_token(force_refresh=True)
                        return await self._async_post_ajax(data, retry_count + 1)
                    raise DtekCsrfError(f"CSRF validation failed with HTTP {resp.status}")

                if resp.status >= 500:
                    if retry_count < MAX_RETRIES:
                        backoff = (INITIAL_BACKOFF * (2**retry_count)) + random.uniform(0.1, 0.5)
                        _LOGGER.warning("DTEK server error %d, retrying in %.1f seconds", resp.status, backoff)
                        await asyncio.sleep(backoff)
                        return await self._async_post_ajax(data, retry_count + 1)
                    raise DtekResponseError(f"DTEK server error HTTP {resp.status}")

                if resp.status >= 400:
                    raise DtekResponseError(f"DTEK request failed with HTTP {resp.status}")

                try:
                    json_data = await resp.json(content_type=None)
                except Exception as err:
                    raw_text = await resp.text()
                    raise DtekResponseError(f"Failed to parse DTEK JSON response: {raw_text[:200]}") from err

                return json_data

        except (TimeoutError, aiohttp.ClientError) as err:
            if retry_count < MAX_RETRIES:
                backoff = (INITIAL_BACKOFF * (2**retry_count)) + random.uniform(0.1, 0.5)
                _LOGGER.warning("DTEK connection error, retrying in %.1f seconds: %s", backoff, err)
                await asyncio.sleep(backoff)
                return await self._async_post_ajax(data, retry_count + 1)
            raise DtekConnectionError(f"Connection failed to DTEK endpoint: {err}") from err

    async def async_get_streets(self, force_refresh: bool = False) -> dict[str, list[str]]:
        """Fetch all settlements and streets from DTEK portal."""
        if self._streets_cache and not force_refresh:
            return self._streets_cache

        payload: dict[str, Any] = {"method": METHOD_GET_STREETS}
        try:
            data = await self._async_post_ajax(payload)
            if isinstance(data, dict) and "streets" in data and isinstance(data["streets"], dict):
                self._streets_cache = data["streets"]
                return self._streets_cache
        except Exception as err:
            _LOGGER.debug("Could not fetch streets list via AJAX: %s", err)

        return self._streets_cache or {}

    async def async_get_home_numbers(
        self,
        city: str,
        street: str,
        update_fact: str | None = None,
        auto_resolve: bool = True,
    ) -> DtekAddressLookupResult:
        """Fetch house numbers and queue mapping for a city and street."""
        resolved_city = city
        resolved_street = street

        if auto_resolve:
            try:
                streets_map = await self.async_get_streets()
                if streets_map:
                    resolved = resolve_settlement_and_street(city, street, streets_map)
                    if resolved:
                        resolved_city, resolved_street = resolved
            except Exception as err:
                _LOGGER.debug("Address resolution failed or skipped: %s", err)

        payload: dict[str, Any] = {
            "method": METHOD_GET_HOME_NUM,
            "data[0][name]": "city",
            "data[0][value]": resolved_city,
            "data[1][name]": "street",
            "data[1][value]": resolved_street,
        }
        if update_fact:
            payload["data[2][name]"] = "updateFact"
            payload["data[2][value]"] = update_fact

        data = await self._async_post_ajax(payload)

        # Parse flags
        result_flag = bool(data.get("result", False))
        lookup_result = DtekAddressLookupResult(
            result=result_flag,
            show_cur_outage_param=bool(data.get("showCurOutageParam", False)),
            show_cur_schedule=bool(data.get("showCurSchedule", False)),
            show_table_schedule=bool(data.get("showTableSchedule", False)),
            show_table_plan=bool(data.get("showTablePlan", False)),
            show_table_fact=bool(data.get("showTableFact", False)),
            show_user_group=bool(data.get("showUserGroup", False)),
            resolved_city=resolved_city,
            resolved_street=resolved_street,
        )

        raw_houses = data.get("data")
        if not isinstance(raw_houses, dict):
            raw_houses = data

        houses: dict[str, DtekHouseInfo] = {}
        for key, val in raw_houses.items():
            if not isinstance(val, dict):
                continue

            sub_type_reason = val.get("sub_type_reason", [])
            group: str | None = None
            if sub_type_reason and isinstance(sub_type_reason, list) and len(sub_type_reason) > 0:
                group = str(sub_type_reason[0])

            house_info = DtekHouseInfo(
                house_num=key,
                group=group,
                sub_type=str(val.get("sub_type", "")),
                start_date=str(val.get("start_date", "")),
                end_date=str(val.get("end_date", "")),
                outage_type=str(val.get("type", "")),
                sub_type_reason=list(sub_type_reason) if isinstance(sub_type_reason, list) else [],
            )
            houses[key] = house_info

        object.__setattr__(lookup_result, "houses", houses)
        if not houses and not result_flag:
            raise DtekAddressNotFoundError(f"No house numbers found for city '{city}', street '{street}'")

        return lookup_result

    async def async_get_schedule(
        self,
        group: str | None = None,
        city: str | None = None,
        street: str | None = None,
        house: str | None = None,
    ) -> list[DtekOutageEvent]:
        """Query schedule and planned outages for a group or address."""
        # Query methods: getPlan or getSchedule if available
        events: list[DtekOutageEvent] = []

        for method in (METHOD_GET_PLAN, METHOD_GET_SCHEDULE, METHOD_GET_CURRENT_SCHEDULE, METHOD_GET_FACT):
            payload: dict[str, Any] = {"method": method}
            if group:
                payload["group"] = group
            if city:
                payload["city"] = city
            if street:
                payload["street"] = street
            if house:
                payload["house"] = house

            try:
                data = await self._async_post_ajax(payload)
                _LOGGER.debug("Response from %s: %s", method, str(data)[:300])
            except Exception as err:
                _LOGGER.debug("Method %s not supported or returned error: %s", method, err)
                continue

        return events

    async def async_cabinet_authenticate(
        self,
        phone: str,
        password: str,
        site: str = "dnem",
    ) -> DtekCabinetUser:
        """Authenticate user against DTEK Personal Cabinet (ok.dtek)."""
        clean_phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not clean_phone.startswith("+"):
            clean_phone = f"+{clean_phone}" if len(clean_phone) > 10 else f"+38{clean_phone}"

        credentials = f"{clean_phone}:{password}"
        encoded_auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")

        url = f"{self._cabinet_base_url}{PATH_CABINET_AUTH_PERSON}"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        payload = {
            "phone": clean_phone,
            "userType": "person",
            "language": "uk-UA",
            "platform": "Win32",
            "site": site,
        }

        try:
            async with self._session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status in (401, 403):
                    raise DtekAuthError("Invalid phone number or password for DTEK Personal Cabinet")
                if resp.status >= 400:
                    raise DtekConnectionError(f"Cabinet authentication failed with HTTP {resp.status}")

                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise DtekConnectionError(f"Connection failed to DTEK cabinet: {err}") from err

        # Handle direct response dict or nested "data" dict
        resp_data = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
        user_data = resp_data.get("user") if isinstance(resp_data, dict) else None
        if not user_data or not user_data.get("token"):
            # Check if token is at top level of user_data or resp_data
            if isinstance(resp_data, dict) and resp_data.get("token"):
                user_data = resp_data
            else:
                status_text = (
                    data.get("message")
                    or data.get("status")
                    or (resp_data.get("message") if isinstance(resp_data, dict) else None)
                    or "Authentication failed"
                )
                raise DtekAuthError(f"DTEK cabinet login rejected: {status_text}")

        token = str(user_data["token"])
        self._cabinet_token = token

        # Extract account info (from user_data or resp_data)
        accounts: list[str] = []
        eic_codes: list[str] = []

        raw_accounts = (
            user_data.get("accounts") or (resp_data.get("accounts") if isinstance(resp_data, dict) else None) or []
        )
        for acc in raw_accounts:
            if isinstance(acc, dict):
                if acc.get("account"):
                    accounts.append(str(acc["account"]))
                if acc.get("eic"):
                    eic_codes.append(str(acc["eic"]))
            elif isinstance(acc, str):
                accounts.append(acc)

        primary_account = accounts[0] if accounts else None
        primary_eic = eic_codes[0] if eic_codes else None
        customer_name = user_data.get("name") if isinstance(user_data, dict) else None

        return DtekCabinetUser(
            token=token,
            phone=clean_phone,
            accounts=accounts,
            eic_codes=eic_codes,
            primary_account=primary_account,
            primary_eic=primary_eic,
            customer_name=customer_name,
        )

    async def async_get_cabinet_objects_info(
        self,
        token: str,
        account: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch registered objects, meters, and address info from cabinet."""
        url = f"{self._cabinet_base_url}{PATH_CABINET_OBJECTS_INFO}"
        payload: dict[str, Any] = {"token": token}
        if account:
            payload["account"] = account

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with self._session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict):
                        objects = data.get("objects") or data.get("data")
                        if isinstance(objects, list):
                            return objects
                    elif isinstance(data, list):
                        return data
        except Exception as err:
            _LOGGER.debug("Could not fetch cabinet objects info: %s", err)
        return []

    async def async_get_cabinet_powertrack_schedule(
        self,
        token: str,
        eic: str,
        account: str,
        site: str = "dnem",
    ) -> dict[str, Any]:
        """Fetch precise account-level GPV schedule from cabinet."""
        url = f"{self._cabinet_base_url}{PATH_CABINET_POWERTRACK}"
        payload = {
            "token": token,
            "eic": eic,
            "account": account,
            "site": site,
        }
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with self._session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
        except Exception as err:
            _LOGGER.debug("Could not fetch powertrack schedule: %s", err)
        return {}

    async def async_get_cabinet_balance(
        self,
        token: str,
        account: str,
    ) -> float | None:
        """Fetch account balance from cabinet."""
        url = f"{self._cabinet_base_url}{PATH_CABINET_BALANCE}"
        payload = {"token": token, "account": account}
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with self._session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict):
                        # May be {"balance": 150.75} or {"data": {"balance": 150.75}}
                        balance_val = data.get("balance")
                        if balance_val is None and isinstance(data.get("data"), dict):
                            balance_val = data["data"].get("balance")
                        if balance_val is not None:
                            return float(balance_val)
        except Exception as err:
            _LOGGER.debug("Could not fetch cabinet balance: %s", err)
        return None
