"""Versions of a recipe with a bag (versions.py): side by side, next time, keep."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from . import test_init as _ti  # noqa: F401

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import versions
from custom_components.xbloom.coffee_lab.models import Brew
from custom_components.xbloom.versions import (
    VersionDesk, parse_next_change, pending_change, versions_of,
)

from .test_coffee_lab_rating import _brew, _lab


def brew(when, grind, rating=None, next_change="", bean="bag", recipe="Test Hot", dose=15.0):
    return Brew(id=when, brewed_at=when, recorded_at=when, dose_g=dose, bean_id=bean,
                recipe=recipe, settings={"grind": grind, "ratio": 16}, rating=rating,
                next_change=next_change)


# The parser's own Arabic words, so a note in Arabic is tested without one
# being written here.
GRIND, RATIO = versions.WORDS["grind"][1], versions.WORDS["ratio"][1]
TO = versions.TO_WORDS[1]


@pytest.mark.parametrize(("text", "found"), [
    ("grind 52", {"grind": 52.0}),
    ("a bit coarser, grind 52.5 and ratio 1:15", {"grind": 52.5, "ratio": 15.0}),
    ("dose 18 g", {"dose_g": 18.0}),
    (f"{GRIND} 56, {RATIO} 1:16", {"grind": 56.0, "ratio": 16.0}),
    ("more fruit next time", {}),
    ("grind from 55 to 56", {"grind": 56.0}),
    (f"only the {GRIND}, 55 {TO} 56, keeping 20 g", {"grind": 56.0}),
    ("ratio 1:15 → 1:16", {"ratio": 16.0}),
    ("longer duration 3, aeration 2", {}),
    ("grind finer, grind 52", {"grind": 52.0}),
    (f"{GRIND} \u0661\u0668\u066b\u0665", {"grind": 18.5}),
])
def test_a_next_time_note_is_read_for_its_settings(text, found):
    assert parse_next_change(text) == found


def test_rated_versions_are_side_by_side_newest_first():
    brews = [brew("3", "52", 3), brew("2", "50", 2), brew("1", "50", 1), brew("0", "54")]
    assert versions_of(brews, "test hot", "bag") == [
        {"grind": 52.0, "ratio": 16.0, "dose_g": 15.0, "verdict": "again", "brews": 1},
        {"grind": 50.0, "ratio": 16.0, "dose_g": 15.0, "verdict": "fine", "brews": 2},
    ]


def test_only_the_latest_brew_s_change_is_offered():
    assert pending_change([brew("2", "50", next_change="grind 52")], "Test Hot", "bag")["settings"] == {"grind": 52.0}
    # The brew after it followed the change and asked for nothing more.
    assert pending_change([brew("3", "52"), brew("2", "50", next_change="grind 52")], "Test Hot", "bag") is None
    assert pending_change([brew("2", "50", next_change="grind 52", bean="other")], "Test Hot", "bag") is None


# ── The desk: using the change, keeping the version ──────────────────────────


def _desk(lab, library):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coordinator = SimpleNamespace(data=library, async_add_recipe=AsyncMock(), async_replace_recipe=AsyncMock())
    registry = MagicMock()
    registry.async_get_entity_id = lambda platform, domain, uid: f"{platform}.{uid}"
    return VersionDesk(hass, "e", lab, coordinator), hass, coordinator, registry


SAVED = {"id": "77", "name": "Test Hot", "dose_g": 15.0, "water_ratio": 16.0, "grinder_size": 50,
         "grinder_size_enabled": 1, "rpm": 90, "pour_count": 1, "cup_type": 2,
         "pours": [{"volume_ml": 240.0, "temperature_c": 92, "pattern": 2, "flow_rate": 3.0,
                    "pause_s": 0, "agitate_before": 2, "agitate_after": 2}]}


async def test_use_next_change_sets_the_one_off_adjustments_only():
    lab, store, bag = await _lab()
    desk, hass, coordinator, registry = _desk(lab, [SAVED])
    desk.next_change = {"text": "grind 52", "settings": {"grind": 52.0}}
    with patch.object(versions.er, "async_get", return_value=registry):
        await desk.async_use_next_change()
    calls = [(c.args[0], c.args[1], c.args[2]) for c in hass.services.async_call.await_args_list]
    assert calls == [
        ("switch", "turn_on", {"entity_id": "switch.xbloom_use_grinder"}),
        ("number", "set_value", {"entity_id": "number.xbloom_brew_grind", "value": 52.0}),
    ]
    coordinator.async_replace_recipe.assert_not_awaited()


async def test_use_without_a_next_change_is_refused():
    lab, store, bag = await _lab()
    desk, *_ = _desk(lab, [SAVED])
    with pytest.raises(HomeAssistantError):
        await desk.async_use_next_change()


async def test_a_changed_version_rated_again_is_offered_and_fine_is_not():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="52")
    await lab.async_rate(verdict="fine")
    assert lab.version_to_keep is None
    await _brew(lab, bag, "run-2", grind="54")
    await lab.async_rate(verdict="again")
    keep = lab.version_to_keep
    assert (keep["recipe"], keep["label"]) == ("Test Hot", "grind 54")


@pytest.mark.parametrize("as_new", [True, False])
async def test_keeping_a_version_rescales_the_saved_recipe(as_new):
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="54")
    await lab.async_rate(verdict="again")
    desk, hass, coordinator, registry = _desk(lab, [SAVED])
    name = await desk.async_keep_version(as_new=as_new)
    if as_new:
        [kept] = coordinator.async_add_recipe.await_args.args
        assert name == "Test Hot (grind 54)" and "id" not in kept
    else:
        [kept] = coordinator.async_replace_recipe.await_args.args
        assert name == "Test Hot" and kept["id"] == "77"
    assert kept["grinder_size"] == 54
    assert lab.version_to_keep is None
