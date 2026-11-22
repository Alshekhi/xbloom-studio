"""A brew's pour lines and story parts, written from built-in content."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from custom_components.xbloom.stories.compose import compose
from custom_components.xbloom.stories.content import Content
from custom_components.xbloom.stories.memory import StoryMemory
from custom_components.xbloom.stories.plan import Slot, plan_slots

FIXTURE = Path(__file__).parent / "story_content_fixture"
CONTENT = Content.load("en", FIXTURE)
TODAY = date(2026, 11, 22)
BAG = {"id": "bag-1", "name": "Test Kenya", "country": "Kenya", "altitude_m": 1800,
       "roast_date": "2026-11-13", "opened_on": "2026-11-17", "tracked": True, "remaining_g": 200}


class _Store:
    data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


async def _memory():
    memory = StoryMemory(_Store())
    await memory.async_load()
    return memory


def _plan():
    return [{"water_ml": 45.0, "wait_s": 35, "volume_ml": 45.0, "temperature_c": 92.0, "pattern": "spiral"},
            {"water_ml": 130.0, "wait_s": 20, "volume_ml": 85.0, "temperature_c": 92.0, "pattern": "spiral"},
            {"water_ml": 205.0, "wait_s": 20, "volume_ml": 75.0, "temperature_c": 92.0, "pattern": "spiral"},
            {"water_ml": 273.0, "wait_s": 10, "volume_ml": 68.0, "temperature_c": 92.0, "pattern": "spiral"}]


async def _texts(bag=BAG, history=(), memory=None):
    memory = memory or await _memory()
    plan = _plan()
    return compose(plan_slots(plan, bag is not None), plan, bag, list(history), memory, CONTENT, TODAY)


async def test_each_pour_line_states_that_pours_own_numbers():
    texts = await _texts()
    assert texts.pour_lines[2].startswith("Pour 2: 85 ml at 92 °C in a spiral.")


async def test_the_bloom_story_is_the_bags_next_chapter():
    heading, text = (await _texts()).stories[Slot("wait", 1, "bag")]
    assert heading == "Test Kenya, chapter 1" and text == "Meet Test Kenya."


async def test_a_brew_without_a_bag_tells_the_big_story_first():
    texts = await _texts(bag=None)
    assert texts.stories[Slot("wait", 1, "big_story")] == ("Where it began, still ahead", "One.")
    assert texts.big_story_part_told


async def test_a_bag_part_already_told_is_not_told_again():
    memory = await _memory()
    first = await _texts(memory=memory)
    await memory.async_record_brew("bag-1", told=first.told, facts=first.facts,
                                   big_story_part_told=first.big_story_part_told,
                                   country="Kenya", teaser=first.teaser)
    again = await _texts(history=[{"rating": 4, "next_change": ""}], memory=memory)
    assert again.stories[Slot("wait", 1, "bag")][1] != "Meet Test Kenya."


async def test_the_draining_line_ends_on_a_teaser_that_the_next_brew_opens_with():
    memory = await _memory()
    first = await _texts(memory=memory)
    _heading, you = first.stories[Slot("draining", 0, "you")]
    assert first.teaser and you.endswith(first.teaser["text"])
    await memory.async_record_brew("bag-1", told=first.told, facts=first.facts,
                                   big_story_part_told=first.big_story_part_told,
                                   country="Kenya", teaser=first.teaser)
    second = await _texts(history=[{"rating": None, "next_change": ""}], memory=memory)
    assert first.teaser["key"] in second.facts


async def test_no_text_contains_an_empty_placeholder():
    texts = await _texts(bag={"id": "bag-2", "name": "Only A Name"})
    every = list(texts.pour_lines.values()) + [t for pair in texts.stories.values() for t in pair]
    assert every and not any("{" in t or "None" in t for t in every)


async def test_a_bag_running_low_says_goodbye():
    texts = await _texts(bag={**BAG, "remaining_g": 30},
                         history=[{"rating": None, "next_change": ""}] * 5)
    assert texts.stories[Slot("wait", 1, "bag")][1] == "Goodbye Test Kenya."


async def test_a_chapter_tied_to_no_country_is_never_still_ahead():
    content = Content.load("en", FIXTURE)
    content._data["big_story"]["chapters"][0]["countries"] = []
    memory = await _memory()
    plan = _plan()
    texts = compose(plan_slots(plan, False), plan, None, [], memory, content, TODAY)
    assert texts.stories[Slot("wait", 1, "big_story")][0] == "Where it began"


async def test_a_brew_without_a_bag_counts_no_cups_of_a_bag():
    texts = await _texts(bag=None)
    _heading, you = texts.stories[Slot("draining", 0, "you")]
    assert "of this bag" not in you


def test_altitude_is_counted_in_the_languages_forms():
    from custom_components.xbloom.stories.compose import _values
    ar = Content.load("ar", FIXTURE)
    assert _values({"altitude_m": 1650}, [], ar, TODAY)["altitude"] == "1650 مترًا"
    assert _values({"altitude_m": 1300, "altitude_max_m": 1650}, [], ar, TODAY)["altitude"] == "1300–1650 مترًا"
    assert _values({"altitude_m": 2000}, [], ar, TODAY)["altitude"] == "2000 متر"
    assert _values({"altitude_m": 1800}, [], CONTENT, TODAY)["altitude"] == "1800 metres"


def test_a_day_that_has_not_passed_is_not_told():
    from custom_components.xbloom.stories.compose import _values
    values = _values({"roast_date": TODAY.isoformat(), "opened_on": TODAY.isoformat()}, [], CONTENT, TODAY)
    assert values["days_since_roast"] is None and values["days_since_open"] is None


async def test_a_kept_promise_is_not_promised_again():
    memory = await _memory()
    short = _plan()[:2]
    for _ in range(3):
        texts = compose(plan_slots(short, True), short, BAG, [], memory, CONTENT, TODAY)
        if memory.teaser:
            assert texts.teaser is None or texts.teaser["key"] != memory.teaser["key"]
        await memory.async_record_brew("bag-1", told=texts.told, facts=texts.facts,
                                       big_story_part_told=texts.big_story_part_told,
                                       country="Kenya", teaser=texts.teaser)


async def test_a_promise_nothing_could_show_is_not_marked_seen():
    memory = await _memory()
    await memory.async_record_brew("bag-1", told=[], facts=[], big_story_part_told=False,
                                   country=None, teaser={"kind": "fact", "key": "water.plain", "text": "x"})
    texts = compose(plan_slots(None, True), None, BAG, [], memory, CONTENT, TODAY)
    assert "water.plain" not in texts.facts


async def test_no_brew_tells_the_same_figure_twice():
    from custom_components.xbloom.stories.compose import _values
    content = Content.load("en")
    bag = {**BAG, "remaining_g": 200}
    history = [{"rating": None, "next_change": ""}] * 3
    for brews in range(6):
        memory = await _memory()
        memory._data["brews"] = brews
        # Origin and process told already, so the roast facts come up.
        memory._data["facts_seen"] = [k for k in content.entry("facts")
                                      if k.startswith(("origin.", "process."))]
        plan = _plan()
        texts = compose(plan_slots(plan, True), plan, bag, history, memory, content, TODAY)
        every = " ".join(list(texts.pour_lines.values()) + [t for _h, t in texts.stories.values()])
        values = _values(bag, history, content, TODAY)
        for key in ("days_since_roast", "days_since_open", "altitude"):
            assert every.count(values[key]) <= 1, (brews, key)


async def test_unseen_facts_of_any_topic_come_before_seen_ones():
    content = Content.load("en")
    memory = await _memory()
    memory._data["facts_seen"] = [k for k in content.entry("facts") if k.startswith(("origin.", "process."))]
    plan = _plan()
    texts = compose(plan_slots(plan, True), plan, BAG, [{"rating": None, "next_change": ""}] * 3,
                    memory, content, TODAY)
    assert not {k for k in texts.facts if k.startswith(("origin.", "process."))}
