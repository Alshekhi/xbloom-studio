"""The brew record as hourly running totals, which the charts draw."""
from datetime import datetime, timedelta, timezone

from custom_components.xbloom.coffee_lab.history import SERIES, first_hour, hourly, statistic_id
from custom_components.xbloom.coffee_lab.models import Brew, Review

ZONE = timezone(timedelta(hours=3))
BY_KEY = {s.key: s for s in SERIES}


def _brew(at, brewer="xBloom Studio", dose=15.0, water=240.0, review=None):
    return Brew(id=at, brewed_at=at, recorded_at=at, dose_g=dose,
                brewer=brewer, water_ml=water, review=review)


def _at(hour, day=26):
    return datetime(2026, 9, day, hour, tzinfo=ZONE)


def test_brews_in_one_hour_are_one_point_and_the_total_runs_on():
    records = [
        _brew("2026-09-26T08:10:00+03:00"),
        _brew("2026-09-26T08:50:00+03:00"),
        _brew("2026-09-27T07:05:00+03:00"),
    ]
    assert hourly(records, BY_KEY["brews_xbloom"], ZONE) == [(_at(8), 2.0), (_at(7, 27), 3.0)]


def test_the_xbloom_and_manual_brews_are_apart():
    records = [_brew("2026-09-26T08:10:00+03:00"), _brew("2026-09-26T09:10:00+03:00", brewer="V60")]
    assert hourly(records, BY_KEY["brews_xbloom"], ZONE) == [(_at(8), 1.0)]
    assert hourly(records, BY_KEY["brews_manual"], ZONE) == [(_at(9), 1.0)]


def test_a_brew_stopped_after_grinding_used_coffee_but_made_none():
    stopped = _brew("2026-09-26T08:10:00+03:00", water=None,
                    review=Review("stopped_after_grinding", ""))
    assert hourly([stopped], BY_KEY["brews_xbloom"], ZONE) == []
    assert hourly([stopped], BY_KEY["coffee_used"], ZONE) == [(_at(8), 15.0)]
    assert hourly([stopped], BY_KEY["water_brewed"], ZONE) == []


def test_a_utc_time_lands_in_the_local_hour():
    assert hourly([_brew("2026-09-26T05:30:00+00:00")], BY_KEY["coffee_used"], ZONE) == [(_at(8), 15.0)]


def test_a_brew_with_no_time_is_placed_by_when_it_was_recorded():
    brew = Brew(id="x", brewed_at="", recorded_at="2026-09-26T08:10:00+03:00", dose_g=12.0, brewer="V60")
    assert hourly([brew], BY_KEY["coffee_used"], ZONE) == [(_at(8), 12.0)]


def test_statistic_ids_are_the_integrations_own():
    assert [statistic_id(s) for s in SERIES] == [
        "xbloom:brews_xbloom", "xbloom:brews_manual", "xbloom:coffee_used", "xbloom:water_brewed"]


def test_the_first_hour_is_the_earliest_brew():
    records = [_brew("2026-09-27T07:05:00+03:00"), _brew("2026-09-26T08:10:00+03:00")]
    assert first_hour(records, ZONE) == _at(8)
    assert first_hour([], ZONE) is None
