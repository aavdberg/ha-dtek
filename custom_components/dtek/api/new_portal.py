"""Cookie-based Dnipro portal authentication and verified read-only APIs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
from dataclasses import replace
from typing import Any
from urllib.parse import unquote

import aiohttp
from yarl import URL

from .client import (
    DEFAULT_USER_AGENT,
    DtekApiClient,
    _format_capacity,
    _to_float,
    normalize_group,
    parse_cabinet_address,
)
from .endpoints import (
    PATH_CABINET_BALANCE,
    PATH_CABINET_CHOICE_ACCOUNT,
    PATH_CABINET_CHOICE_APART,
    PATH_CABINET_OBJECTS_INFO,
    PATH_CABINET_POWERTRACK,
)
from .exceptions import DtekAuthError, DtekConnectionError, DtekError, DtekRateLimitError, DtekResponseError
from .models import DtekCabinetProfile, DtekCabinetUser

PORTAL = URL("https://my.dtek-dnem.com.ua")
AUTH = URL("https://auth.my.dtek-dnem.com.ua")
CLIENT_ID = "ee2b502c-e74e-476c-bb1a-dc7e075e2c47"
CALLBACK = PORTAL / "oauth/callback"
ACCOUNTS_PATH = "/api/billing/joint/objects/get_advanced"
LEGACY = URL("https://ok.dtek-dnem.com.ua")
LEGACY_CALLBACK = LEGACY / "auth/callback"
# The legacy backend performs the code exchange using its first-party verifier.
LEGACY_CHALLENGE = "T0wiJiK1mBexC-LFD46zLufVr-iPXXPSYDMxrsYp_U8"
_LOGGER = logging.getLogger(__name__)


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


class DtekNewPortalClient(DtekApiClient):
    """Use the first-party PKCE callback with an isolated in-memory cookie jar."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = "https://www.dtek-dnem.com.ua",
        cabinet_base_url: str = "https://ok.dtek-dnem.com.ua",
    ) -> None:
        super().__init__(session=session, base_url=base_url, cabinet_base_url=cabinet_base_url)
        self._portal_session: aiohttp.ClientSession | None = None
        self._auth_lock = asyncio.Lock()
        self._x_id_token: str | None = None
        self._generation = 0
        self._expired = False
        self._refresh_error: DtekError | None = None
        self._legacy_lock = asyncio.Lock()
        self._legacy_token: str | None = None
        self._legacy_account: str | None = None

    async def async_close(self) -> None:
        """Dispose of private cookies without closing HA's shared HTTP session."""
        if self._portal_session is not None:
            await self._portal_session.close()
            self._portal_session = None
        self._x_id_token = None
        self._refresh_error = None
        self._legacy_token = None
        self._legacy_account = None

    def _private_session(self) -> aiohttp.ClientSession:
        if self._portal_session is None:
            self._portal_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
            )
        return self._portal_session

    async def _request(
        self,
        method: str,
        url: URL,
        *,
        json_body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        token: bool = False,
        billing: bool = False,
        legacy_authorization: str | None = None,
    ) -> tuple[int, Any, URL | None]:
        is_legacy = url.origin() == LEGACY
        if is_legacy:
            if (
                method != "POST"
                or url.path
                not in (
                    "/api/auth/sms",
                    PATH_CABINET_OBJECTS_INFO,
                    PATH_CABINET_BALANCE,
                    PATH_CABINET_POWERTRACK,
                    PATH_CABINET_CHOICE_APART,
                    PATH_CABINET_CHOICE_ACCOUNT,
                )
                or token
            ):
                raise DtekResponseError("New DTEK portal returned an unexpected legacy destination")
        elif url.origin() not in (PORTAL, AUTH) or legacy_authorization:
            raise DtekResponseError("New DTEK portal returned an unexpected destination")
        session = self._private_session()
        headers: dict[str, str] = {}
        if method != "GET":
            headers["Origin"] = str(url.origin())
            cookie = session.cookie_jar.filter_cookies(url).get("XSRF-TOKEN")
            if cookie:
                headers["X-CSRF"] = unquote(cookie.value)
        if token and self._x_id_token:
            headers["X-Id-Token"] = ("Bearer " if billing else "") + self._x_id_token
        if legacy_authorization:
            headers["Authorization"] = legacy_authorization
        try:
            async with session.request(
                method, url, json=json_body, data=form, headers=headers, allow_redirects=False
            ) as response:
                if response.status == 429:
                    raise DtekRateLimitError("New DTEK portal rate limited the request; try again later")
                if response.status >= 500:
                    raise DtekConnectionError(f"New DTEK portal unavailable (HTTP {response.status})")
                location = response.headers.get("Location")
                redirect = url.join(URL(location)) if location else None
                if "json" in response.headers.get("Content-Type", ""):
                    payload = await response.json()
                else:
                    await response.read()
                    payload = None
                return response.status, payload, redirect
        except (aiohttp.ClientError, TimeoutError, ValueError):
            # Raw transport errors may contain an account URL or response data.
            raise DtekConnectionError("New DTEK portal request failed") from None

    async def _authorize(self, url: URL) -> URL:
        for _ in range(6):
            if url.origin() not in (PORTAL, AUTH):
                raise DtekResponseError("New DTEK portal authorization left the expected origin")
            if url.origin() == PORTAL and url.path == CALLBACK.path:
                return url
            status, _, redirect = await self._request("GET", url)
            if status in (301, 302, 303, 307, 308) and redirect is not None:
                url = redirect
                continue
            if status != 200:
                raise DtekAuthError("New DTEK portal authorization failed; sign in on the website first")
            return url
        raise DtekResponseError("New DTEK portal authorization redirected too many times")

    async def _account_login(self) -> None:
        status, _, _ = await self._request("GET", PORTAL / "api/oauth/userinfo")
        if status != 200:
            raise DtekAuthError("New DTEK portal session expired; please reauthenticate")
        status, payload, _ = await self._request("POST", PORTAL / "api/userData/api/login")
        token = _text(payload.get("xIdToken")) if isinstance(payload, dict) else None
        if status != 200 or not token:
            raise DtekAuthError("New DTEK portal account access failed; complete account setup on the website")
        self._x_id_token = token
        self._refresh_error = None
        self._generation += 1

    async def async_cabinet_authenticate(self, phone: str, password: str, site: str = "dnem") -> DtekCabinetUser:
        """Authenticate without changing passwords or reusing browser state."""
        if site != "dnem":
            raise DtekResponseError("New portal support is currently limited to Dnipro")
        async with self._auth_lock:
            await self.async_close()
            self._expired = False
            clean_phone = "".join(character for character in phone if character.isdigit())
            clean_phone = "+" + (clean_phone if len(clean_phone) > 10 else "38" + clean_phone)
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            state = secrets.token_urlsafe(32)
            authorize = (AUTH / "api/oauth/authorize").with_query(
                response_type="code",
                client_id=CLIENT_ID,
                redirect_uri=str(CALLBACK),
                code_challenge_method="S256",
                code_challenge=challenge,
                state=state,
            )
            await self._authorize(authorize)
            status, _, _ = await self._request(
                "POST",
                AUTH / "api/oauth/api/auth/login",
                json_body={"login": clean_phone, "password": password},
            )
            if status != 200:
                raise DtekAuthError(
                    "New DTEK portal login rejected; verify credentials and required account changes on the website"
                )
            callback = await self._authorize(authorize)
            if (
                callback.origin() != PORTAL
                or callback.path != CALLBACK.path
                or callback.query.getall("state", []) != [state]
                or len(callback.query.getall("code", [])) != 1
                or not callback.query.get("code")
            ):
                raise DtekAuthError("New DTEK portal returned an invalid authorization callback")
            status, _, _ = await self._request(
                "POST",
                PORTAL / "api/oauth/token",
                form={
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "redirect_uri": str(CALLBACK),
                    "code_verifier": verifier,
                    "code": callback.query["code"],
                },
            )
            if status != 200:
                raise DtekAuthError("New DTEK portal token exchange failed")
            await self._account_login()
        accounts = await self.async_get_accounts()
        return DtekCabinetUser(
            token="new_portal_session",
            phone=clean_phone,
            accounts=[account.account for account in accounts if account.account],
            primary_account=accounts[0].account if len(accounts) == 1 else None,
        )

    async def _api(self, path: str, *, billing: bool = False, query: dict[str, str | int] | None = None) -> Any:
        if self._expired:
            raise DtekAuthError("New DTEK portal session expired; please reauthenticate")
        url = PORTAL.with_path(path).with_query(query or {})
        generation = self._generation
        status, payload, _ = await self._request("GET", url, token=True, billing=billing)
        if status == 401:
            async with self._auth_lock:
                if self._expired:
                    raise DtekAuthError("New DTEK portal session expired; please reauthenticate")
                if generation == self._generation:
                    try:
                        refresh_status, _, _ = await self._request(
                            "POST",
                            PORTAL / "api/oauth/token",
                            form={"grant_type": "refresh_token", "client_id": CLIENT_ID},
                        )
                        if refresh_status != 200:
                            raise DtekAuthError("New DTEK portal session expired; please reauthenticate")
                        await self._account_login()
                    except DtekError as err:
                        self._refresh_error = err
                        self._generation += 1
                        self._expired = isinstance(err, DtekAuthError)
                        raise
                elif self._refresh_error is not None:
                    raise self._refresh_error
            status, payload, _ = await self._request("GET", url, token=True, billing=billing)
        if status == 401:
            self._expired = True
            raise DtekAuthError("New DTEK portal denied account access after refreshing")
        if status != 200 or payload is None:
            raise DtekResponseError(f"New DTEK portal API returned an unexpected response (HTTP {status})")
        return payload

    async def _legacy_login(self, account: str) -> None:
        """Exchange a separate first-party authorization code for legacy access."""
        if not self._x_id_token:
            raise DtekResponseError("New DTEK portal account token is missing")
        try:
            parts = self._x_id_token.split(".")
            if len(parts) != 3:
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except (ValueError, UnicodeError):
            raise DtekResponseError("New DTEK portal handoff claims are invalid") from None
        user_id = claims.get("user_data_id") if isinstance(claims, dict) else None
        if not isinstance(user_id, (str, int)) or isinstance(user_id, bool) or not str(user_id):
            raise DtekResponseError("New DTEK portal handoff identity is missing")
        state = json.dumps(
            {
                "account": account,
                "pathDestination": "/cabinet/person/sub-book",
                "forcedPersonType": False,
                "userTypeId": "2",
                "userDataId": user_id,
                "nonce": secrets.token_urlsafe(32),
            },
            separators=(",", ":"),
        )
        authorize = (AUTH / "api/oauth/authorize").with_query(
            response_type="code",
            client_id=CLIENT_ID.upper(),
            redirect_uri=str(LEGACY_CALLBACK),
            state=state,
            code_challenge=LEGACY_CHALLENGE,
            code_challenge_method="S256",
        )
        status, _, callback = await self._request("GET", authorize)
        if (
            status != 302
            or callback is None
            or callback.origin() != LEGACY
            or callback.path != LEGACY_CALLBACK.path
            or callback.query.getall("state", []) != [state]
            or len(callback.query.getall("code", [])) != 1
            or not callback.query.get("code")
        ):
            raise DtekAuthError("DTEK legacy handoff requires a valid authenticated session")
        authorization = base64.b64encode(f"{account}:{callback.query['code']}".encode()).decode()
        status, payload, _ = await self._request(
            "POST",
            LEGACY / "api/auth/sms",
            json_body={
                "action": "token",
                "userType": "person",
                "userTypeId": "2",
                "userDataId": user_id,
                "forcedPersonType": False,
                "account": account,
                "redirectUri": str(LEGACY_CALLBACK),
                "site": "dnem",
                "language": "uk-UA",
                "platform": "Linux",
            },
            legacy_authorization="Basic " + authorization,
        )
        user = payload.get("user") if isinstance(payload, dict) else None
        token = _text(user.get("token")) if isinstance(user, dict) else None
        if status != 200 or not isinstance(payload, dict) or payload.get("status") != "success" or not token:
            raise DtekAuthError("DTEK legacy session exchange failed")
        self._legacy_token = token
        self._legacy_account = account

    async def _legacy_api(self, path: str, account: str, **values: Any) -> dict[str, Any]:
        status, payload, _ = await self._request(
            "POST",
            LEGACY.with_path(path),
            json_body={"token": self._legacy_token, "account": account, **values},
            legacy_authorization="Bearer " + (self._legacy_token or ""),
        )
        if status in (401, 403):
            raise DtekAuthError("DTEK legacy session expired")
        if status != 200 or not isinstance(payload, dict):
            raise DtekResponseError("DTEK legacy data response is invalid")
        if payload.get("status") in ("fail", "error"):
            raise DtekResponseError("DTEK legacy data request was rejected")
        inner = payload.get("data")
        return inner if isinstance(inner, dict) else payload

    async def _legacy_profile(self, account: str) -> DtekCabinetProfile:
        """Read selected-account metadata with one bounded legacy renewal."""
        async with self._legacy_lock:
            for attempt in range(2):
                try:
                    if not self._legacy_token or self._legacy_account != account:
                        await self._legacy_login(account)
                    info = await self._legacy_api(PATH_CABINET_OBJECTS_INFO, account)
                    customer = info.get("customer")
                    if not isinstance(customer, dict) or _text(customer.get("account")) != account:
                        raise DtekResponseError("DTEK legacy response does not match the selected account")
                    eic = _text(customer.get("eic"))
                    group = None
                    if eic:
                        schedule = await self._legacy_api(PATH_CABINET_POWERTRACK, account, eic=eic, site="dnem")
                        group = normalize_group(schedule["gpv"]) if isinstance(schedule.get("gpv"), str) else None
                    balance = await self._legacy_api(PATH_CABINET_BALANCE, account)
                    amount = _to_float(balance.get("balance"))
                    debit, credit = _to_float(balance.get("debet")), _to_float(balance.get("credit"))
                    if amount is None and (debit is not None or credit is not None):
                        amount = (credit or 0.0) - (debit or 0.0)
                    meter_serial = None
                    meter_type = None
                    try:
                        await self._legacy_api(
                            PATH_CABINET_CHOICE_APART,
                            account,
                            item={"account": account},
                        )
                        meter_data = await self._legacy_api(PATH_CABINET_CHOICE_ACCOUNT, account, site="dnem")
                        meters = meter_data.get("meters")
                        meter = (
                            next((item for item in meters if isinstance(item, dict)), None)
                            if isinstance(meters, list)
                            else None
                        )
                        if meter is not None:
                            serial = _text(meter.get("serialNumber")) or _text(meter.get("serial_number"))
                            meter_serial = serial.lstrip("_") if serial else None
                            meter_type = (
                                " ".join(
                                    value
                                    for value in (_text(meter.get("type")), _text(meter.get("construction")))
                                    if value
                                )
                                or None
                            )
                    except DtekAuthError:
                        raise
                    except DtekError as err:
                        _LOGGER.warning("DTEK legacy meter metadata unavailable: %s", err)
                    return DtekCabinetProfile(
                        account=account,
                        customer_name=_text(customer.get("name")),
                        eic=eic,
                        address=_text(customer.get("address")),
                        group=group,
                        balance=amount,
                        object_type=_text(customer.get("objectType")),
                        contract_capacity=_format_capacity(customer.get("demPerm")),
                        contract_date=_text(customer.get("contractDate")),
                        meter_serial=meter_serial,
                        meter_type=meter_type,
                    )
                except DtekAuthError:
                    self._legacy_token = None
                    self._legacy_account = None
                    if attempt:
                        raise
        raise DtekAuthError("DTEK legacy session could not be renewed")

    async def async_get_accounts(self, account: str | None = None) -> list[DtekCabinetProfile]:
        """Read all pages, never silently select the first of several accounts."""
        profiles: list[DtekCabinetProfile] = []
        page = 1
        while page <= 100:
            query: dict[str, str | int] = {"page": page, "pageSize": 200}
            if account:
                query["accountNumber"] = account
            payload = await self._api(ACCOUNTS_PATH, query=query)
            if not isinstance(payload, dict) or payload.get("status") != "success":
                raise DtekResponseError("New DTEK portal did not return a successful account list")
            envelope = payload.get("data")
            if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), list):
                raise DtekResponseError("New DTEK portal account list has an unexpected structure")
            pages = envelope.get("totalPages")
            if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
                raise DtekResponseError("New DTEK portal account pagination is invalid")
            for item in envelope["data"]:
                if not isinstance(item, dict) or not (number := _text(item.get("accountNumber"))):
                    raise DtekResponseError("New DTEK portal returned an invalid account")
                eic_codes = item.get("eic")
                address = _text(item.get("address"))
                city, street, house = parse_cabinet_address(address or "")
                profiles.append(
                    DtekCabinetProfile(
                        account=number,
                        address=address,
                        eic=_text(eic_codes[0]) if isinstance(eic_codes, list) and len(eic_codes) == 1 else None,
                        contract_date=_text(item.get("contractDate")),
                        city=city,
                        street=street,
                        house_number=house,
                    )
                )
            if page >= pages:
                return profiles
            page += 1
        raise DtekResponseError("New DTEK portal account list exceeded the pagination limit")

    async def async_get_cabinet_profile(self, token: str, account: str, site: str = "dnem") -> DtekCabinetProfile:
        profiles = await self.async_get_accounts(account)
        selected = [profile for profile in profiles if profile.account == account]
        if len(selected) != 1:
            raise DtekResponseError("Configured account was not uniquely returned by the new DTEK portal")
        # URL path construction must not let a malformed identifier change the endpoint.
        if not account.isascii() or not account.isdigit():
            raise DtekResponseError("New DTEK portal account identifier is invalid")
        meter = await self._api(
            f"/api/billing-service/api/meters/household/{account}/data",
            billing=True,
        )
        if not isinstance(meter, dict) or meter.get("accountNumber") != account:
            raise DtekResponseError("New DTEK portal meter response does not match the selected account")
        profile = replace(
            selected[0],
            eic=_text(meter.get("installationEic")) or selected[0].eic,
            meter_serial=_text(meter.get("serialNum")),
            meter_type=_text(meter.get("meterType")),
        )
        try:
            legacy = await self._legacy_profile(account)
        except DtekError as err:
            _LOGGER.warning("DTEK legacy metadata unavailable; new portal metadata remains available: %s", err)
            return profile
        address = profile.address or legacy.address
        city, street, house_number = parse_cabinet_address(address or "")
        return replace(
            profile,
            customer_name=legacy.customer_name,
            group=legacy.group,
            balance=legacy.balance,
            object_type=legacy.object_type,
            contract_capacity=legacy.contract_capacity,
            contract_date=profile.contract_date or legacy.contract_date,
            eic=profile.eic or legacy.eic,
            meter_serial=legacy.meter_serial or profile.meter_serial,
            meter_type=legacy.meter_type or profile.meter_type,
            address=address,
            city=profile.city or city,
            street=profile.street or street,
            house_number=profile.house_number or house_number,
        )
