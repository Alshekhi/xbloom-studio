"""Tests for the config-flow recipe wizard (create / edit) added by PR #2.

The load-bearing behaviour here is how pour volumes are recomputed when the
brew step is submitted. The wizard used to flatten every pour to an even split
unconditionally, so merely *stepping through* the edit wizard destroyed a
custom distribution — a 30 ml bloom followed by a 90 ml pour came back as
60/60. PR #2 replaced that with: leave untouched if the total didn't move,
scale proportionally if it did. Both branches are pinned below, because the
regression is silent and only shows up in the cup.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom.config_flow import XBloomOptionsFlow
from xbloom import spec


def _make_flow(draft: dict | None = None):
    coordinator = MagicMock()
    coordinator.data = []
    coordinator.async_refresh = AsyncMock()
    coordinator.async_add_recipe = AsyncMock()
    coordinator.async_replace_recipe = AsyncMock()

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {}
    entry.runtime_data.coordinator = coordinator

    flow = XBloomOptionsFlow(entry)
    flow.config_entry = entry
    flow.hass = MagicMock()
    flow._draft = draft
    return flow, coordinator


def _pours(*volumes: float) -> list[dict]:
    return [
        {
            "id": i, "recipe_id": 0, "name": "", "volume_ml": v,
            "temperature_c": 92.0, "pattern": spec.PATTERN_NAME_TO_API["spiral"],
            "flow_rate": 3.0, "pause_s": 0, "agitate_before": 2, "agitate_after": 2,
        }
        for i, v in enumerate(volumes)
    ]


def _brew_input(**over) -> dict:
    base = {
        "dose_g": 18.0, "ratio": "1:16", "grind_size": 50.0,
        "grinder_speed_rpm": 90, "pour_count": 2,
        "enable_bypass_water": False,
    }
    base.update(over)
    return base


def _total(pours: list[dict]) -> float:
    return round(sum(p["volume_ml"] for p in pours), 1)


# --------------------------------------------------------------------------- #
# _auto_fill_pours — the initial suggestion                                   #
# --------------------------------------------------------------------------- #
def test_auto_fill_total_is_dose_times_ratio() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 3}
    )
    assert _total(pours) == 288.0


def test_auto_fill_splits_evenly() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 20.0, "ratio": "1:15", "pour_count": 3})
    assert [p["volume_ml"] for p in pours] == [100.0, 100.0, 100.0]


def test_auto_fill_absorbs_rounding_drift_into_the_last_pour() -> None:
    """Volumes must sum to the exact total — the machine gates on consistency."""
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 18.0, "ratio": "1:16", "pour_count": 7})
    assert _total(pours) == 288.0


def test_auto_fill_temperature_descends_one_degree_per_pour() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 18.0, "ratio": "1:16", "pour_count": 4})
    assert [p["temperature_c"] for p in pours] == [92.0, 91.0, 90.0, 89.0]


def test_auto_fill_temperature_never_goes_below_the_spec_floor() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 18.0, "ratio": "1:16", "pour_count": 90})
    floor = spec.field("pour_temperature_c").min
    assert all(p["temperature_c"] >= floor for p in pours)


def test_auto_fill_uses_the_spiral_pattern_api_id() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 18.0, "ratio": "1:16", "pour_count": 1})
    assert pours[0]["pattern"] == spec.PATTERN_NAME_TO_API["spiral"]


def test_auto_fill_single_pour_takes_the_whole_total() -> None:
    flow, _ = _make_flow()
    pours = flow._auto_fill_pours({"dose_g": 15.0, "ratio": "1:16", "pour_count": 1})
    assert pours[0]["volume_ml"] == 240.0


# --------------------------------------------------------------------------- #
# The brew step — pour preservation (the PR #2 fix)                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_unchanged_total_leaves_a_custom_distribution_alone() -> None:
    """The regression: stepping through edit must not flatten 30/258 to 144/144."""
    draft = {
        "name": "Bloom heavy", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 2,
        "pours": _pours(30.0, 258.0),
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input())
    assert [p["volume_ml"] for p in flow._draft["pours"]] == [30.0, 258.0]


@pytest.mark.asyncio
async def test_changed_total_scales_pours_proportionally() -> None:
    """Doubling the dose should keep the bloom/pour *shape*, not level it."""
    draft = {
        "name": "Bloom heavy", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 2,
        "pours": _pours(30.0, 258.0),
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input(dose_g=36.0))
    volumes = [p["volume_ml"] for p in flow._draft["pours"]]
    assert _total(flow._draft["pours"]) == 576.0
    # Same 30:258 shape, doubled.
    assert volumes == [60.0, 516.0]


@pytest.mark.asyncio
async def test_changing_the_pour_count_recalculates_from_scratch() -> None:
    """A different number of pours has no old shape to preserve."""
    draft = {
        "name": "R", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 2,
        "pours": _pours(30.0, 258.0),
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input(pour_count=3))
    assert len(flow._draft["pours"]) == 3
    assert _total(flow._draft["pours"]) == 288.0


@pytest.mark.asyncio
async def test_scaled_pours_still_sum_to_the_exact_total() -> None:
    """Proportional scaling introduces rounding — drift goes to the last pour."""
    draft = {
        "name": "R", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 3,
        "pours": _pours(37.0, 111.0, 140.0),
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input(dose_g=21.0, pour_count=3))
    assert _total(flow._draft["pours"]) == round(21.0 * 16, 1)


@pytest.mark.asyncio
async def test_all_zero_pours_fall_back_to_an_even_split() -> None:
    """Degenerate input can't be scaled proportionally (factor would divide by 0)."""
    draft = {
        "name": "R", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 2,
        "pours": _pours(0.0, 0.0),
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input())
    assert _total(flow._draft["pours"]) == 288.0


@pytest.mark.asyncio
async def test_no_existing_pours_are_auto_filled() -> None:
    draft = {
        "name": "R", "cup_type_label": "Omni dripper",
        "ratio": "1:16", "dose_g": 18.0, "pour_count": 2,
    }
    flow, _ = _make_flow(draft)
    flow.async_show_form = MagicMock(return_value={"step_id": "create_recipe_pours"})
    await flow.async_step_create_recipe_brew(_brew_input())
    assert len(flow._draft["pours"]) == 2


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_zero_pours_is_rejected() -> None:
    flow, _ = _make_flow({"name": "R", "cup_type_label": "Omni dripper"})
    shown = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kw: shown.update(kw) or kw)
    await flow.async_step_create_recipe_brew(_brew_input(pour_count=0))
    assert "pour_count" in shown["errors"]


@pytest.mark.asyncio
async def test_bypass_water_requires_a_volume() -> None:
    flow, _ = _make_flow({"name": "R", "cup_type_label": "Omni dripper"})
    shown = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kw: shown.update(kw) or kw)
    await flow.async_step_create_recipe_brew(
        _brew_input(enable_bypass_water=True, bypass_temp_c=90)
    )
    assert "bypass_volume_ml" in shown["errors"]


@pytest.mark.asyncio
async def test_bypass_water_requires_a_temperature() -> None:
    flow, _ = _make_flow({"name": "R", "cup_type_label": "Omni dripper"})
    shown = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kw: shown.update(kw) or kw)
    await flow.async_step_create_recipe_brew(
        _brew_input(enable_bypass_water=True, bypass_volume_ml=50)
    )
    assert "bypass_temp_c" in shown["errors"]


@pytest.mark.asyncio
async def test_bypass_disabled_needs_neither_field() -> None:
    flow, _ = _make_flow({"name": "R", "cup_type_label": "Omni dripper"})
    shown = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kw: shown.update(kw) or kw)
    await flow.async_step_create_recipe_brew(_brew_input(enable_bypass_water=False))
    assert shown.get("errors", {}) == {}


@pytest.mark.asyncio
async def test_name_is_required() -> None:
    flow, _ = _make_flow()
    shown = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kw: shown.update(kw) or kw)
    await flow.async_step_create_recipe(
        {"name": "   ", "cup_type": spec.DEFAULT_CUP_LABEL}
    )
    assert "name" in shown["errors"]


@pytest.mark.asyncio
async def test_name_and_cup_are_stored_on_the_draft() -> None:
    flow, _ = _make_flow()
    flow.async_step_create_recipe_brew = AsyncMock(return_value={"step_id": "brew"})
    await flow.async_step_create_recipe(
        {"name": "  Ethiopia  ", "cup_type": spec.DEFAULT_CUP_LABEL}
    )
    assert flow._draft["name"] == "Ethiopia"
    assert flow._draft["cup_type_label"] == spec.DEFAULT_CUP_LABEL


@pytest.mark.asyncio
async def test_editing_preserves_existing_brew_data() -> None:
    """Renaming a recipe must not wipe its pours."""
    draft = {"name": "Old", "cup_type_label": "Omni dripper", "pours": _pours(30.0)}
    flow, _ = _make_flow(draft)
    flow.async_step_create_recipe_brew = AsyncMock(return_value={"step_id": "brew"})
    await flow.async_step_create_recipe(
        {"name": "New", "cup_type": spec.DEFAULT_CUP_LABEL}
    )
    assert flow._draft["pours"] == _pours(30.0)
    assert flow._draft["name"] == "New"
