"""Tests for the one-off brew scaler (vendor/xbloom/brew_scale.py)."""
from __future__ import annotations

import os
import sys

_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor")
)
sys.path.insert(0, _VENDOR)

from xbloom import brew_scale  # noqa: E402
from xbloom import ble  # noqa: E402

# "وصفة زيادة الحلاوة" 872025 shape (dose 20, ratio 15, 300 ml over 5 pours).
_RECIPE = {
    "name": "زيادة الحلاوة",
    "dose_g": 20.0,
    "water_ratio": 15.0,
    "grinder_size": 50,
    "grinder_size_enabled": 1,
    "rpm": 100,
    "cup_type": 3,
    "pours": [
        {"volume_ml": 30, "temperature_c": 92, "pattern": 3, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 90, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 85, "pattern": 1, "flow_rate": 3.5,
         "pause_s": 5, "agitate_before": 2, "agitate_after": 2},
    ],
}


def _vols(r):
    return [p["volume_ml"] for p in r["pours"]]


def test_dose_only_scales_pours_proportionally():
    # Same ratio (15), dose 20 → 30 g ⟹ ×1.5.
    out = brew_scale.scale_recipe(_RECIPE, dose_g=30, ratio=15.0)
    assert _vols(out) == [45.0, 135.0, 90.0, 90.0, 90.0]
    assert sum(_vols(out)) == 450.0            # 30 × 15
    assert out["dose_g"] == 30.0 and out["water_ratio"] == 15.0


def test_identity_when_unchanged():
    out = brew_scale.scale_recipe(_RECIPE, dose_g=20, ratio=15.0)
    assert _vols(out) == [30.0, 90.0, 60.0, 60.0, 60.0]


def test_ratio_change_scales_water_only():
    # Dose fixed (20), ratio 15 → 18 ⟹ ×1.2 water.
    out = brew_scale.scale_recipe(_RECIPE, dose_g=20, ratio=18.0)
    assert sum(_vols(out)) == 360.0            # 20 × 18
    assert out["water_ratio"] == 18.0


def test_original_not_mutated():
    before = _vols(_RECIPE)
    brew_scale.scale_recipe(_RECIPE, dose_g=40, ratio=20.0, grind_size=70)
    assert _vols(_RECIPE) == before            # source untouched
    assert _RECIPE["grinder_size"] == 50


def test_grind_override():
    out = brew_scale.scale_recipe(_RECIPE, dose_g=20, ratio=15.0, grind_size=65)
    assert out["grinder_size"] == 65


def test_scaled_recipe_still_encodes_a_valid_blob():
    # A scaled recipe must still produce a well-formed blob (ratio×10 tail).
    out = brew_scale.scale_recipe(_RECIPE, dose_g=25, ratio=16.0, grind_size=55)
    blob = ble.encode_recipe_blob(
        out["pours"], grinder_size=55, dose_g=25.0, rpm=100,
    )
    assert blob[-1] == 160          # ratio 16.0 × 10
    assert blob[-2] == 55           # grind
