"""Shared validator + normaliser for xBloom recipes (create, edit, share-URL import).

`validate_recipe` returns a flat dict of field_path -> error_key. Empty = valid.

`normalize_recipe` reconciles the two shapes a recipe can arrive in before
validation. Share-URL imports come straight from the xBloom API via
`client._parse_recipe` and carry `grinder_size`/`rpm` with no `ratio` key,
where `water_ratio` (grandWater) holds the ratio *denominator*. Recipes the
options flow builds carry `ratio`/`grind_size`/`grinder_speed_rpm`, where
`water_ratio` holds *total water in ml*. Validate only ever sees the second
shape, so callers must normalise first.
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


def denom_to_ratio_str(denom: Any) -> str:
    """Format a numeric ratio denominator as '1:N' (no trailing '.0')."""
    d = float(denom)
    if d == int(d):
        return f"1:{int(d)}"
    return f"1:{d:g}"


def snap_ratio_denom(denom: float) -> str:
    """Clamp denom to [5, 25] and round to the nearest 0.5 step."""
    denom = max(_RATIO_DENOM_MIN, min(_RATIO_DENOM_MAX, denom))
    denom = round(denom / _RATIO_DENOM_STEP) * _RATIO_DENOM_STEP
    return denom_to_ratio_str(denom)


def _parse_ratio_denom(ratio_str: Any) -> float | None:
    """Pull the denominator out of a '1:N' string, or None if unparseable."""
    try:
        return float(ratio_str.split(":", 1)[1])
    except (ValueError, IndexError, AttributeError):
        return None


def snap_ratio(ratio_str: str) -> str:
    """Return the nearest valid '1:N' option for any raw ratio string.

    Unparseable input falls back to '1:16' — safe for the options flow, whose
    ratio always comes from a fixed dropdown. Callers accepting arbitrary
    input should use `normalize_recipe`, which preserves a malformed ratio so
    the validator can report `ratio_invalid` instead of silently coercing it.
    """
    denom = _parse_ratio_denom(ratio_str)
    if denom is None:
        return "1:16"
    return snap_ratio_denom(denom)


def guess_ratio(recipe: dict) -> str:
    """Reconstruct '1:N' from dose_g + water_ratio when 'ratio' is absent.

    xBloom's grandWater field is ambiguous: it stores the ratio denominator
    N (e.g. 16.2 for 1:16) in share-URL imports, but total water ml (e.g.
    291.6 for 18 g × 1:16.2) in recipes we create locally.  The two ranges
    are separated at ~26 ml: valid denominators are 5–25, realistic total
    water is always ≥ 25 ml.  Values ≤ 25 are treated as the denominator
    directly; values > 25 are treated as total water and divided by dose.
    """
    try:
        dose = float(recipe.get("dose_g") or 0)
        water = float(recipe.get("water_ratio") or 0)
    except (TypeError, ValueError):
        return "1:16"
    if water <= 0:
        return "1:16"
    if water <= _RATIO_DENOM_MAX:
        denom = water
    elif dose > 0:
        denom = water / dose
    else:
        return "1:16"
    return snap_ratio_denom(denom)


def normalize_recipe(recipe: dict) -> dict:
    """Return a copy in the shape `validate_recipe` expects.

    Fills `ratio` (from an existing value, else inferred from the ambiguous
    grandWater), and mirrors the API's `grinder_size`/`rpm` onto the
    `grind_size`/`grinder_speed_rpm` names. Already-normalised recipes pass
    through with only their ratio snapped to the 0.5 grid. Never mutates the
    input.
    """
    if not isinstance(recipe, dict):
        return recipe
    out = dict(recipe)
    raw_ratio = recipe.get("ratio")
    if raw_ratio in (None, ""):
        # Absent (share-URL import) — infer from the ambiguous grandWater.
        out["ratio"] = guess_ratio(recipe)
    else:
        # Present but malformed: leave it alone so validate_recipe reports
        # `ratio_invalid` rather than having it coerced to a silent default.
        denom = _parse_ratio_denom(raw_ratio)
        out["ratio"] = raw_ratio if denom is None else snap_ratio_denom(denom)
    if out.get("grind_size") is None and recipe.get("grinder_size") is not None:
        out["grind_size"] = recipe["grinder_size"]
    if out.get("grinder_speed_rpm") is None and recipe.get("rpm") is not None:
        out["grinder_speed_rpm"] = recipe["rpm"]
    return out


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
