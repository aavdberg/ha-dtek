"""Unit tests for DtekApiClient."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.dtek.api.client import (
    DTEK_TIMEZONE,
    MAX_RETRIES,
    PORTAL_BLOCK_COOLDOWN_SECONDS,
    DtekApiClient,
    _response_shape,
    ensure_dtek_timezone,
    find_house_info,
    normalize_house_number,
    parse_cabinet_address,
    parse_house_outage,
)
from custom_components.dtek.api.exceptions import (
    DtekAddressNotFoundError,
    DtekAuthError,
    DtekConnectionError,
    DtekCsrfError,
    DtekRateLimitError,
)
from custom_components.dtek.api.models import DtekHouseInfo


class MockResponse:
    """Mock for aiohttp response."""

    def __init__(self, status: int, text_data: str = "", json_data: Any = None) -> None:
        self.status = status
        self._text_data = text_data
        self._json_data = json_data

    async def text(self) -> str:
        return self._text_data

    async def json(self, content_type: Any = None) -> Any:
        return self._json_data

    async def __aenter__(self) -> MockResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_ensure_csrf_token_success(mock_html_with_csrf: str) -> None:
    """Test extracting CSRF token from portal HTML."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get = MagicMock(return_value=MockResponse(status=200, text_data=mock_html_with_csrf))

    client = DtekApiClient(session=session)
    token = await client.async_ensure_csrf_token()

    assert token == "test_dtek_csrf_token_1234567890"
    assert client._csrf_token == "test_dtek_csrf_token_1234567890"


@pytest.mark.asyncio
async def test_ensure_csrf_token_missing() -> None:
    """Test exception when CSRF token is not found in HTML."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get = MagicMock(return_value=MockResponse(status=200, text_data="<html><body>No token</body></html>"))

    client = DtekApiClient(session=session)
    with pytest.raises(DtekCsrfError):
        await client.async_ensure_csrf_token()


@pytest.mark.asyncio
async def test_ensure_csrf_token_rate_limit() -> None:
    """Test exception when 429 received while getting CSRF token."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get = MagicMock(return_value=MockResponse(status=429))

    client = DtekApiClient(session=session)
    with pytest.raises(DtekRateLimitError):
        await client.async_ensure_csrf_token()


@pytest.mark.asyncio
async def test_ensure_csrf_token_connection_error() -> None:
    """Test exception on connection failure."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("Network down"))

    client = DtekApiClient(session=session)
    with pytest.raises(DtekConnectionError):
        await client.async_ensure_csrf_token()


@pytest.mark.asyncio
async def test_ensure_csrf_token_forbidden_mentions_possible_waf() -> None:
    """The HTTP 403 error identifies a possible WAF block and cooldown."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = MockResponse(status=403)

    with pytest.raises(DtekRateLimitError, match="portal or its WAF may be blocking"):
        await DtekApiClient(session).async_ensure_csrf_token()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_portal_cooldown_survives_new_clients_and_expires(
    status: int, monkeypatch: pytest.MonkeyPatch, mock_html_with_csrf: str
) -> None:
    """Setup retries/reloads do not reset or extend the 900-second pause."""
    clock = MagicMock(return_value=1000.0)
    monkeypatch.setattr("custom_components.dtek.api.client.monotonic", clock)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get.side_effect = [
        MockResponse(status=status),
        MockResponse(status=200, text_data=mock_html_with_csrf),
    ]
    with pytest.raises(DtekRateLimitError, match="15 minutes"):
        await DtekApiClient(session).async_ensure_csrf_token()

    for elapsed in (5, 15, 35, 75, 155, 315, 635, 899):
        clock.return_value = 1000.0 + elapsed
        client = DtekApiClient(session)
        client._csrf_token = "previous_token"
        with pytest.raises(DtekRateLimitError, match=f"another {900 - elapsed} seconds"):
            await client.async_ensure_csrf_token()
        assert client._csrf_token is None
        assert session.get.call_count == 1
        session.post.assert_not_called()

    clock.return_value = 1000.0 + PORTAL_BLOCK_COOLDOWN_SECONDS
    recovered = DtekApiClient(session)
    assert await recovered.async_ensure_csrf_token() == "test_dtek_csrf_token_1234567890"
    assert session.get.call_count == 2
    assert await recovered.async_ensure_csrf_token() == "test_dtek_csrf_token_1234567890"
    assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_portal_cooldown_is_scoped_to_session_and_portal(mock_html_with_csrf: str) -> None:
    """A blocked portal does not block another region or HA session."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get.side_effect = [
        MockResponse(status=403),
        MockResponse(status=200, text_data=mock_html_with_csrf),
    ]
    with pytest.raises(DtekRateLimitError):
        await DtekApiClient(session).async_ensure_csrf_token()

    other_portal = DtekApiClient(session, base_url="https://www.dtek-kem.com.ua")
    assert await other_portal.async_ensure_csrf_token() == "test_dtek_csrf_token_1234567890"

    other_session = MagicMock(spec=aiohttp.ClientSession)
    other_session.cookie_jar = []
    other_session.get.return_value = MockResponse(status=200, text_data=mock_html_with_csrf)
    assert await DtekApiClient(other_session).async_ensure_csrf_token() == "test_dtek_csrf_token_1234567890"


@pytest.mark.asyncio
async def test_concurrent_csrf_get_cannot_post_after_another_client_starts_cooldown(
    mock_html_with_csrf: str,
) -> None:
    """A GET already in flight must not lead to a new POST during cooldown."""
    reading = asyncio.Event()
    finish = asyncio.Event()

    class DelayedResponse(MockResponse):
        async def text(self) -> str:
            reading.set()
            await finish.wait()
            return await super().text()

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get.side_effect = [
        DelayedResponse(status=200, text_data=mock_html_with_csrf),
        MockResponse(status=403),
    ]
    first_client = DtekApiClient(session)
    pending = asyncio.create_task(first_client._async_post_ajax({"method": "getStreets"}))
    try:
        await asyncio.wait_for(reading.wait(), timeout=5)
        with pytest.raises(DtekRateLimitError, match="15 minutes"):
            await DtekApiClient(session).async_ensure_csrf_token()
    finally:
        finish.set()
        with pytest.raises(DtekRateLimitError, match="another"):
            await pending

    assert first_client._csrf_token is None
    assert session.get.call_count == 2
    session.post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["script", "iframe"])
async def test_portal_challenge_is_not_a_csrf_error(tag: str) -> None:
    """An HTTP 200 Incapsula challenge is recognized even with stale cookies."""
    session = MagicMock(spec=aiohttp.ClientSession)
    cookie = MagicMock()
    cookie.key = "_csrf"
    cookie.value = "stale_cookie_token"
    session.cookie_jar = [cookie]
    session.get.return_value = MockResponse(
        status=200,
        text_data=f'<html><{tag} src="/_Incapsula_Resource?test=1"></{tag}></html>',
    )
    client = DtekApiClient(session)
    client._csrf_token = "previous_token"
    with pytest.raises(DtekRateLimitError, match="Incapsula security page"):
        await client.async_ensure_csrf_token(force_refresh=True)

    with pytest.raises(DtekRateLimitError, match="another"):
        await DtekApiClient(session).async_ensure_csrf_token()
    assert client._csrf_token is None
    assert session.get.call_count == 1
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_normal_portal_with_incapsula_resource_still_works(mock_html_with_csrf: str) -> None:
    """An Incapsula script alone is not proof of a challenge."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get.return_value = MockResponse(
        status=200,
        text_data=mock_html_with_csrf + '<script src="/_Incapsula_Resource?test=1"></script>',
    )
    assert await DtekApiClient(session).async_ensure_csrf_token() == "test_dtek_csrf_token_1234567890"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "text", "error"),
    [
        (403, "", DtekRateLimitError),
        (429, "", DtekRateLimitError),
        (200, '<script src="/_Incapsula_Resource?test=1"></script>', DtekRateLimitError),
        (200, "<html>No token</html>", DtekCsrfError),
    ],
)
async def test_address_resolution_does_not_repeat_failed_portal_request(
    status: int, text: str, error: type[Exception]
) -> None:
    """A failed streets lookup must not trigger another GET for house lookup."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.get.return_value = MockResponse(status=status, text_data=text)

    with pytest.raises(error):
        await DtekApiClient(session).async_get_home_numbers(city="Example", street="Test")
    assert session.get.call_count == 1
    session.post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "text"),
    [
        (403, ""),
        (429, ""),
        (200, '<script src="/_Incapsula_Resource?test=1"></script>'),
    ],
)
async def test_schedule_block_is_an_error_not_an_empty_schedule(status: int, text: str) -> None:
    """Stop at the first blocked legacy method and preserve update failure."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = MockResponse(status=status, text_data=text)
    client = DtekApiClient(session)
    client._csrf_token = "cached_token"

    with pytest.raises(DtekRateLimitError, match="15 minutes"):
        await client.async_get_schedule(group="GPV1.2")
    with pytest.raises(DtekRateLimitError, match="another"):
        await client.async_get_schedule(group="GPV1.2")
    assert session.post.call_count == 1
    session.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_home_numbers_success(mock_home_num_response: dict[str, Any]) -> None:
    """Test successful address and house number lookup."""
    session = MagicMock(spec=aiohttp.ClientSession)
    client = DtekApiClient(session=session)
    client._csrf_token = "cached_token"

    session.post = MagicMock(return_value=MockResponse(status=200, json_data=mock_home_num_response))

    result = await client.async_get_home_numbers(
        city="м. Дніпро",
        street="вул. Центральна",
    )

    assert result.result is True
    assert result.show_cur_outage_param is True
    assert result.show_cur_schedule is True
    assert result.show_table_plan is False
    assert "1" in result.houses
    assert result.houses["1"].group == "GPV1.2"
    assert result.houses["1"].sub_type_reason == ["GPV1.2"]
    assert "2" in result.houses
    assert result.houses["2"].group == "GPV1.1"


@pytest.mark.asyncio
async def test_get_home_numbers_not_found() -> None:
    """Test when no houses are found and result is false."""
    session = MagicMock(spec=aiohttp.ClientSession)
    client = DtekApiClient(session=session)
    client._csrf_token = "cached_token"

    empty_response = {"result": False}
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=empty_response))

    with pytest.raises(DtekAddressNotFoundError):
        await client.async_get_home_numbers(city="Nonexistent", street="Fake")


def test_resolve_settlement_and_street() -> None:
    """Test resolving plain address inputs against streets map."""
    from custom_components.dtek.api.client import resolve_settlement_and_street

    streets_map = {
        "с-ще Прикладне": ["вул. Миру", "вул. Шевченка"],
        "м. Дніпро": ["вул. Центральна", "просп. Поля"],
        "с. Степове": ["пров. Сонячний"],
    }

    # Plain city and street without prefixes
    resolved = resolve_settlement_and_street("Прикладне", "Миру", streets_map)
    assert resolved == ("с-ще Прикладне", "вул. Миру")

    # City with prefix and street without
    resolved = resolve_settlement_and_street("м. Дніпро", "Центральна", streets_map)
    assert resolved == ("м. Дніпро", "вул. Центральна")

    # Both with prefixes
    resolved = resolve_settlement_and_street("с. Степове", "пров. Сонячний", streets_map)
    assert resolved == ("с. Степове", "пров. Сонячний")

    # Non-existent
    resolved = resolve_settlement_and_street("Невідоме", "Невідома", streets_map)
    assert resolved is None


@pytest.mark.asyncio
async def test_cabinet_authenticate_success() -> None:
    """Test successful login to DTEK cabinet."""
    session = MagicMock(spec=aiohttp.ClientSession)
    mock_resp_data = {
        "status": "success",
        "data": {
            "user": {
                "id": "123",
                "phone": "+380501112233",
                "name": "Тестовий Користувач",
                "token": "secret_cabinet_jwt_token",
            },
            "accounts": [
                {
                    "account": "12345678",
                    "eic": "62Z1234567890123",
                    "address": "м. Дніпро, вул. Центральна, 1",
                }
            ],
        },
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=mock_resp_data))

    client = DtekApiClient(session=session)
    user = await client.async_cabinet_authenticate("+380501112233", "password123")

    assert user.token == "secret_cabinet_jwt_token"
    assert user.phone == "+380501112233"
    assert user.primary_account == "12345678"
    assert user.primary_eic == "62Z1234567890123"


@pytest.mark.asyncio
async def test_cabinet_authenticate_invalid_credentials() -> None:
    """Test cabinet authentication failure."""
    session = MagicMock(spec=aiohttp.ClientSession)
    mock_resp_data = {
        "status": "error",
        "message": "Invalid credentials",
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=mock_resp_data))

    client = DtekApiClient(session=session)
    with pytest.raises(DtekAuthError):
        await client.async_cabinet_authenticate("+380501112233", "wrong_pass")


@pytest.mark.asyncio
async def test_cabinet_balance_success() -> None:
    """Test fetching balance from cabinet."""
    session = MagicMock(spec=aiohttp.ClientSession)
    mock_resp_data = {
        "status": "success",
        "data": {
            "balance": 150.75,
        },
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=mock_resp_data))

    client = DtekApiClient(session=session)
    balance = await client.async_get_cabinet_balance("secret_token", "12345678")

    assert balance == 150.75


@pytest.mark.asyncio
async def test_cabinet_authenticate_real_response_shape() -> None:
    """Login response puts user/accounts at the root and splits the name."""
    session = MagicMock(spec=aiohttp.ClientSession)
    mock_resp_data = {
        "status": "success",
        "accounts": [{"account": "100000000000", "name": None, "address": None}],
        "user": {
            "token": "secret_cabinet_jwt_token",
            "name": "Тест",
            "surname": "Тестенко",
            "middle_n": "Тестович",
            "phone": "+380501112233",
        },
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=mock_resp_data))

    client = DtekApiClient(session=session)
    user = await client.async_cabinet_authenticate("+380501112233", "pwd")

    assert user.token == "secret_cabinet_jwt_token"
    assert user.primary_account == "100000000000"
    assert user.primary_eic is None
    assert user.customer_name == "Тестенко Тест Тестович"


@pytest.mark.asyncio
async def test_cabinet_objects_info_returns_mapping() -> None:
    """objects/info returns a customer/place mapping rather than a list."""
    session = MagicMock(spec=aiohttp.ClientSession)
    payload = {
        "customer": {"account": "100000000000", "eic": "62Z1234567890123"},
        "place": {"address": "с-ще Тестове, вул. Тестова буд. 1 Б"},
        "status": "success",
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=payload))

    client = DtekApiClient(session=session)
    info = await client.async_get_cabinet_objects_info("token", "100000000000")

    assert info["customer"]["eic"] == "62Z1234567890123"


@pytest.mark.asyncio
async def test_cabinet_balance_from_debet_and_credit() -> None:
    """Balance is derived from credit minus debet when no balance field exists."""
    session = MagicMock(spec=aiohttp.ClientSession)
    payload = {"data": {"debet": "120.50", "credit": "20.00"}, "status": "success"}
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=payload))

    client = DtekApiClient(session=session)
    assert await client.async_get_cabinet_balance("token", "123") == -100.5


@pytest.mark.asyncio
async def test_cabinet_balance_none_when_empty() -> None:
    """A cabinet account without billing figures yields no balance."""
    session = MagicMock(spec=aiohttp.ClientSession)
    payload = {"data": {"debet": None, "credit": None}, "items": [], "status": "success"}
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=payload))

    client = DtekApiClient(session=session)
    assert await client.async_get_cabinet_balance("token", "123") is None


@pytest.mark.asyncio
async def test_cabinet_group_normalises_cyrillic() -> None:
    """The cabinet reports the queue in Cyrillic; it is normalised to Latin."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = MagicMock(return_value=MockResponse(status=200, json_data={"status": "success", "gpv": "ГПВ1.2"}))

    client = DtekApiClient(session=session)
    group = await client.async_get_cabinet_group("token", "62Z123", "123")

    assert group == "GPV1.2"


@pytest.mark.asyncio
async def test_cabinet_meters_extracted_from_choice_account(caplog: pytest.LogCaptureFixture) -> None:
    """Meter details come from the account selection endpoint."""
    caplog.set_level(logging.DEBUG, logger="custom_components.dtek.api.client")
    session = MagicMock(spec=aiohttp.ClientSession)
    responses = [
        MockResponse(status=200, json_data={"status": "success"}),
        MockResponse(
            status=200,
            json_data={
                "meters": [
                    {
                        "type": "private_meter_type",
                        "construction": "private_construction",
                        "serialNumber": "private_serial_value",
                        "private_serial_registry_key": "private_value",
                    },
                ]
            },
        ),
    ]
    session.post = MagicMock(side_effect=responses)

    client = DtekApiClient(session=session)
    meters = await client.async_get_cabinet_meters("token", "123")

    assert meters[0]["serialNumber"] == "private_serial_value"
    assert "DTEK legacy meter response shape" in caplog.text
    assert "serialNumber" in caplog.text
    assert "private_serial_registry_key" not in caplog.text
    assert "private_serial_value" not in caplog.text
    assert "private_meter_type" not in caplog.text
    assert "private_construction" not in caplog.text


def test_response_shape_describes_json_strings_without_private_values() -> None:
    shape = _response_shape(
        {
            "data": '{"meters":[{"serialNumber":"private_serial_value","type":"private_meter_type"}]}',
            "message": "private_error_message",
        }
    )
    serialized = str(shape)

    assert shape["keys"]["data"]["content"]["keys"]["meters"]["length"] == 1
    assert "serialNumber" in serialized
    assert all(
        value not in serialized for value in ("private_serial_value", "private_meter_type", "private_error_message")
    )


def test_response_shape_bounds_nested_json_strings() -> None:
    value = "[" * 50 + "0" + "]" * 50
    shape = _response_shape(value)

    assert isinstance(shape, dict)
    assert shape["type"] == "json-string"
    assert len(str(shape)) < 500


def test_response_shape_handles_json_recursion_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_deep_json(value: str) -> None:
        raise RecursionError

    monkeypatch.setattr("custom_components.dtek.api.client.json.loads", reject_deep_json)
    assert _response_shape("[0]") == "string"


@pytest.mark.asyncio
async def test_cabinet_profile_aggregates_all_sources() -> None:
    """The profile combines customer info, meters, balance and queue group."""
    session = MagicMock(spec=aiohttp.ClientSession)
    client = DtekApiClient(session=session)
    client.async_get_cabinet_objects_info = AsyncMock(
        return_value={
            "customer": {
                "account": "100000000000",
                "name": "Тестенко Т.Т.",
                "address": "с-ще Тестове, вул. Тестова буд. 1 Б",
                "objectType": "Житловий будинок",
                "demPerm": "40.2000000",
                "contractDate": "24.10.2024",
                "eic": "62Z1234567890123",
            },
            "place": {"address": "с-ще Тестове, вул. Тестова буд. 1 Б"},
        }
    )
    client.async_get_cabinet_meters = AsyncMock(
        return_value=[{"type": "GAMA", "construction": "G3M 144.230", "serialNumber": "_04860803"}]
    )
    client.async_get_cabinet_balance = AsyncMock(return_value=-12.5)
    client.async_get_cabinet_group = AsyncMock(return_value="GPV1.2")

    profile = await client.async_get_cabinet_profile("token", "100000000000")

    assert profile.customer_name == "Тестенко Т.Т."
    assert profile.eic == "62Z1234567890123"
    assert profile.meter_serial == "04860803"
    assert profile.meter_type == "GAMA G3M 144.230"
    assert profile.contract_capacity == "40.2 kW"
    assert profile.object_type == "Житловий будинок"
    assert profile.city == "с-ще Тестове"
    assert profile.street == "вул. Тестова"
    assert profile.house_number == "1Б"
    assert profile.balance == -12.5
    assert profile.group == "GPV1.2"


def test_parse_cabinet_address_variants() -> None:
    """Addresses with and without an explicit house marker are split correctly."""
    assert parse_cabinet_address("с-ще Тестове, вул. Тестова буд. 1 Б") == (
        "с-ще Тестове",
        "вул. Тестова",
        "1Б",
    )
    assert parse_cabinet_address("м. Дніпро, вул. Центральна 12") == (
        "м. Дніпро",
        "вул. Центральна",
        "12",
    )
    assert parse_cabinet_address("") == (None, None, None)


@pytest.mark.asyncio
async def test_post_ajax_starts_cooldown_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 starts a cooldown instead of retrying after a few seconds."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("custom_components.dtek.api.client.asyncio.sleep", fake_sleep)

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    responses = [
        MockResponse(status=429),
        MockResponse(status=429),
        MockResponse(status=200, json_data={"data": "ok"}),
    ]
    session.post = MagicMock(side_effect=responses)

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    with pytest.raises(DtekRateLimitError, match="15 minutes"):
        await client._async_post_ajax({"method": "getSchedule"})

    assert session.post.call_count == 1
    assert delays == []


@pytest.mark.asyncio
async def test_post_ajax_does_not_retry_rate_limit_during_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated calls after a 429 do not send further AJAX requests."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("custom_components.dtek.api.client.asyncio.sleep", fake_sleep)

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.post = MagicMock(return_value=MockResponse(status=429))

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    with pytest.raises(DtekRateLimitError, match="15 minutes"):
        await client._async_post_ajax({"method": "getSchedule"})

    with pytest.raises(DtekRateLimitError, match="another"):
        await client._async_post_ajax({"method": "getSchedule"})

    assert session.post.call_count == 1
    session.get.assert_not_called()
    assert delays == []


@pytest.mark.asyncio
async def test_post_ajax_retries_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures are retried with backoff before succeeding."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("custom_components.dtek.api.client.asyncio.sleep", fake_sleep)

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.post = MagicMock(
        side_effect=[
            aiohttp.ClientConnectionError("connection reset"),
            MockResponse(status=200, json_data={"data": "ok"}),
        ]
    )

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    result = await client._async_post_ajax({"method": "getSchedule"})

    assert result == {"data": "ok"}
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_post_ajax_raises_connection_error_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persistent network failures give up and raise DtekConnectionError."""

    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("custom_components.dtek.api.client.asyncio.sleep", fake_sleep)

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.post = MagicMock(side_effect=aiohttp.ClientConnectionError("network down"))

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    with pytest.raises(DtekConnectionError, match="Connection failed"):
        await client._async_post_ajax({"method": "getSchedule"})

    assert session.post.call_count == MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_post_ajax_retries_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 5xx is retried with backoff before succeeding."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("custom_components.dtek.api.client.asyncio.sleep", fake_sleep)

    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.post = MagicMock(
        side_effect=[
            MockResponse(status=503),
            MockResponse(status=200, json_data={"data": "ok"}),
        ]
    )

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    result = await client._async_post_ajax({"method": "getSchedule"})

    assert result == {"data": "ok"}
    assert len(delays) == 1


def _house(**kwargs: Any) -> DtekHouseInfo:
    """Build a DtekHouseInfo with getHomeNum defaults."""
    defaults: dict[str, Any] = {
        "house_num": "7",
        "group": "GPV1.2",
        "sub_type": "",
        "start_date": "",
        "end_date": "",
        "outage_type": "",
    }
    defaults.update(kwargs)
    return DtekHouseInfo(**defaults)


def test_parse_house_outage_planned_works() -> None:
    """type=1 maps to a planned maintenance window."""
    event = parse_house_outage(_house(outage_type="1", start_date="10:00 24.09.2026", end_date="17:00 24.09.2026"))

    assert event is not None
    assert event.outage_type == "planned"
    assert event.start == datetime(2026, 9, 24, 10, 0, tzinfo=DTEK_TIMEZONE)
    assert event.end == datetime(2026, 9, 24, 17, 0, tzinfo=DTEK_TIMEZONE)
    assert event.description == "Планові ремонтні роботи"
    assert event.group == "GPV1.2"


def test_parse_house_outage_emergency_uses_sub_type_text() -> None:
    """type=2 keeps the portal's free-text reason."""
    event = parse_house_outage(
        _house(
            outage_type="2",
            sub_type="Аварійні ремонтні роботи",
            start_date="07:56 02.07.2025",
            end_date="15:25 01.10.2026",
        )
    )

    assert event is not None
    assert event.outage_type == "emergency"
    assert event.description == "Аварійні ремонтні роботи"


def test_parse_house_outage_without_window_returns_none() -> None:
    """An unaffected address carries empty date fields."""
    assert parse_house_outage(_house()) is None


def test_parse_house_outage_ignores_malformed_dates() -> None:
    """A malformed timestamp must not raise."""
    assert parse_house_outage(_house(outage_type="1", start_date="not-a-date", end_date="17:00 24.09.2026")) is None


def test_parse_house_outage_rejects_end_before_start() -> None:
    """An inverted window is not a usable event."""
    assert (
        parse_house_outage(_house(outage_type="1", start_date="17:00 24.09.2026", end_date="10:00 24.09.2026")) is None
    )


def test_parse_house_outage_ignores_unknown_type() -> None:
    """An undocumented type code must not be reported as a real outage."""
    assert (
        parse_house_outage(_house(outage_type="7", start_date="10:00 24.09.2026", end_date="17:00 24.09.2026")) is None
    )


def test_parse_house_outage_ignores_missing_type() -> None:
    """A window with no type must not be fabricated into an emergency."""
    assert (
        parse_house_outage(_house(outage_type="", start_date="10:00 24.09.2026", end_date="17:00 24.09.2026")) is None
    )


def test_parse_house_outage_is_timezone_aware_in_source_zone() -> None:
    """Wall-clock portal times are anchored to Ukraine, not to the host."""
    event = parse_house_outage(_house(outage_type="1", start_date="10:00 24.09.2026", end_date="17:00 24.09.2026"))

    assert event is not None
    assert event.start.tzinfo is not None
    # 24 September is summer time in Kyiv: UTC+3.
    assert event.start.utcoffset() == timedelta(hours=3)
    assert event.start.astimezone(UTC) == datetime(2026, 9, 24, 7, 0, tzinfo=UTC)


def test_parse_house_outage_handles_winter_time() -> None:
    """A January window uses UTC+2, so DST is applied rather than a fixed offset."""
    event = parse_house_outage(_house(outage_type="1", start_date="10:00 15.01.2026", end_date="17:00 15.01.2026"))

    assert event is not None
    assert event.start.utcoffset() == timedelta(hours=2)


def test_ensure_dtek_timezone_leaves_aware_values_untouched() -> None:
    """An already-aware timestamp must not be re-anchored."""
    aware = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)

    assert ensure_dtek_timezone(aware) is aware
    assert ensure_dtek_timezone(datetime(2026, 9, 24, 10, 0)).tzinfo is DTEK_TIMEZONE


@pytest.mark.asyncio
async def test_get_schedule_returns_empty_on_unknown_method() -> None:
    """Retired AJAX methods answer 'Unknown method!' and yield no events."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    session.post = MagicMock(
        return_value=MockResponse(status=200, json_data={"result": False, "error": ["Unknown method!"]})
    )

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    assert await client.async_get_schedule(group="GPV1.2") == []


@pytest.mark.asyncio
async def test_get_schedule_parses_payload_when_served() -> None:
    """A region that still serves a schedule payload is parsed, not discarded."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    payload = {
        "result": True,
        "data": [
            {
                "type": "1",
                "sub_type": "",
                "start_date": "10:00 24.09.2026",
                "end_date": "17:00 24.09.2026",
            }
        ],
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=payload))

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    events = await client.async_get_schedule(group="GPV1.2")

    # The same window is reported by all four methods, so it must be deduped.
    assert len(events) == 1
    assert events[0].outage_type == "planned"
    assert events[0].start == datetime(2026, 9, 24, 10, 0, tzinfo=DTEK_TIMEZONE)


@pytest.mark.asyncio
async def test_get_schedule_skips_entries_with_unknown_type() -> None:
    """Schedule entries carrying an undocumented type code are dropped."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.cookie_jar = []
    payload = {
        "result": True,
        "data": [
            {
                "type": "9",
                "sub_type": "",
                "start_date": "10:00 24.09.2026",
                "end_date": "17:00 24.09.2026",
            }
        ],
    }
    session.post = MagicMock(return_value=MockResponse(status=200, json_data=payload))

    client = DtekApiClient(session=session)
    client._csrf_token = "token"

    assert await client.async_get_schedule(group="GPV1.2") == []


def test_normalize_house_number_folds_separators_and_lookalikes() -> None:
    """The portal writes 1/Б where the cabinet returns 1Б."""
    assert normalize_house_number("1/Б") == normalize_house_number("1Б")
    assert normalize_house_number(" 1 / б ") == normalize_house_number("1Б")
    # Latin B typed instead of Cyrillic Б.
    assert normalize_house_number("1/B") == normalize_house_number("1Б")
    assert normalize_house_number("12-A") == normalize_house_number("12А")


def test_find_house_info_matches_across_formats() -> None:
    """A cabinet-derived house number resolves against portal keys."""
    houses = {
        "1": _house(house_num="1"),
        "1/А": _house(house_num="1/А"),
        "1/Б": _house(house_num="1/Б", outage_type="1"),
    }

    # Regression: the cabinet stores "1Б" while the portal key is "1/Б", so
    # exact matching silently dropped the house and every outage with it.
    matched = find_house_info(houses, "1Б")
    assert matched is not None
    assert matched.house_num == "1/Б"

    # An exact key still wins and must not be confused with its neighbours.
    assert find_house_info(houses, "1/А").house_num == "1/А"
    assert find_house_info(houses, "1").house_num == "1"


def test_find_house_info_returns_none_when_absent() -> None:
    """A house that genuinely is not listed yields None rather than a guess."""
    houses = {"1": _house(house_num="1")}
    assert find_house_info(houses, "99") is None
    assert find_house_info(houses, "") is None
    assert find_house_info(houses, None) is None
