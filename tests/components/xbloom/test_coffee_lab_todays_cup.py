"""Today's cup: which open bag, which recipe, and why."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.xbloom.coffee_lab.models import Bean, Brew
from custom_components.xbloom.coffee_lab.opening import Opening
from custom_components.xbloom.coffee_lab.todays_cup import OwnRecipe, candidates

ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=ZONE)
RULES = Opening()
DOSE = 17.0


def day(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).date().isoformat()


def opened(id: str, left: float | None = 150.0, days_open: int = 5, roaster: str = "") -> Bean:
    return Bean(id=id, name=f"Coffee {id}", status="open", tracked=left is not None,
                remaining_g=left, bag_size_g=250.0, opened_on=day(days_open), roaster=roaster)


def sealed(id: str, roasted: int = 20) -> Bean:
    return Bean(id=id, name=f"Coffee {id}", status="unopened", bag_size_g=250.0, roast_date=day(roasted))


def brew(bean: str, recipe: str = "R1", days_ago: int = 1, rating: int | None = None) -> Brew:
    when = (NOW - timedelta(days=days_ago)).isoformat()
    return Brew(id=f"{bean}{recipe}{days_ago}", brewed_at=when, recorded_at=when, dose_g=DOSE,
                bean_id=bean, recipe=recipe, rating=rating)


def own(*names: str, again: bool = True, matched: str = "this_bag") -> list[OwnRecipe]:
    return [OwnRecipe(n, again, matched) for n in names]


def pick(beans, brews, recipes=None, community=None, drink="hot", rules=RULES):
    return candidates(beans, brews, recipes or {}, community or {}, drink, NOW, rules, DOSE)


def test_a_liked_bag_beats_one_not_rated():
    beans = [opened("a"), opened("b")]
    first = pick(beans, [brew("b", rating=3, days_ago=3)], {"b": own("R1")})[0]
    assert first.bag_id == "b" and first.reasons[0] == "liked"


def test_two_liked_bags_alternate():
    beans = [opened("a"), opened("b")]
    brews = [brew("a", rating=3, days_ago=4), brew("b", rating=3, days_ago=3), brew("a", days_ago=1)]
    first = pick(beans, brews, {"a": own("R1"), "b": own("R1")})[0]
    assert first.bag_id == "b" and first.reasons[0] == "not_yesterday"


def test_a_bag_that_would_fade_first_wins_over_variety():
    beans = [opened("a", left=150, days_open=20), opened("b")]
    brews = [brew("a", rating=3, days_ago=4), brew("b", rating=3, days_ago=3), brew("a", days_ago=1)]
    first = pick(beans, brews, {"a": own("R1"), "b": own("R1")})[0]
    assert first.bag_id == "a" and first.reasons[0] == "use_soon"


def test_a_bag_past_its_best_is_never_the_pick_while_another_qualifies():
    beans = [opened("old", days_open=40), opened("b")]
    brews = [brew("old", rating=3, days_ago=5)]
    picks = pick(beans, brews, {"old": own("R1"), "b": own("R2", again=False)})
    assert picks[0].bag_id == "b"
    assert any(p.bag_id == "old" and p.reasons[0] == "past_best" for p in picks)


def test_the_only_bag_past_its_best_is_still_the_pick():
    first = pick([opened("old", days_open=40)], [], {"old": own("R1")})[0]
    assert first.bag_id == "old" and first.reasons[0] == "past_best"


def test_an_open_bag_without_a_dose_is_passed_over():
    picks = pick([opened("low", left=5), opened("b")], [], {"low": own("R1"), "b": own("R1")})
    assert picks[0].bag_id == "b" and all(p.bag_id != "low" for p in picks)
    only = pick([opened("low", left=5), sealed("s")], [], {"s": own("R1")})[0]
    assert only.bag_id == "s" and only.reasons[0] == "open_next"


def test_a_bag_with_no_open_date_still_ranks():
    beans = [Bean(id="n", name="Coffee n", status="open"), opened("b")]
    assert {p.bag_id for p in pick(beans, [], {})} == {"n", "b"}


def test_recipes_rotate_between_those_rated_again():
    brews = [brew("a", "R1", days_ago=1), brew("a", "R2", days_ago=3)]
    first = pick([opened("a")], brews, {"a": own("R1", "R2")})[0]
    assert first.recipe == "R2" and first.reasons[-1] == "rated_again"
    one = pick([opened("a")], brews, {"a": own("R1") + own("R3", again=False)})[0]
    assert one.recipe == "R1"


def test_another_walks_every_recipe_of_a_bag_before_the_next_bag():
    picks = pick([opened("a"), opened("b")], [brew("a", rating=3)], {"a": own("R1", "R2"), "b": own("R9")})
    # R1 was used last with a, so R2 comes first.
    assert [(p.bag_id, p.recipe) for p in picks] == [("a", "R2"), ("a", "R1"), ("b", "R9")]


def test_with_no_own_recipe_the_community_one():
    first = pick([opened("a")], [], {}, {"a": {"id": 42, "name": "Shared"}})[0]
    assert (first.recipe, first.recipe_source, first.hub_id) == ("Shared", "community", 42)
    assert first.reasons[-1] == "community"


def test_with_neither_the_bag_alone():
    first = pick([opened("a")], [], {})[0]
    assert first.recipe is None and first.recipe_source is None


def test_recipe_reasons_say_where_it_was_proven():
    first = pick([opened("a")], [], {"a": own("R1", again=False, matched="origin")})[0]
    assert first.reasons[-1] == "like_this_coffee"
    first = pick([opened("a")], [], {"a": own("R1", again=False)})[0]
    assert first.reasons[-1] == "brewed_with_bag"


def test_every_candidate_carries_the_dose_and_drink_given():
    picks = candidates([opened("a")], [], {"a": own("R1")}, {}, "iced", NOW, RULES, 20.0)
    assert all(p.dose_g == 20.0 and p.drink == "iced" for p in picks)


def test_no_coffee_bag_no_pick():
    tea = Bean(id="t", name="Tea", status="open", kind="tea")
    assert pick([tea], [], {}) == []


def test_bags_past_their_best_are_ranked_like_the_others():
    # Every open bag past its best: still the liked one first, and not the one brewed last.
    beans = [opened("plain", days_open=40), opened("a", days_open=45), opened("b", days_open=50)]
    brews = [brew("a", rating=3, days_ago=5), brew("b", rating=3, days_ago=4), brew("a", days_ago=1)]
    picks = pick(beans, brews, {"a": own("R1"), "b": own("R1"), "plain": own("R2", again=False)})
    assert [p.bag_id for p in picks] == ["b", "a", "plain"]
    assert picks[0].reasons[0] == "past_best"


def test_a_tea_brewed_since_does_not_break_the_alternation():
    tea = Bean(id="t", name="Tea", status="open", kind="tea")
    beans = [opened("a"), opened("b"), tea]
    brews = [brew("a", rating=3, days_ago=4), brew("b", rating=3, days_ago=3),
             brew("a", days_ago=2), brew("t", days_ago=1)]
    assert pick(beans, brews, {"a": own("R1"), "b": own("R1")})[0].bag_id == "b"


def test_use_soon_follows_the_grams_brewed_a_day():
    # Two cups a day across two liked bags: a 150 g bag opened 15 days ago
    # finishes in 10 days at 15 g a day, inside the 13 it has left.
    beans = [opened("a", left=150, days_open=15), opened("b")]
    brews = [brew("a", rating=3, days_ago=4), brew("b", rating=3, days_ago=3), brew("a", days_ago=1)]
    picks = candidates(beans, brews, {"a": own("R1"), "b": own("R1")}, {}, "hot", NOW, RULES, DOSE,
                       daily_g=30.0)
    assert picks[0].bag_id == "b"
    one_cup = candidates(beans, brews, {"a": own("R1"), "b": own("R1")}, {}, "hot", NOW, RULES, DOSE)
    assert one_cup[0].bag_id == "a"


def test_rotation_reads_recipe_names_however_they_were_written():
    brews = [brew("a", "daily", days_ago=1), brew("a", "R2", days_ago=3)]
    first = pick([opened("a")], brews, {"a": own("Daily", "R2")})[0]
    assert first.recipe == "R2"


# When the card is due: once a day, from the usual first-cup time when there is one.

from custom_components.xbloom.coffee_lab.todays_cup import due, shows_from  # noqa: E402


def first_cups(hours: list[int]) -> list[Brew]:
    out = []
    for i, h in enumerate(hours):
        day_ = (NOW - timedelta(days=i + 1)).replace(hour=h, minute=15)
        out.append(Brew(id=f"f{i}", brewed_at=day_.isoformat(), recorded_at="", dose_g=DOSE, bean_id="a"))
    return out


def test_a_clear_first_cup_habit_sets_the_time():
    start = shows_from(first_cups([7, 8, 7, 9, 8, 7, 8, 7, 9, 8, 8]), NOW)
    assert (start.hour, start.minute) == (6, 15)


def test_first_cups_spread_out_set_no_time():
    assert shows_from(first_cups([1, 13, 7, 22, 4, 18, 9, 16, 0, 12, 20]), NOW) is None


def test_too_few_days_set_no_time():
    assert shows_from(first_cups([7, 8, 7]), NOW) is None


def test_the_card_waits_for_the_usual_time_then_goes_once_brewed():
    habit = first_cups([7, 8, 7, 9, 8, 7, 8, 7, 9, 8, 8])
    early = NOW.replace(hour=5)
    assert not due(habit, early)
    morning = NOW.replace(hour=6, minute=30)
    assert due(habit, morning)
    brewed = habit + [Brew(id="today", brewed_at=morning.replace(minute=10).isoformat(),
                           recorded_at="", dose_g=DOSE, bean_id="a")]
    assert not due(brewed, morning)


def test_without_a_habit_the_card_is_due_from_midnight_until_the_first_cup():
    assert due([], NOW.replace(hour=0, minute=5))
    today = Brew(id="t", brewed_at=NOW.replace(hour=1).isoformat(), recorded_at="", dose_g=DOSE, bean_id="a")
    assert not due([today], NOW)


def test_tea_or_a_stopped_brew_does_not_count_as_the_days_coffee():
    from custom_components.xbloom.coffee_lab.models import Review
    tea = Brew(id="t", brewed_at=NOW.replace(hour=1).isoformat(), recorded_at="", dose_g=4, dripper="Tea")
    stopped = Brew(id="s", brewed_at=NOW.replace(hour=2).isoformat(), recorded_at="", dose_g=DOSE,
                   review=Review("stopped_after_grinding"))
    assert due([tea, stopped], NOW)


def test_the_habit_is_the_middle_sixty_percent_and_shows_an_hour_before():
    # Ten days: 20th to 80th percentile by the same rounding at both ends.
    start = shows_from(first_cups([7, 7, 7, 8, 8, 8, 8, 9, 13, 14]), NOW)
    assert start is not None and (start.hour, start.minute) == (6, 15)


def test_the_card_shows_an_hour_before_not_up_to_two():
    cups = []
    for i in range(11):
        when = (NOW - timedelta(days=i + 1)).replace(hour=7, minute=54)
        cups.append(Brew(id=f"g{i}", brewed_at=when.isoformat(), recorded_at="", dose_g=DOSE, bean_id="a"))
    start = shows_from(cups, NOW)
    assert (start.hour, start.minute) == (6, 54)


def test_a_brew_with_a_date_but_no_time_says_nothing_about_the_hour():
    cups = first_cups([7, 8, 7, 9, 8, 7, 8, 7, 9, 8, 8])
    cups += [Brew(id=f"d{i}", brewed_at=(NOW - timedelta(days=i + 12)).date().isoformat(),
                  recorded_at="", dose_g=DOSE, bean_id="a") for i in range(5)]
    assert shows_from(cups, NOW) is not None


# ── The last cup of a bag ────────────────────────────────────────────────────


def test_the_last_cup_of_a_bag_offers_all_of_it():
    first = pick([opened("a", left=25.5)], [], {"a": own("R1")})[0]
    assert first.dose_g == 25.5 and "last_cup" in first.reasons


def test_a_last_cup_without_a_recipe_keeps_the_usual_dose():
    first = pick([opened("a", left=25.5)], [])[0]
    assert first.dose_g == DOSE and "last_cup" not in first.reasons
