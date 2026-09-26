"""Coffee Lab stats: what a stretch of brews adds up to, on the local clock."""
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.xbloom.coffee_lab.models import Brew
from custom_components.xbloom.coffee_lab.stats import (
    PERIODS, period_report, totals, window,
)

RIYADH = ZoneInfo("Asia/Riyadh")
NOW = datetime(2026, 9, 26, 10, 0, tzinfo=RIYADH)
SEPTEMBER = (datetime(2026, 9, 1, tzinfo=RIYADH), datetime(2026, 10, 1, tzinfo=RIYADH))


def brew(when, dose=16.0, water=None, brewer="xBloom Studio", recorded=""):
    return Brew(id="x", brewed_at=when, recorded_at=recorded, dose_g=dose,
                brewer=brewer, water_ml=water)


def test_a_month_adds_up_its_brews():
    t = totals([
        brew("2026-09-24T22:22:00Z", 16, 256),
        brew("2026-09-10T08:00:00+03:00", 20, 300),
        brew("2026-08-30T08:00:00+03:00", 18, 270),
    ], *SEPTEMBER)
    assert (t.brews, t.coffee_g, t.water_ml) == (2, 36.0, 556.0)


def test_a_brew_belongs_to_the_local_month():
    # 23:30 UTC on 31 August is 02:30 on 1 September in Riyadh.
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
    assert (w.start, w.end) == (datetime(2026, 9, 26, tzinfo=RIYADH), NOW)
    assert (w.before_start, w.before_end) == (datetime(2026, 9, 25, tzinfo=RIYADH), w.start)

    assert window("last_7_days", NOW).start == datetime(2026, 9, 19, 10, 0, tzinfo=RIYADH)

    w = window("last_month", NOW)
    assert (w.start, w.end) == (datetime(2026, 8, 1, tzinfo=RIYADH),
                                datetime(2026, 9, 1, tzinfo=RIYADH))
    assert w.before_start == datetime(2026, 7, 1, tzinfo=RIYADH)

    w = window("this_month", datetime(2026, 1, 5, tzinfo=RIYADH))
    assert w.before_start == datetime(2025, 12, 1, tzinfo=RIYADH)


def test_a_report_counts_the_window_and_the_one_before():
    r = period_report([
        brew("2026-09-25T09:00:00+03:00", 16, 256),
        brew("2026-09-24T09:00:00+03:00", 15, None, "V60"),
        brew("2026-09-15T09:00:00+03:00", 20, 300),
    ], "last_7_days", NOW)
    assert (r.now.brews, r.now.coffee_g, r.now.water_ml) == (2, 31.0, 256.0)
    assert r.before.brews == 1 and r.change_in_brews == 1
