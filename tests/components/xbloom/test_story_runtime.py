"""Brew Stories during a brew: what the Brew Story sensor shows, stage by stage."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.sensor import RestoreSensor

from custom_components.xbloom.brew_stage import pour_plan
from custom_components.xbloom.stories.content import Content
from custom_components.xbloom.stories.entities import XBloomBrewStoriesSelect, XBloomBrewStorySensor
from custom_components.xbloom.stories.runtime import HISTORY_BREWS, StoryRuntime

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


async def _runtime(lab=None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data = SimpleNamespace(coffee_lab=lab)
    store = _Store()
    hass = MagicMock()
    hass.config.language = "en"
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


def test_the_select_offers_off_and_built_in():
    assert XBloomBrewStoriesSelect._attr_options == ["off", "built_in"]


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
