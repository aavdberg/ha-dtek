"""Unit tests for DTEK config flow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.dtek.api import DtekApiClient, DtekAuthError, DtekConnectionError, DtekError
from custom_components.dtek.api.models import (
    DtekAddressLookupResult,
    DtekCabinetProfile,
    DtekCabinetUser,
    DtekHouseInfo,
)
from custom_components.dtek.api.new_portal import DtekNewPortalClient
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


@pytest.fixture
def new_account_flow(monkeypatch: pytest.MonkeyPatch) -> tuple[DtekConfigFlow, MagicMock]:
    flow = DtekConfigFlow()
    flow.hass = MagicMock()
    flow._new_accounts = ["12345"]
    flow._new_data = {"dso": "dtek-dnem", "phone": "0000000000", "password": "test_password", "cabinet_portal": "new"}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
    client = MagicMock()
    client.async_cabinet_authenticate = AsyncMock(
        return_value=DtekCabinetUser(token="test_token", phone="0000000000", accounts=["12345"])
    )
    client.async_get_cabinet_profile = AsyncMock(
        return_value=DtekCabinetProfile(
            account="12345",
            group="GPV1.2",
            eic="test_eic",
            city="test_city",
            street="test_street",
            house_number="1",
        )
    )
    client.async_get_home_numbers = AsyncMock()
    client.async_close = AsyncMock()
    monkeypatch.setattr("custom_components.dtek.config_flow.DtekNewPortalClient", MagicMock(return_value=client))
    return flow, client


@pytest.mark.asyncio
async def test_new_account_form_does_not_require_group(new_account_flow: tuple[DtekConfigFlow, MagicMock]) -> None:
    flow, client = new_account_flow
    result = await flow.async_step_new_account()
    assert result["data_schema"]({"account": "12345"}) == {"account": "12345"}
    client.async_cabinet_authenticate.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_account_detects_and_persists_profile(new_account_flow: tuple[DtekConfigFlow, MagicMock]) -> None:
    flow, client = new_account_flow
    result = await flow.async_step_new_account({"account": "12345"})
    assert result["type"] == "create_entry"
    assert result["data"] == {
        **flow._new_data,
        "account": "12345",
        "group": "GPV1.2",
        "eic": "test_eic",
        "city": "test_city",
        "street": "test_street",
        "house_number": "1",
    }
    client.async_get_cabinet_profile.assert_awaited_once_with(token="test_token", account="12345")
    client.async_get_home_numbers.assert_not_awaited()
    client.async_close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("manual_group", [None, " gpv2.1 "])
async def test_new_account_requires_confirmed_group_when_unresolved(
    new_account_flow: tuple[DtekConfigFlow, MagicMock],
    manual_group: str | None,
) -> None:
    flow, client = new_account_flow
    client.async_get_cabinet_profile.return_value = DtekCabinetProfile(account="12345")
    user_input = {"account": "12345"}
    if manual_group is not None:
        user_input["group"] = manual_group
    result = await flow.async_step_new_account(user_input)
    if manual_group is None:
        assert result["errors"] == {"base": "no_group"}
    else:
        assert result["type"] == "create_entry"
        assert result["data"]["group"] == "GPV2.1"
    client.async_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_account_uses_address_group(new_account_flow: tuple[DtekConfigFlow, MagicMock]) -> None:
    flow, client = new_account_flow
    client.async_get_cabinet_profile.return_value = DtekCabinetProfile(
        account="12345",
        city="test_city",
        street="test_street",
        house_number="1",
    )
    client.async_get_home_numbers.return_value = DtekAddressLookupResult(
        result=True,
        houses={"1": DtekHouseInfo(house_num="1", group="GPV3.1")},
    )
    result = await flow.async_step_new_account({"account": "12345"})
    assert result["data"]["group"] == "GPV3.1"
    client.async_get_home_numbers.assert_awaited_once_with(city="test_city", street="test_street")


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_after_login", [False, True])
async def test_new_account_rejects_unknown_account(
    new_account_flow: tuple[DtekConfigFlow, MagicMock],
    changed_after_login: bool,
) -> None:
    flow, client = new_account_flow
    if changed_after_login:
        client.async_cabinet_authenticate.return_value = DtekCabinetUser(token="test_token", phone="0000000000")
    result = await flow.async_step_new_account({"account": "12345" if changed_after_login else "67890"})
    assert result["errors"] == {"base": "no_account"}
    client.async_get_cabinet_profile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DtekAuthError("expired"), "invalid_auth"),
        (DtekConnectionError("offline"), "cannot_connect"),
        (DtekError("invalid response"), "unknown"),
    ],
)
async def test_new_account_surfaces_errors_and_closes_session(
    new_account_flow: tuple[DtekConfigFlow, MagicMock],
    error: DtekError,
    expected: str,
) -> None:
    flow, client = new_account_flow
    client.async_get_cabinet_profile.side_effect = error
    result = await flow.async_step_new_account({"account": "12345"})
    assert result["errors"] == {"base": expected}
    client.async_close.assert_awaited_once()


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


@pytest.fixture
def reauth_flow(monkeypatch: pytest.MonkeyPatch) -> tuple[DtekConfigFlow, MagicMock, dict[str, MagicMock]]:
    """Use real client classes with mocked network methods for both portals."""
    clients = {}
    for portal, client_class in (("legacy", DtekApiClient), ("new", DtekNewPortalClient)):
        client = MagicMock()
        client.async_cabinet_authenticate = AsyncMock(
            return_value=DtekCabinetUser(token="test_token", phone="0000000000", accounts=["12345"])
        )
        client.async_get_cabinet_profile = AsyncMock(return_value=DtekCabinetProfile(account="12345"))
        monkeypatch.setattr(client_class, "async_cabinet_authenticate", client.async_cabinet_authenticate)
        monkeypatch.setattr(client_class, "async_get_cabinet_profile", client.async_get_cabinet_profile)
        clients[portal] = client
    clients["new"].async_close = AsyncMock()
    monkeypatch.setattr(DtekNewPortalClient, "async_close", clients["new"].async_close)

    entry = MagicMock()
    entry.data = {
        "dso": "dtek-oem",
        "phone": "0000000000",
        "password": "old_test_password",
        "account": "12345",
        "group": "GPV1.2",
        "eic": "test_eic",
        "city": "test_city",
        "street": "test_street",
        "house_number": "test_house",
    }
    entry.options = {"update_interval": 30}
    flow = DtekConfigFlow()
    flow.hass = MagicMock()
    flow._get_reauth_entry = MagicMock(return_value=entry)
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort", "reason": "reauth_successful"})
    return flow, entry, clients


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dso", "site", "portal_source"),
    [
        ("dtek-dnem", "dnem", None),
        ("dtek-kem", "kem", None),
        ("dtek-krem", "krem", None),
        ("dtek-oem", "oem", None),
        ("dtek-dnem", "dnem", "data"),
        ("dtek-dnem", "dnem", "options"),
    ],
)
async def test_reauth_updates_only_credentials_for_existing_dso(
    reauth_flow: tuple[DtekConfigFlow, MagicMock, dict[str, MagicMock]],
    dso: str,
    site: str,
    portal_source: str | None,
) -> None:
    flow, entry, clients = reauth_flow
    entry.data["dso"] = dso
    if portal_source == "data":
        entry.data["cabinet_portal"] = "new"
    elif portal_source == "options":
        entry.data["cabinet_portal"] = "legacy"
        entry.options["cabinet_portal"] = "new"
    original_data = entry.data.copy()
    original_options = entry.options.copy()
    result = await flow.async_step_reauth(entry.data)
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {}
    for client in clients.values():
        client.async_cabinet_authenticate.assert_not_awaited()
    assert set(result["data_schema"].schema) == {"phone", "password"}

    result = await flow.async_step_reauth_confirm({"phone": " 1111111111 ", "password": " new_test_password "})
    assert result == {"type": "abort", "reason": "reauth_successful"}
    portal = "new" if portal_source else "legacy"
    clients[portal].async_cabinet_authenticate.assert_awaited_once_with(
        phone="1111111111", password=" new_test_password ", site=site
    )
    clients[portal].async_get_cabinet_profile.assert_awaited_once_with(token="test_token", account="12345", site=site)
    clients["legacy" if portal == "new" else "new"].async_cabinet_authenticate.assert_not_awaited()
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, data_updates={"phone": "1111111111", "password": " new_test_password "}
    )
    assert entry.data == original_data
    assert entry.options == original_options
    assert clients["new"].async_close.await_count == (1 if portal == "new" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("portal", ["legacy", "new"])
@pytest.mark.parametrize("operation", ["async_cabinet_authenticate", "async_get_cabinet_profile"])
@pytest.mark.parametrize(
    ("exception", "error"),
    [(DtekAuthError, "invalid_auth"), (DtekConnectionError, "cannot_connect"), (DtekError, "unknown")],
)
async def test_reauth_failures_preserve_configuration(
    reauth_flow: tuple[DtekConfigFlow, MagicMock, dict[str, MagicMock]],
    portal: str,
    operation: str,
    exception: type[DtekError],
    error: str,
) -> None:
    flow, entry, clients = reauth_flow
    entry.data["dso"] = "dtek-dnem"
    entry.options["cabinet_portal"] = portal
    original_data, original_options = entry.data.copy(), entry.options.copy()
    getattr(clients[portal], operation).side_effect = exception("test failure")

    result = await flow.async_step_reauth_confirm({"phone": "1111111111", "password": "new_test_password"})

    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": error}
    flow.async_update_reload_and_abort.assert_not_called()
    assert entry.data == original_data
    assert entry.options == original_options
    assert clients["new"].async_close.await_count == (1 if portal == "new" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("portal", ["legacy", "new"])
async def test_reauth_rejects_different_account(
    reauth_flow: tuple[DtekConfigFlow, MagicMock, dict[str, MagicMock]], portal: str
) -> None:
    flow, entry, clients = reauth_flow
    entry.data["dso"] = "dtek-dnem"
    entry.options["cabinet_portal"] = portal
    original_data, original_options = entry.data.copy(), entry.options.copy()
    clients[portal].async_cabinet_authenticate.return_value = DtekCabinetUser(
        token="test_token", phone="1111111111", accounts=["67890"]
    )

    result = await flow.async_step_reauth_confirm({"phone": "1111111111", "password": "new_test_password"})

    assert result["errors"] == {"base": "no_account"}
    clients[portal].async_get_cabinet_profile.assert_not_awaited()
    flow.async_update_reload_and_abort.assert_not_called()
    assert entry.data == original_data
    assert entry.options == original_options
    assert clients["new"].async_close.await_count == (1 if portal == "new" else 0)


@pytest.mark.parametrize("language", ["strings", "en", "nl", "uk"])
def test_reauth_translations(language: str) -> None:
    root = Path(__file__).resolve().parents[1] / "custom_components" / "dtek"
    path = root / "strings.json" if language == "strings" else root / "translations" / f"{language}.json"
    config = json.loads(path.read_text(encoding="utf-8"))["config"]
    form = config["step"]["reauth_confirm"]
    assert form["title"]
    assert form["description"]
    assert set(form["data"]) == {"phone", "password"}
    assert all(form["data"].values())
    assert config["abort"]["reauth_successful"]
    for error in ("invalid_auth", "cannot_connect", "unknown", "no_account"):
        assert config["error"][error]
