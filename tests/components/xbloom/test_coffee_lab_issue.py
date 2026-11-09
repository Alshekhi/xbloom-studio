"""What was wrong with a cup, and the Next Change it sets.

Sour grinds finer, bitter coarser, too weak a stronger ratio, too strong a
lighter one, each counted from the version brewed and never taking the grind
more than ISSUE_GRIND_REACH from the saved recipe's.
"""
import pytest

from custom_components.xbloom.coffee_lab import actions
from custom_components.xbloom.coffee_lab.lab import issue_change
from custom_components.xbloom.versions import parse_next_change, pending_change

from .test_coffee_lab_rating import SAVED, _at, _brew, _lab


@pytest.mark.parametrize(("issue", "version", "change"), [
    ("sour", {"grind": 50.0, "ratio": 16.0}, "grind 47"),
    ("bitter", {"grind": 50.0, "ratio": 16.0}, "grind 53"),
    ("weak", {"grind": 50.0, "ratio": 16.0}, "ratio 1:15"),
    ("strong", {"grind": 50.0, "ratio": 16.5}, "ratio 1:17.5"),
    ("none", {"grind": 50.0, "ratio": 16.0}, None),
    ("sour", {"grind": None, "ratio": 16.0}, None),
])
def test_each_answer_moves_one_setting_one_step(issue, version, change):
    assert issue_change(issue, version, SAVED) == change
    if change:
        assert parse_next_change(change), "written in words the Next Change is read in"


def test_answers_stop_six_grind_steps_from_the_saved_recipe():
    assert issue_change("sour", {"grind": 45.0}, SAVED) == "grind 44"
    assert issue_change("sour", {"grind": 44.0}, SAVED) is None
    assert issue_change("bitter", {"grind": 55.0}, SAVED) == "grind 56"


def test_the_ratio_stays_within_the_machine_s():
    assert issue_change("strong", {"ratio": 25.0}, SAVED) is None


async def test_what_was_wrong_is_asked_after_fine_or_not_again_and_sets_the_next_change():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="50")
    with _at(lab, 16):
        question = lab.rating_question_due()
        assert lab.issue_question is None, "not before the verdict"
        await lab.async_rate(verdict="fine", brew_id=question["brew_id"])
        asked = lab.issue_question
        assert (asked["brew_id"], asked["recipe"], asked["bag"]) == (question["brew_id"], "Test Hot", "Kenya")
        await lab.async_rate(issue="sour", brew_id=asked["brew_id"])
        assert lab.issue_question is None, "answered, it goes"
        brews = await store.async_list_brews()
        assert pending_change(brews, "Test Hot", bag.id)["settings"] == {"grind": 47.0}


@pytest.mark.parametrize("verdict", ["again"])
async def test_a_cup_liked_is_not_asked_what_was_wrong(verdict):
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    with _at(lab, 16):
        await lab.async_rate(verdict=verdict)
    assert lab.issue_question is None


async def test_nothing_wrong_sets_nothing_and_closes_the_question():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    with _at(lab, 16):
        await lab.async_rate(verdict="not_again")
        await lab.async_rate(issue="none")
    assert lab.issue_question is None
    assert pending_change(await store.async_list_brews(), "Test Hot", bag.id) is None


async def test_an_issue_given_with_the_verdict_is_not_asked_again():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="50")
    with _at(lab, 16):
        await lab.async_rate(verdict="fine", issue="bitter")
    assert lab.issue_question is None
    assert pending_change(await store.async_list_brews(), "Test Hot", bag.id)["settings"] == {"grind": 53.0}


async def test_the_action_says_what_it_set_and_takes_an_issue_alone():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="50")
    with _at(lab, 16):
        facts = await actions.rate_brew(lab, {"issue": "weak"})
    assert facts["next_change"] == "ratio 1:15"


async def test_a_brew_with_no_question_is_answered_from_its_own_record():
    lab, store, bag = await _lab()
    result = await _brew(lab, bag, "run-1", grind="50")
    await lab.async_rate(verdict="fine", brew_id=result.brew_id)
    facts = await actions.rate_brew(lab, {"issue": "bitter", "brew_id": result.brew_id})
    assert facts["next_change"] == "grind 53"
