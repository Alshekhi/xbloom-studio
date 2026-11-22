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
