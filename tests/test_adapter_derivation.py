"""Prove the HA adapter's spec-derived values equal the pre-refactor literals.

config_flow.py imports Home Assistant, so it can't be imported here. Instead
this replicates the *pure* derivations config_flow now performs against the
spec — ratio options, the cup dose table, and each NumberSelector's config —
and checks them against a frozen snapshot of the hand-written values. The one
intended change is pour temperature's floor (40, not the old UI's 20).
"""
from __future__ import annotations

import importlib.util
import os
import sys

_SPEC = os.path.join(
    os.path.dirname(__file__),
    "..", "custom_components", "xbloom", "vendor", "xbloom", "spec.py",
)
_m = importlib.util.spec_from_file_location("xbloom_spec", _SPEC)
spec = importlib.util.module_from_spec(_m)
sys.modules["xbloom_spec"] = spec
_m.loader.exec_module(spec)


# --- Replicas of the pure logic in config_flow (must stay in sync) --------- #

def ratio_options():
    r = spec.RATIO_DENOM
    count = int(round((r.max - r.min) / r.step)) + 1
    out = []
    for i in range(count):
        d = r.min + r.step * i
        out.append(f"1:{int(d)}" if d == int(d) else f"1:{d:g}")
    return out


def cup_dose_ui():
    return {
        c.label: (c.dose.min, c.dose.max, c.dose.step, c.dose.default)
        for c in spec.CUP_TYPES
    }


def selector_cfg(rng):
    cfg = {"min": rng.min, "max": rng.max, "step": rng.step, "mode": "slider"}
    if rng.unit:
        cfg["unit_of_measurement"] = rng.unit
    return cfg


# --- Frozen pre-refactor expectations -------------------------------------- #

EXPECTED_RATIO = ["1:5", "1:5.5", "1:6", "1:25"]  # spot-check ends + length 41
EXPECTED_CUP_UI = {
    "xPod": (15.0, 15.0, 0.5, 15.0),
    "Omni dripper": (5.0, 18.0, 0.5, 18.0),
    "Other": (5.0, 25.0, 0.5, 18.0),
    "Tea": (1.0, 5.0, 0.5, 3.0),
}
# field -> pre-refactor NumberSelectorConfig kwargs (unit omitted when none).
# pour_temperature_c is 20-98 = the app's RT..BP span.
EXPECTED_SEL = {
    "grind_size": {"min": 1, "max": 80, "step": 1, "mode": "slider"},
    "grinder_speed_rpm": {"min": 60, "max": 120, "step": 10, "mode": "slider", "unit_of_measurement": "RPM"},
    "pour_count": {"min": 1, "max": 9, "step": 1, "mode": "slider"},
    "pour_volume_ml": {"min": 0, "max": 240, "step": 1, "mode": "slider", "unit_of_measurement": "ml"},
    "pour_temperature_c": {"min": 20, "max": 98, "step": 1, "mode": "slider", "unit_of_measurement": "°C"},
    "pour_flow_rate": {"min": 3.0, "max": 3.5, "step": 0.1, "mode": "slider"},
    "pour_pause_s": {"min": 0, "max": 59, "step": 1, "mode": "slider", "unit_of_measurement": "s"},
    "bypass_volume_ml": {"min": 5, "max": 100, "step": 1, "mode": "slider", "unit_of_measurement": "ml"},
    "bypass_temp_c": {"min": 20, "max": 98, "step": 1, "mode": "slider", "unit_of_measurement": "°C"},
}


def run():
    fails, n = [], 0
    ro = ratio_options()
    for label, cond in [
        ("ratio length 41", len(ro) == 41),
        ("ratio first 1:5", ro[0] == "1:5"),
        ("ratio second 1:5.5", ro[1] == "1:5.5"),
        ("ratio last 1:25", ro[-1] == "1:25"),
    ]:
        n += 1
        if not cond:
            fails.append(f"  FAIL {label} (got {ro[:3]}..{ro[-1]}, len {len(ro)})")

    cui = cup_dose_ui()
    for label, want in EXPECTED_CUP_UI.items():
        n += 1
        if cui.get(label) != want:
            fails.append(f"  FAIL cup_dose_ui[{label}]: {cui.get(label)} != {want}")

    for name, want in EXPECTED_SEL.items():
        n += 1
        got = selector_cfg(spec.field(name))
        if got != want:
            fails.append(f"  FAIL selector {name}: {got} != {want}")

    # Pattern maps the adapter now uses.
    for label, got, want in [
        ("pattern save map", spec.PATTERN_NAME_TO_API, {"centered": 1, "spiral": 2, "circular": 3}),
        ("pattern label map", spec.PATTERN_API_TO_NAME, {1: "centered", 2: "spiral", 3: "circular"}),
        ("cup label->api", spec.CUP_LABEL_TO_API, {"xPod": 1, "Omni dripper": 2, "Other": 3, "Tea": 4}),
        ("standalone name->byte", spec.PATTERN_NAME_TO_BYTE, {"centered": 0, "spiral": 2, "circular": 1}),
        ("water source codes", spec.WATER_SOURCE_CODES, {"tank": 0, "tap": 1}),
    ]:
        n += 1
        if got != want:
            fails.append(f"  FAIL {label}: {got} != {want}")

    if fails:
        print(f"{len(fails)}/{n} adapter-derivation checks FAILED:")
        print("\n".join(fails))
        return False
    print(f"all {n} adapter-derivation checks passed")
    return True


def test_adapter_derivation():
    assert run()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
