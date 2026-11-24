"""Coffee Lab opening rules: few bags open, and which sealed bag to open next."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.xbloom.coffee_lab.models import Bean, Brew
from custom_components.xbloom.coffee_lab.opening import (
    Opening, fading, holds_a_dose, open_next, usual_dose,
)

ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=ZONE)
RULES = Opening()


def day(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).date().isoformat()


def opened(id: str, left: float | None = 100.0, days_open: int = 5) -> Bean:
    return Bean(id=id, name=f"Open {id}", status="open", tracked=left is not None,
                remaining_g=left, bag_size_g=250.0, opened_on=day(days_open))


def sealed(id: str, roasted: int | None) -> Bean:
    return Bean(id=id, name=f"Sealed {id}", status="unopened", bag_size_g=250.0,
                roast_date=day(roasted) if roasted is not None else "")


def test_nothing_opens_while_the_open_bags_are_at_the_limit():
    beans = [opened("a", 10), opened("b", 30), sealed("s", 20)]
    assert open_next(beans, 17, NOW, RULES) is None


def test_the_next_bag_opens_when_the_open_ones_run_low():
    beans = [opened("a", 30), sealed("s", 20)]
    assert open_next(beans, 17, NOW, RULES).id == "s"


def test_not_while_the_open_bags_hold_more_than_two_doses():
    beans = [opened("a", 60), sealed("s", 20)]
    assert open_next(beans, 17, NOW, RULES) is None


def test_a_bag_still_resting_waits_for_an_older_one():
    beans = [opened("a", 20), sealed("fresh", 3), sealed("rested", 20)]
    assert open_next(beans, 17, NOW, RULES).id == "rested"


def test_when_none_has_rested_the_oldest_roast():
    beans = [opened("a", 20), sealed("two", 2), sealed("four", 4)]
    assert open_next(beans, 17, NOW, RULES).id == "four"


def test_undated_sealed_bags_come_after_dated_ones():
    beans = [opened("a", 20), sealed("undated", None), sealed("dated", 3)]
    assert open_next(beans, 17, NOW, RULES).id == "dated"


def test_no_open_bag_with_a_dose_names_the_next_one():
    beans = [opened("a", 5), opened("b", 5), sealed("s", 20)]
    assert open_next(beans, 17, NOW, RULES).id == "s"


def test_with_no_bag_open_the_next_one():
    assert open_next([sealed("s", 20)], 17, NOW, RULES).id == "s"


def test_an_open_bag_of_unknown_amount_holds_a_dose():
    assert holds_a_dose(opened("a", None), 17)
    assert not holds_a_dose(opened("a", 10), 17)
    beans = [opened("a", None), sealed("s", 20)]
    assert open_next(beans, 17, NOW, RULES) is None


def test_a_bag_open_past_its_fade_age_is_fading():
    assert fading(opened("a", days_open=30), NOW, RULES)
    assert not fading(opened("a", days_open=20), NOW, RULES)
    no_date = Bean(id="x", name="x", status="open")
    assert not fading(no_date, NOW, RULES)
    assert not fading(sealed("s", 60), NOW, RULES)


def test_tea_and_xpods_are_left_alone():
    tea = Bean(id="t", name="Tea", status="unopened", kind="tea", bag_size_g=100.0)
    assert open_next([tea], 17, NOW, RULES) is None
    pods = Bean(id="p", name="Pods", status="open", kind="xpod", opened_on=day(60))
    assert not fading(pods, NOW, RULES)


def brew(days_ago: int, dose: float, ratio: float = 15.0) -> Brew:
    when = (NOW - timedelta(days=days_ago)).isoformat()
    return Brew(id=f"r{days_ago}{dose}", brewed_at=when, recorded_at=when, dose_g=dose,
                settings={"ratio": ratio})


def test_the_usual_dose_falls_back():
    assert usual_dose([brew(1, 17), brew(2, 17), brew(3, 17)], NOW) == 17.0
    assert usual_dose([brew(1, 16), brew(2, 18)], NOW) == 17.0
    assert usual_dose([], NOW) == 15.0
    # Older than 30 days: not the usual any more.
    assert usual_dose([brew(40, 20), brew(41, 20), brew(42, 20)], NOW) == 15.0


async def test_the_opening_settings_are_kept_and_checked():
    import pytest
    from .test_coffee_lab_lab import _lab
    lab = await _lab()
    assert lab.opening == Opening(2, 7, 28)
    await lab.async_set_opening(limit=3, rest_days=10, fade_days=21)
    assert lab.opening == Opening(3, 10, 21)
    with pytest.raises(ValueError):
        await lab.async_set_opening(limit=0)
    with pytest.raises(ValueError):
        await lab.async_set_opening(fade_days=200)


async def test_the_bag_list_names_the_bag_to_open_and_those_past_their_best():
    from custom_components.xbloom.coffee_lab.entities import BagsSensor
    from .test_coffee_lab_lab import _lab
    lab = await _lab()
    old = await lab.store.async_add_bean(name="Old", status="open", tracked=True,
                                         remaining_g=20.0, bag_size_g=250.0, opened_on="2000-01-01")
    nxt = await lab.store.async_add_bean(name="Next", status="unopened", bag_size_g=250.0,
                                         roast_date="2000-01-01")
    sensor = BagsSensor(lab)
    await sensor.async_read()
    attrs = sensor._attr_extra_state_attributes
    assert attrs["open_next"] == nxt.id
    assert attrs["fading"] == [old.id]


def test_a_bag_under_a_dose_counts_as_empty_toward_nearly_done():
    beans = [opened("a", 10), opened("b", 25), sealed("s", 20)]
    assert open_next(beans, 15, NOW, Opening(limit=3)).id == "s"


def test_an_open_bag_of_unknown_amount_never_reads_as_nearly_done():
    # It may hold plenty: naming a sealed bag now could open one too soon.
    beans = [opened("a", None), opened("b", 5), sealed("s", 20)]
    assert open_next(beans, 17, NOW, Opening(limit=3)) is None
