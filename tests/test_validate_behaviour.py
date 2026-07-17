"""Behaviour parity for recipe_validate after the spec migration.

Imports the vendor core as the top-level package `xbloom` (the package
__init__ is lazy, so this pulls no aiohttp). Each case asserts the exact set
of error keys validate_recipe returns, matching the pre-migration behaviour —
plus normalize_recipe round-trips.

Run directly or under pytest.
"""
from __future__ import annotations

import copy
import os
import sys

_VENDOR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor",
)
sys.path.insert(0, os.path.abspath(_VENDOR))

from xbloom import recipe_validate as rv  # noqa: E402

# A valid wizard-shape recipe (the real 803560, corrected volumes/patterns).
VALID = {
    "id": "803560", "name": "وصفة زيادة الحلاوة", "dose_g": 20.0,
    "ratio": "1:15", "water_ratio": 300.0, "grind_size": 50,
    "grinder_size": 50, "grinder_size_enabled": 1, "grinder_speed_rpm": 100,
    "rpm": 100, "pour_count": 5, "cup_type": 3, "cup_type_name": "Other",
    "bypass_water_enabled": 2,
    "pours": [
        {"name": "الترطيب", "volume_ml": 30, "temperature_c": 92, "pattern": 3, "flow_rate": 3.2, "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"name": "الصبة 2", "volume_ml": 90, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2, "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"name": "الصبة 3", "volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2, "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"name": "الصبة 4", "volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2, "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"name": "الصبة 5", "volume_ml": 60, "temperature_c": 85, "pattern": 1, "flow_rate": 3.5, "pause_s": 5, "agitate_before": 2, "agitate_after": 2},
    ],
}


def mut(**over):
    r = copy.deepcopy(VALID)
    r.update(over)
    return r


def with_pour(idx, **over):
    r = copy.deepcopy(VALID)
    r["pours"][idx].update(over)
    return r


CASES = [
    ("valid recipe", VALID, set()),
    ("bad ratio", mut(ratio="banana"), {"ratio"}),
    ("dose out of range for cup", mut(dose_g=999), {"dose_g", "pours"}),  # sum also breaks
    ("grind too high", mut(grind_size=200), {"grind_size"}),
    ("rpm off-step (95)", mut(grinder_speed_rpm=95), {"grinder_speed_rpm"}),
    ("rpm float 100.0 ok", mut(grinder_speed_rpm=100.0), set()),
    ("invalid cup type", mut(cup_type=9), {"cup_type"}),
    ("pour_count mismatch", mut(pour_count=4), {"pour_count"}),
    ("temp 20 = RT accepted", with_pour(0, temperature_c=20), set()),
    ("temp 98 = BP accepted", with_pour(0, temperature_c=98), set()),
    ("temp 30 accepted (in RT..BP)", with_pour(0, temperature_c=30), set()),
    ("temp 19 rejected (below RT)", with_pour(0, temperature_c=19), {"pours.0.temperature_c"}),
    ("temp 99 rejected (above BP)", with_pour(0, temperature_c=99), {"pours.0.temperature_c"}),
    ("flow out of range", with_pour(1, flow_rate=5.0), {"pours.1.flow_rate"}),
    ("pause float rejected", with_pour(2, pause_s=5.5), {"pours.2.pause_s"}),
    ("pattern 0 invalid (API is 1-3)", with_pour(0, pattern=0), {"pours.0.pattern"}),
    ("volume sum mismatch", with_pour(0, volume_ml=10), {"pours"}),
    ("name required", mut(name="  "), {"name"}),
]


def run():
    fails, n = [], 0
    for label, recipe, expect_keys in CASES:
        n += 1
        got = set(rv.validate_recipe(recipe).keys())
        if got != expect_keys:
            fails.append(f"  FAIL {label}: got {sorted(got)}, expected {sorted(expect_keys)}")

    # normalize: imported (API) shape must validate clean after normalize.
    imported = {
        "id": "803560", "name": "x", "dose_g": 20.0, "water_ratio": 15.0,
        "grinder_size": 50.0, "grinder_size_enabled": 1, "rpm": 100,
        "pour_count": 5, "cup_type": 3, "cup_type_name": "Other",
        "bypass_water_enabled": 2,
        "pours": copy.deepcopy(VALID["pours"]),
    }
    n += 1
    norm = rv.normalize_recipe(imported)
    errs = rv.validate_recipe(norm)
    if errs:
        fails.append(f"  FAIL normalize(imported) still invalid: {errs}")
    n += 1
    if norm.get("ratio") != "1:15":
        fails.append(f"  FAIL normalize ratio: got {norm.get('ratio')!r}")

    if fails:
        print(f"{len(fails)}/{n} behaviour checks FAILED:")
        print("\n".join(fails))
        return False
    print(f"all {n} behaviour checks passed")
    return True


def test_validate_behaviour():
    assert run()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
