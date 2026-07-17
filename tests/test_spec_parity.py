"""Parity guard for the domain spec (vendor/xbloom/spec.py).

EXPECTED below is a frozen snapshot of the constants as they were hardcoded
across recipe_validate.py, config_flow.py and ble.py BEFORE they were
centralised into spec.py. The spec must reproduce every one of them, so this
proves the refactor changed no behaviour — and stays a regression guard after
migration, since the consumers now derive from spec.

The single deliberate exception is documented inline: pour temperature's floor
is 40 (the machine rule the validator always enforced), not the 20 the edit
wizard's slider previously allowed.

Run directly (`python tests/test_spec_parity.py`) or under pytest.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_SPEC_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "custom_components", "xbloom", "vendor", "xbloom", "spec.py",
)
_spec_mod = importlib.util.spec_from_file_location("xbloom_spec", _SPEC_PATH)
spec = importlib.util.module_from_spec(_spec_mod)
# Register before exec so @dataclass can resolve the module via sys.modules.
sys.modules["xbloom_spec"] = spec
_spec_mod.loader.exec_module(spec)


# --- Frozen pre-refactor values -------------------------------------------- #

# Pattern: (name, api integer, BLE byte) — from ble._API_PATTERN_TO_BLE +
# PATTERN_NAMES + config_flow's label/save maps, all reconciled.
EXPECTED_PATTERNS = {
    "centered": (1, 0),
    "spiral": (2, 2),
    "circular": (3, 1),
}

# Cup: api -> (label, dose_min, dose_max, dose_step, dose_default)
# from config_flow._CUP_DOSE_UI + the int<->label maps + recipe_validate
# _CUP_DOSE_RANGES (min/max must agree between the two).
EXPECTED_CUPS = {
    1: ("xPod", 15.0, 15.0, 0.5, 15.0),
    2: ("Omni dripper", 5.0, 18.0, 0.5, 18.0),
    3: ("Other", 5.0, 25.0, 0.5, 18.0),
    4: ("Tea", 1.0, 5.0, 0.5, 3.0),
}

# Field: name -> (min, max, step) as validated / sliderped before the spec.
# `ui_min_override` marks the one intentional change from the old UI value.
EXPECTED_FIELDS = {
    "grind_size": (1, 80, 1),            # validate 1..80, UI 1..80
    "grinder_speed_rpm": (60, 120, 10),  # validate 60..120 step 10, UI same
    "pour_count": (1, 9, 1),             # validate 1..9, UI 1..9
    "pour_volume_ml": (0, 240, 1),       # validate 0..240, UI 0..240
    "pour_temperature_c": (40, 98, 1),   # validate 40..98 (UI was 20 — fixed)
    "pour_flow_rate": (3.0, 3.5, 0.1),   # validate 3.0..3.5, UI same
    "pour_pause_s": (0, 59, 1),          # validate 0..59, UI 0..59
    "bypass_volume_ml": (5, 100, 1),     # UI only
    "bypass_temp_c": (20, 98, 1),        # UI only; bypass floor is 20
}

EXPECTED_RATIO = (5.0, 25.0, 0.5)        # recipe_validate _RATIO_DENOM_*
EXPECTED_VOLUME_TOL = 0.5                # recipe_validate VOLUME_TOLERANCE_ML
EXPECTED_WATER = {"tank": 0, "tap": 1}   # ble water_feed
EXPECTED_WEIGHT_UNIT = {"g": 0, "oz": 1, "ml": 2}   # ble _WEIGHT_UNIT_CODES


def _checks():
    # Patterns — every direction of the maps.
    for name, (api, byte) in EXPECTED_PATTERNS.items():
        yield f"pattern {name} api", spec.PATTERN_NAME_TO_API[name], api
        yield f"pattern {name} byte", spec.PATTERN_NAME_TO_BYTE[name], byte
        yield f"pattern api->name {api}", spec.PATTERN_API_TO_NAME[api], name
        yield f"pattern api->byte {api}", spec.PATTERN_API_TO_BYTE[api], byte
        yield f"pattern byte->name {byte}", spec.PATTERN_BYTE_TO_NAME[byte], name

    # Cups.
    for api, (label, lo, hi, step, default) in EXPECTED_CUPS.items():
        yield f"cup {api} label", spec.CUP_API_TO_LABEL[api], label
        yield f"cup {label} api", spec.CUP_LABEL_TO_API[label], api
        d = spec.CUP_DOSE[api]
        yield f"cup {api} dose min", d.min, lo
        yield f"cup {api} dose max", d.max, hi
        yield f"cup {api} dose step", d.step, step
        yield f"cup {api} dose default", d.default, default
    yield "valid cup types", spec.VALID_CUP_TYPES, frozenset(EXPECTED_CUPS)

    # Fields.
    for name, (lo, hi, step) in EXPECTED_FIELDS.items():
        r = spec.FIELDS[name]
        yield f"field {name} min", r.min, lo
        yield f"field {name} max", r.max, hi
        yield f"field {name} step", r.step, step

    # Ratio, tolerance, enums.
    yield "ratio min", spec.RATIO_DENOM.min, EXPECTED_RATIO[0]
    yield "ratio max", spec.RATIO_DENOM.max, EXPECTED_RATIO[1]
    yield "ratio step", spec.RATIO_DENOM.step, EXPECTED_RATIO[2]
    yield "volume tolerance", spec.VOLUME_TOLERANCE_ML, EXPECTED_VOLUME_TOL
    yield "water source codes", spec.WATER_SOURCE_CODES, EXPECTED_WATER
    yield "weight unit codes", spec.WEIGHT_UNIT_CODES, EXPECTED_WEIGHT_UNIT

    # Behavioural spot-checks on NumRange helpers.
    yield "grind snap 63.4->63", spec.field("grind_size").snap(63.4), 63
    yield "rpm snap 95->100", spec.field("grinder_speed_rpm").snap(95), 100
    yield "temp 30 rejected", spec.field("pour_temperature_c").contains(30), False
    yield "temp 92 ok", spec.field("pour_temperature_c").contains(92), True
    yield "ratio snap 40->25 (clamp)", spec.RATIO_DENOM.snap(40), 25.0


def run():
    fails = []
    n = 0
    for label, got, want in _checks():
        n += 1
        if got != want:
            fails.append(f"  FAIL {label}: got {got!r}, expected {want!r}")
    if fails:
        print(f"{len(fails)}/{n} parity checks FAILED:")
        print("\n".join(fails))
        return False
    print(f"all {n} parity checks passed")
    return True


def test_spec_parity():
    assert run()


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
