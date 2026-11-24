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
    assert figure(s, "cups") == 10.0 and figure(s, "days") == 50.0
    four = stock_of("coffee", beans, brews[:4], NOW)
    assert figure(four, "days") is None and figure(four, "cups") is None


def test_brews_older_than_30_days_and_of_another_kind_do_not_count_toward_the_pace():
    beans = [bag(remaining_g=180, tracked=True), bag(id="t", kind="tea", remaining_g=50, tracked=True)]
    brews = [brew(days_ago=d) for d in range(5)] + [brew(days_ago=40), brew(bean="t")]
    assert figure(stock_of("coffee", beans, brews, NOW), "days") == 60.0


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
