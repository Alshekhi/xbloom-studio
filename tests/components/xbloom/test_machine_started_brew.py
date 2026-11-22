"""A prepared recipe started with the machine's own button is followed.

The machine shows a prepared recipe on its recipe screen (activity 31), and its
button starts it with 40502 — the frame a start from Home Assistant produces
too. Nothing of Home Assistant's ran for that brew: no "started preparing"
announcement, no completion, no record, and Pause and Cancel had no brew to act
on. Now such a brew is followed as if Home Assistant had started it, with
nothing sent to the machine.
"""
import asyncio
from unittest.mock import MagicMock, patch

from xbloom import ble

from custom_components.xbloom.ble_entities import signal_event

from .test_brew_completion_contract import _Entry, _make_hass, _setup_and_get_handlers
from .test_held_session import _PreparingSession, _fired, _frames_through_the_session, _machine_in_range

RECIPE_SCREEN = {"cmd": 8023, "activity": 31}
BUTTON = {"cmd": 40502}


async def _rig():
    hass = _make_hass()
    tasks: list[asyncio.Task] = []

    def _create_task(coro, *_a, **_kw):
        task = asyncio.get_event_loop().create_task(coro)
        tasks.append(task)
        return task

    hass.async_create_task = _create_task
    entry = _Entry()
    followers: list = []

    def _connect(_hass, signal, handler):
        if signal == signal_event(entry.entry_id):
            followers.append(handler)
        return lambda: None

    with patch("custom_components.xbloom.async_dispatcher_connect", _connect), _machine_in_range():
        handlers = await _setup_and_get_handlers(hass, entry)
    session = _PreparingSession()
    entry.runtime_data.live_session_listener = session
    return hass, entry, handlers, session, followers, tasks


def _hear(followers, *frames):
    for frame in frames:
        for follow in followers:
            follow(frame)


async def _settle():
    for _ in range(20):
        await asyncio.sleep(0)


async def test_the_button_on_a_prepared_recipe_is_followed_without_sending_anything():
    hass, entry, _handlers, session, followers, tasks = await _rig()
    frames, capture = _frames_through_the_session()
    with capture, _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN, BUTTON)
        await _settle()
        assert [e["recipe_name"] for e in _fired(hass, "xbloom_brew_started")] == ["Test Recipe One"]
        for frame in frames:
            await frame({"cmd": 40512})
        await asyncio.gather(*tasks)
        await entry.tasks[0]

    assert session.sent == ["prepare"]
    assert [e["outcome"] for e in _fired(hass, "xbloom_brew_completed")] == ["confirmed"]


async def test_the_button_is_followed_once():
    hass, entry, _handlers, _session, followers, tasks = await _rig()
    with _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN, BUTTON, BUTTON)
        await _settle()
    assert len(tasks) == 1
    for task in (*tasks, *entry.tasks):
        task.cancel()


async def test_nothing_is_followed_without_a_prepared_recipe():
    _hass, _entry, _handlers, _session, followers, tasks = await _rig()
    _hear(followers, RECIPE_SCREEN, BUTTON)
    await _settle()
    assert tasks == []


async def test_a_grinder_start_off_the_recipe_screen_is_not_the_button():
    # The standalone grinder, or a brew Home Assistant is already running.
    _hass, entry, _handlers, _session, followers, tasks = await _rig()
    with _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, {"cmd": 8023, "activity": 2}, BUTTON)
        await _settle()
    assert tasks == []


async def test_a_start_from_home_assistant_is_not_followed_a_second_time():
    hass, entry, handlers, session, followers, tasks = await _rig()
    frames, capture = _frames_through_the_session()
    with capture, _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        await handlers["start_brew"](MagicMock(data={"dose": 15}))
        await _settle()
        _hear(followers, RECIPE_SCREEN, BUTTON)
        await _settle()
        for frame in frames:
            await frame({"cmd": 40512})
        await entry.tasks[0]

    assert [t for t in tasks if t.get_coro().__name__ == "_start_brew"] == []
    assert session.sent == ["prepare", "start"]
    assert len(_fired(hass, "xbloom_brew_started")) == 1


async def test_a_brew_from_the_machines_own_slots_is_announced_without_a_name():
    # Nothing prepared: the machine brews a recipe Home Assistant never sent.
    hass, _entry, _handlers, _session, followers, tasks = await _rig()
    _hear(followers, {"cmd": 8023, "activity": 65}, BUTTON, BUTTON)
    await _settle()
    assert tasks == []
    assert _fired(hass, "xbloom_machine_brew_started") == [{}]


async def test_a_followed_brew_is_not_also_announced_as_a_slot_brew():
    hass, entry, _handlers, _session, followers, tasks = await _rig()
    with _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN, BUTTON, BUTTON)
        await _settle()
    assert _fired(hass, "xbloom_machine_brew_started") == []
    for task in (*tasks, *entry.tasks):
        task.cancel()


LOW = {"cmd": 40522, "water_enough": 0}
WATER_SCREEN = {"cmd": 8023, "activity": 12}


async def test_a_prepared_recipe_refused_at_the_button_is_a_failed_start():
    # Home Assistant sent nothing for this start, so no refusal reaches it: the
    # machine answers the button with the low-water switch and its water screen.
    hass, entry, _handlers, _session, followers, tasks = await _rig()
    with _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN, LOW, WATER_SCREEN)
        await _settle()
    failed = _fired(hass, "xbloom_brew_failed")
    assert len(failed) == 1
    assert failed[0]["reason"] == "no_water"
    assert failed[0]["recipe_name"] == "Test Recipe One"
    assert failed[0]["water_needed_ml"] > 0
    assert tasks == []


async def test_a_refusal_at_the_button_without_a_prepared_recipe_has_no_name():
    hass, _entry, _handlers, _session, followers, _tasks = await _rig()
    _hear(followers, RECIPE_SCREEN, LOW, WATER_SCREEN)
    await _settle()
    assert _fired(hass, "xbloom_brew_failed") == [{"reason": "no_water", "recipe_name": None}]


async def test_the_water_screen_mid_brew_is_not_a_refused_start():
    hass, _entry, _handlers, _session, followers, _tasks = await _rig()
    _hear(followers, {"cmd": 8023, "activity": 35}, LOW, WATER_SCREEN)
    await _settle()
    assert _fired(hass, "xbloom_brew_failed") == []


class _RefusingStart(_PreparingSession):
    async def send_start(self):
        self.sent.append("start")
        raise ble.CommandRefused("execute", "no_water")


async def test_a_start_from_home_assistant_refused_for_water_is_reported_once():
    # Home Assistant's own start hears the refusal and reports it; the water
    # screen the machine shows next is that same refusal, not a second one.
    hass, entry, handlers, _session, followers, _tasks = await _rig()
    entry.runtime_data.live_session_listener = _RefusingStart()
    with _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN)
        await handlers["start_brew"](MagicMock(data={"dose": 15}))
        await _settle()
        _hear(followers, LOW, WATER_SCREEN)
        await _settle()
    assert [e["reason"] for e in _fired(hass, "xbloom_brew_failed")] == ["no_water"]


async def test_the_started_brew_carries_its_pour_plan():
    # Brew Stage tells a pour's end from it, so a prepared brew the button
    # started gets its waits and countdown like one Home Assistant started.
    hass, entry, _handlers, session, followers, tasks = await _rig()
    frames, capture = _frames_through_the_session()
    with capture, _machine_in_range():
        await entry.runtime_data.preparer._prepare({"dose": 15})
        _hear(followers, RECIPE_SCREEN, BUTTON)
        await _settle()
        started = _fired(hass, "xbloom_brew_started")
        for frame in frames:
            await frame({"cmd": 40512})
        await asyncio.gather(*tasks)
        await entry.tasks[0]

    # The plan is the recipe as sent, after the prepare step scaled it.
    [pour] = started[0]["pours"]
    assert (pour["water_ml"], pour["wait_s"]) == (started[0]["recipe_water_ml"], 0)
