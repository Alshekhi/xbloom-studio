"""The story content: filled only from what is known, counted words right."""
from __future__ import annotations

from pathlib import Path

from custom_components.xbloom.stories.content import Content

FIXTURE = Path(__file__).parent / "story_content_fixture"
CONTENT = Content.load("en", FIXTURE)
VALUES = {"days_since_roast": "9 days", "days_since_open": "5 days"}


def test_a_template_with_every_value_is_filled():
    assert CONTENT.fill("Grown at {altitude} m", {"altitude": "1800"}) == "Grown at 1800 m"


def test_a_template_missing_a_value_is_not_filled():
    assert CONTENT.fill("Grown at {altitude} m", {}) is None
    assert CONTENT.fill("Grown at {altitude} m", {"altitude": None}) is None


def test_a_fact_needing_an_unknown_value_is_never_chosen():
    key, text = CONTENT.pick_fact("bloom", {"days_since_roast": None, "days_since_open": "5 days"}, set(), 1)
    assert key == "bloom.open"
    assert "None" not in text and "{" not in text


def test_seen_facts_are_skipped_until_none_are_left():
    first, _ = CONTENT.pick_fact("bloom", VALUES, set(), 1)
    second, _ = CONTENT.pick_fact("bloom", VALUES, {first}, 1)
    assert second != first
    again, _ = CONTENT.pick_fact("bloom", VALUES, {first, second}, 1)
    assert again in (first, second)


def test_facts_above_the_level_are_not_chosen():
    seen: set[str] = set()
    for _ in range(4):
        key, _text = CONTENT.pick_fact("bloom", VALUES, seen, 1)
        seen.add(key)
    assert "bloom.deep" not in seen
    assert CONTENT.pick_fact("bloom", VALUES, {"bloom.co2", "bloom.open"}, 2)[0] == "bloom.deep"


def test_a_topic_with_nothing_to_say_gives_nothing():
    assert CONTENT.pick_fact("no_such_topic", VALUES, set(), 3) is None


def test_arabic_counts_take_the_right_form():
    ar = Content.load("ar", FIXTURE)
    assert [ar.count(n, "day") for n in (1, 2, 3, 11, 100, 101)] == [
        "يوم واحد", "يومان", "3 أيام", "11 يومًا", "100 يوم", "101 يوم"]


def test_english_counts():
    assert [CONTENT.count(n, "day") for n in (1, 2)] == ["1 day", "2 days"]


def test_a_language_without_a_file_falls_back_to_english():
    assert Content.load("fr", FIXTURE).count(2, "day") == "2 days"


def test_entries_are_reached_by_path():
    assert CONTENT.entry("big_story.chapters")[0]["key"] == "ethiopia"
    assert CONTENT.entry("bag.intro") == ["Meet {name}."]
