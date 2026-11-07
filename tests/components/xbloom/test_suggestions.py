"""Ranking your own recipes for a bag from the brew record (suggestions.py)."""
from . import test_init as _ti  # noqa: F401

from custom_components.xbloom.coffee_lab.models import Bean, Brew, Review
from custom_components.xbloom.suggestions import rank

BAG = Bean(id="bag", name="Test Bag", status="open", country="Ethiopia", process="Natural")
TWIN = Bean(id="twin", name="Older Bag", status="finished", country="ethiopia", process="natural")
COUSIN = Bean(id="cousin", name="Washed Bag", status="finished", country="Ethiopia", process="Washed")
FAR = Bean(id="far", name="Far Bag", status="finished", country="Kenya", process="Natural")
BEANS = [BAG, TWIN, COUSIN, FAR]
LIBRARY = [{"name": n} for n in ("Alpha", "Beta", "Gamma", "Delta")]


def brew(recipe, bean, when="2026-10-01", brewer="xBloom Studio", review=None):
    return Brew(id=recipe + when, brewed_at=when, recorded_at=when, dose_g=15.0,
                brewer=brewer, bean_id=bean, recipe=recipe, review=review)


def test_this_bag_outweighs_coffee_like_it():
    brews = [brew("Alpha", "twin"), brew("Alpha", "twin"), brew("Beta", "bag"), brew("Beta", "bag")]
    ranked = rank(BAG, BEANS, brews, LIBRARY)
    assert [(s.name, s.matched, s.brews) for s in ranked] == [("Beta", "this_bag", 2), ("Alpha", "origin_process", 2)]
    assert ranked[0].brews == 2


def test_same_origin_counts_but_another_origin_does_not():
    ranked = rank(BAG, BEANS, [brew("Gamma", "cousin"), brew("Delta", "far")], LIBRARY)
    assert [(s.name, s.matched) for s in ranked] == [("Gamma", "origin")]


def test_recipes_gone_from_the_library_and_other_brewers_are_ignored():
    brews = [brew("Removed", "bag"), brew("Alpha", "bag", brewer="V60"),
             brew("Beta", "bag", review=Review(reason="stopped_after_grinding"))]
    assert rank(BAG, BEANS, brews, LIBRARY) == []


def test_ties_go_to_the_most_recent_and_at_most_three_are_offered():
    brews = [brew(n, "bag", when=f"2026-10-0{i}") for i, n in enumerate(("Alpha", "Beta", "Gamma", "Delta"), 1)]
    assert [s.name for s in rank(BAG, BEANS, brews, LIBRARY)] == ["Delta", "Gamma", "Beta"]


def test_a_recipe_name_matches_the_library_whatever_its_case():
    assert [s.name for s in rank(BAG, BEANS, [brew("alpha", "bag")], LIBRARY)] == ["Alpha"]


def test_the_count_said_is_the_closest_matchs_alone():
    """Ranked on all, but "3 times with this bag" counts this bag only."""
    brews = [brew("Alpha", "bag")] + [brew("Alpha", "twin") for _ in range(4)]
    [only] = rank(BAG, BEANS, brews, LIBRARY)
    assert (only.matched, only.brews) == ("this_bag", 1)


def rated(recipe, bean, rating, when="2026-10-01"):
    from dataclasses import replace

    return replace(brew(recipe, bean, when=when), rating=rating)


def test_a_recipe_rated_again_rises_above_one_brewed_as_often():
    brews = [brew("Alpha", "bag", when="2026-10-05"), rated("Beta", "bag", 3)]
    assert [s.name for s in rank(BAG, BEANS, brews, LIBRARY)] == ["Beta", "Alpha"]


def test_not_again_with_this_bag_keeps_a_recipe_out():
    brews = [rated("Alpha", "bag", 1, when="2026-10-05"), rated("Alpha", "bag", 3, when="2026-10-01")]
    assert rank(BAG, BEANS, brews, LIBRARY) == []


def test_a_later_again_brings_it_back():
    brews = [rated("Alpha", "bag", 3, when="2026-10-05"), rated("Alpha", "bag", 1, when="2026-10-01")]
    assert [s.name for s in rank(BAG, BEANS, brews, LIBRARY)] == ["Alpha"]


def test_not_again_with_another_bag_only_lowers_it():
    brews = [rated("Alpha", "twin", 1), brew("Beta", "cousin")]
    assert [s.name for s in rank(BAG, BEANS, brews, LIBRARY)] == ["Alpha", "Beta"]
