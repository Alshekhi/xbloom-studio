"""Coffee Lab at runtime: counting a brew once, and the active bag."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from xbloom import spec

from custom_components.xbloom.coffee_lab.lab import CoffeeLab
from custom_components.xbloom.coffee_lab.store import LocalStore, ProcessedRuns, UnknownBean
from custom_components.xbloom.const import CONF_BREWERS, CONF_COFFEE_LAB, CONF_COFFEE_LAB_STORE

from .test_coffee_lab_store import FakeStorage

XPOD = spec.CUP_LABEL_TO_API["xPod"]


async def _lab():
    store = LocalStore(FakeStorage())
    runs = ProcessedRuns(FakeStorage())
    await store.async_load()
    await runs.async_load()
    lab = CoffeeLab(store, runs, FakeStorage(), on_change=MagicMock())
    await lab.async_load_state()
    return lab


async def _bag(lab, **values):
    return await lab.store.async_add_bean(**{
        "name": "Kenya", "status": "unopened", "tracked": True, "remaining_g": 250.0,
        **values,
    })


async def test_a_brew_is_taken_from_its_bag_and_recorded():
    lab = await _lab()
    bag = await _bag(lab)
    result = await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1", recipe="K")
    assert (result.result, result.remaining_g, result.opened) == ("counted", 232.0, True)
    assert (await lab.store.async_get_bean(bag.id)).status == "open"
    [brew] = await lab.store.async_list_brews()
    assert (brew.bean_id, brew.dose_g, brew.run_id, brew.review) == (bag.id, 18.0, "run-1", None)
    lab.on_change.assert_called()


async def test_the_same_completion_twice_counts_once():
    lab = await _lab()
    bag = await _bag(lab)
    await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    again = await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    assert again.result == "skipped" and again.reason == "already_counted"
    assert (await lab.store.async_get_bean(bag.id)).remaining_g == 232.0
    assert len(await lab.store.async_list_brews()) == 1


async def test_two_deliveries_at_once_still_count_once():
    lab = await _lab()
    bag = await _bag(lab, tracked=False, remaining_g=None, status="open")
    real_create = lab.store.async_create_brew

    async def slow_create(brew):
        # A store that waits on the network while writing, as Notion does.
        await asyncio.sleep(0.01)
        return await real_create(brew)

    lab.store.async_create_brew = slow_create
    results = await asyncio.gather(*(
        lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1") for _ in range(2)
    ))
    assert sorted(r.result for r in results) == ["recorded", "skipped"]
    assert len(await lab.store.async_list_brews()) == 1


async def test_a_brew_with_no_bag_is_recorded_for_review_never_guessed():
    lab = await _lab()
    await _bag(lab)
    result = await lab.async_consume(bean_id=None, grams=18, run_id="run-1")
    assert (result.result, result.reason) == ("flagged", "no_bag")
    [brew] = await lab.store.async_list_brews()
    assert brew.bean_id is None and brew.review.reason == "no_bag"


async def test_more_than_is_left_leaves_the_bag_alone():
    lab = await _lab()
    bag = await _bag(lab, remaining_g=10.0, status="open")
    result = await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    assert result.result == "flagged"
    assert (await lab.store.async_get_bean(bag.id)).remaining_g == 10.0
    [brew] = await lab.store.async_list_brews()
    assert brew.bean_id == bag.id and brew.review.reason == "more_than_left"


async def test_an_untracked_bag_s_brew_is_recorded_against_it():
    lab = await _lab()
    bag = await _bag(lab, tracked=False, remaining_g=None, status="open")
    result = await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    assert (result.result, result.reason) == ("recorded", "untracked")
    [brew] = await lab.store.async_list_brews()
    assert brew.bean_id == bag.id


async def test_an_xpod_brew_is_recorded_against_no_bag():
    lab = await _lab()
    bag = await _bag(lab)
    result = await lab.async_consume(bean_id=bag.id, grams=15, run_id="r", cup_type=XPOD)
    assert result.result == "recorded"
    [brew] = await lab.store.async_list_brews()
    assert brew.bean_id is None and brew.dripper == "xPod"
    assert (await lab.store.async_get_bean(bag.id)).remaining_g == 250.0


async def test_the_active_bag_survives_a_restart_and_clears_when_finished():
    state = FakeStorage()
    lab = await _lab()
    lab._state_storage = state
    bag = await _bag(lab, status="open", remaining_g=10.0)
    await lab.async_select(bag.id)
    restarted = CoffeeLab(lab.store, lab._runs, state)
    await restarted.async_load_state()
    assert (await restarted.async_active_bean()).id == bag.id
    await restarted.async_finish(bag.id)
    assert await restarted.async_active_bean() is None


async def test_a_finished_bag_cannot_be_selected():
    lab = await _lab()
    bag = await _bag(lab, status="finished")
    with pytest.raises(UnknownBean):
        await lab.async_select(bag.id)


async def test_two_bags_of_one_name_are_both_offered():
    lab = await _lab()
    await _bag(lab)
    await _bag(lab, status="open")
    await _bag(lab, status="finished")
    assert len(await lab.async_matching("kenya")) == 2


@pytest.mark.parametrize("values, refusal", [
    ({"status": "unopened"}, "bag_unopened"),
    ({"status": "open", "remaining_g": 40.0}, "bag_not_empty"),
    ({"status": "open", "remaining_g": 12.0}, None),
    ({"status": "open", "tracked": False, "remaining_g": None}, None),
])
async def test_when_a_bag_may_be_finished(values, refusal):
    lab = await _lab()
    assert CoffeeLab.finish_refusal(await _bag(lab, **values)) == refusal


async def test_stats_read_the_record():
    lab = await _lab()
    bag = await _bag(lab)
    await lab.async_consume(bean_id=bag.id, grams=18, run_id="r1",
                            brewed_at="2026-09-25T09:00:00+03:00")
    now = datetime(2026, 9, 26, 10, tzinfo=ZoneInfo("Asia/Riyadh"))
    report = await lab.async_stats("last_7_days", now)
    assert (report.now.brews, report.now.coffee_g) == (1, 18.0)


# ── The switch ───────────────────────────────────────────────────────────────


async def test_the_switch_is_in_the_options_menu_and_off_by_default():
    from custom_components.xbloom.config_flow import XBloomOptionsFlow

    entry = MagicMock()
    entry.data = {}
    entry.entry_id = "e1"
    flow = XBloomOptionsFlow(entry)
    flow.config_entry = entry
    flow.hass = MagicMock()
    flow.hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
    flow.hass.config_entries.async_reload = AsyncMock()

    form = await flow.async_step_coffee_lab()
    assert form["step_id"] == "coffee_lab"

    await flow.async_step_coffee_lab(
        {"enable": True, "brewers": ["V60", " ", "Hario Switch", "V60 "]}
    )
    # Blank and repeated brewers dropped, the order kept.
    flow.hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={
            CONF_COFFEE_LAB: True, CONF_BREWERS: ["V60", "Hario Switch"],
            CONF_COFFEE_LAB_STORE: "local",
        }
    )


async def test_a_brew_already_in_the_record_is_not_counted_again():
    # Home Assistant's own list of counted runs can be lost to a restore; the
    # store's record of the brew is the second guard.
    lab = await _lab()
    bag = await _bag(lab)
    await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    lab._runs._run_ids = []
    again = await lab.async_consume(bean_id=bag.id, grams=18, run_id="run-1")
    assert again.result == "skipped"
    assert (await lab.store.async_get_bean(bag.id)).remaining_g == 232.0


async def test_a_bag_finished_by_hand_or_by_a_brew_records_the_day():
    lab = await _lab()
    by_hand = await _bag(lab, status="open", remaining_g=10.0)
    assert (await lab.async_finish(by_hand.id)).finished_on
    by_brew = await _bag(lab, status="open", remaining_g=20.0)
    await lab.async_consume(bean_id=by_brew.id, grams=18, run_id="r")
    after = await lab.store.async_get_bean(by_brew.id)
    assert after.status == "finished" and after.finished_on
