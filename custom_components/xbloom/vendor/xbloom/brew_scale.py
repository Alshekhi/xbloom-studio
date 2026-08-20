"""One-off brew scaling — override a recipe's dose / ratio / grind for a single
brew (or a "save as new recipe") WITHOUT mutating the stored recipe.

Pure module: no Home Assistant, no I/O — just a dict → dict transform, so it is
trivially testable and reusable by any bridge.

Model (matches how the machine and the app think about it):
    total_water = dose_g × ratio          (ratio = grandWater, the 1:N number)
Each pour keeps its SHARE of the original total and is rescaled to the new
total, so the brew's shape (bloom/pour proportions) is preserved and the ratio
is exact. Temperatures, patterns, flow rates, pauses, agitation, cup type, rpm
— everything else — is carried over untouched. The result feeds
``ble.encode_recipe_blob`` / the start-brew flow directly, and it round-trips
through ``encode_recipe_blob`` byte-identically to what the cloud would build
(verified 2026-07-22).
"""
from __future__ import annotations

from copy import deepcopy


def scaled_total_water(dose_g: float, ratio: float) -> float:
    """Total brew water (ml) for a dose (g) at a ratio (1:N)."""
    return float(dose_g) * float(ratio)


def scale_recipe(
    recipe: dict,
    *,
    dose_g: float,
    ratio: float,
    grind_size: int | None = None,
) -> dict:
    """Return a NEW recipe dict with the pours rescaled to ``dose_g × ratio``.

    Args:
        recipe: an internal recipe dict (``dose_g``, ``water_ratio``,
            ``grinder_size``, ``pours: [{volume_ml, temperature_c, pattern,
            flow_rate, pause_s, agitate_before, agitate_after}, …]``, …).
        dose_g: the new coffee dose in grams.
        ratio: the new brew ratio N (of 1:N).
        grind_size: optional new grind size (UI 1-80); unchanged if None.

    The original dict is never mutated. Per-pour volumes are scaled by
    ``(dose_g × ratio) / Σ(original volumes)`` and rounded to 0.1 ml.
    """
    src_pours = recipe.get("pours") or []
    cur_total = sum(float(p.get("volume_ml", 0) or 0) for p in src_pours)
    new_total = scaled_total_water(dose_g, ratio)
    factor = (new_total / cur_total) if cur_total > 0 else 0.0

    out = deepcopy(recipe)
    out["pours"] = [
        {**deepcopy(p),
         "volume_ml": round(float(p.get("volume_ml", 0) or 0) * factor, 1)}
        for p in src_pours
    ]
    out["dose_g"] = float(dose_g)
    out["water_ratio"] = float(ratio)
    if grind_size is not None:
        out["grinder_size"] = int(grind_size)
    return out
