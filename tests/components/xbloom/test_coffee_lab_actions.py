"""Coffee Lab's actions, its completion listener, and its AI tool."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import llm_api, tool_coffee_lab
from custom_components.xbloom.coffee_lab import actions
from custom_components.xbloom.coffee_lab.listener import async_count_completed_brews

from .test_coffee_lab_lab import _bag, _lab


async def _refused(coro) -> str:
    with pytest.raises(HomeAssistantError) as caught:
        await coro
    return caught.value.translation_key


# ── Which bag a name means ───────────────────────────────────────────────────


async def test_a_name_shared_by_two_bags_is_refused_not_guessed():
    lab = await _lab()
    await _bag(lab)
    await _bag(lab, status="open")
    assert await _refused(actions.set_active_bean(lab, {"bean": "kenya"})) == "bag_ambiguous"


async def test_an_id_settles_a_shared_name():
    lab = await _lab()
    await _bag(lab)
    second = await _bag(lab, status="open")
    facts = await actions.set_active_bean(lab, {"bean_id": second.id})
    assert facts["active_bag"]["id"] == second.id


async def test_a_finished_bag_is_not_found_for_brewing():
    lab = await _lab()
    await _bag(lab, status="finished")
    assert await _refused(actions.set_active_bean(lab, {"bean": "Kenya"})) == "bag_not_found"


async def test_a_finished_bag_can_still_be_corrected():
    lab = await _lab()
    bag = await _bag(lab, status="finished")
    facts = await actions.update_bean(lab, {"bean": "Kenya", "roaster": "Somewhere"})
    assert facts["updated"]["id"] == bag.id and facts["updated"]["roaster"] == "Somewhere"


# ── Changing ─────────────────────────────────────────────────────────────────


async def test_a_bag_added_with_an_amount_is_counted_down():
    lab = await _lab()
    facts = await actions.add_bean(lab, {"name": "Kenya", "remaining_g": 250.0})
    assert facts["added"]["tracked"] and facts["added"]["remaining_g"] == 250.0
    assert facts["added"]["status"] == "unopened"


async def test_a_bag_added_without_an_amount_is_not_counted():
    lab = await _lab()
    facts = await actions.add_bean(lab, {"name": "Kenya"})
    assert not facts["added"]["tracked"] and facts["added"]["remaining_g"] is None


async def test_coffee_used_elsewhere_is_never_recorded_as_the_xbloom():
    lab = await _lab()
    await _bag(lab)
    await actions.consume(lab, {"bean": "Kenya", "grams": 15.0})
    [brew] = await lab.store.async_list_brews()
    assert brew.brewer is None


@pytest.mark.parametrize("values, refusal", [
    ({"status": "unopened"}, "bag_unopened"),
    ({"status": "open", "remaining_g": 40.0}, "bag_not_empty"),
])
async def test_finishing_a_bag_that_is_not_empty_is_refused(values, refusal):
    lab = await _lab()
    await _bag(lab, **values)
    assert await _refused(actions.finish_bag(lab, {"bean": "Kenya"})) == refusal


# ── Counting a completed brew ────────────────────────────────────────────────


class Bus:
    def __init__(self):
        self.listeners = {}

    def async_listen(self, event_type, cb):
        self.listeners[event_type] = cb
        return lambda: self.listeners.pop(event_type)

    async def fire(self, event_type, data):
        await self.listeners[event_type](SimpleNamespace(data=data))


async def _listening():
    lab = await _lab()
    bus = Bus()
    stop = async_count_completed_brews(SimpleNamespace(bus=bus), lab)
    return lab, bus, stop


COMPLETION = {
    "run_id": "run-1", "recipe_name": "K", "dose_g": 18, "cup_type": 2,
    "outcome": "presumed", "ended_at": "2026-09-26T07:00:00+00:00",
    "grind": 55, "water_ml": 288.0, "ratio": 16.0, "temperature_c": None,
}


async def test_a_completion_counts_against_the_bag_it_started_with():
    lab, bus, _stop = await _listening()
    bag = await _bag(lab)
    await bus.fire("xbloom_brew_completed", {**COMPLETION, "bean_id": bag.id})
    assert (await lab.store.async_get_bean(bag.id)).remaining_g == 232.0
    [brew] = await lab.store.async_list_brews()
    assert (brew.outcome, brew.water_ml) == ("presumed", 288.0)
    assert brew.settings == {"grind": 55, "water_ml": 288.0, "ratio": 16.0}


async def test_an_unattributed_brew_is_recorded_without_a_flag():
    lab, bus, _stop = await _listening()
    await bus.fire("xbloom_brew_completed", {**COMPLETION, "unattributed": True})
    [brew] = await lab.store.async_list_brews()
    assert brew.bean_id is None and brew.review is None


async def test_a_completion_with_no_bag_is_recorded_for_review():
    lab, bus, _stop = await _listening()
    await bus.fire("xbloom_brew_completed", COMPLETION)
    [brew] = await lab.store.async_list_brews()
    assert brew.review.reason == "no_bag"


async def test_only_a_finished_brew_is_counted():
    lab, bus, _stop = await _listening()
    await bus.fire("xbloom_brew_completed", {**COMPLETION, "outcome": None})
    assert await lab.store.async_list_brews() == []


# ── The tool ─────────────────────────────────────────────────────────────────


async def test_the_description_names_the_bags_there_are_now():
    lab = await _lab()
    await _bag(lab)
    text = tool_coffee_lab.describe(await lab.store.async_list_beans())
    assert "Kenya (unopened)" in text


@pytest.mark.parametrize("action", list(tool_coffee_lab.ACTIONS))
def test_each_action_line_names_what_it_needs(action):
    [line] = [l for l in tool_coffee_lab.describe([]).splitlines() if l.startswith(f"- {action}:")]
    spec = tool_coffee_lab.ACTIONS[action]
    for name in spec.requires + spec.one_of:
        assert name in line


async def test_the_tool_refuses_a_call_without_its_bag():
    lab = await _lab()
    assert await _refused(tool_coffee_lab.run(lab, "consume", {"grams": 10.0})) == "missing_arguments"


async def test_the_tool_marks_what_it_records_as_its_own():
    lab = await _lab()
    await _bag(lab)
    await tool_coffee_lab.run(lab, "consume", {"bean": "Kenya", "grams": 10.0, "brewer": "V60"})
    [brew] = await lab.store.async_list_brews()
    assert (brew.brewer, brew.recipe_source) == ("V60", "assistant")


async def test_with_coffee_lab_on_there_are_two_tools_and_the_bag_rule():
    lab = await _lab()
    entry = SimpleNamespace(runtime_data=SimpleNamespace(coffee_lab=lab))
    instance = await llm_api.XBloomAPI(MagicMock(), entry).async_get_api_instance(MagicMock())
    assert [t.name for t in instance.tools] == ["xbloom", "coffee_lab"]
    assert "bean" in instance.tools[0].description
