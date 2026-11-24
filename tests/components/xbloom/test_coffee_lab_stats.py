"""Coffee Lab stats: what a stretch of brews adds up to, on the local clock."""
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.xbloom.coffee_lab.models import Brew, Review
from custom_components.xbloom.coffee_lab.stats import (
    PERIODS, period_report, totals, window,
)

ZONE = ZoneInfo("Etc/GMT-5")
NOW = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
SEPTEMBER = (datetime(2026, 9, 1, tzinfo=ZONE), datetime(2026, 10, 1, tzinfo=ZONE))


def brew(when, dose=16.0, water=None, brewer="xBloom Studio", recorded=""):
    return Brew(id="x", brewed_at=when, recorded_at=recorded, dose_g=dose,
                brewer=brewer, water_ml=water)


def test_a_month_adds_up_its_brews():
    t = totals([
        brew("2026-09-24T22:22:00Z", 16, 256),
        brew("2026-09-10T08:00:00+05:00", 20, 300),
        brew("2026-08-30T08:00:00+05:00", 18, 270),
    ], *SEPTEMBER)
    assert (t.brews, t.coffee_g, t.water_ml) == (2, 36.0, 556.0)


def test_a_brew_belongs_to_the_local_month():
    # 23:30 UTC on 31 August is 04:30 on 1 September at UTC+5.
    assert totals([brew("2026-08-31T23:30:00Z")], *SEPTEMBER).brews == 1


def test_water_is_counted_only_where_it_was_recorded():
    t = totals([brew("2026-09-10", 16, 256), brew("2026-09-11", 16, None)], *SEPTEMBER)
    assert t.water_ml == 256.0 and t.brews_with_water == 1


def test_a_date_without_a_time_still_counts():
    assert totals([brew("2026-09-08")], *SEPTEMBER).brews == 1


def test_the_most_used_brewer_comes_first():
    t = totals([
        brew("2026-09-10", brewer="V60"),
        brew("2026-09-11", brewer="xBloom Studio"),
        brew("2026-09-12", brewer="V60"),
    ], *SEPTEMBER)
    assert t.by_brewer[0] == ("V60", 2) and t.top_brewer == "V60"


def test_a_brew_with_no_brewer_is_counted_not_dropped():
    t = totals([brew("2026-09-10", brewer=None)], *SEPTEMBER)
    assert t.by_brewer == (("other", 1),)


def test_an_empty_stretch_is_zero_not_missing():
    t = totals([], *SEPTEMBER)
    assert (t.brews, t.coffee_g, t.water_ml, t.top_brewer) == (0, 0.0, 0.0, None)


def test_a_brew_with_no_time_counts_when_it_was_recorded():
    t = totals([brew("", 20.0, 320.0, recorded="2026-09-08T14:31:51.000Z")], *SEPTEMBER)
    assert (t.brews, t.coffee_g, t.water_ml) == (1, 20.0, 320.0)


def test_a_brew_with_no_date_at_all_is_left_out():
    assert totals([brew("")], *SEPTEMBER).brews == 0


def test_the_periods_offered_are_keys_not_labels():
    assert PERIODS == ("today", "yesterday", "last_7_days", "last_30_days",
                       "this_month", "last_month", "this_year")


def test_windows_and_what_they_compare_with():
    w = window("today", NOW)
    assert (w.start, w.end) == (datetime(2026, 9, 26, tzinfo=ZONE), NOW)
    assert (w.before_start, w.before_end) == (datetime(2026, 9, 25, tzinfo=ZONE), w.start)

    assert window("last_7_days", NOW).start == datetime(2026, 9, 19, 10, 0, tzinfo=ZONE)

    w = window("last_month", NOW)
    assert (w.start, w.end) == (datetime(2026, 8, 1, tzinfo=ZONE),
                                datetime(2026, 9, 1, tzinfo=ZONE))
    assert w.before_start == datetime(2026, 7, 1, tzinfo=ZONE)

    w = window("this_month", datetime(2026, 1, 5, tzinfo=ZONE))
    assert w.before_start == datetime(2025, 12, 1, tzinfo=ZONE)


def test_a_report_counts_the_window_and_the_one_before():
    r = period_report([
        brew("2026-09-25T09:00:00+05:00", 16, 256),
        brew("2026-09-24T09:00:00+05:00", 15, None, "V60"),
        brew("2026-09-15T09:00:00+05:00", 20, 300),
    ], "last_7_days", NOW)
    assert (r.now.brews, r.now.coffee_g, r.now.water_ml) == (2, 31.0, 256.0)
    assert r.before.brews == 1 and r.change_in_brews == 1


def test_a_brew_stopped_after_grinding_counts_its_coffee_but_not_as_a_brew():
    stopped = Brew(id="s", brewed_at="2026-09-10", recorded_at="", dose_g=17.0,
                   brewer="xBloom Studio", review=Review("stopped_after_grinding"))
    t = totals([brew("2026-09-11", 16), stopped], *SEPTEMBER)
    assert (t.brews, t.coffee_g) == (1, 33.0)
    assert t.by_brewer == (("xBloom Studio", 1),)


def test_a_brew_flagged_for_another_reason_still_counts():
    flagged = Brew(id="f", brewed_at="2026-09-10", recorded_at="", dose_g=18.0,
                   review=Review("no_bag"))
    assert totals([flagged], *SEPTEMBER).brews == 1



def test_the_coffee_total_leaves_out_tea_and_keeps_xpods():
    tea = Brew(id="t", brewed_at="2026-09-10T08:00:00+05:00", recorded_at="", dose_g=5.0, dripper="Tea")
    pod = Brew(id="p", brewed_at="2026-09-11T08:00:00+05:00", recorded_at="", dose_g=15.0, dripper="xPod")
    t = totals([tea, pod, brew("2026-09-12T08:00:00+05:00", 16)], *SEPTEMBER)
    assert (t.brews, t.coffee_g) == (3, 31.0)


def test_the_history_by_month_and_by_week_newest_first():
    from custom_components.xbloom.coffee_lab.stats import by_month, by_week
    records = [brew("2026-09-25T09:00:00+05:00", 16, 256), brew("2026-09-21T09:00:00+05:00", 18, 270),
               brew("2026-08-10T09:00:00+05:00", 20, 300)]
    months = by_month(records, NOW, 3)
    assert months == [
        {"start": "2026-09-01", "brews": 2, "coffee_g": 34.0, "water_ml": 526.0},
        {"start": "2026-08-01", "brews": 1, "coffee_g": 20.0, "water_ml": 300.0},
    ]
    weeks = by_week(records, NOW, 2)
    # Weeks start on Monday: 21 and 25 September fall in the week of the 21st.
    assert weeks == [
        {"start": "2026-09-21", "brews": 2, "coffee_g": 34.0, "water_ml": 526.0},
        {"start": "2026-09-14", "brews": 0, "coffee_g": 0.0, "water_ml": 0.0},
    ]


def test_months_before_the_first_brew_are_left_out():
    from custom_components.xbloom.coffee_lab.stats import by_month
    months = by_month([brew("2026-08-10T09:00:00+05:00", 20, 300)], NOW, 12)
    assert [m["start"] for m in months] == ["2026-09-01", "2026-08-01"]
    assert by_month([], NOW, 12) == []


def test_no_brews_no_weeks_either():
    from custom_components.xbloom.coffee_lab.stats import by_week
    assert by_week([], NOW, 8) == []
