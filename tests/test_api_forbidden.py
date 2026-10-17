"""Tests for DTEK portal access denial handling."""

from __future__ import annotations

import pytest

from custom_components.dtek.api.client import DtekApiClient
from custom_components.dtek.api.exceptions import DtekConnectionError


class ForbiddenResponse:
    """Minimal async response stub for an HTTP 403."""

    status = 403

    async def __aenter__(self) -> ForbiddenResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class ForbiddenSession:
    """Minimal session stub that returns an HTTP 403 response."""

    def get(self, *_: object, **__: object) -> ForbiddenResponse:
        return ForbiddenResponse()


@pytest.mark.asyncio
async def test_ensure_csrf_token_forbidden_mentions_possible_waf() -> None:
    client = DtekApiClient(ForbiddenSession())  # type: ignore[arg-type]

    with pytest.raises(DtekConnectionError, match="portal or its WAF may be blocking"):
        await client.async_ensure_csrf_token()
