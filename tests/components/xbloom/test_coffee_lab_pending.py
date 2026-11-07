"""Brews that cannot reach the store wait in Home Assistant (coffee_lab/pending.py).

A store kept in Notion can fail at any of its writes. These tests fail it on
purpose — at reading the bag, at writing the bag, at writing the row — and
check the brew is kept, retried, and in the end counted exactly once.
"""
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.coffee_lab.lab import CoffeeLab
from custom_components.xbloom.coffee_lab.pending import PendingBrews
from custom_components.xbloom.coffee_lab.store import LocalStore, ProcessedRuns

from .test_coffee_lab_store import FakeStorage


class FlakyStore(LocalStore):
    """A local store that refuses chosen writes until told it is back."""

    def __init__(self, storage) -> None:
        super().__init__(storage)
        self.down: set[str] = set()

    def _check(self, method: str) -> None:
        if method in self.down:
            raise HomeAssistantError(f"{method}: store unreachable")

    async def async_get_bean(self, bean_id):
        self._check("get_bean")
        return await super().async_get_bean(bean_id)

    async def async_apply_bean_update(self, *args, **kwargs):
        self._check("bean_update")
        return await super().async_apply_bean_update(*args, **kwargs)

    async def async_create_brew(self, brew):
        self._check("create_brew")
        return await super().async_create_brew(brew)


async def _lab(pending_storage=None):
    store = FlakyStore(FakeStorage())
    runs = ProcessedRuns(FakeStorage())
    pending = PendingBrews(pending_storage or FakeStorage())
    await store.async_load()
    await runs.async_load()
    await pending.async_load()
    lab = CoffeeLab(store, runs, FakeStorage(), on_change=MagicMock(), pending=pending)
    await lab.async_load_state()
    bag = await store.async_add_bean(name="Kenya", status="open", tracked=True, remaining_g=100.0)
    return lab, store, bag


async def _remaining(store, bag):
    return (await store.async_get_bean(bag.id)).remaining_g


@pytest.mark.parametrize("failing", ["get_bean", "bean_update", "create_brew"])
async def test_a_brew_the_store_refuses_waits_and_is_counted_once(failing):
    lab, store, bag = await _lab()
    store.down = {failing}
    result = await lab.async_consume(bean_id=bag.id, grams=17, run_id="manual-1", brewer="V60")
    assert result.result == "queued" and failing in result.reason
    assert len(lab.pending) == 1
    assert lab.last_count["result"] == "queued"

    # Still down: retrying changes nothing and keeps it.
    assert await lab.async_retry_pending() == 1

    store.down = set()
    assert await lab.async_retry_pending() == 0
    assert await _remaining(store, bag) == 83.0, "taken from the bag exactly once"
    assert lab.last_count["result"] == "counted", "no longer shown as waiting"
    [brew] = await store.async_list_brews()
    assert (brew.run_id, brew.dose_g, brew.brewer) == ("manual-1", 17.0, "V60")


async def test_the_time_of_a_waiting_brew_is_when_it_happened():
    lab, store, bag = await _lab()
    store.down = {"get_bean"}
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="manual-1")
    queued = lab.pending.oldest["args"]["brewed_at"]
    store.down = set()
    await lab.async_retry_pending()
    [brew] = await store.async_list_brews()
    assert brew.brewed_at == queued


async def test_a_brew_reported_without_an_id_gets_one_and_is_written_once():
    lab, store, bag = await _lab()
    store.down = {"create_brew"}
    await lab.async_consume(bean_id=bag.id, grams=17, run_id=None, brewer="V60")
    store.down = set()
    await lab.async_retry_pending()
    await lab.async_retry_pending()
    [brew] = await store.async_list_brews()
    assert brew.run_id.startswith("lab-")
    assert await _remaining(store, bag) == 83.0


async def test_brews_wait_in_order_behind_one_that_cannot_be_counted():
    lab, store, bag = await _lab()
    store.down = {"get_bean"}
    first = await lab.async_consume(bean_id=bag.id, grams=10, run_id="a")
    store.down = set()
    # The store is back, but the new brew still goes after the waiting one.
    second = await lab.async_consume(bean_id=bag.id, grams=20, run_id="b")
    assert (first.result, second.result) == ("queued", "counted")
    assert second.remaining_g == 70.0, "the first brew was counted before it"
    assert [b.run_id for b in await store.async_list_brews()] in (["a", "b"], ["b", "a"])
    assert len(lab.pending) == 0


async def test_a_second_delivery_of_a_waiting_brew_is_refused():
    lab, store, bag = await _lab()
    store.down = {"get_bean"}
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="run-1")
    again = await lab.async_consume(bean_id=bag.id, grams=17, run_id="run-1")
    assert (again.result, again.reason) == ("skipped", "already_queued")
    assert len(lab.pending) == 1


async def test_waiting_brews_survive_a_restart():
    storage = FakeStorage()
    lab, store, bag = await _lab(storage)
    store.down = {"bean_update"}
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="run-1")
    reloaded = PendingBrews(storage)
    await reloaded.async_load()
    assert [e["run_id"] for e in reloaded.entries] == ["run-1"]


async def test_a_stopped_brew_waits_too():
    lab, store, bag = await _lab()
    store.down = {"create_brew"}
    result = await lab.async_record_stopped(bean_id=bag.id, grams=17, run_id="stop-1")
    assert result.result == "queued"
    store.down = set()
    await lab.async_retry_pending()
    [brew] = await store.async_list_brews()
    assert (brew.run_id, brew.outcome) == ("stop-1", "stopped")
    assert await _remaining(store, bag) == 100.0, "a stopped brew leaves the bag alone"


async def test_a_brew_that_cannot_be_counted_does_not_hold_back_the_next():
    """A fault in this code, not the store, is kept but stepped past."""
    lab, store, bag = await _lab()
    real_create = store.async_create_brew

    async def broken_once(brew):
        if brew.run_id == "bad":
            raise KeyError("bug")
        return await real_create(brew)

    store.async_create_brew = broken_once
    bad = await lab.async_consume(bean_id=None, grams=17, run_id="bad")
    good = await lab.async_consume(bean_id=bag.id, grams=20, run_id="good")
    assert bad.result == "queued" and "KeyError" in bad.reason
    assert good.result == "counted"
    assert [e["run_id"] for e in lab.pending.entries] == ["bad"]


# ── Before the queue: the bag must not have to be read ───────────────────────
#
# Found by cutting Home Assistant off from Notion on a real install: the manual
# brew button and an agent's report both read the bag before counting, so with
# the store down they failed before the brew was ever queued.

from custom_components.xbloom.coffee_lab import actions  # noqa: E402


async def test_a_manual_brew_is_queued_when_the_bag_cannot_be_read():
    lab, store, bag = await _lab()
    await lab.async_select(bag.id)
    await lab.async_set_manual_dose(17)
    store.down = {"get_bean"}
    facts = await actions.record_manual_brew(lab, {})
    assert facts["result"] == "queued"
    assert lab.pending.oldest["args"]["bean_id"] == bag.id
    store.down = set()
    await lab.async_retry_pending()
    assert await _remaining(store, bag) == 83.0


async def test_a_reported_brew_by_bag_id_is_queued_when_the_bag_cannot_be_read():
    lab, store, bag = await _lab()
    store.down = {"get_bean"}
    facts = await actions.consume(lab, {"bean_id": bag.id, "grams": 17, "brewer": "V60"})
    assert facts["result"] == "queued"


async def test_a_reported_brew_by_name_needs_the_store_to_find_the_bag():
    lab, store, bag = await _lab()

    async def down(**kwargs):
        raise HomeAssistantError("store unreachable")

    store.async_list_beans = down
    with pytest.raises(HomeAssistantError):
        await actions.consume(lab, {"bean": "Kenya", "grams": 17})
    assert len(lab.pending) == 0


async def test_an_unknown_bag_is_still_refused():
    from homeassistant.exceptions import ServiceValidationError

    lab, store, bag = await _lab()
    with pytest.raises(ServiceValidationError):
        await actions.consume(lab, {"bean_id": "no-such-bag", "grams": 17})
