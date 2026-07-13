"""Shared validator for xBloom recipes (create, edit, share-URL import).

Returns a flat dict of field_path -> error_key. Empty dict = valid.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("xbloom.recipe_validate")

_RATIO_RE = re.compile(r"^1:\d+(\.\d)?$")
# grandWater range — single rule for all cup types (from the xBloom app).
_RATIO_DENOM_MIN = 5.0
_RATIO_DENOM_MAX = 25.0
_RATIO_DENOM_STEP = 0.5
_VOLUME_TOLERANCE_ML = 0.5   # both over and under rejected if diff > 0.5 ml
_VALID_CUP_TYPES = {1, 2, 3, 4}
_VALID_PATTERNS = {1, 2, 3}

# Per-cup dose ranges — matched to the xBloom app's behaviour.
# {cup_type: (min_g, max_g)}.
# xPod is locked at 15 g (preground pod). Tea uses a separate range.
_CUP_DOSE_RANGES = {
    1: (15.0, 15.0),   # xPod — locked
    2: (5.0, 18.0),    # Omni / Xdripper
    3: (5.0, 25.0),    # Other
    4: (1.0, 5.0),     # Tea
}


def _ratio_denom(ratio: Any) -> float | None:
    """Parse '1:N' and enforce xBloom range (5–25, step 0.5)."""
    if not isinstance(ratio, str) or not _RATIO_RE.match(ratio):
        return None
    try:
        denom = float(ratio.split(":", 1)[1])
    except (ValueError, IndexError):
        return None
    if not (_RATIO_DENOM_MIN <= denom <= _RATIO_DENOM_MAX):
        return None
    # Enforce 0.5 step — denom × 2 must be a whole number.
    if abs(denom * 2 - round(denom * 2)) > 1e-9:
        return None
    return denom


def validate_recipe(recipe: dict) -> dict[str, str]:
    errors: dict[str, str] = {}

    # name
    name = recipe.get("name")
    if not isinstance(name, str) or not name.strip():
        errors["name"] = "name_required"

    # dose_g — cup-type-specific (xBloom app limits)
    dose = recipe.get("dose_g")
    cup_type = recipe.get("cup_type")
    dose_range = _CUP_DOSE_RANGES.get(cup_type) if cup_type in _VALID_CUP_TYPES else None
    if dose_range is not None:
        lo, hi = dose_range
        if (
            not isinstance(dose, (int, float))
            or isinstance(dose, bool)
            or not (lo <= dose <= hi)
        ):
            errors["dose_g"] = "dose_out_of_range_for_cup"
    else:
        # cup_type invalid — flagged separately below; fall back to permissive check
        if (
            not isinstance(dose, (int, float))
            or isinstance(dose, bool)
            or not (1 <= dose <= 25)
        ):
            errors["dose_g"] = "dose_out_of_range_for_cup"

    # ratio
    denom = _ratio_denom(recipe.get("ratio", ""))
    if denom is None:
        errors["ratio"] = "ratio_invalid"

    # grind_size 1..80
    grind = recipe.get("grind_size")
    if (
        not isinstance(grind, (int, float))
        or isinstance(grind, bool)
        or not (1 <= grind <= 80)
    ):
        errors["grind_size"] = "grind_out_of_range"

    # rpm 60..120 in steps of 10 (machine only supports discrete 10-RPM steps)
    rpm = recipe.get("grinder_speed_rpm")
    if (
        not isinstance(rpm, (int, float))
        or isinstance(rpm, bool)
        or not (60 <= rpm <= 120)
        or int(rpm) != rpm
        or int(rpm) % 10 != 0
    ):
        errors["grinder_speed_rpm"] = "rpm_out_of_range"

    # cup_type ∈ {1,2,3,4}
    if cup_type not in _VALID_CUP_TYPES:
        errors["cup_type"] = "cup_type_invalid"

    # pour_count + pours length (xBloom app cap: 1..9)
    pours = recipe.get("pours") or []
    pour_count = recipe.get("pour_count")
    if (
        not isinstance(pour_count, int)
        or isinstance(pour_count, bool)
        or not (1 <= pour_count <= 9)
        or not isinstance(pours, list)
        or len(pours) != pour_count
    ):
        errors["pour_count"] = "pour_count_mismatch"

    # per-pour
    if isinstance(pours, list):
        for i, p in enumerate(pours):
            if not isinstance(p, dict):
                continue
            t = p.get("temperature_c")
            if (
                not isinstance(t, (int, float))
                or isinstance(t, bool)
                or not (40 <= t <= 98)
            ):
                errors[f"pours.{i}.temperature_c"] = "temp_out_of_range"
            fr = p.get("flow_rate")
            if (
                not isinstance(fr, (int, float))
                or isinstance(fr, bool)
                or not (3.0 <= fr <= 3.5)
            ):
                errors[f"pours.{i}.flow_rate"] = "flow_out_of_range"
            ps = p.get("pause_s")
            if (
                not isinstance(ps, int)
                or isinstance(ps, bool)
                or not (0 <= ps <= 59)
            ):
                errors[f"pours.{i}.pause_s"] = "pause_out_of_range"
            pat = p.get("pattern")
            if pat not in _VALID_PATTERNS:
                errors[f"pours.{i}.pattern"] = "pattern_invalid"

    # sum-of-volumes (skip if ratio invalid or pours missing)
    if (
        denom is not None
        and isinstance(dose, (int, float))
        and not isinstance(dose, bool)
        and isinstance(pours, list)
        and pours
    ):
        expected = round(float(dose) * denom, 1)
        try:
            actual = sum(float(p.get("volume_ml", 0) or 0) for p in pours if isinstance(p, dict))
        except (TypeError, ValueError):
            actual = 0.0
        if abs(actual - expected) > _VOLUME_TOLERANCE_ML:
            errors["pours"] = "volume_total_mismatch"

        # Per-pour volume cap (xBloom app edit limit 0–240 ml per pour).
        for i, p in enumerate(pours):
            if not isinstance(p, dict):
                continue
            v = p.get("volume_ml")
            if (
                not isinstance(v, (int, float))
                or isinstance(v, bool)
                or not (0 <= v <= 240)
            ):
                errors[f"pours.{i}.volume_ml"] = "volume_out_of_range"

    # bypass conditional — 1 = bypass on, 2 = off (BLE/share-URL convention from client.py:_parse_recipe)
    try:
        bypass_on = int(recipe.get("bypass_water_enabled", 2)) == 1
    except (TypeError, ValueError):
        bypass_on = False
    if bypass_on:
        if recipe.get("bypass_volume_ml") in (None, ""):
            errors["bypass_volume_ml"] = "bypass_volume_required"
        if recipe.get("bypass_temp_c") in (None, ""):
            errors["bypass_temp_c"] = "bypass_temp_required"

    return errors
