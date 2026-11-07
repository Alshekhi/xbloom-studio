"""How a brew was: the one question, the verdict, and what is kept.

The question is asked for the first brew of a recipe, bag and version (grind,
ratio, dose) that has no verdict, is due a while after the brew, and lapses
after a day. Asking must never undo a count.
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


async def test_a_newer_brew_replaces_the_open_question():
    lab, store, bag = await _lab()
    await _brew(lab, bag, "run-1")
    second = await _brew(lab, bag, "run-2", grind="52")
    assert lab.rating_question["brew_id"] == second.brew_id


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
    assert "rating_question" not in await actions.active_bean(lab, {})
    with _at(lab, 16):
        facts = await actions.active_bean(lab, {})
    assert facts["rating_question"]["recipe"] == "Test Hot"


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
