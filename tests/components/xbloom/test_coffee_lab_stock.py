"""Coffee Lab stock: what is left of each kind, and when it crosses a level."""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.xbloom.coffee_lab.models import Bean, Brew
from custom_components.xbloom.coffee_lab.stock import crossing, figure, floor, stock_of

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def bag(id="b1", kind="coffee", status="open", tracked=False, remaining_g=None,
        bag_size_g=None, pods_left=None):
    return Bean(id=id, name="Test Coffee", status=status, kind=kind, tracked=tracked,
                remaining_g=remaining_g, bag_size_g=bag_size_g, pods_left=pods_left)


def brew(dose=18.0, days_ago=0, bean="b1"):
    when = (NOW - timedelta(days=days_ago, hours=1)).isoformat()
    return Brew(id=f"r{days_ago}", brewed_at=when, recorded_at=when, dose_g=dose, bean_id=bean)


def test_tracked_and_unopened_bags_add_up_and_an_untracked_open_bag_is_unknown():
    s = stock_of("coffee", [bag(id="t", remaining_g=40, tracked=True),
                            bag(id="n", status="unopened", bag_size_g=250),
                            bag(id="u")], [], NOW)
    assert (s.amount, s.bags, s.unknown) == (290.0, 3, ("u",))
    assert figure(s, "grams") is None and floor(s, "grams") == 290.0 and figure(s, "bags") == 3


def test_days_and_cups_come_from_the_last_30_days_and_need_5_brews():
    brews = [brew(dose=18, days_ago=d) for d in range(6)]
    beans = [bag(remaining_g=180, tracked=True)]
    s = stock_of("coffee", beans, brews, NOW)
    # 108 g over the 6 days brewed: 18 g a day.
    assert figure(s, "cups") == 10.0 and figure(s, "days") == 10.0
    four = stock_of("coffee", beans, brews[:4], NOW)
    assert figure(four, "days") is None and figure(four, "cups") is None


def test_brews_older_than_30_days_and_of_another_kind_do_not_count_toward_the_pace():
    beans = [bag(remaining_g=180, tracked=True), bag(id="t", kind="tea", remaining_g=50, tracked=True)]
    brews = [brew(days_ago=d) for d in range(5)] + [brew(days_ago=40), brew(bean="t")]
    # 90 g over 5 days: the brew 40 days ago and the tea do not count.
    assert figure(stock_of("coffee", beans, brews, NOW), "days") == 10.0


def test_an_xpod_box_counts_pods_and_boxes():
    s = stock_of("xpod", [bag(kind="xpod", pods_left=3, tracked=True),
                          bag(id="b", kind="xpod", status="unopened")], [], NOW)
    assert figure(s, "boxes") == 2 and figure(s, "pods") is None and floor(s, "pods") == 3


def test_a_kind_never_kept_never_turns_low():
    s = stock_of("tea", [bag()], [], NOW)
    assert not s.kept
    finished_tea = stock_of("tea", [bag(kind="tea", status="finished")], [], NOW)
    assert finished_tea.kept and figure(finished_tea, "grams") == 0.0


@pytest.mark.parametrize("stored, value, level, expected", [
    (None, 3.0, 7, (True, None)),
    (None, 9.0, 7, (False, None)),
    (False, 6.9, 7, (True, "low")),
    (True, 5.0, 7, (True, None)),
    (True, 7.0, 7, (False, "restored")),
    (True, None, 7, (True, None)),
    (True, 3.0, 0, (True, None)),
    (False, None, 7, (False, None)),
])
def test_a_crossing_changes_only_on_a_known_figure(stored, value, level, expected):
    assert crossing(stored, value, level) == expected


# ── Levels and state kept by Coffee Lab ──────────────────────────────────────

from .test_coffee_lab_lab import _bag, _lab  # noqa: E402


async def test_a_level_is_kept_per_measure():
    lab = await _lab()
    assert (lab.stock_measure("coffee"), lab.stock_level("coffee")) == ("days", 7)
    await lab.async_set_stock_level("coffee", 4)
    await lab.async_set_stock_measure("coffee", "grams")
    assert lab.stock_level("coffee") == 250
    await lab.async_set_stock_measure("coffee", "days")
    assert lab.stock_level("coffee") == 4


async def test_a_measure_the_kind_does_not_have_is_refused():
    lab = await _lab()
    with pytest.raises(ValueError):
        await lab.async_set_stock_measure("xpod", "grams")


async def test_the_low_state_and_the_added_item_are_kept():
    lab = await _lab()
    assert lab.stock_low_state("coffee") is None and lab.stock_item("coffee") is None
    await lab.async_set_stock_low_state("coffee", True)
    await lab.async_set_stock_item("coffee", "uid-1")
    assert (lab.stock_low_state("coffee"), lab.stock_item("coffee")) == (True, "uid-1")


async def test_buy_again_yes_tells_the_watch_and_maybe_does_not():
    lab = await _lab()
    told = []
    lab.on_buy_again = told.append
    bag = await _bag(lab, status="finished")
    await lab.async_rate_bag("maybe", bag.id)
    await lab.async_rate_bag("yes", bag.id)
    assert [b.id for b in told] == [bag.id]


# ── Final review ─────────────────────────────────────────────────────────────


def test_tea_starts_counted_in_bags_at_one():
    from custom_components.xbloom.coffee_lab.stock import DEFAULT_LEVEL, DEFAULT_MEASURE
    assert DEFAULT_MEASURE["tea"] == "bags" and DEFAULT_LEVEL["bags"] == 1


def test_the_pace_is_over_the_days_brewed_not_always_30():
    # Six cups of 18 g over the last 6 days: 18 g a day, so 180 g lasts 10 days.
    brews = [brew(dose=18, days_ago=d) for d in range(6)]
    s = stock_of("coffee", [bag(remaining_g=180, tracked=True)], brews, NOW)
    assert figure(s, "days") == 10.0
