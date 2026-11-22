"""Which pour and which wait of a brew carries which text.

A story part shows when a wait begins and stays until the next one, so a
wait gets one only when there is time to read it: about 30 s since the last
story began, and before draining replaces it.
"""
from __future__ import annotations

from custom_components.xbloom.stories import MIN_READ_S, POUR_PACE_ML_S
from custom_components.xbloom.stories.plan import Slot, plan_slots


def _plan(waits, volumes):
    return [{"water_ml": float(sum(volumes[: i + 1])), "wait_s": w, "volume_ml": float(v),
             "temperature_c": 92.0, "pattern": "spiral"}
            for i, (w, v) in enumerate(zip(waits, volumes))]


def _windows(plan):
    """Seconds from each wait's start to the next wait's start (draining after the last)."""
    out = []
    for i, pour in enumerate(plan):
        nxt = plan[i + 1]["volume_ml"] / POUR_PACE_ML_S if i + 1 < len(plan) else 0
        out.append(pour["wait_s"] + nxt)
    return out


def _window_until_next(plan, story_waits, pour):
    windows = _windows(plan)
    later = [p for p in story_waits if p > pour]
    end = later[0] - 1 if later else len(plan)
    return sum(windows[pour - 1:end])


def test_every_pour_gets_a_pour_line():
    slots = plan_slots(_plan([35, 10, 10, 10], [45, 85, 75, 68]), has_bag=True)
    assert [s.pour for s in slots if s.kind == "pour_line"] == [1, 2, 3, 4]


def test_the_bloom_wait_tells_the_bag_story_and_draining_the_you_line():
    slots = plan_slots(_plan([35, 20, 20, 10], [45, 85, 75, 68]), has_bag=True)
    assert Slot("wait", 1, "bag") in slots and Slot("draining", 0, "you") in slots


def test_middle_waits_tell_the_big_story_then_science():
    slots = plan_slots(_plan([35, 20, 20, 10], [45, 85, 75, 68]), True)
    assert [s.kind for s in slots if s.at == "wait"] == ["bag", "big_story", "science"]


def test_close_waits_share_one_story():
    plan = _plan([45] + [5] * 7, [45] + [33] * 7)
    story_waits = [s.pour for s in plan_slots(plan, True) if s.at == "wait"]
    assert len(story_waits) < 7
    assert all(_window_until_next(plan, story_waits, p) >= MIN_READ_S for p in story_waits)


def test_a_brew_without_a_bag_tells_the_big_story_at_the_bloom():
    slots = plan_slots(_plan([35, 20, 20, 10], [45, 85, 75, 68]), has_bag=False)
    assert [s.kind for s in slots if s.at == "wait"] == ["big_story", "science", "science"]


def test_slots_come_in_the_order_of_the_brew():
    slots = plan_slots(_plan([35, 20], [45, 85]), True)
    assert slots == [Slot("pour", 1, "pour_line"), Slot("wait", 1, "bag"),
                     Slot("pour", 2, "pour_line"), Slot("draining", 0, "you")]


def test_a_brew_without_a_recipe_gets_a_story_on_the_first_pour_and_draining():
    assert plan_slots(None, True) == [Slot("pour", 1, "bag"), Slot("draining", 0, "you")]
