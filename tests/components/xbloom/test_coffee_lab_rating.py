"""How a brew was: the questions, the verdict, and what is kept.

A question is asked for a recipe, bag and version (grind, ratio, dose) that
has no verdict; cups of the same one share it, and a different one gets its
own. Each is due a while after its last cup and lapses after a day. Asking
must never undo a count.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom.coffee_lab import actions, lab as lab_module
from custom_components.xbloom.coffee_lab.lab import CoffeeLab, brew_version, version_changes
from custom_components.xbloom.coffee_lab.notion import brew_from_page, rating_properties
from custom_components.xbloom.coffee_lab.store import LocalStore, ProcessedRuns

from .test_coffee_lab_store import FakeStorage

SAVED = {"name": "Test Hot", "dose_g": 15.0, "water_ratio": 16.0, "grinder_size": 50, "rpm": 90,
         "pour_count": 3}


async def _lab():
    store = LocalStore(FakeStorage())
    runs = ProcessedRuns(FakeStorage())
    await store.async_load()
    await runs.async_load()
    lab = CoffeeLab(store, runs, FakeStorage(), on_change=MagicMock())
    await lab.async_load_state()
    lab.recipe_lookup = lambda name: SAVED if name == "Test Hot" else None
    bag = await store.async_add_bean(name="Kenya", status="open", tracked=True, remaining_g=200.0)
    return lab, store, bag


async def _brew(lab, bag, run, grind="50", ratio=16.0, grams=15, recipe="Test Hot"):
    return await lab.async_consume(
        bean_id=bag.id, grams=grams, run_id=run, recipe=recipe,
        settings={"grind": grind, "ratio": ratio},
    )


def _at(lab, minutes):
    """The clock, `minutes` after now."""
    later = lab_module.dt_util.utcnow() + timedelta(minutes=minutes)
    return patch.object(lab_module.dt_util, "utcnow", return_value=later)


async def test_the_first_brew_of_a_recipe_with_a_bag_is_asked_about_later():
    lab, store, bag = await _lab()
    result = await _brew(lab, bag, "run-1")
    question = lab.rating_question
    assert question["brew_id"] == result.brew_id
    assert (question["recipe"], question["bag"], question["changes"]) == ("Test Hot", "Kenya", [])
    assert lab.rating_question_due() is None, "not with the cup in hand"
    with _at(lab, 16):
        assert lab.rating_question_due() is not None
    with _at(lab, 60 * 25):
        assert lab.rating_question is None, "lapsed after a day"


async def test_a_manual_brew_is_never_asked_about():
    lab, store, bag = await _lab()
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="m-1", brewer="V60")
    assert lab.rating_question is None


async def test_a_version_already_rated_is_not_asked_again():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    await lab.async_rate(verdict="fine")
    assert lab.rating_question is None
    await _brew(lab, bag, "run-2", grind="50.0")  # the same grind, as the record keeps it
    assert lab.rating_question is None


async def test_a_changed_version_is_asked_about_and_names_the_change():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    await lab.async_rate(verdict="fine")
    await _brew(lab, bag, "run-2", grind="52")
    assert lab.rating_question["changes"] == [{"setting": "grind", "value": 52.0, "saved": 50.0}]


async def test_two_cups_of_the_same_coffee_share_one_question_due_after_the_second():
    lab, store, bag = await _lab()
    first = await _brew(lab, bag, "run-1")
    with _at(lab, 10):
        second = await _brew(lab, bag, "run-2")
    [question] = lab.rating_questions
    assert question["brew_ids"] == [first.brew_id, second.brew_id]
    with _at(lab, 20):
        assert lab.rating_question_due() is None, "not before the second cup can be tasted"
    with _at(lab, 26):
        await lab.async_rate(verdict="again", tasting={"sweetness": "high"})
    brews = {b.id: b for b in await store.async_list_brews()}
    assert {brews[first.brew_id].rating, brews[second.brew_id].rating} == {3}
    assert brews[first.brew_id].tasting == brews[second.brew_id].tasting
    assert lab.rating_questions == []


async def test_another_version_recipe_or_bag_gets_its_own_question_oldest_first():
    lab, store, bag = await _lab()
    other_bag = await store.async_add_bean(name="Colombia", status="open", tracked=True, remaining_g=200.0)
    first = await _brew(lab, bag, "run-1")
    changed = await _brew(lab, bag, "run-2", grind="52")
    elsewhere = await _brew(lab, other_bag, "run-3")
    assert [q["brew_id"] for q in lab.rating_questions] == [
        first.brew_id, changed.brew_id, elsewhere.brew_id,
    ]
    with _at(lab, 16):
        assert lab.rating_question_due()["brew_id"] == first.brew_id
        await lab.async_rate(verdict="fine")
        assert lab.rating_question_due()["brew_id"] == changed.brew_id
        await lab.async_rate(verdict="again", brew_id=elsewhere.brew_id)
        assert [q["brew_id"] for q in lab.rating_questions] == [changed.brew_id]


async def test_no_more_than_three_questions_stay_open():
    lab, store, bag = await _lab()
    cups = [await _brew(lab, bag, f"run-{g}", grind=str(g)) for g in (50, 51, 52, 53)]
    assert [q["brew_id"] for q in lab.rating_questions] == [c.brew_id for c in cups[1:]]


async def test_a_question_kept_by_the_earlier_single_slot_is_still_asked():
    lab, store, bag = await _lab()
    result = await _brew(lab, bag, "run-1")
    question = lab.rating_question
    del question["brew_ids"]
    lab._state = {"rating_question": question}
    assert lab.rating_question["brew_ids"] == [result.brew_id]
    await lab.async_rate(verdict="fine")
    assert lab.rating_question is None


async def test_two_changed_versions_rated_again_are_both_offered_in_turn():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1", grind="52")
    await _brew(lab, bag, "run-2", grind="54")
    await lab.async_rate(verdict="again")
    await lab.async_rate(verdict="again")
    assert [k["label"] for k in lab.versions_to_keep] == ["grind 52", "grind 54"]
    await lab.async_clear_version_to_keep()
    assert lab.version_to_keep["label"] == "grind 54"


async def test_answering_keeps_the_verdict_and_closes_the_question():
    lab, store, bag = await _lab()
    result = await _brew(lab, bag, "run-1")
    await lab.async_rate(verdict="again")
    [brew] = await store.async_list_brews()
    assert (brew.id, brew.rating) == (result.brew_id, 3)
    assert lab.rating_question is None


async def test_rate_brew_keeps_only_what_was_said():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    facts = await actions.rate_brew(lab, {
        "sweetness": "High", "cool_notes": "chocolate as it cooled", "next_change": "grind 52",
    })
    brew = facts["brew"]
    assert brew["tasting"] == {"sweetness": "high", "cool_notes": "chocolate as it cooled"}
    assert brew["next_change"] == "grind 52"
    assert "verdict" not in brew, "no verdict was given"
    assert lab.rating_question is not None, "still open without a verdict"


async def test_rate_brew_with_nothing_to_keep_is_refused():
    from homeassistant.exceptions import ServiceValidationError

    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    with pytest.raises(ServiceValidationError):
        await actions.rate_brew(lab, {})


async def test_a_failure_while_asking_never_undoes_the_count():
    lab, store, bag = await _lab()

    async def broken(**kwargs):
        raise RuntimeError("history unreadable")

    store.async_list_brews = broken
    result = await _brew(lab, bag, "run-1")
    assert result.result == "counted"
    assert lab.rating_question is None


async def test_the_open_question_reaches_an_agent_once_due():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    assert "rating_questions" not in await actions.active_bean(lab, {})
    with _at(lab, 16):
        facts = await actions.active_bean(lab, {})
    [question] = facts["rating_questions"]
    assert (question["recipe"], question["cups"]) == ("Test Hot", 1)


def test_versions_compare_as_numbers():
    assert brew_version(15, {"grind": "50", "ratio": 16}) == brew_version(15.0, {"grind": "50.0", "ratio": 16.0})


def test_changes_are_against_the_saved_recipe():
    version = brew_version(18, {"grind": "50", "ratio": 15})
    assert version_changes(version, SAVED) == [
        {"setting": "ratio", "value": 15.0, "saved": 16.0},
        {"setting": "dose_g", "value": 18.0, "saved": 15.0},
    ]
    assert version_changes(version, None) == []


def test_notion_writes_and_reads_back_the_same_verdict_and_tasting():
    props = rating_properties(3, {"body": "full", "hot_notes": "bright"}, "grind 52")
    page = {"id": "p", "properties": {**props, "Brew": {"title": []}}}
    # Notion answers a select by name and text as plain_text.
    page["properties"]["Body"] = {"select": {"name": "Full"}}
    page["properties"]["Hot Notes"] = {"rich_text": [{"plain_text": "bright"}]}
    page["properties"]["Next Change"] = {"rich_text": [{"plain_text": "grind 52"}]}
    brew = brew_from_page(page)
    assert (brew.rating, brew.tasting, brew.next_change) == (3, {"body": "full", "hot_notes": "bright"}, "grind 52")


def test_the_question_sensor_ticks_in_home_assistants_event_loop():
    """A timer runs a plain function in a worker thread; only a callback runs in the loop.

    Read from the source, since each test module stubs `callback` its own way.
    """
    import ast
    import inspect

    from custom_components.xbloom.coffee_lab import entities

    tree = ast.parse(inspect.getsource(entities.RatingQuestionSensor))
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_tick")
    assert any(isinstance(d, ast.Name) and d.id == "callback" for d in tick.decorator_list)


# ── Buy again: one question per bag, when it is finished ─────────────────────


async def test_finishing_a_bag_asks_whether_to_buy_it_again():
    lab, store, bag = await _lab()
    await store.async_update_bean(bag.id, remaining_g=10.0)
    await lab.async_finish(bag.id)
    assert lab.bag_question["name"] == "Kenya"
    bean = await lab.async_rate_bag("yes")
    assert bean.buy_again == "yes" and lab.bag_question is None


async def test_a_brew_that_empties_the_bag_asks_too():
    lab, store, bag = await _lab()
    await store.async_update_bean(bag.id, remaining_g=15.0)
    await _brew(lab, bag, "run-1", grams=15)
    assert lab.bag_question["bean_id"] == bag.id


async def test_a_bag_already_answered_is_not_asked_again():
    lab, store, bag = await _lab()
    await store.async_update_bean(bag.id, remaining_g=10.0, buy_again="no")
    await lab.async_finish(bag.id)
    assert lab.bag_question is None


async def test_the_bag_question_lapses_after_a_week():
    lab, store, bag = await _lab()
    await store.async_update_bean(bag.id, remaining_g=10.0)
    await lab.async_finish(bag.id)
    with _at(lab, 60 * 24 * 8):
        assert lab.bag_question is None


async def test_rate_bag_reaches_the_finished_bag_and_an_agent_sees_the_question():
    lab, store, bag = await _lab()
    await store.async_update_bean(bag.id, remaining_g=10.0)
    await lab.async_finish(bag.id)
    assert (await actions.active_bean(lab, {}))["bag_question"]["bag"] == "Kenya"
    facts = await actions.rate_bag(lab, {"buy_again": "maybe"})
    assert facts["bag"]["buy_again"] == "maybe"


def test_notion_keeps_buy_again_in_its_own_column():
    from custom_components.xbloom.coffee_lab.notion import bean_from_page, bean_properties

    assert bean_properties({"buy_again": "maybe"}) == {"Buy Again": {"select": {"name": "Maybe"}}}
    page = {"id": "b", "properties": {"Buy Again": {"select": {"name": "Maybe"}}}}
    assert bean_from_page(page).buy_again == "maybe"


async def test_the_rate_brew_service_needs_no_bag_and_answers_the_question():
    from custom_components.xbloom.coffee_lab import services

    lab, store, bag = await _lab()
    result = await _brew(lab, bag, "run-1")
    handlers = {}
    hass = MagicMock()
    hass.services.async_register.side_effect = (
        lambda domain, name, handler, **kw: handlers.__setitem__(name, (handler, kw["schema"]))
    )
    services.async_register_lab_services(hass, lab)
    handler, _ = handlers["rate_brew"]  # the schema is stubbed here; Home Assistant checks it
    call = MagicMock(service="rate_brew", data={"brew_id": result.brew_id, "verdict": "again"},
                     return_response=False)
    await handler(call)
    [brew] = await store.async_list_brews()
    assert brew.rating == 3 and lab.rating_question is None
