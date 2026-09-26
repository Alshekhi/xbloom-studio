"""Coffee Lab's own store, and the guard against counting a brew twice."""
from datetime import datetime, timezone

import pytest

from custom_components.xbloom.coffee_lab.models import Brew, Review
from custom_components.xbloom.coffee_lab.store import (
    KEEP_RUN_IDS, LocalStore, ProcessedRuns, UnknownBean,
)


class FakeStorage:
    """Home Assistant's Store: what was last saved is what the next load reads."""

    def __init__(self, data=None):
        self.data = data
        self.saves = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.saves += 1


async def _store(storage=None):
    store = LocalStore(storage or FakeStorage())
    await store.async_load()
    return store


async def test_a_bag_survives_a_restart():
    storage = FakeStorage()
    store = await _store(storage)
    added = await store.async_add_bean(name="Kenya", status="unopened", bag_size_g=250.0)
    again = await _store(storage)
    assert await again.async_get_bean(added.id) == added


async def test_only_open_and_unopened_bags_can_be_brewed_from():
    store = await _store()
    for status in ("open", "unopened", "finished", "archived"):
        await store.async_add_bean(name=status, status=status)
    assert {b.name for b in await store.async_list_beans()} == {"open", "unopened"}
    assert len(await store.async_list_beans(selectable_only=False)) == 4


async def test_two_bags_may_share_a_name():
    store = await _store()
    a = await store.async_add_bean(name="Kenya", status="open")
    b = await store.async_add_bean(name="Kenya", status="open")
    assert a.id != b.id


async def test_a_bag_s_id_cannot_be_changed_nor_an_unknown_field_set():
    store = await _store()
    bean = await store.async_add_bean(name="Kenya", status="open")
    with pytest.raises(ValueError):
        await store.async_update_bean(bean.id, id="other")
    with pytest.raises(ValueError):
        await store.async_update_bean(bean.id, colour="red")


async def test_an_unknown_bag_is_an_error_not_none():
    with pytest.raises(UnknownBean):
        await (await _store()).async_get_bean("missing")


async def test_first_use_opens_the_bag_on_that_day():
    store = await _store()
    bean = await store.async_add_bean(name="K", status="unopened", tracked=True, remaining_g=250.0)
    after = await store.async_apply_bean_update(
        bean.id, remaining_g=230.0, open_bag=True, finish=False, today="2026-09-26"
    )
    assert (after.status, after.remaining_g, after.opened_on) == ("open", 230.0, "2026-09-26")


async def test_finishing_wins_over_opening():
    store = await _store()
    bean = await store.async_add_bean(name="K", status="unopened", tracked=True, remaining_g=20.0)
    after = await store.async_apply_bean_update(
        bean.id, remaining_g=0.0, open_bag=True, finish=True, today="2026-09-26"
    )
    assert after.status == "finished"


async def test_brews_come_back_newest_first_across_time_zones():
    storage = FakeStorage()
    store = await _store(storage)
    # 07:00Z is later than 09:00+03:00 (06:00Z), though it sorts first as text.
    await store.async_create_brew(Brew(id="", brewed_at="2026-09-25T09:00:00+03:00",
                                       recorded_at="", dose_g=15.0))
    await store.async_create_brew(Brew(id="", brewed_at="2026-09-25T07:00:00Z",
                                       recorded_at="", dose_g=16.0,
                                       review=Review("no_bag", {"grams": 16.0})))
    again = await _store(storage)
    brews = await again.async_list_brews()
    assert [b.dose_g for b in brews] == [16.0, 15.0]
    assert brews[0].review == Review("no_bag", {"grams": 16.0})
    assert all(b.id for b in brews)


async def test_brews_since_a_moment():
    store = await _store()
    for when in ("2026-09-20T10:00:00Z", "2026-09-25T10:00:00Z"):
        await store.async_create_brew(Brew(id="", brewed_at=when, recorded_at="", dose_g=15.0))
    since = datetime(2026, 9, 24, tzinfo=timezone.utc)
    assert [b.brewed_at for b in await store.async_list_brews(since=since)] == [
        "2026-09-25T10:00:00Z"
    ]


async def test_a_run_is_counted_once_and_remembered_across_a_restart():
    storage = FakeStorage()
    runs = ProcessedRuns(storage)
    await runs.async_load()
    await runs.async_add("run-1")
    await runs.async_add("run-1")
    assert storage.saves == 1
    again = ProcessedRuns(storage)
    await again.async_load()
    assert again.contains("run-1") and not again.contains("run-2")
    assert not again.contains(None) and not again.contains("")


async def test_only_the_latest_runs_are_kept():
    storage = FakeStorage()
    runs = ProcessedRuns(storage)
    await runs.async_load()
    for i in range(KEEP_RUN_IDS + 5):
        await runs.async_add(f"run-{i}")
    assert len(storage.data["run_ids"]) == KEEP_RUN_IDS
    assert not runs.contains("run-0") and runs.contains(f"run-{KEEP_RUN_IDS + 4}")
