"""Coffee Lab habits: how a person brews, read from a stretch of the record."""
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.xbloom.coffee_lab.habits import habits
from custom_components.xbloom.coffee_lab.models import Bean, Brew, Review

ZONE = ZoneInfo("Asia/Riyadh")
START = datetime(2026, 9, 1, tzinfo=ZONE)
NOW = datetime(2026, 9, 10, 20, 0, tzinfo=ZONE)

HOUSE = Bean(id="b1", name="Hill Farm", status="open", roaster="Roastery")
HOUSE_AGAIN = Bean(id="b2", name="Hill Farm", status="open", roaster="Roastery", opened_on="2026-09-05")
OTHER = Bean(id="b3", name="Valley Lot", status="open", opened_on="2026-08-20")
TEA = Bean(id="t1", name="Green Leaf", status="open", kind="tea")
BEANS = [HOUSE, HOUSE_AGAIN, OTHER, TEA]


def brew(day, hour=8, dose=17.0, ratio=15.0, bean="b1", recipe="Daily Hot",
         rating=None, dripper="Omni dripper", review=None, brewer="xBloom Studio"):
    settings = {"ratio": ratio} if ratio is not None else {}
    return Brew(
        id=f"{day}-{hour}", brewed_at=f"2026-09-{day:02d}T{hour:02d}:00:00+03:00",
        recorded_at="", dose_g=dose, bean_id=bean, recipe=recipe, settings=settings,
        rating=rating, dripper=dripper, review=review, brewer=brewer,
    )


def test_days_brewed_count_each_day_once_out_of_the_days_so_far():
    h = habits([brew(1), brew(1, 15), brew(3), brew(4)], BEANS, START, NOW)
    assert h["days_brewed"] == 3
    assert h["days_in_period"] == 10
    assert h["cups_per_brewing_day"] == 1.3


def test_the_longest_run_of_days_in_a_row():
    h = habits([brew(1), brew(2), brew(3), brew(5), brew(6)], BEANS, START, NOW)
    assert h["longest_streak_days"] == 3


def test_the_usual_dose_and_ratio_are_kept_apart_for_hot_and_iced():
    records = [brew(d) for d in (1, 2, 3, 4)] + [brew(5, dose=20.0)]
    records += [brew(d, 16, dose=20.0, ratio=8.0, recipe="Iced") for d in (1, 2, 3)]
    h = habits(records, BEANS, START, NOW)
    assert h["usual"]["hot"] == {"dose_g": 17.0, "ratio": 15.0, "brews": 5}
    assert h["usual"]["iced"] == {"dose_g": 20.0, "ratio": 8.0, "brews": 3}


def test_a_drink_brewed_too_few_times_has_no_usual():
    h = habits([brew(1), brew(2), brew(3, dose=20.0, ratio=8.0)], BEANS, START, NOW)
    assert "iced" not in h["usual"]
    assert "hot" not in h["usual"]  # two brews say too little


def test_tea_and_a_brew_without_a_ratio_say_nothing_about_a_coffee_dose():
    records = [brew(d, dose=4.0, bean="t1", dripper="Tea") for d in (1, 2, 3)]
    records += [brew(d, ratio=None, brewer="V60") for d in (4, 5, 6)]
    assert habits(records, BEANS, START, NOW)["usual"] == {}


def test_the_top_coffee_counts_every_bag_of_the_same_coffee():
    records = [brew(1, bean="b1"), brew(2, bean="b2"), brew(3, bean="b3"), brew(4, bean="b3", hour=9)]
    records.append(brew(5, bean="b2"))
    h = habits(records, BEANS, START, NOW)
    assert h["top_coffee"] == {"name": "Hill Farm", "brews": 3}


def test_tea_is_not_the_top_coffee():
    records = [brew(d, bean="t1", dripper="Tea") for d in (1, 2, 3)] + [brew(4, bean="b3")]
    assert habits(records, BEANS, START, NOW)["top_coffee"] == {"name": "Valley Lot", "brews": 1}


def test_the_top_recipe():
    records = [brew(1, recipe="A"), brew(2, recipe="B"), brew(3, recipe="B")]
    assert habits(records, BEANS, START, NOW)["top_recipe"] == {"name": "B", "brews": 2}


def test_verdicts_are_counted_by_what_they_say():
    records = [brew(1, rating=3), brew(2, rating=3), brew(3, rating=1), brew(4)]
    assert habits(records, BEANS, START, NOW)["verdicts"] == {"again": 2, "not_again": 1}


def test_a_time_of_day_only_when_it_clearly_wins():
    mornings = [brew(d, hour=7) for d in (1, 2, 3, 4)] + [brew(5, hour=22)]
    assert habits(mornings, BEANS, START, NOW)["time_of_day"] == "morning"
    scattered = [brew(1, 7), brew(2, 13), brew(3, 19), brew(4, 23), brew(5, 2)]
    assert habits(scattered, BEANS, START, NOW)["time_of_day"] is None


def test_too_few_brews_say_nothing_about_the_time_of_day():
    assert habits([brew(1, 7), brew(2, 7)], BEANS, START, NOW)["time_of_day"] is None


def test_bags_opened_in_the_period():
    assert habits([], BEANS, START, NOW)["bags_opened"] == ["Hill Farm"]


def test_a_stopped_brew_is_not_a_cup_and_outside_brews_do_not_count():
    stopped = Review("stopped_after_grinding")
    records = [brew(1), brew(2, review=stopped)]
    records.append(Brew(id="old", brewed_at="2026-08-31T08:00:00+03:00", recorded_at="", dose_g=17.0))
    h = habits(records, BEANS, START, NOW)
    assert h["days_brewed"] == 1 and h["cups_per_brewing_day"] == 1.0


def test_an_empty_period():
    h = habits([], BEANS, START, NOW)
    assert h["days_brewed"] == 0
    assert h["cups_per_brewing_day"] is None
    assert h["top_coffee"] is None and h["top_recipe"] is None
    assert h["longest_streak_days"] == 0


def test_two_roasters_coffees_of_one_name_stay_apart():
    a = Bean(id="r1", name="Sunrise", status="open", roaster="North")
    b = Bean(id="r2", name="Sunrise", status="open", roaster="South")
    records = [brew(1, bean="r1"), brew(2, bean="r1"), brew(3, bean="r2")]
    assert habits(records, [a, b], START, NOW)["top_coffee"] == {"name": "Sunrise (North)", "brews": 2}


def test_a_rolling_week_counts_every_date_it_touches():
    start = datetime(2026, 9, 19, 10, 0, tzinfo=ZONE)
    now = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
    records = [brew(19, hour=11)] + [brew(d) for d in range(20, 27)]
    h = habits(records, BEANS, start, now)
    assert (h["days_brewed"], h["days_in_period"], h["longest_streak_days"]) == (8, 8, 8)


def test_a_period_ending_at_midnight_does_not_reach_the_next_day():
    start = datetime(2026, 9, 4, tzinfo=ZONE)
    end = datetime(2026, 9, 5, tzinfo=ZONE)
    h = habits([], BEANS, start, end)
    assert h["days_in_period"] == 1
    assert h["bags_opened"] == []  # Hill Farm's second bag was opened on the 5th
