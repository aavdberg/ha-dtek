"""Unit tests for DTEK diagnostics redaction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dtek.api.models import DtekState
from custom_components.dtek.diagnostics import REDACTED, async_get_config_entry_diagnostics
from custom_components.dtek.models import DtekRuntimeData


@pytest.mark.asyncio
async def test_diagnostics_redacts_house_number() -> None:
    """Test that house number is redacted from diagnostics."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.version = 1
    entry.domain = "dtek"
    entry.title = "DTEK Test"
    entry.data = {
        "dso": "dtek-dnem",
        "city": "м. Дніпро",
        "street": "вул. Центральна",
        "house_number": "1",
        "group": "GPV1.2",
    }
    entry.options = {}

    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2")

    entry.runtime_data = DtekRuntimeData(
        client=MagicMock(),
        coordinator=coordinator,
        dso="dtek-dnem",
        group="GPV1.2",
        city="м. Дніпро",
        street="вул. Центральна",
        house_number="1",
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # House number must be redacted in entry data
    assert diagnostics["entry"]["data"]["house_number"] == REDACTED
    assert diagnostics["entry"]["data"]["city"] == "м. Дніпро"
    assert diagnostics["coordinator"]["group"] == "GPV1.2"


@pytest.mark.asyncio
async def test_diagnostics_redacts_cabinet_credentials() -> None:
    """Credentials and account identifiers never appear in a diagnostics download."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.version = 1
    entry.domain = "dtek"
    entry.title = "DTEK Account"
    entry.data = {
        "dso": "dtek-dnem",
        "phone": "+380501112233",
        "password": "super-secret",
        "account": "12345678",
        "eic": "62Z1234567890123",
        "city": "м. Дніпро",
        "street": "вул. Центральна",
        "house_number": "1",
        "group": "GPV1.2",
    }
    entry.options = {}

    coordinator = MagicMock()
    coordinator.data = DtekState(group="GPV1.2")
    entry.runtime_data = DtekRuntimeData(
        client=MagicMock(),
        coordinator=coordinator,
        dso="dtek-dnem",
        group="GPV1.2",
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    data = diagnostics["entry"]["data"]

    for key in ("password", "phone", "account", "eic", "house_number"):
        assert data[key] == REDACTED, f"{key} leaked into diagnostics"

    assert "super-secret" not in str(diagnostics)
    assert "+380501112233" not in str(diagnostics)
    # Non-sensitive context is preserved.
    assert data["city"] == "м. Дніпро"
    assert data["group"] == "GPV1.2"
