"""The request a story agent is sent for a brew, and how its reply is read."""
from __future__ import annotations

from custom_components.xbloom.stories.agent import build_request, parse_reply, slot_key
from custom_components.xbloom.stories.compose import compose
from custom_components.xbloom.stories.plan import plan_slots

from .test_story_compose import BAG, CONTENT, TODAY, _memory, _plan


async def _texts(bag=BAG, memory=None):
    memory = memory or await _memory()
    plan = _plan()
    return compose(plan_slots(plan, bag is not None), plan, bag, [], memory, CONTENT, TODAY), plan, memory


async def test_the_structure_asks_one_text_per_story_slot_and_a_teaser():
    texts, plan, memory = await _texts()
    _instructions, structure = build_request(texts, plan, BAG, [], memory, "en")
    assert set(structure) == {slot_key(s) for s in texts.stories} | {"teaser"}
    assert all(f["required"] is True and "text" in f["selector"] for f in structure.values())


async def test_the_request_carries_the_bag_the_told_texts_the_teaser_and_the_language():
    memory = await _memory()
    await memory.async_record_brew("bag-1", told=[], facts=[], big_story_part_told=False,
                                   country=None, teaser={"kind": "agent", "key": None,
                                                         "text": "Next: the rain."},
                                   agent_texts=["The hills were green."])
    texts, plan, _ = await _texts(memory=memory)
    instructions, _ = build_request(texts, plan, BAG, [{"rating": 4, "next_change": ""}], memory, "ar")
    for expected in ("Kenya", "1800", "The hills were green.", "Next: the rain.",
                     "Modern Standard Arabic"):
        assert expected in instructions


async def test_a_brew_without_a_bag_asks_for_no_bag_part():
    texts, plan, memory = await _texts(bag=None)
    instructions, structure = build_request(texts, plan, None, [], memory, "en")
    assert not any(s.kind == "bag" and slot_key(s) in structure for s in texts.stories)
    assert "no bag" in instructions.lower()


async def test_the_reply_keeps_the_built_in_heading_and_takes_the_agents_text():
    texts, _plan_, _ = await _texts()
    slot, (heading, _text) = next(iter(texts.stories.items()))
    stories, teaser = parse_reply(texts, {slot_key(slot): " Hello. ", "teaser": "Next: water."})
    assert stories[slot] == (heading, "Hello.")
    assert teaser == {"kind": "agent", "key": None, "text": "Next: water."}


async def test_an_empty_or_missing_field_gives_no_part_for_that_slot():
    texts, _plan_, _ = await _texts()
    first, second = list(texts.stories)[:2]
    stories, teaser = parse_reply(texts, {slot_key(first): "  ", "teaser": ""})
    assert first not in stories and second not in stories and teaser is None


async def test_the_teaser_ends_the_draining_text_and_stands_alone_if_the_line_is_empty():
    texts, _plan_, _ = await _texts()
    draining = next(s for s in texts.stories if s.at == "draining")
    stories, _ = parse_reply(texts, {"draining": "Enjoy it.", "teaser": "Next: water."})
    assert stories[draining][1] == "Enjoy it. Next: water."
    stories, _ = parse_reply(texts, {"draining": "", "teaser": "Next: water."})
    assert stories[draining][1] == "Next: water."
