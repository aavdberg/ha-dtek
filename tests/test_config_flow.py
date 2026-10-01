"""Unit tests for DTEK config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.dtek.config_flow import DtekConfigFlow


def _make_cabinet_flow(user: object, profile: object) -> DtekConfigFlow:
    """Build a config flow whose cabinet client returns the given responses."""
    flow = DtekConfigFlow()
    flow.hass = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}

    client = MagicMock()
    client.async_cabinet_authenticate = AsyncMock(return_value=user)
    client.async_get_cabinet_profile = AsyncMock(return_value=profile)
    flow._test_client = client

    patcher = patch("custom_components.dtek.config_flow.DtekApiClient", return_value=client)
    patcher.start()
    flow._test_patcher = patcher
    return flow


@pytest.fixture(autouse=True)
def _stop_patches() -> object:
    """Ensure client patches do not leak between tests."""
    yield
    patch.stopall()


def test_config_flow_instantiation() -> None:
    """Test config flow can be imported and initialized."""
    flow = DtekConfigFlow()
    assert flow.VERSION == 1
    assert flow._dso == "dtek-dnem"


@pytest.mark.asyncio
async def test_cabinet_step_aborts_without_account() -> None:
    """A login that returns no account must not create a placeholder entry."""
    from custom_components.dtek.api.models import DtekCabinetUser

    flow = _make_cabinet_flow(
        user=DtekCabinetUser(token="t", phone="+380501112233", primary_account=None),
        profile=None,
    )

    result = await flow.async_step_cabinet({"phone": "+380501112233", "password": "pwd"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "no_account"


@pytest.mark.asyncio
async def test_cabinet_step_aborts_without_group() -> None:
    """An unresolved queue must not silently fall back to an arbitrary group."""
    from custom_components.dtek.api.models import DtekCabinetProfile, DtekCabinetUser

    flow = _make_cabinet_flow(
        user=DtekCabinetUser(token="t", phone="+380501112233", primary_account="12345678"),
        profile=DtekCabinetProfile(account="12345678", group=None),
    )

    result = await flow.async_step_cabinet({"phone": "+380501112233", "password": "pwd"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "no_group"


@pytest.mark.asyncio
async def test_cabinet_step_uses_dso_specific_site() -> None:
    """Choosing a non-Dnipro DSO must not send Dnipro-scoped cabinet requests."""
    from custom_components.dtek.api.models import DtekCabinetProfile, DtekCabinetUser

    flow = _make_cabinet_flow(
        user=DtekCabinetUser(token="t", phone="+380501112233", primary_account="12345678"),
        profile=DtekCabinetProfile(account="12345678", group="GPV1.2", eic="62Z1"),
    )
    flow._dso = "dtek-oem"

    await flow.async_step_cabinet({"phone": "+380501112233", "password": "pwd"})

    client = flow._test_client
    assert client.async_cabinet_authenticate.await_args.kwargs["site"] == "oem"
    assert client.async_get_cabinet_profile.await_args.kwargs["site"] == "oem"


def test_cabinet_site_and_base_url_mapping() -> None:
    """Every supported DSO maps to its own cabinet site and host."""
    from custom_components.dtek.const import (
        SUPPORTED_DSOS,
        cabinet_base_url_for_dso,
        cabinet_site_for_dso,
    )

    assert cabinet_site_for_dso("dtek-dnem") == "dnem"
    assert cabinet_site_for_dso("dtek-kem") == "kem"
    assert cabinet_site_for_dso("dtek-krem") == "krem"
    assert cabinet_site_for_dso("dtek-oem") == "oem"
    # Unknown DSOs fall back to the default rather than raising.
    assert cabinet_site_for_dso("nope") == "dnem"

    sites = {cabinet_site_for_dso(dso) for dso in SUPPORTED_DSOS}
    assert len(sites) == len(SUPPORTED_DSOS)
    assert cabinet_base_url_for_dso("dtek-oem") == "https://ok.dtek-oem.com.ua"
