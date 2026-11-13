"""The water tracker turns the low-water switch into amounts.

The machine has one low-water switch and no level reading. It trips with
about 270 ml left (`spec.WATER_RESERVE_ML`), the brew keeps pouring, and it
pauses on the water-shortage screen (activity 12) once the tank is empty;
a refill alone does not resume it, the knob does (9011). The numbers here
follow one measured 500 ml brew: the switch tripped 112 ml in.
"""
from custom_components.xbloom.water import WaterTracker, recipe_water_ml

LOW = {"cmd": 40522, "water_enough": 0}
HIGH = {"cmd": 40522, "water_enough": 1}
KNOB = {"cmd": 9011}


def poured(ml):
    return {"cmd": 40523, "water_ml": ml}


def pour(index):
    return {"cmd": 40510, "pour_index": index}


def screen(code):
    return {"cmd": 8023, "activity": code}


def run(tracker, frames):
    """Feed (now, frame) pairs; return every decision the tracker made."""
    return [ev for now, frame in frames if (ev := tracker.feed(frame, now))]


def tripped_at(ml, recipe=500):
    t = WaterTracker(recipe)
    run(t, [(0, pour(0)), (1, poured(ml)), (2, LOW)])
    return t


def test_trip_with_enough_water_reports_amounts():
    t = WaterTracker(500)
    events = run(t, [(0, pour(0)), (1, poured(300)), (2, LOW)])
    assert events == [("water_low", {"water_left_ml": 270, "water_needed_ml": 200,
                                     "water_short_ml": 0, "enough_to_finish": True})]


def test_trip_that_will_not_finish_reports_the_shortfall():
    t = WaterTracker(500)
    events = run(t, [(0, pour(0)), (1, poured(112.4)), (2, LOW)])
    assert events == [("water_low", {"water_left_ml": 270, "water_needed_ml": 388,
                                     "water_short_ml": 118, "enough_to_finish": False})]


def test_left_counts_down_after_the_trip():
    t = tripped_at(112)
    t.feed(poured(312), 3)
    assert t.state == {"water_left_ml": 70, "water_needed_ml": 188,
                       "water_short_ml": 118, "enough_to_finish": False}


def test_flicker_under_the_hold_fires_once_and_keeps_the_trip():
    t = WaterTracker(500)
    events = run(t, [(0, pour(0)), (1, poured(150)), (10, LOW), (10.5, HIGH),
                     (11, LOW), (15, poured(200)), (20, poured(250))])
    assert [name for name, _ in events] == ["water_low"]
    assert t.state is not None


def test_refill_before_the_pause_clears_silently_and_a_second_trip_fires_again():
    t = tripped_at(112)
    events = run(t, [(30, HIGH), (31, poured(200)), (32.1, poured(210))])
    assert events == []
    assert t.state is None
    events = run(t, [(40, poured(408)), (41, LOW)])
    assert events == [("water_low", {"water_left_ml": 270, "water_needed_ml": 92,
                                     "water_short_ml": 0, "enough_to_finish": True})]


def test_low_before_the_first_pour_is_not_a_trip():
    t = WaterTracker(500)
    events = run(t, [(0, LOW), (1, pour(0)), (2, poured(250)), (3, poured(500))])
    assert events == []
    assert t.state is None
    assert t.completion_fields() == {"tank_low": True}


def test_water_pause_refill_and_knob():
    t = tripped_at(112)
    assert run(t, [(50, poured(394.9)), (100, screen(12))]) == [
        ("water_paused", {"water_needed_ml": 105})]
    assert run(t, [(170, HIGH), (171, screen(31))]) == [("water_refilled", {})]
    run(t, [(200, KNOB)])
    assert t.paused_seconds(300) == 100.0


def test_paused_time_counts_while_still_paused():
    t = tripped_at(112)
    run(t, [(100, screen(12))])
    assert t.paused_seconds(130) == 30.0


def test_completion_after_a_trip_reports_what_is_left():
    t = tripped_at(300)
    t.feed(poured(500), 9)
    assert t.completion_fields() == {"tank_low": True, "water_left_ml": 70}


def test_completion_with_water_says_nothing():
    t = WaterTracker(500)
    run(t, [(0, HIGH), (1, pour(0)), (2, poured(500))])
    assert t.completion_fields() == {}


def test_recipe_water_is_the_pours_only():
    assert recipe_water_ml({"pours": [{"volume_ml": 125}] * 4,
                            "bypass_volume_ml": 30}) == 500


def test_a_flicker_from_an_already_low_tank_is_not_a_trip():
    t = WaterTracker(200)
    events = run(t, [(0, LOW), (1, pour(0)), (2, poured(50)), (5, HIGH), (5.3, LOW),
                     (6, poured(80))])
    assert events == []
    assert t.completion_fields() == {"tank_low": True}


def test_a_low_blip_during_a_refill_is_not_a_new_trip():
    t = tripped_at(112)
    run(t, [(50, poured(394.9)), (100, screen(12)), (170, HIGH)])
    assert run(t, [(170.5, LOW), (171, HIGH), (172, screen(31))]) == []
