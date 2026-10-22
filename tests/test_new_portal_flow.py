"""New portal opt-in, identity preservation, reauth and lifecycle tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.dtek import async_setup_entry, async_unload_entry
from custom_components.dtek.api.exceptions import DtekAuthError, DtekRateLimitError
from custom_components.dtek.api.models import DtekCabinetProfile, DtekCabinetUser
from custom_components.dtek.api.new_portal import DtekNewPortalClient
from custom_components.dtek.config_flow import DtekConfigFlow, DtekOptionsFlow
from custom_components.dtek.coordinator import DtekDataUpdateCoordinator


@pytest.mark.parametrize("language", ["strings", "en", "nl", "uk"])
def test_options_errors_use_home_assistant_translation_structure(language: str) -> None:
    root = Path(__file__).resolve().parents[1] / "custom_components" / "dtek"
    path = root / "strings.json" if language == "strings" else root / "translations" / f"{language}.json"
    options = json.loads(path.read_text(encoding="utf-8"))["options"]
    assert "error" not in options["step"]["init"]
    assert set(options["error"]) == {
        "new_portal_unsupported",
        "no_account",
        "invalid_auth",
        "cannot_connect",
        "unknown",
    }


@pytest.fixture
def new_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    methods = {
        "async_cabinet_authenticate": AsyncMock(
            return_value=DtekCabinetUser(token="new_portal_session", phone="0000000000", accounts=["12345", "67890"])
        ),
        "async_get_cabinet_profile": AsyncMock(
            return_value=DtekCabinetProfile(account="12345", meter_serial="test_meter", eic="test_eic")
        ),
        "async_close": AsyncMock(),
    }
    for name, method in methods.items():
        monkeypatch.setattr(DtekNewPortalClient, name, method)
    return methods


def entry() -> MagicMock:
    result = MagicMock()
    result.entry_id = "test_entry"
    result.data = {
        "dso": "dtek-dnem",
        "phone": "0000000000",
        "password": "test_password",
        "account": "12345",
        "group": "GPV1.2",
    }
    result.options = {}
    return result


@pytest.mark.asyncio
async def test_new_setup_requires_explicit_account_and_queue(new_client: dict[str, AsyncMock]) -> None:
    flow = DtekConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user({"dso": "dtek-dnem", "setup_mode": "new_cabinet"})
    assert result["step_id"] == "new_cabinet"
    result = await flow.async_step_new_cabinet({"phone": "0000000000", "password": " test_password "})
    assert result["step_id"] == "new_account"
    new_client["async_close"].assert_awaited_once()
    assert new_client["async_cabinet_authenticate"].call_args.kwargs["password"] == " test_password "
    result = await flow.async_step_new_account({"account": "12345", "group": ""})
    assert result["errors"]["base"] == "no_group"
    result = await flow.async_step_new_account({"account": "99999", "group": "GPV1.2"})
    assert result["errors"]["base"] == "no_account"
    result = await flow.async_step_new_account({"account": "12345", "group": "gpv1.2"})
    assert result["type"] == "create_entry"
    assert result["data"]["cabinet_portal"] == "new"
    assert result["data"]["group"] == "GPV1.2"
    assert flow._unique_id == "dtek-dnem_cabinet_12345"
    assert "token" not in result["data"]


@pytest.mark.asyncio
async def test_non_dnipro_new_portal_is_rejected(new_client: dict[str, AsyncMock]) -> None:
    flow = DtekConfigFlow()
    result = await flow.async_step_user({"dso": "dtek-oem", "setup_mode": "new_cabinet"})
    assert result["errors"]["base"] == "new_portal_unsupported"
    new_client["async_cabinet_authenticate"].assert_not_awaited()


@pytest.mark.asyncio
async def test_options_migration_validates_existing_account_without_changing_identity(
    new_client: dict[str, AsyncMock],
) -> None:
    existing = entry()
    flow = DtekOptionsFlow(existing)
    flow.hass = MagicMock()
    result = await flow.async_step_init(
        {"cabinet_portal": "new", "update_interval": 60, "password": "new_test_password"}
    )
    assert result == {"type": "create_entry", "title": "", "data": {"cabinet_portal": "new", "update_interval": 60}}
    assert existing.entry_id == "test_entry"
    assert existing.data["account"] == "12345"
    assert new_client["async_cabinet_authenticate"].call_args.kwargs["password"] == "new_test_password"
    assert new_client["async_get_cabinet_profile"].call_args.kwargs["account"] == "12345"
    new_client["async_close"].assert_awaited_once()
    update = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert update["password"] == "new_test_password"
    assert update["group"] == "GPV1.2"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["auth", "account"])
async def test_failed_options_validation_does_not_switch_portal(new_client: dict[str, AsyncMock], failure: str) -> None:
    if failure == "auth":
        new_client["async_cabinet_authenticate"].side_effect = DtekAuthError("test rejection")
    else:
        new_client["async_cabinet_authenticate"].return_value = DtekCabinetUser(
            token="test", phone="0000000000", accounts=["67890"]
        )
    flow = DtekOptionsFlow(entry())
    flow.hass = MagicMock()
    result = await flow.async_step_init({"cabinet_portal": "new", "update_interval": 60})
    assert result["type"] == "form"
    assert result["errors"]["base"] == ("invalid_auth" if failure == "auth" else "no_account")
    flow.hass.config_entries.async_update_entry.assert_not_called()
    new_client["async_close"].assert_awaited_once()


@pytest.mark.asyncio
async def test_reauth_keeps_account_and_entry_identity(new_client: dict[str, AsyncMock]) -> None:
    existing = entry()
    existing.options = {"cabinet_portal": "new"}
    flow = DtekConfigFlow()
    flow.hass = MagicMock()
    flow._reauth_entry = existing
    assert (await flow.async_step_reauth(existing.data))["step_id"] == "reauth_confirm"
    result = await flow.async_step_reauth_confirm({"phone": "0000000000", "password": "new_test_password"})
    assert result["reason"] == "reauth_successful"
    assert existing.data["account"] == "12345"
    assert existing.entry_id == "test_entry"
    assert existing.data["password"] == "new_test_password"
    new_client["async_close"].assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_uses_selected_new_client_during_public_cooldown(
    new_client: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = entry()
    existing.options = {"cabinet_portal": "new"}
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    monkeypatch.setattr(
        DtekNewPortalClient, "raise_if_portal_cooling_down", MagicMock(side_effect=DtekRateLimitError("paused"))
    )

    async def refresh(coordinator):
        coordinator.data = await coordinator._async_update_data()

    monkeypatch.setattr(DtekDataUpdateCoordinator, "async_config_entry_first_refresh", refresh)
    assert await async_setup_entry(hass, existing)
    assert isinstance(existing.runtime_data.client, DtekNewPortalClient)
    assert existing.runtime_data.coordinator.data.meter_serial == "test_meter"
    assert existing.runtime_data.coordinator.data.outage_data_available is False
    new_client["async_close"].assert_not_awaited()
    stop_callback = hass.bus.async_listen_once.call_args.args[1]
    await stop_callback(MagicMock())
    new_client["async_close"].assert_awaited_once()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    assert await async_unload_entry(hass, existing)
    assert new_client["async_close"].await_count == 2


@pytest.mark.asyncio
async def test_failed_setup_closes_private_session(new_client: dict[str, AsyncMock]) -> None:
    existing = entry()
    existing.options = {"cabinet_portal": "new"}
    new_client["async_cabinet_authenticate"].side_effect = DtekAuthError("test rejection")
    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(MagicMock(), existing)
    new_client["async_close"].assert_awaited_once()


@pytest.mark.asyncio
async def test_interval_change_does_not_repeat_new_portal_login(new_client: dict[str, AsyncMock]) -> None:
    existing = entry()
    existing.options = {"cabinet_portal": "new"}
    flow = DtekOptionsFlow(existing)
    flow.hass = MagicMock()
    result = await flow.async_step_init({"cabinet_portal": "new", "update_interval": 60})
    assert result["type"] == "create_entry"
    new_client["async_cabinet_authenticate"].assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_first_refresh_closes_private_session(
    new_client: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = entry()
    existing.options = {"cabinet_portal": "new"}
    monkeypatch.setattr(
        DtekDataUpdateCoordinator,
        "async_config_entry_first_refresh",
        AsyncMock(side_effect=ConfigEntryNotReady("test failure")),
    )
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(MagicMock(), existing)
    new_client["async_close"].assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_runtime_session_requests_reauthentication() -> None:
    client = MagicMock()
    client.async_get_cabinet_profile = AsyncMock(side_effect=DtekAuthError("expired"))
    coordinator = DtekDataUpdateCoordinator(
        MagicMock(), client, "GPV1.2", cabinet_token="test", cabinet_account="12345"
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
