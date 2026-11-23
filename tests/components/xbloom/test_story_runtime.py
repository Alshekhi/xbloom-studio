"""Brew Stories during a brew: what the Brew Story sensor shows, stage by stage."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.sensor import RestoreSensor

from custom_components.xbloom.brew_stage import pour_plan
from custom_components.xbloom.stories.content import Content
from custom_components.xbloom.stories.entities import (
    XBloomBrewStoriesSelect, XBloomBrewStorySensor, XBloomStoryLanguageSelect)
from custom_components.xbloom.stories import runtime as runtime_module
from custom_components.xbloom.stories.runtime import HISTORY_BREWS, StoryRuntime
from homeassistant.exceptions import HomeAssistantError

from .test_coffee_lab_lab import _bag, _lab

FIXTURE = Path(__file__).parent / "story_content_fixture"
RECIPE = {"pours": [
    {"volume_ml": 45, "pause_s": 35, "temperature_c": 92, "pattern": 2},
    {"volume_ml": 85, "pause_s": 20, "temperature_c": 92, "pattern": 2},
    {"volume_ml": 75, "pause_s": 20, "temperature_c": 92, "pattern": 2},
    {"volume_ml": 68, "pause_s": 10, "temperature_c": 92, "pattern": 2},
]}


class _Store:
    def __init__(self):
        self.data, self.saves = None, 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data, self.saves = data, self.saves + 1


async def _runtime(lab=None, agent=None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"story_agent": "ai_task.test"} if agent is not None else {}
    entry.runtime_data = SimpleNamespace(coffee_lab=lab)
    store = _Store()
    hass = MagicMock()
    hass.config.language = "en"
    entry.async_create_background_task = lambda _hass, coro, _name: asyncio.ensure_future(coro)
    if agent is not None:
        hass.services.async_call = agent
    runtime = StoryRuntime(hass, entry, store=store, content=Content.load("en", FIXTURE))
    await runtime.async_load()
    return runtime, store


async def _started(runtime, bean_id=None):
    data = {"recipe_name": "R", "pours": pour_plan(RECIPE)}
    if bean_id:
        data["bean_id"] = bean_id
    await runtime.async_brew_started(data)


async def test_a_pour_shows_its_line():
    runtime, _ = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("pouring", 2)
    assert runtime.current["now"].startswith("Pour 2: 85 ml")


async def test_a_planned_wait_shows_its_story_and_keeps_it_through_the_next_pour():
    runtime, _ = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    story = runtime.current["story"]
    assert story == "One." and runtime.current["kind"] == "big_story"
    await runtime.async_on_stage("pouring", 2)
    assert runtime.current["story"] == story


async def test_a_bag_brew_tells_the_bag_story_at_the_bloom():
    lab = await _lab()
    bag = await _bag(lab, status="open")
    runtime, _ = await _runtime(lab)
    await _started(runtime, bag.id)
    await runtime.async_on_stage("waiting", 1)
    assert runtime.current["kind"] == "bag" and runtime.current["heading"].endswith("chapter 1")


async def test_draining_shows_the_you_line():
    lab = await _lab()
    bag = await _bag(lab, status="open")
    runtime, _ = await _runtime(lab)
    await _started(runtime, bag.id)
    await runtime.async_on_stage("draining", 4)
    assert runtime.current["kind"] == "you" and runtime.current["story"].startswith("Cup 1")


async def test_done_records_the_brew_once():
    runtime, store = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("done", None)
    await runtime.async_on_stage("done", None)
    assert store.saves == 1 and store.data["brews"] == 1


async def test_idle_clears_what_is_shown():
    runtime, _ = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("idle", None)
    assert runtime.current == {"heading": None, "now": None, "story": None, "kind": None}


async def test_off_shows_nothing():
    runtime, store = await _runtime()
    runtime.mode = "off"
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("done", None)
    assert runtime.current["now"] is None and store.saves == 0


async def test_a_brew_from_the_machines_own_slots_tells_its_story_on_the_first_pour():
    runtime, _ = await _runtime()
    await runtime.async_machine_brew_started()
    await runtime.async_on_stage("pouring", 1)
    assert runtime.current["story"] == "One." and runtime.current["now"] is None


def test_story_sensor_is_not_restored():
    assert not issubclass(XBloomBrewStorySensor, RestoreSensor)


async def test_the_select_offers_agent_only_while_an_agent_is_set():
    runtime, _ = await _runtime()
    select = XBloomBrewStoriesSelect(runtime.entry)
    runtime.entry.runtime_data.stories = runtime
    assert select.options == ["off", "built_in"]
    runtime.set_agent("ai_task.test")
    assert select.options == ["off", "built_in", "agent"]


async def test_clearing_the_agent_while_in_agent_mode_returns_to_built_in():
    runtime, _ = await _runtime(agent=_agent())
    runtime.set_mode("agent")
    runtime.set_agent(None)
    assert runtime.mode == "built_in"


async def test_a_story_written_after_its_wait_began_shows_at_once():
    runtime, _ = await _runtime()
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    await _started(runtime)
    assert runtime.current["story"] == "One."


async def test_a_finished_brews_texts_do_not_show_in_the_next_brew():
    runtime, _ = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("draining", 4)
    await runtime.async_on_stage("done", None)
    shown = dict(runtime.current)
    await runtime.async_on_stage("pouring", 1)
    assert runtime.current == shown


async def test_turning_stories_off_mid_brew_clears_them():
    runtime, store = await _runtime()
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    runtime.set_mode("off")
    assert runtime.current == {"heading": None, "now": None, "story": None, "kind": None}
    await runtime.async_on_stage("pouring", 2)
    await runtime.async_on_stage("done", None)
    assert runtime.current["now"] is None and store.saves == 0


def test_the_language_select_offers_each_language_the_stories_are_written_in():
    written = sorted(p.stem for p in (Path(__file__).parents[3] / "custom_components/xbloom/stories/content").glob("*.json"))
    assert sorted(XBloomStoryLanguageSelect._attr_options) == written == ["ar", "en"]


async def test_stories_start_in_home_assistants_language_if_written_in_it_else_english():
    runtime, _ = await _runtime()
    runtime.hass.config.language = "ar-SA"
    assert runtime._language() == "ar"
    runtime.hass.config.language = "fr"
    assert runtime._language() == "en"


async def test_a_picked_language_is_kept_across_a_restart_and_an_unpicked_one_is_not():
    runtime, store = await _runtime()
    runtime.hass.config.language = "en"
    # Restarted without a pick: Home Assistant's language is still followed.
    again = StoryRuntime(runtime.hass, runtime.entry, store=store)
    await again.async_load()
    runtime.hass.config.language = "ar"
    assert again._language() == "ar"
    await again.async_set_language("en")
    after = StoryRuntime(runtime.hass, runtime.entry, store=store)
    await after.async_load()
    assert after._language() == "en"


async def test_the_cup_count_holds_every_brew_of_the_bag_however_many_others_came_after():
    lab = await _lab()
    bag = await _bag(lab, status="open")
    other = await _bag(lab, name="Other", status="open", remaining_g=5000.0)
    # One by hand from this bag, then more brews of another bag than one page holds.
    await lab.async_consume(bean_id=bag.id, grams=15, run_id="by-hand", brewer="V60")
    for n in range(HISTORY_BREWS + 1):
        await lab.async_consume(bean_id=other.id, grams=15, run_id=f"other-{n}")
    runtime, _ = await _runtime(lab)
    await _started(runtime, bag.id)
    await runtime.async_on_stage("draining", 4)
    assert runtime.current["story"].startswith("Cup 2")


async def test_a_brew_still_waiting_to_be_saved_is_saved_before_the_story_reads_the_bag():
    lab = await _lab()
    bag = await _bag(lab, status="open")
    lab.async_retry_pending = AsyncMock(return_value=0)
    runtime, _ = await _runtime(lab)
    await _started(runtime, bag.id)
    lab.async_retry_pending.assert_awaited_once()


REPLY = {"wait_1": "Agent bag.", "wait_2": "Agent history.", "wait_3": "Agent fact.",
         "draining": "Agent closing.", "teaser": "Next: the rain."}


def _agent(reply=REPLY, gate=None):
    async def call(domain, service, data, **kw):
        if gate is not None:
            await gate.wait()
        if isinstance(reply, Exception):
            raise reply
        return {"data": reply}
    return AsyncMock(side_effect=call)


async def _agent_runtime(lab=None, **kw):
    runtime, store = await _runtime(lab, agent=_agent(**kw))
    runtime.set_mode("agent")
    return runtime, store


async def test_agent_mode_shows_pour_lines_before_the_reply_and_the_agents_story_after():
    gate = asyncio.Event()
    runtime, _ = await _agent_runtime(gate=gate)
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    assert runtime.current["now"].startswith("Pour 1:") and runtime.current["story"] is None
    gate.set()
    await runtime._agent_task
    await runtime.async_on_stage("waiting", 1)
    # No bag: the first story is the big story's.
    assert runtime.current["story"] == "Agent bag." and runtime.current["kind"] == "big_story"


async def test_the_request_is_sent_once_per_brew_and_names_the_agent():
    runtime, _ = await _agent_runtime()
    await _started(runtime)
    await runtime._agent_task
    call = runtime.hass.services.async_call
    call.assert_awaited_once()
    args, kwargs = call.await_args
    assert args[:2] == ("ai_task", "generate_data") and args[2]["entity_id"] == "ai_task.test"
    assert kwargs.get("return_response") is True and kwargs.get("blocking") is True


async def test_a_late_reply_shows_only_the_part_whose_slot_is_running():
    gate = asyncio.Event()
    runtime, _ = await _agent_runtime(gate=gate)
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    await runtime.async_on_stage("pouring", 2)
    await runtime.async_on_stage("waiting", 2)
    gate.set()
    await runtime._agent_task
    assert runtime.current["story"] == "Agent history."


async def test_a_reply_arriving_during_a_pour_shows_the_part_of_the_wait_before_it():
    gate = asyncio.Event()
    runtime, _ = await _agent_runtime(gate=gate)
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    await runtime.async_on_stage("pouring", 2)
    gate.set()
    await runtime._agent_task
    assert runtime.current["story"] == "Agent bag."


async def test_a_reply_for_an_earlier_brew_is_dropped():
    gate = asyncio.Event()
    runtime, _ = await _agent_runtime(gate=gate)
    await _started(runtime)
    first = runtime._agent_task
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    runtime._agent_task.cancel()
    gate.set()
    await asyncio.gather(first, return_exceptions=True)
    assert runtime.current["story"] is None


async def test_an_agent_failure_leaves_pour_lines_and_no_story():
    runtime, _ = await _agent_runtime(reply=HomeAssistantError("down"))
    await _started(runtime)
    await runtime._agent_task
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    assert runtime.current["now"].startswith("Pour 1:") and runtime.current["story"] is None


async def test_a_timeout_is_a_failure(monkeypatch):
    monkeypatch.setattr(runtime_module, "AGENT_TIMEOUT_S", 0.01)
    runtime, _ = await _agent_runtime(gate=asyncio.Event())
    await _started(runtime)
    await runtime._agent_task
    await runtime.async_on_stage("waiting", 1)
    assert runtime.current["story"] is None


async def test_an_agent_brew_records_its_texts_and_teaser_not_built_in_facts():
    lab = await _lab()
    bag = await _bag(lab, status="open")
    runtime, _ = await _agent_runtime(lab)
    await _started(runtime, bag.id)
    await runtime._agent_task
    await runtime.async_on_stage("draining", 4)
    await runtime.async_on_stage("done", None)
    memory = runtime.memory
    assert memory.agent_told(bag.id) == [
        "Agent bag.", "Agent history.", "Agent fact.", "Agent closing. Next: the rain."]
    assert memory.teaser == {"kind": "agent", "key": None, "text": "Next: the rain."}
    assert memory.facts_seen == set()


async def test_without_an_agent_set_agent_mode_shows_pour_lines_only():
    runtime, _ = await _runtime()
    runtime.mode = "agent"
    await _started(runtime)
    await runtime._agent_task
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    assert runtime.current["now"].startswith("Pour 1:") and runtime.current["story"] is None
    runtime.hass.services.async_call.assert_not_called()


async def test_a_late_reply_that_left_the_running_slot_empty_shows_nothing():
    gate = asyncio.Event()
    runtime, _ = await _agent_runtime(reply={**REPLY, "wait_2": ""}, gate=gate)
    await _started(runtime)
    await runtime.async_on_stage("pouring", 1)
    await runtime.async_on_stage("waiting", 1)
    await runtime.async_on_stage("pouring", 2)
    await runtime.async_on_stage("waiting", 2)
    gate.set()
    await runtime._agent_task
    assert runtime.current["story"] is None


async def test_a_new_brew_cancels_the_last_brews_request():
    runtime, _ = await _agent_runtime(gate=asyncio.Event())
    await _started(runtime)
    first = runtime._agent_task
    await _started(runtime)
    await asyncio.sleep(0)
    assert first.cancelled()
    runtime._agent_task.cancel()
