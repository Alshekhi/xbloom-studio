"""The rating, asked of the brew's caller once due, once a sitting (rating_calls.py)."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from . import test_init as _ti  # noqa: F401

from custom_components.xbloom import rating_calls
from custom_components.xbloom.rating_calls import RatingAsker

from .test_coffee_lab_rating import _at, _brew, _lab


class FakeHass:
    def __init__(self):
        self.tasks = []

    def async_create_task(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


class FakeCallbacks:
    def __init__(self, callers):
        self.callers = callers
        self.targets = {"phone": object()}
        self.sent = []

    def caller_of(self, run_id):
        return self.callers.get(run_id)

    def send_rating_due(self, target, context, questions):
        self.sent.append((target, context, [(q["brew_id"], q["recipe"]) for q in questions]))


async def _settle(hass):
    while hass.tasks:
        await hass.tasks.pop(0)


@pytest.fixture
def timers():
    """Every timer set, as (when, callback); fired by hand."""
    set_ = []

    def track(hass, action, when):
        set_.append((when, action))
        return lambda: set_.remove((when, action)) if (when, action) in set_ else None

    with patch.object(rating_calls, "async_track_point_in_utc_time", side_effect=track):
        yield set_


async def _asker(callers):
    lab, store, bag = await _lab()
    hass, callbacks = FakeHass(), FakeCallbacks(callers)
    asker = RatingAsker(hass, lab, callbacks)
    asker.start()
    return lab, bag, hass, callbacks, asker


async def _fire(hass, timers):
    when, action = timers.pop()
    action(when)
    await _settle(hass)


async def test_a_brew_an_agent_started_is_asked_about_once_when_due(timers):
    lab, bag, hass, callbacks, asker = await _asker({"run-1": ("phone", {"member": "m"})})
    result = await _brew(lab, bag, "run-1")
    await _settle(hass)
    [(when, _)] = timers
    assert when.isoformat() == lab.rating_question["due_at"], "asked when the card appears, not before"
    assert callbacks.sent == []
    await _fire(hass, timers)
    assert callbacks.sent == [("phone", {"member": "m"}, [(result.brew_id, "Test Hot")])]
    assert lab.rating_question["asked"] is True
    timers.clear()
    asker.start()
    assert timers == [], "never sent twice"


async def test_nothing_is_sent_once_the_card_was_answered(timers):
    lab, bag, hass, callbacks, _ = await _asker({"run-1": ("phone", None)})
    await _brew(lab, bag, "run-1")
    await _settle(hass)
    await lab.async_rate(verdict="fine")
    await _fire(hass, timers)
    assert callbacks.sent == []


async def test_a_brew_started_on_the_dashboard_is_left_to_the_card(timers):
    lab, bag, hass, callbacks, _ = await _asker({})
    await _brew(lab, bag, "run-1")
    await _settle(hass)
    assert timers == [] and callbacks.sent == []


async def test_a_question_open_before_a_restart_is_still_asked(timers):
    lab, bag, hass, callbacks, asker = await _asker({"run-1": ("phone", None)})
    await _brew(lab, bag, "run-1")
    await _settle(hass)
    asker.stop()
    timers.clear()
    # Home Assistant starts again: the callers in memory are gone, the question is not.
    restarted = RatingAsker(hass, lab, FakeCallbacks({}))
    restarted.start()
    await _fire(hass, timers)
    assert restarted._callbacks.sent and restarted._callbacks.sent[0][0] == "phone"


async def test_cups_in_one_sitting_are_one_message_after_the_last(timers):
    callers = {f"run-{i}": ("phone", {"member": "m"}) for i in (1, 2, 3)}
    lab, bag, hass, callbacks, _ = await _asker(callers)
    first = await _brew(lab, bag, "run-1")
    await _settle(hass)
    with _at(lab, 5):
        again = await _brew(lab, bag, "run-2")
        await _settle(hass)
    with _at(lab, 10):
        other = await _brew(lab, bag, "run-3", recipe="Test Iced")
        await _settle(hass)
    [(when, _)] = timers
    assert when.isoformat() == lab.rating_questions[-1]["due_at"], "after the last cup"
    await _fire(hass, timers)
    [(target, context, asked)] = callbacks.sent
    assert asked == [(again.brew_id, "Test Hot"), (other.brew_id, "Test Iced")]
    assert lab.question_of(first.brew_id)["brew_ids"] == [first.brew_id, again.brew_id]


async def test_each_member_is_asked_about_their_own_cups(timers):
    callers = {"run-1": ("phone", {"member": "a"}), "run-2": ("phone", {"member": "b"})}
    lab, bag, hass, callbacks, _ = await _asker(callers)
    await _brew(lab, bag, "run-1")
    await _brew(lab, bag, "run-2", recipe="Test Iced")
    await _settle(hass)
    while timers:
        await _fire(hass, timers)
    assert sorted(c[1]["member"] for c in callbacks.sent) == ["a", "b"]


async def test_a_dashboard_cup_of_an_agent_s_coffee_moves_the_call_after_it(timers):
    lab, bag, hass, callbacks, _ = await _asker({"run-1": ("phone", None)})
    await _brew(lab, bag, "run-1")
    await _settle(hass)
    with _at(lab, 10):
        await _brew(lab, bag, "run-2")
        await _settle(hass)
    [(when, _)] = timers
    assert when.isoformat() == lab.rating_question["due_at"]


def test_the_rating_message_is_its_own_message_after_the_ending():
    from custom_components.xbloom.callbacks import Callbacks

    callbacks = Callbacks(MagicMock(), {})
    callbacks.send_rating_due("phone", {"member": "m"}, [
        {"brew_id": "b1", "brew_ids": ["b0", "b1"], "run_id": "r1", "recipe": "Test Hot",
         "bag": "Kenya", "changes": []},
        {"brew_id": "b2", "run_id": "r2", "recipe": "Test Iced", "bag": "Kenya", "changes": []},
    ])
    message = callbacks._queue.get_nowait()
    data = message.payload["data"]
    assert message.payload["type"] == "xbloom.rating.due"
    assert (data["event"], data["final"], data["run_id"]) == ("rating_due", False, "r2")
    assert (data["brew_id"], data["recipe"]) == ("b1", "Test Hot")
    assert [(b["brew_id"], b["cups"]) for b in data["brews"]] == [("b1", 2), ("b2", 1)]
    assert message.payload["context"] == {"member": "m"}
