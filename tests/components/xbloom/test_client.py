"""Tests for XBloomClient — Phase 7 extensions.

Covers new methods added in Phase 7:
- get_recipe_command(recipe, device_id, product_id) -> desired string (CTL-01)
- get_devices() -> list of devices (D-04)
- send_command(device_id, product_id, desired) includes product_id in POST body

All HTTP calls are patched — no real network traffic.

homeassistant is not installed in this dev environment; we inject minimal mock
modules into sys.modules before any custom_components import.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs (needed when custom_components is imported).
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by the vendor client import path."""

    def _mod(name):
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    _mod("homeassistant")
    _mod("homeassistant.components")

    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = MagicMock

    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock

    exc_mod = _mod("homeassistant.exceptions")
    exc_mod.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    _mod("homeassistant.helpers")
    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    dev_reg = _mod("homeassistant.helpers.device_registry")
    dev_reg.DeviceInfo = MagicMock

    uc = _mod("homeassistant.helpers.update_coordinator")
    uc.UpdateFailed = Exception


_inject_stubs()

# Now safe to import — vendor client does not depend on homeassistant, but
# importing via custom_components.xbloom.vendor triggers the package __init__.
from custom_components.xbloom.vendor.xbloom.client import XBloomClient  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="obsolete: cloud-auth client removed in BLE-only rewrite — XBloomClient now takes only a session; tGetRecipeMadeCmd/devices endpoints are gone")
@pytest.mark.asyncio
async def test_get_recipe_command() -> None:
    """CTL-01: get_recipe_command posts to tGetRecipeMadeCmd.thtml and returns desired string."""
    recipe = {
        "name": "Ethiopia Yirgacheffe",
        "dose_g": 18.0,
        "water_ratio": 250.0,
        "grinder_size": 3.0,
        "grinder_size_enabled": 1,
        "pours": [],
    }
    async with aiohttp.ClientSession() as session:
        client = XBloomClient("tok_abc", "ref_abc", session=session)
        with patch.object(client, "_raw_post", new=AsyncMock(return_value={"desired": "AABBCCDDEEFF0011"})):
            result = await client.get_recipe_command(recipe, "device_001", "product_001")
    assert result == "AABBCCDDEEFF0011"


@pytest.mark.skip(reason="obsolete: cloud-auth client removed in BLE-only rewrite — XBloomClient now takes only a session; tGetRecipeMadeCmd/devices endpoints are gone")
@pytest.mark.asyncio
async def test_get_devices() -> None:
    """D-04: get_devices() GETs /api/enduser/devices/ and returns a list."""
    fake_devices = [{"device_id": "dev_001", "product_id": "prod_001"}]
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"list": fake_devices})
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    async with aiohttp.ClientSession() as session:
        client = XBloomClient("tok_abc", "ref_abc", session=session)
        with patch.object(client._session, "get", return_value=mock_resp):
            devices = await client.get_devices()
    assert isinstance(devices, list)
    assert devices[0]["device_id"] == "dev_001"


@pytest.mark.skip(reason="obsolete: cloud-auth client removed in BLE-only rewrite — XBloomClient now takes only a session; tGetRecipeMadeCmd/devices endpoints are gone")
@pytest.mark.asyncio
async def test_send_command_includes_product_id() -> None:
    """Pitfall 1: send_command must include product_id in POST body."""
    captured = {}

    async def fake_auth_post(url, body):
        captured["body"] = body
        return {}

    async with aiohttp.ClientSession() as session:
        client = XBloomClient("tok_abc", "ref_abc", session=session)
        with patch.object(client, "_authenticated_post", new=fake_auth_post):
            await client.send_command("dev_001", "prod_001", {"state": {"desired": {"bruw_curve": "FFFF11"}}})
    assert captured["body"].get("product_id") == "prod_001"
