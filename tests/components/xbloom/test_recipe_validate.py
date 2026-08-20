"""RED-state tests for the shared xBloom recipe validator.

This test file is intentionally written before `recipe_validate.py` exists.
Running the suite today MUST fail with ModuleNotFoundError on import — that
is the RED gate for plan 09-01. Plan 09-03 implements the validator (GREEN).

Validator contract (target — does NOT yet exist):

    def validate_recipe(recipe: dict) -> dict[str, str]:
        '''Return {field_path: error_key}. Empty dict means valid.'''

Field paths use HA flow conventions:
  - top-level: "name", "dose_g", "ratio", "grind_size",
    "grinder_speed_rpm", "pour_count", "cup_type",
    "bypass_volume_ml", "bypass_temp_c", "pours"
  - per-pour: "pours.<i>.volume_ml", "pours.<i>.temperature_c",
    "pours.<i>.flow_rate", "pours.<i>.pause_s",
    "pours.<i>.pattern"

Bypass convention: `bypass_water_enabled` is an int — `1` means ON,
`2` means OFF (matches BLE/share-URL data path; see D-31).
"""

from __future__ import annotations

import sys
import types
from copy import deepcopy
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs.
#
# `recipe_validate.py` itself depends only on stdlib + `re`, but importing it
# through `custom_components.xbloom.vendor.xbloom.*` triggers the parent
# package's `__init__.py`, which imports `homeassistant`. HA is not installed
# in this dev environment, so we mirror the stub pattern from
# tests/components/xbloom/test_client.py to make the import path reachable.
# When `recipe_validate.py` lands in plan 09-03, this test will go GREEN; until
# then it MUST fail with ModuleNotFoundError on `recipe_validate` (RED).
# ---------------------------------------------------------------------------


def _inject_stubs() -> None:
    def _mod(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    _mod("homeassistant")
    _mod("homeassistant.components")

    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = MagicMock

    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock
    core.callback = lambda f: f

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

    storage_mod = _mod("homeassistant.helpers.storage")


_inject_stubs()

from custom_components.xbloom.vendor.xbloom.recipe_validate import validate_recipe  # noqa: E402


def _valid_recipe() -> dict:
    """Return a fully-valid baseline recipe.

    dose=18g, ratio=1:16 → expected total water = 288 ml.
    Three pours of 96 ml each → sum == 288 ml.
    Baseline uses canonical int convention: bypass_water_enabled=2 (OFF).
    """
    return {
        "id": "local-test-0001",
        "name": "Test Recipe",
        "dose_g": 18.0,
        "ratio": "1:16",
        "grind_size": 40,
        "grinder_speed_rpm": 90,
        "pour_count": 3,
        "cup_type": 2,                    # Omni
        "bypass_water_enabled": 2,        # 2 = OFF (canonical int convention; D-31)
        "pours": [
            {"volume_ml": 96.0, "temperature_c": 92, "pattern": 3,
             "flow_rate": 3.0, "pause_s": 0,
             "agitate_before": 2, "agitate_after": 2},
            {"volume_ml": 96.0, "temperature_c": 91, "pattern": 3,
             "flow_rate": 3.0, "pause_s": 0,
             "agitate_before": 2, "agitate_after": 2},
            {"volume_ml": 96.0, "temperature_c": 90, "pattern": 3,
             "flow_rate": 3.0, "pause_s": 0,
             "agitate_before": 2, "agitate_after": 2},
        ],
    }


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_valid_recipe_returns_empty_dict():
    assert validate_recipe(_valid_recipe()) == {}


# ---------------------------------------------------------------------------
# 2. name
# ---------------------------------------------------------------------------


def test_name_required():
    recipe = _valid_recipe()
    recipe["name"] = ""
    errors = validate_recipe(recipe)
    assert errors.get("name") == "name_required"


# ---------------------------------------------------------------------------
# 3-4. dose_g range
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dose", [4.9, -1, 0])
def test_dose_too_low(dose):
    recipe = _valid_recipe()
    recipe["dose_g"] = dose
    errors = validate_recipe(recipe)
    assert errors.get("dose_g") == "dose_out_of_range_for_cup"


@pytest.mark.parametrize("dose", [25.1, 30, 100])
def test_dose_too_high(dose):
    recipe = _valid_recipe()
    recipe["dose_g"] = dose
    # also clear pour-volume mismatch noise: keep dose-only error meaningful
    errors = validate_recipe(recipe)
    assert errors.get("dose_g") == "dose_out_of_range_for_cup"


# ---------------------------------------------------------------------------
# 5-6. ratio
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ratio", ["16", "1:", "1:16.55", "1:abc", "", "2:16"])
def test_ratio_invalid_format(ratio):
    recipe = _valid_recipe()
    recipe["ratio"] = ratio
    errors = validate_recipe(recipe)
    assert errors.get("ratio") == "ratio_invalid"


@pytest.mark.parametrize("ratio,total_ml", [("1:16", 288.0), ("1:8", 144.0), ("1:16.5", 297.0)])
def test_ratio_valid_formats(ratio, total_ml):
    recipe = _valid_recipe()
    recipe["ratio"] = ratio
    # rebalance pours so sum-of-volumes still matches the new total
    per_pour = round(total_ml / 3, 1)
    # distribute remainder onto the last pour to hit exact total
    recipe["pours"][0]["volume_ml"] = per_pour
    recipe["pours"][1]["volume_ml"] = per_pour
    recipe["pours"][2]["volume_ml"] = round(total_ml - 2 * per_pour, 1)
    errors = validate_recipe(recipe)
    assert "ratio" not in errors


# ---------------------------------------------------------------------------
# 7. grind_size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grind", [0, 81, -5, 200])
def test_grind_size_out_of_range(grind):
    recipe = _valid_recipe()
    recipe["grind_size"] = grind
    errors = validate_recipe(recipe)
    assert errors.get("grind_size") == "grind_out_of_range"


# ---------------------------------------------------------------------------
# 8. grinder_speed_rpm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rpm", [59, 121, 0, 500])
def test_rpm_out_of_range(rpm):
    recipe = _valid_recipe()
    recipe["grinder_speed_rpm"] = rpm
    errors = validate_recipe(recipe)
    assert errors.get("grinder_speed_rpm") == "rpm_out_of_range"


# ---------------------------------------------------------------------------
# 9-10. pour_count
# ---------------------------------------------------------------------------


def test_pour_count_zero():
    recipe = _valid_recipe()
    recipe["pour_count"] = 0
    recipe["pours"] = []
    errors = validate_recipe(recipe)
    assert errors.get("pour_count") == "pour_count_mismatch"


def test_pour_count_mismatch():
    recipe = _valid_recipe()
    recipe["pour_count"] = 3
    # drop one pour → length 2 vs declared 3
    recipe["pours"] = recipe["pours"][:2]
    errors = validate_recipe(recipe)
    assert errors.get("pour_count") == "pour_count_mismatch"


# ---------------------------------------------------------------------------
# 11-12. cup_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cup", [0, 5, -1])
def test_cup_type_invalid(cup):
    recipe = _valid_recipe()
    recipe["cup_type"] = cup
    errors = validate_recipe(recipe)
    assert errors.get("cup_type") == "cup_type_invalid"


@pytest.mark.parametrize("cup", [1, 2, 3, 4])
def test_cup_type_valid(cup):
    recipe = _valid_recipe()
    recipe["cup_type"] = cup
    errors = validate_recipe(recipe)
    assert "cup_type" not in errors


# ---------------------------------------------------------------------------
# 13-14. volume sum (cross-pour rule, top-level "pours" key)
# ---------------------------------------------------------------------------


def test_volume_total_mismatch():
    recipe = _valid_recipe()
    # dose=18, ratio=1:16 → expected 288 ml; force pours to sum to 200 ml
    recipe["pours"][0]["volume_ml"] = 70.0
    recipe["pours"][1]["volume_ml"] = 70.0
    recipe["pours"][2]["volume_ml"] = 60.0
    errors = validate_recipe(recipe)
    assert errors.get("pours") == "volume_total_mismatch"


def test_volume_total_within_1ml_passes():
    recipe = _valid_recipe()
    # 287.6 sum vs 288 expected → within ±1 ml tolerance
    recipe["pours"][0]["volume_ml"] = 95.9
    recipe["pours"][1]["volume_ml"] = 95.9
    recipe["pours"][2]["volume_ml"] = 95.8
    errors = validate_recipe(recipe)
    assert "pours" not in errors


# ---------------------------------------------------------------------------
# 15-18. per-pour ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("temp", [19, 99, 0, 200])
def test_pour_temp_out_of_range(temp):
    recipe = _valid_recipe()
    recipe["pours"][0]["temperature_c"] = temp
    errors = validate_recipe(recipe)
    assert errors.get("pours.0.temperature_c") == "temp_out_of_range"


@pytest.mark.parametrize("flow", [2.9, 3.6, 0.0, 10.0])
def test_pour_flow_rate_out_of_range(flow):
    recipe = _valid_recipe()
    recipe["pours"][0]["flow_rate"] = flow
    errors = validate_recipe(recipe)
    assert errors.get("pours.0.flow_rate") == "flow_out_of_range"


@pytest.mark.parametrize("pause", [-1, 60, 100])
def test_pour_pause_out_of_range(pause):
    recipe = _valid_recipe()
    recipe["pours"][1]["pause_s"] = pause
    errors = validate_recipe(recipe)
    assert errors.get("pours.1.pause_s") == "pause_out_of_range"


@pytest.mark.parametrize("pattern", [0, 4, -1, 99])
def test_pour_pattern_invalid(pattern):
    recipe = _valid_recipe()
    recipe["pours"][2]["pattern"] = pattern
    errors = validate_recipe(recipe)
    assert errors.get("pours.2.pattern") == "pattern_invalid"


# ---------------------------------------------------------------------------
# 19-23. bypass water (int convention: 1=ON, 2=OFF)
# ---------------------------------------------------------------------------


def test_bypass_volume_required_when_enabled():
    recipe = _valid_recipe()
    recipe["bypass_water_enabled"] = 1
    recipe["bypass_temp_c"] = 90.0
    # bypass_volume_ml deliberately missing
    errors = validate_recipe(recipe)
    assert errors.get("bypass_volume_ml") == "bypass_volume_required"


def test_bypass_temp_required_when_enabled():
    recipe = _valid_recipe()
    recipe["bypass_water_enabled"] = 1
    recipe["bypass_volume_ml"] = 50.0
    # bypass_temp_c deliberately missing
    errors = validate_recipe(recipe)
    assert errors.get("bypass_temp_c") == "bypass_temp_required"


def test_bypass_fields_ignored_when_disabled():
    recipe = _valid_recipe()
    recipe.update({"bypass_water_enabled": 2})  # OFF — canonical int convention
    # neither bypass_volume_ml nor bypass_temp_c set
    errors = validate_recipe(recipe)
    assert "bypass_volume_ml" not in errors
    assert "bypass_temp_c" not in errors


def test_bypass_disabled_int_convention_no_error():
    """Lock the int convention: bypass_water_enabled=2 (int two) and no
    bypass fields produces ZERO bypass-related errors."""
    recipe = _valid_recipe()
    recipe["bypass_water_enabled"] = 2
    recipe.pop("bypass_volume_ml", None)
    recipe.pop("bypass_temp_c", None)
    errors = validate_recipe(recipe)
    assert "bypass_volume_ml" not in errors
    assert "bypass_temp_c" not in errors


def test_bypass_enabled_int_convention_requires_fields():
    """Symmetric guard: bypass_water_enabled=1 (int one) without bypass
    fields MUST surface BOTH bypass_volume_required and bypass_temp_required."""
    recipe = _valid_recipe()
    recipe["bypass_water_enabled"] = 1
    recipe.pop("bypass_volume_ml", None)
    recipe.pop("bypass_temp_c", None)
    errors = validate_recipe(recipe)
    assert errors.get("bypass_volume_ml") == "bypass_volume_required"
    assert errors.get("bypass_temp_c") == "bypass_temp_required"


# ---------------------------------------------------------------------------
# 24. accumulation
# ---------------------------------------------------------------------------


def test_multiple_errors_accumulate():
    recipe = _valid_recipe()
    recipe["name"] = ""
    recipe["dose_g"] = 100.0
    errors = validate_recipe(recipe)
    assert errors.get("name") == "name_required"
    assert errors.get("dose_g") == "dose_out_of_range_for_cup"


# ---------------------------------------------------------------------------
# Defensive: deepcopy guard — validator must not mutate input
# ---------------------------------------------------------------------------


def test_validator_does_not_mutate_input():
    recipe = _valid_recipe()
    snapshot = deepcopy(recipe)
    validate_recipe(recipe)
    assert recipe == snapshot
