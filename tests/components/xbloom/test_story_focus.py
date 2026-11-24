"""What to notice in a cup: decided by rule before anything is written."""
import pytest

from custom_components.xbloom.coffee_lab.models import Bean, Brew
from custom_components.xbloom.stories.content import Content
from custom_components.xbloom.stories.focus import Focus, decide, sentence

BAG = Bean(id="b2", name="Test Coffee", status="open", roaster="Test Roaster", roast_date="2026-11-01")
OLD = Bean(id="b1", name="Test Coffee", status="finished", roaster="Test Roaster", roast_date="2026-10-01")
OTHER = Bean(id="b3", name="Test Coffee", status="open", roaster="Other Roaster")
NOW = {"grind": 50, "ratio": 15, "temperature_c": 92, "dose_g": 17}


def brew(bean="b2", recipe="Test Hot", grind="50.0", ratio=15.0, temp=92, next_change="", dose=20):
    return Brew(id="x", brewed_at="2026-11-20", recorded_at="2026-11-20", dose_g=dose, bean_id=bean,
                recipe=recipe, settings={"grind": grind, "ratio": ratio, "temperature_c": temp},
                next_change=next_change)


def test_the_same_recipe_coffee_and_settings_has_nothing_to_notice():
    # The dose is how much is made: 17 g against 20 g is not a case.
    assert decide("Test Hot", NOW, BAG, [BAG], [brew(dose=20)]) is None


def test_a_recipe_never_brewed_with_the_coffee_is_its_first_time():
    assert decide("Test Hot", NOW, BAG, [BAG], [brew(recipe="Other")]) == Focus("first_time")


def test_a_changed_setting_is_named_with_before_and_now():
    focus = decide("test hot", NOW, BAG, [BAG], [brew(grind="53", temp=90)])
    assert focus == Focus("changed", {"grind": (53.0, 50.0), "temperature_c": (90.0, 92.0)})


def test_the_change_asked_for_last_time_is_its_own_case():
    focus = decide("Test Hot", NOW, BAG, [BAG], [brew(grind="53", next_change="grind 50")])
    assert focus == Focus("next_change", {"grind": (53.0, 50.0)})


def test_a_change_other_than_the_one_asked_for_is_a_plain_change():
    focus = decide("Test Hot", NOW, BAG, [BAG], [brew(grind="53", next_change="grind 47")])
    assert focus.case == "changed"


def test_the_coffee_s_earlier_bag_counts_and_a_new_bag_is_its_own_case():
    assert decide("Test Hot", NOW, BAG, [BAG, OLD], [brew(bean="b1")]) == Focus("new_bag")
    # Once the new bag has brewed it, it is the same cup again.
    assert decide("Test Hot", NOW, BAG, [BAG, OLD], [brew(), brew(bean="b1")]) is None


def test_another_roaster_s_coffee_of_that_name_is_not_its_history():
    assert decide("Test Hot", NOW, BAG, [BAG, OTHER], [brew(bean="b3")]) == Focus("first_time")


@pytest.mark.parametrize("bag", [None, Bean(id="t", name="Tea", status="open", kind="tea")])
def test_no_bag_of_coffee_has_nothing_to_notice(bag):
    assert decide("Test Hot", NOW, bag, [], []) is None


def test_the_built_in_sentence_names_each_change():
    focus = Focus("changed", {"grind": (53.0, 50.0), "temperature_c": (90.0, 92.0)})
    assert sentence(focus, Content.load("en")) == (
        "The grind is 50 instead of 53, and the water is 92 degrees instead of 90 since the "
        "last cup of this recipe with this coffee: what changed in the taste?")
    # The same sentence in Arabic, built from that file's own words.
    ar = Content.load("ar")
    named = ar.entry("focus.and").join([
        ar.entry("focus.changes.grind").format(before="53", now="50"),
        ar.entry("focus.changes.temperature_c").format(before="90", now="92")])
    assert sentence(focus, ar) == ar.entry("focus.changed").format(changes=named)


def test_the_events_carry_the_case_the_changes_and_the_sentence():
    data = Focus("next_change", {"grind": (53.0, 50.0)}).as_data("text")
    assert data == {"case": "next_change", "changes": [{"setting": "grind", "before": 53.0, "now": 50.0}],
                    "text": "text"}
