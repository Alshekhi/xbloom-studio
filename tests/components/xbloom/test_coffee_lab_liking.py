"""How much a coffee is liked, worked out from what was already asked."""
from custom_components.xbloom.coffee_lab.liking import LIKED, NOT_KNOWN, NOT_LIKED, liking
from custom_components.xbloom.coffee_lab.models import Bean, Brew

BAG = Bean(id="b1", name="Hill Farm", status="open", roaster="North")
EARLIER = Bean(id="b0", name="Hill Farm", status="finished", roaster="North", finished_on="2026-08-01")
OTHER = Bean(id="x", name="Valley Lot", status="open", roaster="South")


def rated(bean: str, recipe: str, rating: int, n: int = 0) -> Brew:
    return Brew(id=f"{bean}{recipe}{n}", brewed_at=f"2026-09-0{n + 1}T08:00:00+00:00",
                recorded_at="", dose_g=17.0, bean_id=bean, recipe=recipe, rating=rating)


def test_one_recipe_rated_again_makes_the_coffee_liked():
    brews = [rated("b1", "A", 3), rated("b1", "B", 1)]
    assert liking(BAG, [BAG], brews) == LIKED


def test_every_recipe_doesnt_suit_makes_it_not_liked():
    brews = [rated("b1", "A", 1), rated("b1", "B", 1)]
    assert liking(BAG, [BAG], brews) == NOT_LIKED


def test_close_needs_a_tweak_alone_says_nothing_yet():
    assert liking(BAG, [BAG], [rated("b1", "A", 2)]) == NOT_KNOWN


def test_nothing_rated_is_not_known():
    assert liking(BAG, [BAG], [rated("x", "A", 3)]) == NOT_KNOWN


def test_the_latest_verdict_for_a_recipe_counts():
    brews = [rated("b1", "A", 3, 0), rated("b1", "A", 1, 1)]
    assert liking(BAG, [BAG], brews) == NOT_LIKED


def test_the_same_coffee_bought_before_counts():
    assert liking(BAG, [BAG, EARLIER], [rated("b0", "A", 3)]) == LIKED


def test_buy_again_yes_settles_it_as_liked():
    yes = Bean(**{**EARLIER.__dict__, "buy_again": "yes"})
    assert liking(BAG, [BAG, yes], []) == LIKED
    assert liking(BAG, [BAG, yes], [rated("b1", "A", 1)]) == LIKED


def test_buy_again_no_or_maybe_says_nothing_about_taste():
    # Not buying a coffee again can be its price or wanting something new.
    for answer in ("no", "maybe"):
        bag = Bean(**{**EARLIER.__dict__, "buy_again": answer})
        assert liking(BAG, [BAG, bag], []) == NOT_KNOWN
        assert liking(BAG, [BAG, bag], [rated("b1", "A", 3)]) == LIKED
        assert liking(BAG, [BAG, bag], [rated("b1", "A", 1)]) == NOT_LIKED
