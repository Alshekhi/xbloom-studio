"""Tests for config_flow.py -- XBloomConfigFlow.

Covers HA-01: config flow creates entry with correct data.
All Playwright calls are patched -- no real browser launched.

homeassistant is not installed in the dev environment; we inject minimal mock
modules into sys.modules before any custom_components import so that
config_flow.py can be imported and exercised in isolation.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# OBSOLETE — pre-BLE architecture. tests the removed cloud-auth config flow (CONF_ACCESS_TOKEN); current flow is BLE discovery.
# Skipped at module level until rewritten against the BLE-only component.
pytest.skip(
    "obsolete: tests the removed cloud-auth config flow (CONF_ACCESS_TOKEN); current flow is BLE discovery",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# Inject minimal homeassistant + xbloom stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by the component tree."""

    def _mod(name):
        """Create and register an empty module."""
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    # ------------------------------------------------------------------
    # homeassistant.config_entries
    # ------------------------------------------------------------------
    ce = _mod("homeassistant.config_entries")

    class _ConfigEntry:
        def __init__(self):
            self.data = {}
            self.entry_id = "stub"
            self.runtime_data = None

    ce.ConfigEntry = _ConfigEntry
    ce.SOURCE_REAUTH = "reauth"

    class _ConfigFlow:
        """Minimal ConfigFlow base."""

        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__(**kw)
            cls._domain = domain

        def __init__(self):
            self.hass = None
            self.source = None
            self.unique_id = None

        def async_show_form(self, *, step_id, data_schema=None, errors=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_show_progress(self, *, progress_action, progress_task):
            return {"type": "progress", "progress_action": progress_action}

        def async_show_progress_done(self, *, next_step_id):
            return {"type": "progress_done", "step_id": next_step_id}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

        def async_update_reload_and_abort(self, entry, *, data):
            return {"type": "abort", "reason": "reauth_successful"}

        def _abort_if_unique_id_configured(self):
            pass

        async def async_set_unique_id(self, uid):
            self.unique_id = uid

        def _get_reauth_entry(self):
            return None

    ce.ConfigFlow = _ConfigFlow
    ce.FlowResult = dict

    # ------------------------------------------------------------------
    # homeassistant root, core, exceptions
    # ------------------------------------------------------------------
    ha = _mod("homeassistant")
    ha.config_entries = ce

    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock

    exc_mod = _mod("homeassistant.exceptions")
    exc_mod.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    # ------------------------------------------------------------------
    # homeassistant.helpers.*
    # ------------------------------------------------------------------
    helpers = _mod("homeassistant.helpers")

    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    uc = _mod("homeassistant.helpers.update_coordinator")
    uc.UpdateFailed = Exception

    # ------------------------------------------------------------------
    # homeassistant.components.*
    # ------------------------------------------------------------------
    components = _mod("homeassistant.components")
    button_comp = _mod("homeassistant.components.button")
    select_comp = _mod("homeassistant.components.select")


_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom.config_flow import XBloomConfigFlow  # noqa: E402
from custom_components.xbloom.const import (  # noqa: E402
    CONF_ACCESS_TOKEN,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_REFRESH_TOKEN,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

FAKE_TOKENS = {
    CONF_ACCESS_TOKEN: "tok_abc123",
    CONF_REFRESH_TOKEN: "ref_def456",
}
FAKE_MQTT = {CONF_MQTT_HOST: "192.168.1.100", CONF_MQTT_PORT: 1883}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_step_user_returns_form_with_no_input() -> None:
    """async_step_user with no input must return a form."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


async def test_step_user_routes_to_manual() -> None:
    """Choosing manual auth must route to async_step_manual."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input={"auth_method": "manual"})
    assert result["step_id"] == "manual"


async def test_manual_step_stores_tokens_and_routes_to_mqtt() -> None:
    """Manual step with valid tokens must proceed to mqtt step."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_manual(user_input=FAKE_TOKENS)
    assert result["step_id"] == "mqtt"
    # _tokens may also contain device_id/product_id after async_step_device runs
    assert flow._tokens[CONF_ACCESS_TOKEN] == FAKE_TOKENS[CONF_ACCESS_TOKEN]
    assert flow._tokens[CONF_REFRESH_TOKEN] == FAKE_TOKENS[CONF_REFRESH_TOKEN]


async def test_manual_step_rejects_empty_access_token() -> None:
    """Manual step must return errors if access_token is empty."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_manual(
        user_input={CONF_ACCESS_TOKEN: "", CONF_REFRESH_TOKEN: "ref_x"}
    )
    assert result["type"] == "form"
    assert CONF_ACCESS_TOKEN in result["errors"]


async def test_mqtt_step_creates_entry_with_all_keys() -> None:
    """async_step_mqtt must call async_create_entry with all 4 data keys."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    flow._tokens = FAKE_TOKENS

    async def _fake_set_unique_id(uid):
        flow.unique_id = uid

    flow.async_set_unique_id = _fake_set_unique_id
    flow._abort_if_unique_id_configured = MagicMock()

    created = {}

    def _fake_create_entry(title, data):
        created["title"] = title
        created["data"] = data
        return {"type": "create_entry", "title": title, "data": data}

    flow.async_create_entry = _fake_create_entry

    await flow.async_step_mqtt(user_input=FAKE_MQTT)
    assert created["data"][CONF_ACCESS_TOKEN] == "tok_abc123"
    assert created["data"][CONF_REFRESH_TOKEN] == "ref_def456"
    assert created["data"][CONF_MQTT_HOST] == "192.168.1.100"
    assert created["data"][CONF_MQTT_PORT] == 1883


async def test_playwright_failure_redirects_to_manual() -> None:
    """If playwright task raises, flow must show manual form with playwright_failed error."""
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    # Simulate a completed-but-failed task
    task = MagicMock()
    task.done.return_value = True
    task.exception.return_value = RuntimeError("Chromium failed")
    flow._playwright_task = task
    result = await flow.async_step_playwright()
    assert result["type"] == "form"
    assert result["step_id"] == "manual"
    assert result["errors"].get("base") == "playwright_failed"


@pytest.mark.asyncio
async def test_device_step_stores_ids() -> None:
    """D-04: config flow stores device_id + product_id after calling get_devices()."""
    from unittest.mock import AsyncMock, patch
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    # Set up _tokens as if manual login succeeded
    flow._tokens = {
        CONF_ACCESS_TOKEN: "tok_abc",
        CONF_REFRESH_TOKEN: "ref_abc",
    }
    with patch(
        "custom_components.xbloom.vendor.xbloom.client.XBloomClient.get_devices",
        new=AsyncMock(return_value=[{"device_id": "dev_001", "product_id": "prod_001"}]),
    ):
        # Call the device step directly — it does not yet exist (RED state)
        result = await flow.async_step_device(user_input=None)
    # After device step, _tokens must contain device_id and product_id
    assert flow._tokens.get("device_id") == "dev_001"
    assert flow._tokens.get("product_id") == "prod_001"


@pytest.mark.asyncio
async def test_device_step_handles_empty_devices() -> None:
    """D-04: empty device list is non-fatal; flow continues to MQTT step."""
    from unittest.mock import AsyncMock, patch
    flow = XBloomConfigFlow()
    flow.hass = MagicMock()
    flow._tokens = {
        CONF_ACCESS_TOKEN: "tok_abc",
        CONF_REFRESH_TOKEN: "ref_abc",
    }
    with patch(
        "custom_components.xbloom.vendor.xbloom.client.XBloomClient.get_devices",
        new=AsyncMock(return_value=[]),
    ):
        # Call the device step directly — it does not yet exist (RED state)
        result = await flow.async_step_device(user_input=None)
    # Flow should continue to MQTT step form (not error out)
    assert result.get("type") == "form"
    assert result.get("step_id") == "mqtt"
