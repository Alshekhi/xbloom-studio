"""Tests for XBloomConfigFlow — BLE discovery setup and cloud reauth.

This replaces an obsolete file of the same name that tested the pre-BLE
cloud-auth flow and had been skipped at module level since the BLE rewrite.
The reauth half is genuinely new: PR #2 re-added cloud login, so an auth flow
that had no coverage at all now has some.

Two properties matter most. Setup must derive a *stable* unique_id from the
advertiser name, because that is what stops a rediscovered machine from being
added twice. And reauth must not persist a password the user declined to
remember — the whole point of the remember flag.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom import config_flow as cf
from custom_components.xbloom.config_flow import (
    XBloomConfigFlow,
    _serial_suffix,
)
from custom_components.xbloom.const import (
    CONF_BLE_NAME,
    CONF_CLOUD,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_MEMBER_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REMEMBER,
    CONF_CLOUD_TOKEN,
    CONF_PRODUCT_ID,
)
from xbloom.exceptions import XBloomAPIError

BLE_NAME = "XBLOOM ABC123"


def _make_flow(*, discovered: list[str] | None = None, entries: list | None = None):
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.language = "en"
    flow.context = {}
    flow._async_current_entries = MagicMock(return_value=entries or [])
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    infos = []
    for name in discovered or []:
        info = MagicMock()
        info.name = name
        infos.append(info)
    flow._discovered_infos = infos
    return flow


def _discovery(name: str):
    info = MagicMock()
    info.name = name
    return info


# --------------------------------------------------------------------------- #
# Serial suffix — the basis of the unique_id                                  #
# --------------------------------------------------------------------------- #
def test_suffix_is_extracted_from_the_advertiser_name() -> None:
    assert _serial_suffix("XBLOOM ABC123") == "ABC123"


def test_suffix_is_empty_for_a_foreign_advertiser() -> None:
    assert _serial_suffix("Kettle 9000") == ""


def test_suffix_is_empty_for_a_bare_prefix() -> None:
    """'XBLOOM ' with nothing after it can't identify a machine."""
    assert _serial_suffix("XBLOOM ") == ""


def test_suffix_is_empty_for_an_empty_name() -> None:
    assert _serial_suffix("") == ""


# --------------------------------------------------------------------------- #
# Bluetooth discovery                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_discovery_of_a_foreign_device_is_rejected() -> None:
    flow = _make_flow()
    result = await flow.async_step_bluetooth(_discovery("Some Other Kettle"))
    assert result["type"] == "abort"
    assert result["reason"] == "not_supported"


@pytest.mark.asyncio
async def test_discovery_sets_a_stable_unique_id() -> None:
    """Same machine, same id — this is what prevents a duplicate entry."""
    flow = _make_flow()
    await flow.async_step_bluetooth(_discovery(BLE_NAME))
    flow.async_set_unique_id.assert_awaited_once_with("xbloom-ABC123")


@pytest.mark.asyncio
async def test_discovery_aborts_if_already_configured() -> None:
    flow = _make_flow()
    await flow.async_step_bluetooth(_discovery(BLE_NAME))
    flow._abort_if_unique_id_configured.assert_called_once()


@pytest.mark.asyncio
async def test_discovery_shows_a_confirm_form_named_for_the_machine() -> None:
    flow = _make_flow()
    result = await flow.async_step_bluetooth(_discovery(BLE_NAME))
    assert result["step_id"] == "confirm"
    assert flow.context["title_placeholders"] == {"name": BLE_NAME}


@pytest.mark.asyncio
async def test_confirming_a_discovery_creates_the_entry() -> None:
    flow = _make_flow()
    await flow.async_step_bluetooth(_discovery(BLE_NAME))
    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_BLE_NAME] == BLE_NAME
    assert result["data"][CONF_PRODUCT_ID] == "ABC123"


# --------------------------------------------------------------------------- #
# Manual setup                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_manual_setup_rejects_an_empty_name() -> None:
    flow = _make_flow()
    with patch.object(cf, "async_discovered_service_info", MagicMock(return_value=[])):
        result = await flow.async_step_user({CONF_BLE_NAME: "   "})
    assert result["errors"][CONF_BLE_NAME] == "ble_name_required"


@pytest.mark.asyncio
async def test_manual_setup_rejects_a_name_without_the_prefix() -> None:
    flow = _make_flow()
    with patch.object(cf, "async_discovered_service_info", MagicMock(return_value=[])):
        result = await flow.async_step_user({CONF_BLE_NAME: "MYBLOOM ABC123"})
    assert result["errors"][CONF_BLE_NAME] == "ble_name_invalid"


@pytest.mark.asyncio
async def test_manual_setup_rejects_a_prefix_with_no_suffix() -> None:
    flow = _make_flow()
    with patch.object(cf, "async_discovered_service_info", MagicMock(return_value=[])):
        result = await flow.async_step_user({CONF_BLE_NAME: "XBLOOM "})
    assert result["errors"][CONF_BLE_NAME] == "ble_name_invalid"


@pytest.mark.asyncio
async def test_manual_setup_accepts_a_valid_name() -> None:
    flow = _make_flow()
    with patch.object(cf, "async_discovered_service_info", MagicMock(return_value=[])):
        result = await flow.async_step_user({CONF_BLE_NAME: BLE_NAME})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PRODUCT_ID] == "ABC123"


@pytest.mark.asyncio
async def test_already_configured_machines_are_hidden_from_the_picker() -> None:
    """Offering a machine you've already added is a dead end."""
    existing = MagicMock()
    existing.unique_id = "xbloom-ABC123"
    flow = _make_flow(entries=[existing])
    with patch.object(
        cf, "async_discovered_service_info",
        MagicMock(return_value=[_discovery(BLE_NAME), _discovery("XBLOOM ZZZ999")]),
    ):
        result = await flow.async_step_user()
    assert result["description_placeholders"]["discovered_count"] == "1"


@pytest.mark.asyncio
async def test_discovery_failure_falls_back_to_manual_entry() -> None:
    """The bluetooth integration may not be loaded — that must not crash setup."""
    flow = _make_flow()
    with patch.object(
        cf, "async_discovered_service_info",
        MagicMock(side_effect=RuntimeError("bluetooth not loaded")),
    ):
        result = await flow.async_step_user()
    assert result["step_id"] == "user"
    assert result["description_placeholders"]["discovered_count"] == "0"


@pytest.mark.asyncio
async def test_non_xbloom_advertisers_are_not_offered() -> None:
    flow = _make_flow()
    with patch.object(
        cf, "async_discovered_service_info",
        MagicMock(return_value=[_discovery("Smart Bulb"), _discovery(BLE_NAME)]),
    ):
        result = await flow.async_step_user()
    assert result["description_placeholders"]["discovered_count"] == "1"


# --------------------------------------------------------------------------- #
# Cloud reauth (re-added by PR #2)                                            #
# --------------------------------------------------------------------------- #
def _reauth_flow(*, remember_stored: bool = True):
    flow = _make_flow()
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {
        CONF_BLE_NAME: BLE_NAME,
        CONF_CLOUD: {
            CONF_CLOUD_EMAIL: "user@example.invalid",
            CONF_CLOUD_MEMBER_ID: 1,
            CONF_CLOUD_TOKEN: "old",
            CONF_CLOUD_REMEMBER: remember_stored,
        },
    }
    flow.context = {"entry_id": "e1"}
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    flow.hass.config_entries.async_update_entry = MagicMock()
    flow.hass.config_entries.async_reload = AsyncMock()
    return flow, entry


def _patch_login(result=None, error: Exception | None = None):
    """Patch the cloud client reauth_confirm imports at their source module."""
    import xbloom.cloud as cloud_mod

    client = MagicMock()
    client.login = AsyncMock(
        return_value=result or {"memberId": 7, "token": "fresh"},
        side_effect=error,
    )
    return patch.object(cloud_mod, "XBloomCloudClient", MagicMock(return_value=client))


@pytest.mark.asyncio
async def test_reauth_prompts_with_the_stored_email() -> None:
    flow, _ = _reauth_flow()
    result = await flow.async_step_reauth({})
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["email"] == "user@example.invalid"


@pytest.mark.asyncio
async def test_reauth_requires_a_password() -> None:
    flow, _ = _reauth_flow()
    result = await flow.async_step_reauth_confirm({"password": ""})
    assert result["errors"]["base"] == "credentials_required"


@pytest.mark.asyncio
async def test_reauth_surfaces_a_rejected_login() -> None:
    flow, _ = _reauth_flow()
    with _patch_login(error=XBloomAPIError("bad credentials")):
        result = await flow.async_step_reauth_confirm({"password": "wrong"})
    assert result["errors"]["base"] == "cloud_login_failed"


@pytest.mark.asyncio
async def test_reauth_does_not_touch_the_entry_on_failure() -> None:
    """A failed retry must leave the existing (stale) creds untouched."""
    flow, _ = _reauth_flow()
    with _patch_login(error=XBloomAPIError("bad credentials")):
        await flow.async_step_reauth_confirm({"password": "wrong"})
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_successful_reauth_stores_the_fresh_token() -> None:
    flow, _ = _reauth_flow()
    with _patch_login():
        result = await flow.async_step_reauth_confirm(
            {"password": "right", "remember": True}
        )
    assert result["reason"] == "reauth_successful"
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_CLOUD][CONF_CLOUD_TOKEN] == "fresh"
    assert saved[CONF_CLOUD][CONF_CLOUD_MEMBER_ID] == 7


@pytest.mark.asyncio
async def test_successful_reauth_stores_the_password_when_remembered() -> None:
    flow, _ = _reauth_flow()
    with _patch_login():
        await flow.async_step_reauth_confirm({"password": "right", "remember": True})
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_CLOUD][CONF_CLOUD_PASSWORD] == "right"


@pytest.mark.asyncio
async def test_reauth_does_not_store_the_password_when_declined() -> None:
    """Declining 'remember me' must not leave the password on disk."""
    flow, _ = _reauth_flow()
    with _patch_login():
        await flow.async_step_reauth_confirm({"password": "right", "remember": False})
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert CONF_CLOUD_PASSWORD not in saved[CONF_CLOUD]


@pytest.mark.asyncio
async def test_reauth_preserves_the_ble_configuration() -> None:
    """Re-logging in to the cloud must not lose which machine this entry is."""
    flow, _ = _reauth_flow()
    with _patch_login():
        await flow.async_step_reauth_confirm({"password": "right", "remember": True})
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_BLE_NAME] == BLE_NAME


@pytest.mark.asyncio
async def test_successful_reauth_reloads_the_entry() -> None:
    """Without a reload the coordinator keeps using the dead token."""
    flow, _ = _reauth_flow()
    with _patch_login():
        await flow.async_step_reauth_confirm({"password": "right", "remember": True})
    flow.hass.config_entries.async_reload.assert_awaited_once_with("e1")
