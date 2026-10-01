"""Unit tests for DtekApiClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.dtek.api.client import DtekApiClient, parse_cabinet_address
from custom_components.dtek.api.exceptions import (
    DtekAddressNotFoundError,
    DtekAuthError,
    DtekConnectionError,
    DtekCsrfError,
    DtekRateLimitError,
)


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
async def test_cabinet_meters_extracted_from_choice_account() -> None:
    """Meter details come from the account selection endpoint."""
    session = MagicMock(spec=aiohttp.ClientSession)
    responses = [
        MockResponse(status=200, json_data={"status": "success"}),
        MockResponse(
            status=200,
            json_data={
                "meters": [
                    {
                        "type": "GAMA",
                        "construction": "G3M 144.230",
                        "serialNumber": "_04860803",
                    }
                ]
            },
        ),
    ]
    session.post = MagicMock(side_effect=responses)

    client = DtekApiClient(session=session)
    meters = await client.async_get_cabinet_meters("token", "123")

    assert meters[0]["serialNumber"] == "_04860803"


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
