"""New portal protocol, parsing, refresh, and credential-isolation tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from yarl import URL

from custom_components.dtek.api.exceptions import (
    DtekAuthError,
    DtekConnectionError,
    DtekRateLimitError,
    DtekResponseError,
)
from custom_components.dtek.api.new_portal import ACCOUNTS_PATH, AUTH, CALLBACK, PORTAL, DtekNewPortalClient


def accounts_response(page_count: int = 1, numbers: tuple[str, ...] = ("12345",)) -> dict:
    """Synthetic account metadata; no live response values."""
    return {
        "status": "success",
        "data": {
            "totalPages": page_count,
            "data": [
                {
                    "accountNumber": number,
                    "address": "Test city, Test street буд. 1",
                    "eic": ["test_eic"],
                    "contractDate": "2020-01-01",
                }
                for number in numbers
            ],
        },
    }


@pytest.mark.asyncio
async def test_login_pkce_and_cookie_flow() -> None:
    client = DtekNewPortalClient(MagicMock())
    state = ""
    challenge = ""

    async def request(method: str, url: URL, **kwargs):
        nonlocal state, challenge
        if url.path == "/api/oauth/authorize":
            if not state:
                state = url.query["state"]
                challenge = url.query["code_challenge"]
                return 302, None, AUTH / "login"
            return 302, None, CALLBACK.with_query(code="test_code", state=state)
        if url.path == "/login":
            return 200, None, None
        if url.path == "/api/oauth/api/auth/login":
            assert method == "POST"
            assert url.origin() == AUTH
            assert kwargs["json_body"] == {"login": "+380000000000", "password": "test_password"}
            return 200, None, None
        if url.path == "/api/oauth/token":
            import base64
            import hashlib

            form = kwargs["form"]
            calculated = (
                base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            )
            assert calculated == challenge
            assert form["redirect_uri"] == str(CALLBACK)
            return 200, None, None
        if url.path == "/api/oauth/userinfo":
            return 200, {}, None
        if url.path == "/api/userData/api/login":
            return 200, {"xIdToken": "test_account_token"}, None
        assert url.path == ACCOUNTS_PATH
        assert url.query["page"] == "1"
        assert url.query["pageSize"] == "200"
        return 200, accounts_response(), None

    client._request = AsyncMock(side_effect=request)
    user = await client.async_cabinet_authenticate("0000000000", "test_password")
    assert user.primary_account == "12345"
    assert user.accounts == ["12345"]
    assert user.token == "new_portal_session"
    assert not any(call.args[1].path == CALLBACK.path for call in client._request.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback",
    [
        CALLBACK.with_query(code="test_code", state="wrong"),
        URL("https://unexpected.invalid/oauth/callback?code=test_code"),
        PORTAL / "unexpected",
    ],
)
async def test_invalid_authorization_callback_cannot_exchange_tokens(callback: URL) -> None:
    client = DtekNewPortalClient(MagicMock())
    client._authorize = AsyncMock(side_effect=[AUTH / "login", callback])
    client._request = AsyncMock(return_value=(200, None, None))
    with pytest.raises(DtekAuthError):
        await client.async_cabinet_authenticate("0000000000", "test_password")
    assert client._request.await_count == 1


@pytest.mark.asyncio
async def test_external_redirect_not_followed() -> None:
    client = DtekNewPortalClient(MagicMock())
    client._request = AsyncMock(return_value=(302, None, URL("https://unexpected.invalid/login")))
    with pytest.raises(DtekResponseError, match="origin"):
        await client._authorize(AUTH / "api/oauth/authorize")
    assert client._request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409])
async def test_rejected_credentials_or_required_account_changes_stop_login(status: int) -> None:
    client = DtekNewPortalClient(MagicMock())
    client._authorize = AsyncMock(return_value=AUTH / "login")
    client._request = AsyncMock(return_value=(status, None, None))
    with pytest.raises(DtekAuthError, match="website"):
        await client.async_cabinet_authenticate("0000000000", "test_password")
    assert client._request.await_count == 1


@pytest.mark.asyncio
async def test_account_pagination_and_multiple_accounts() -> None:
    client = DtekNewPortalClient(MagicMock())
    client._api = AsyncMock(
        side_effect=[
            accounts_response(2, ("12345",)),
            accounts_response(2, ("67890",)),
        ]
    )
    profiles = await client.async_get_accounts()
    assert [profile.account for profile in profiles] == ["12345", "67890"]
    assert client._api.call_args_list[1].kwargs["query"] == {"page": 2, "pageSize": 200}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "error"},
        {"status": "success", "data": {}},
        {"status": "success", "data": {"data": [], "totalPages": True}},
        {"status": "success", "data": {"data": [{}], "totalPages": 1}},
    ],
)
async def test_invalid_account_response_is_explicit_error(payload: dict) -> None:
    client = DtekNewPortalClient(MagicMock())
    client._api = AsyncMock(return_value=payload)
    with pytest.raises(DtekResponseError):
        await client.async_get_accounts()


@pytest.mark.asyncio
async def test_profile_selects_exact_account_and_meter() -> None:
    client = DtekNewPortalClient(MagicMock())
    client._api = AsyncMock(
        side_effect=[
            accounts_response(numbers=("67890", "12345")),
            {
                "accountNumber": "12345",
                "serialNum": "test_meter",
                "meterType": "test_type",
                "installationEic": "test_meter_eic",
            },
        ]
    )
    profile = await client.async_get_cabinet_profile("unused", "12345")
    assert profile.account == "12345"
    assert profile.meter_serial == "test_meter"
    assert profile.eic == "test_meter_eic"
    assert profile.group is None
    assert client._api.call_args_list[1].kwargs["billing"] is True


@pytest.mark.asyncio
async def test_meter_for_wrong_account_is_not_accepted() -> None:
    client = DtekNewPortalClient(MagicMock())
    client._api = AsyncMock(side_effect=[accounts_response(), {"accountNumber": "67890"}])
    with pytest.raises(DtekResponseError, match="selected account"):
        await client.async_get_cabinet_profile("unused", "12345")


@pytest.mark.asyncio
async def test_concurrent_unauthorized_requests_refresh_once() -> None:
    client = DtekNewPortalClient(MagicMock())
    initial_requests = 0
    refreshed = False
    both_started = asyncio.Event()

    async def request(method: str, url: URL, **kwargs):
        nonlocal initial_requests, refreshed
        if url.path == "/api/oauth/token":
            assert kwargs["form"]["grant_type"] == "refresh_token"
            refreshed = True
            return 200, None, None
        if not refreshed:
            initial_requests += 1
            if initial_requests == 2:
                both_started.set()
            await both_started.wait()
            return 401, None, None
        return 200, {"ok": True}, None

    async def login():
        client._generation += 1

    client._request = AsyncMock(side_effect=request)
    client._account_login = AsyncMock(side_effect=login)
    results = await asyncio.gather(client._api("/api/test"), client._api("/api/test"))
    assert results == [{"ok": True}, {"ok": True}]
    assert client._account_login.await_count == 1
    assert sum(call.args[1].path == "/api/oauth/token" for call in client._request.call_args_list) == 1


@pytest.mark.asyncio
async def test_failed_refresh_requires_reauthentication_without_repeated_refreshes() -> None:
    client = DtekNewPortalClient(MagicMock())
    client._request = AsyncMock(side_effect=[(401, None, None), (403, None, None)])
    for _ in range(2):
        with pytest.raises(DtekAuthError, match="reauthenticate"):
            await client._api("/api/test")
    assert client._request.await_count == 2


@pytest.mark.asyncio
async def test_private_session_cleanup_does_not_close_shared_session() -> None:
    shared = MagicMock()
    client = DtekNewPortalClient(shared)
    private = client._private_session()
    assert private is not shared
    assert client._private_session() is private
    await client.async_close()
    assert private.closed
    shared.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("billing", "expected"), [(False, "test_token"), (True, "Bearer test_token")])
async def test_request_headers_cookie_csrf_and_redirect_isolation(billing: bool, expected: str) -> None:
    client = DtekNewPortalClient(MagicMock())
    session = MagicMock()
    cookie = MagicMock()
    cookie.value = "test%20csrf"
    session.cookie_jar.filter_cookies.return_value = {"XSRF-TOKEN": cookie}
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {}
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    session.request.return_value.__aexit__ = AsyncMock(return_value=False)
    client._portal_session = session
    client._x_id_token = "test_token"
    await client._request("POST", PORTAL / "api/test", token=True, billing=billing)
    kwargs = session.request.call_args.kwargs
    assert kwargs["headers"]["X-Id-Token"] == expected
    assert kwargs["headers"]["X-CSRF"] == "test csrf"
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "error"), [(429, DtekRateLimitError), (503, DtekConnectionError)])
async def test_transport_errors_are_not_successful_empty_responses(status: int, error: type[Exception]) -> None:
    client = DtekNewPortalClient(MagicMock())
    session = MagicMock()
    response = AsyncMock()
    response.status = status
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    session.request.return_value.__aexit__ = AsyncMock(return_value=False)
    client._portal_session = session
    with pytest.raises(error):
        await client._request("GET", PORTAL / "api/test")


@pytest.mark.asyncio
async def test_transport_error_does_not_expose_request_url() -> None:
    client = DtekNewPortalClient(MagicMock())
    session = MagicMock()
    session.request.side_effect = aiohttp.ClientError("private URL")
    client._portal_session = session
    with pytest.raises(DtekConnectionError) as raised:
        await client._request("GET", PORTAL / "api/test")
    assert "private" not in str(raised.value)
    assert raised.value.__suppress_context__
