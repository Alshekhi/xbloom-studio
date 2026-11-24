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
