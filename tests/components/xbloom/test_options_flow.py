"""Tests for XBloomOptionsFlow — create / edit / delete / write-to-slot.

Plan 09-05. Covers:
  - Create flow (recipe-level + pours step)
  - Edit flow (pick + pre-filled pours + replace path)
  - Delete flow (pick + confirm)
  - Write-to-slot sub-step (skip + service call)
  - Round-trip _build_recipe → validate_recipe (D-31 bypass int contract)

homeassistant is not installed in the dev environment; we inject minimal
sys.modules stubs (matching test_config_flow.py / test_storage_id_methods.py)
before importing config_flow.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# ---------------------------------------------------------------------------

def _inject_stubs() -> None:
    def _mod(name: str):
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    ha = _mod("homeassistant")  # noqa: F841

    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock

    exc = _mod("homeassistant.exceptions")
    exc.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    # config_entries: ConfigFlow + OptionsFlow + ConfigEntry
    ce = _mod("homeassistant.config_entries")

    class _ConfigEntry:
        def __init__(self):
            self.data = {}
            self.entry_id = "stub"
            self.runtime_data = None
            self.options = {}

    ce.ConfigEntry = _ConfigEntry
    ce.SOURCE_REAUTH = "reauth"

    class _FlowBase:
        def __init__(self):
            self.hass = None

        def async_show_form(self, *, step_id, data_schema=None, errors=None,
                            description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

        def async_show_menu(self, *, step_id, menu_options):
            return {"type": "menu", "step_id": step_id, "menu_options": menu_options}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

        def _abort_if_unique_id_configured(self):
            pass

        async def async_set_unique_id(self, uid):
            self.unique_id = uid

    class _ConfigFlow(_FlowBase):
        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__(**kw)
            cls._domain = domain

    class _OptionsFlow(_FlowBase):
        pass

    ce.ConfigFlow = _ConfigFlow
    ce.OptionsFlow = _OptionsFlow
    ce.FlowResult = dict

    def _callback(fn):
        return fn

    ce.callback = _callback

    # data_entry_flow
    def_mod = _mod("homeassistant.data_entry_flow")
    def_mod.FlowResult = dict

    # bluetooth
    bt = _mod("homeassistant.components.bluetooth")

    class _BluetoothServiceInfoBleak:
        pass

    bt.BluetoothServiceInfoBleak = _BluetoothServiceInfoBleak
    bt.async_discovered_service_info = MagicMock(return_value=[])

    # helpers
    helpers = _mod("homeassistant.helpers")  # noqa: F841

    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    uc = _mod("homeassistant.helpers.update_coordinator")
    uc.UpdateFailed = Exception

    storage_mod = _mod("homeassistant.helpers.storage")

    class _StubStore:
        def __init__(self, hass, version, key):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

        async def async_remove(self):
            return None

    storage_mod.Store = _StubStore

    # selector — passthrough stubs
    selector_mod = _mod("homeassistant.helpers.selector")

    class _PassthroughSelector:
        def __init__(self, *a, **kw):
            self.args = a
            self.kwargs = kw

        def __call__(self, value):
            return value

    selector_mod.NumberSelector = _PassthroughSelector
    selector_mod.NumberSelectorConfig = _PassthroughSelector
    selector_mod.SelectSelector = _PassthroughSelector
    selector_mod.SelectSelectorConfig = _PassthroughSelector
    selector_mod.BooleanSelector = _PassthroughSelector

    # components.button + select (touched by other modules but harmless here)
    _mod("homeassistant.components")
    button_comp = _mod("homeassistant.components.button")
    select_comp = _mod("homeassistant.components.select")


_inject_stubs()


from custom_components.xbloom.config_flow import XBloomOptionsFlow  # noqa: E402
from custom_components.xbloom.vendor.xbloom.recipe_validate import (  # noqa: E402
    validate_recipe,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeStore:
    def __init__(self, recipes=None):
        self._recipes = list(recipes or [])

    async def async_load(self):
        return list(self._recipes)


class FakeCoordinator:
    """Stand-in for XBloomCoordinator.

    PR #2's options flow pulls the recipe list from `coordinator.data` after an
    explicit `async_refresh()`, instead of reading the store directly, so that
    cloud-side edits made on the phone show up without waiting for the poll.
    The fake mirrors that contract: `async_refresh` really does repopulate
    `data` from the store, so a flow that forgets to refresh sees `data` as it
    was — not a mock that silently answers anything.
    """

    def __init__(self, recipes=None):
        self.store = FakeStore(recipes)
        self.data: list[dict] = []
        self.refresh_count = 0
        self.async_add_recipe = AsyncMock()
        self.async_replace_recipe = AsyncMock()
        self.async_delete_recipe = AsyncMock(return_value=True)

    async def async_refresh(self) -> None:
        self.refresh_count += 1
        self.data = await self.store.async_load()

    async def async_request_refresh(self) -> None:
        await self.async_refresh()


class FakeRuntimeData:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class FakeEntry:
    def __init__(self, coordinator):
        self.runtime_data = FakeRuntimeData(coordinator)
        self.entry_id = "test_entry"
        self.options = {}


class FakeHass:
    def __init__(self):
        self.services = MagicMock()
        self.services.async_call = AsyncMock()


def _make_flow(recipes=None):
    coord = FakeCoordinator(recipes)
    entry = FakeEntry(coord)
    flow = XBloomOptionsFlow(entry)
    flow.config_entry = entry
    flow.hass = FakeHass()
    return flow, coord


_VALID_RECIPE_INPUT = {
    "name": "Test",
    "dose_g": 18.0,
    "ratio": "1:16",
    "grind_size": 40,
    "grinder_speed_rpm": 90,
    "pour_count": 3,
    "cup_type": "Omni dripper",
    "enable_bypass_water": False,
}


def _stored_recipe():
    return {
        "id": "local-test-1",
        "name": "Stored Recipe",
        "dose_g": 18.0,
        "ratio": "1:16",
        "water_ratio": 288.0,
        "grind_size": 40,
        "grinder_size": 40,
        "grinder_speed_rpm": 90,
        "rpm": 90,
        "pour_count": 3,
        "cup_type": 2,
        "cup_type_name": "Omni",
        "bypass_water_enabled": 2,
        "pours": [
            {
                "id": i,
                "recipe_id": 0,
                "name": "",
                "volume_ml": 96.0,
                "temperature_c": 92.0 - i,
                "pattern": 3,
                "flow_rate": 3.0,
                "pause_s": 0,
                "agitate_before": 2,
                "agitate_after": 2,
            }
            for i in range(3)
        ],
    }


def _pours_input(pours):
    """Build the form input dict create_recipe_pours expects."""
    out = {}
    pat_label = {1: "centered", 2: "circular", 3: "spiral"}
    for i, p in enumerate(pours):
        out[f"pour_{i}_volume_ml"] = p["volume_ml"]
        out[f"pour_{i}_temperature_c"] = p["temperature_c"]
        out[f"pour_{i}_pattern"] = pat_label[p["pattern"]]
        out[f"pour_{i}_flow_rate"] = p["flow_rate"]
        out[f"pour_{i}_pause_s"] = p["pause_s"]
        out[f"pour_{i}_vib_before"] = p["agitate_before"] == 1
        out[f"pour_{i}_vib_after"] = p["agitate_after"] == 1
    return out


# ---------------------------------------------------------------------------
# Create flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_recipe_renders_form_when_no_input():
    flow, _ = _make_flow()
    result = await flow.async_step_create_recipe(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "create_recipe"


@pytest.mark.asyncio
async def test_create_recipe_advances_to_pours_with_valid_input():
    flow, _ = _make_flow()
    result = await flow.async_step_create_recipe(user_input=_VALID_RECIPE_INPUT)
    assert result["step_id"] == "create_recipe_brew"
    result = await flow.async_step_create_recipe_brew(user_input=_VALID_RECIPE_INPUT)
    assert result["step_id"] == "create_recipe_pours"
    assert flow._draft is not None
    assert len(flow._draft["pours"]) == 3
    assert flow._draft["pours"][0]["temperature_c"] == 92.0


@pytest.mark.asyncio
async def test_create_recipe_pours_validation_error_returns_form():
    flow, coord = _make_flow()
    # Prime draft via valid recipe-level submit.
    await flow.async_step_create_recipe(user_input=_VALID_RECIPE_INPUT)
    await flow.async_step_create_recipe_brew(user_input=_VALID_RECIPE_INPUT)
    # Build pours input with all volumes 0 → volume_total_mismatch.
    pours_input = _pours_input(flow._draft["pours"])
    for k in list(pours_input):
        if k.endswith("_volume_ml"):
            pours_input[k] = 0.0
    result = await flow.async_step_create_recipe_pours(user_input=pours_input)
    assert result["type"] == "form"
    assert result["step_id"] == "create_recipe_pours"
    assert result["errors"].get("base") == "volume_total_mismatch"
    coord.async_add_recipe.assert_not_called()


@pytest.mark.asyncio
async def test_create_recipe_pours_save_calls_async_add_recipe():
    flow, coord = _make_flow()
    await flow.async_step_create_recipe(user_input=_VALID_RECIPE_INPUT)
    await flow.async_step_create_recipe_brew(user_input=_VALID_RECIPE_INPUT)
    pours_input = _pours_input(flow._draft["pours"])
    result = await flow.async_step_create_recipe_pours(user_input=pours_input)
    # Save success → write-to-slot sub-step appears.
    assert result["step_id"] == "write_to_slot"
    coord.async_add_recipe.assert_called_once()
    saved_recipe = coord.async_add_recipe.call_args[0][0]
    assert saved_recipe["id"].startswith("local-")


# ---------------------------------------------------------------------------
# Edit flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_recipe_aborts_when_no_recipes():
    flow, _ = _make_flow(recipes=[])
    result = await flow.async_step_edit_recipe(user_input=None)
    assert result["type"] == "abort"
    assert result["reason"] == "no_recipes"


@pytest.mark.asyncio
async def test_edit_recipe_pre_fills_pours_and_save_uses_replace():
    stored = _stored_recipe()
    flow, coord = _make_flow(recipes=[stored])

    # First call: render the picker form.
    form = await flow.async_step_edit_recipe(user_input=None)
    assert form["step_id"] == "edit_recipe"

    # Pick the recipe by id → re-enters the create flow at step 1 (name/cup)
    # so name, cup, and brew params are editable too.
    advance = await flow.async_step_edit_recipe(user_input={"recipe_id": "local-test-1"})
    assert advance["step_id"] == "create_recipe"
    assert flow._draft is not None
    assert flow._draft.get("edit_existing") is True
    assert flow._draft["id"] == "local-test-1"

    # Walk steps 1-2 with the pre-filled draft values to reach the pours step.
    step1 = await flow.async_step_create_recipe(user_input={
        "name": flow._draft["name"],
        "cup_type": flow._draft["cup_type_label"],
    })
    assert step1["step_id"] == "create_recipe_brew"
    step2 = await flow.async_step_create_recipe_brew(user_input={
        "dose_g": flow._draft["dose_g"],
        "ratio": flow._draft["ratio"],
        "grind_size": flow._draft["grind_size"],
        "grinder_speed_rpm": flow._draft["grinder_speed_rpm"],
        "pour_count": flow._draft["pour_count"],
        "enable_bypass_water": False,
    })
    assert step2["step_id"] == "create_recipe_pours"

    # Submit the (already-valid) pours and verify replace path is used.
    pours_input = _pours_input(flow._draft["pours"])
    result = await flow.async_step_create_recipe_pours(user_input=pours_input)
    assert result["step_id"] == "write_to_slot"
    coord.async_replace_recipe.assert_called_once()
    coord.async_add_recipe.assert_not_called()
    replaced = coord.async_replace_recipe.call_args[0][0]
    assert replaced["id"] == "local-test-1"  # tableId preserved (D-61)


# ---------------------------------------------------------------------------
# Delete flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_recipe_aborts_when_no_recipes():
    flow, _ = _make_flow(recipes=[])
    result = await flow.async_step_delete_recipe(user_input=None)
    assert result["type"] == "abort"
    assert result["reason"] == "no_recipes"


@pytest.mark.asyncio
async def test_delete_recipe_confirm_calls_async_delete_recipe():
    stored = _stored_recipe()
    flow, coord = _make_flow(recipes=[stored])
    pick = await flow.async_step_delete_recipe(user_input={"recipe_id": "local-test-1"})
    assert pick["step_id"] == "delete_recipe_confirm"
    result = await flow.async_step_delete_recipe_confirm(user_input={"confirm": True})
    assert result["type"] == "create_entry"
    assert result["data"].get("_last_deleted") == "Stored Recipe"
    coord.async_delete_recipe.assert_called_once_with("local-test-1")


@pytest.mark.asyncio
async def test_delete_recipe_unconfirmed_does_not_delete():
    stored = _stored_recipe()
    flow, coord = _make_flow(recipes=[stored])
    await flow.async_step_delete_recipe(user_input={"recipe_id": "local-test-1"})
    result = await flow.async_step_delete_recipe_confirm(user_input={"confirm": False})
    assert result["type"] == "create_entry"
    assert result["data"].get("_cancelled") is True
    coord.async_delete_recipe.assert_not_called()


# ---------------------------------------------------------------------------
# Write-to-slot sub-step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_to_slot_skip_returns_success():
    flow, _ = _make_flow()
    flow._post_save = {"action": "_last_created", "name": "Test"}
    result = await flow.async_step_write_to_slot(user_input={"slot": "skip"})
    assert result["type"] == "create_entry"
    assert result["data"].get("_last_created") == "Test"
    flow.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_write_to_slot_calls_xbloom_service():
    flow, _ = _make_flow()
    flow._post_save = {"action": "_last_created", "name": "Test"}
    result = await flow.async_step_write_to_slot(user_input={"slot": "A"})
    assert result["type"] == "create_entry"
    assert result["data"].get("_slot_written") == "A"
    flow.hass.services.async_call.assert_called_once_with(
        "xbloom",
        "write_slot",
        {"slot": "A", "recipe_name": "Test"},
        blocking=True,
    )


# ---------------------------------------------------------------------------
# Round-trip _build_recipe → validate_recipe (D-31 bypass int contract)
# ---------------------------------------------------------------------------


def test_build_recipe_bypass_disabled_passes_validator():
    flow, _ = _make_flow()
    draft = {
        "name": "Test",
        "dose_g": 18.0,
        "ratio": "1:16",
        "grind_size": 40,
        "grinder_speed_rpm": 90,
        "pour_count": 3,
        "cup_type_label": "Omni dripper",
        "bypass_water_enabled": False,
        "bypass_volume_ml": None,
        "bypass_temp_c": None,
    }
    pours = flow._auto_fill_pours(draft)
    recipe = flow._build_recipe(draft, pours)
    assert validate_recipe(recipe) == {}


def test_build_recipe_bypass_enabled_passes_validator_when_fields_present():
    flow, _ = _make_flow()
    draft = {
        "name": "Test",
        "dose_g": 18.0,
        "ratio": "1:16",
        "grind_size": 40,
        "grinder_speed_rpm": 90,
        "pour_count": 3,
        "cup_type_label": "Omni dripper",
        "bypass_water_enabled": True,
        "bypass_volume_ml": 80.0,
        "bypass_temp_c": 92.0,
    }
    pours = flow._auto_fill_pours(draft)
    recipe = flow._build_recipe(draft, pours)
    assert validate_recipe(recipe) == {}
