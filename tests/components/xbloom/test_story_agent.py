"""The request a story agent is sent for a brew, and how its reply is read."""
from __future__ import annotations

from custom_components.xbloom.stories.agent import (
    AGENT_KINDS, build_request, changes_since, parse_reply, slot_key,
)
from custom_components.xbloom.stories.compose import compose
from custom_components.xbloom.stories.plan import plan_slots

from .test_story_compose import BAG, CONTENT, TODAY, _memory, _plan

SETTINGS = {"grind": 48, "ratio": 15.0, "temperature_c": 92.0, "dose_g": 17.0}
STOCKED = {**BAG, "remaining_g": 57, "bag_size_g": 250, "buy_again": "maybe", "roaster_notes": "Grape, orange blossom."}


def _brew(recipe="R", verdict=None, **settings):
    return {"recipe": recipe, "settings": settings, "verdict": verdict, "tasting": {}, "next_change": ""}


async def _texts(bag=BAG, memory=None):
    memory = memory or await _memory()
    plan = _plan()
    return compose(plan_slots(plan, bag is not None), plan, bag, [], memory, CONTENT, TODAY), plan, memory


async def _request(bag=STOCKED, bag_brews=(), rated=(), recipe="R", **kw):
    texts, plan, memory = await _texts(bag=bag)
    return texts, build_request(texts, plan, recipe, SETTINGS, bag, list(bag_brews), list(rated),
                                memory, kw.get("language", "en"))


async def test_only_the_bag_and_closing_slots_are_asked_for():
    texts, (_instructions, structure) = await _request()
    assert set(structure) == {slot_key(s) for s in texts.stories if s.kind in AGENT_KINDS}
    assert "teaser" not in structure and {"wait_1", "draining"} <= set(structure)
    assert all(f["required"] is True and "text" in f["selector"] for f in structure.values())


async def test_stock_fields_never_reach_the_agent():
    _texts_, (instructions, _) = await _request()
    for field in ("remaining_g", "bag_size_g", "buy_again", "maybe"):
        assert field not in instructions
    assert "orange blossom" in instructions and "Kenya" in instructions


async def test_verdicts_are_words():
    _t, (instructions, _) = await _request(bag_brews=[_brew(verdict="not again", grind=50)])
    assert "not again" in instructions and "of 5" not in instructions


async def test_the_change_since_the_last_brew_of_the_same_recipe_is_stated():
    _t, (instructions, _) = await _request(
        bag_brews=[_brew(recipe="Other", grind=40), _brew(recipe="R", grind=50, temperature_c=92.0)])
    changed = instructions.split("Changed since", 1)[1].split("\n\n", 1)[0]
    assert "grind" in changed and "50" in changed and "48" in changed
    assert "temperature_c" not in changed


async def test_a_first_brew_of_the_pair_has_no_change_since_last_time():
    _t, (instructions, _) = await _request(bag_brews=[_brew(recipe="Other", grind=40)])
    assert "first brew of this recipe with this bag" in instructions
    assert "Changed since" not in instructions


def test_a_setting_missing_on_either_side_is_not_a_change():
    assert changes_since({"grind": 50}, {"grind": 50, "ratio": 15}) == {}
    assert changes_since({"grind": 50, "ratio": None}, {"grind": 48, "ratio": 15}) == {"grind": (50, 48)}


async def test_no_rated_history_asks_for_no_pattern():
    _t, (instructions, _) = await _request()
    assert "no rated history" in instructions.lower()


async def test_rated_history_is_listed_for_patterns():
    rated = [{**_brew(verdict="again", temperature_c=93.0), "bag": "Gedeb", "country": "Ethiopia",
              "process": "Natural"}]
    _t, (instructions, _) = await _request(rated=rated)
    assert "Gedeb" in instructions and "again" in instructions


async def test_a_brew_without_a_bag_asks_for_the_closing_line_only():
    texts, (instructions, structure) = await _request(bag=None)
    assert set(structure) == {"draining"} and "no bag" in instructions.lower()


async def test_the_closing_text_ends_on_the_built_in_teaser():
    texts, _ = await _request()
    texts.teaser = {"kind": "fact", "key": "water.plain", "text": "Next cup: something about water."}
    draining = next(s for s in texts.stories if s.at == "draining")
    stories = parse_reply(texts, {"draining": "Two clicks finer.", "wait_1": "Smell it."})
    assert stories[draining][1] == "Two clicks finer. Next cup: something about water."
    assert parse_reply(texts, {"draining": " "})[draining][1] == "Next cup: something about water."
    texts.teaser = None
    assert draining not in parse_reply(texts, {"draining": ""})


async def test_a_reply_text_goes_under_the_built_in_heading():
    texts, _ = await _request()
    bag_slot = next(s for s in texts.stories if s.kind == "bag")
    heading = texts.stories[bag_slot][0]
    assert parse_reply(texts, {"wait_1": " Smell it. "})[bag_slot] == (heading, "Smell it.")
