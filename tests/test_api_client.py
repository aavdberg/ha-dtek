"""Unit tests for DtekApiClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.dtek.api.client import DtekApiClient
from custom_components.dtek.api.exceptions import (
    DtekAddressNotFoundError,
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
