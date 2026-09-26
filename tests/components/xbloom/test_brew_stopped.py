"""How a stopped brew is reported, and what every event of a brew carries.

A brew someone stops — at the machine, or with Cancel — was reported as a
timeout ten minutes later, or not at all. It is now `xbloom_brew_stopped`,
saying who stopped it. A fault the machine gives up on sends it home a moment
before the fault itself arrives, so a stop waits briefly for one: that fault is
the ending, reported as a failure.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import ACTIVITY_BREWING, CMD_MACHINE_ACTIVITY

from .test_brew_completion_contract import (
    CMD_BREW_END, _Entry, _FakeBle, _make_hass, _setup_and_get_handlers,
)

NO_BEANS = 40517
HOME = 1


def _fired(hass, name):
    return [c.args[1] for c in hass.bus.async_fire.call_args_list if c.args and c.args[0] == name]


async def _until(condition, tries=200):
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("never happened")


@pytest.fixture
def brewing():
    """A brew under way whose RD_ENJOY never comes, with its handlers."""

    async def start(data=None):
        _FakeBle.enjoy = False
        hass, entry = _make_hass(), _Entry()
        stack = [
            patch("custom_components.xbloom._resolve_ble_device",
                  AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))),
            patch("xbloom.ble.XBloomBleClient", _FakeBle),
            patch("custom_components.xbloom.BREW_STOP_GRACE_S", 0.05),
        ]
        for p in stack:
            p.start()
        handlers = await _setup_and_get_handlers(hass, entry)
        response = await handlers["start_brew"](MagicMock(data=data or {}))
        await _until(lambda: _fired(hass, "xbloom_brew_started"))
        return hass, entry, handlers, response, stack

    started = []

    async def fixture(data=None):
        result = await start(data)
        started.append(result[-1])
        return result[:-1]

    yield fixture
    for stack in started:
        for p in stack:
            p.stop()
    # Shared with every module that imports the fake; left False, their brews
    # wait forever for an ending.
    _FakeBle.enjoy = True


def _frame(activity=None, cmd=CMD_MACHINE_ACTIVITY):
    return {"cmd": cmd, "activity": activity} if activity is not None else {"cmd": cmd}


async def test_a_brew_stopped_at_the_machine_is_reported_as_stopped(brewing):
    hass, entry, _h, _r = await brewing({"context": {"chat": "abc"}})
    ble = _FakeBle.instances[-1]
    await ble.on_event(_frame(ACTIVITY_BREWING))
    await ble.on_event(_frame(HOME))
    await entry.tasks[0]

    [stopped] = _fired(hass, "xbloom_brew_stopped")
    assert stopped["by"] == "machine" and stopped["context"] == {"chat": "abc"}
    assert stopped["run_id"] == _fired(hass, "xbloom_brew_started")[0]["run_id"]
    for other in ("xbloom_brew_completed", "xbloom_brew_timeout", "xbloom_brew_failed"):
        assert _fired(hass, other) == [], other


async def test_a_fault_just_after_going_home_is_the_ending_not_a_stop(brewing):
    hass, entry, _h, _r = await brewing()
    ble = _FakeBle.instances[-1]
    await ble.on_event(_frame(ACTIVITY_BREWING))
    await ble.on_event(_frame(HOME))
    await ble.on_event(_frame(cmd=NO_BEANS))
    await entry.tasks[0]

    assert _fired(hass, "xbloom_brew_stopped") == []
    [failed] = _fired(hass, "xbloom_brew_failed")
    assert failed["reason"] == "no_beans" and failed["run_id"]


async def test_the_home_screen_before_the_brew_runs_is_not_a_stop(brewing):
    # An idle machine reports its home screen on connect.
    hass, entry, _h, _r = await brewing()
    ble = _FakeBle.instances[-1]
    with patch("custom_components.xbloom.BREW_END_GRACE_S", 0.01):
        await ble.on_event(_frame(HOME))
        await ble.on_event(_frame(ACTIVITY_BREWING))
        await ble.on_event(_frame(cmd=CMD_BREW_END))
        await entry.tasks[0]

    assert _fired(hass, "xbloom_brew_stopped") == []
    assert _fired(hass, "xbloom_brew_completed")[0]["outcome"] == "presumed"


async def test_cancel_reports_the_brew_stopped_by_home_assistant(brewing):
    hass, entry, handlers, response = await brewing({"context": "ring-back"})
    await handlers["stop_brew"](MagicMock(data={}))

    [stopped] = _fired(hass, "xbloom_brew_stopped")
    assert stopped["by"] == "home_assistant" and stopped["context"] == "ring-back"
    assert stopped["run_id"] == response["run_id"]


async def test_every_event_of_a_brew_carries_its_run_id(brewing):
    hass, entry, _h, response = await brewing()
    ble = _FakeBle.instances[-1]
    with patch("custom_components.xbloom.BREW_END_GRACE_S", 0.01):
        await ble.on_event(_frame(cmd=CMD_BREW_END))
        await entry.tasks[0]
    started = _fired(hass, "xbloom_brew_started")[0]
    completed = _fired(hass, "xbloom_brew_completed")[0]
    assert started["run_id"] == completed["run_id"] == response["run_id"]
    assert "context" not in started, "no context is sent when the caller gave none"


async def test_a_brew_refused_before_it_runs_still_has_a_run_id():
    hass, entry = _make_hass(), _Entry()
    entry.data = {}
    handlers = await _setup_and_get_handlers(hass, entry)
    response = await handlers["start_brew"](MagicMock(data={"context": 7}))
    [failed] = _fired(hass, "xbloom_brew_failed")
    assert failed["run_id"] == response["run_id"] and failed["context"] == 7


async def test_a_stop_says_whether_the_grinder_had_run(brewing):
    hass, entry, _h, _r = await brewing()
    ble = _FakeBle.instances[-1]
    await ble.on_event(_frame(cmd=40502))       # the grinder starting
    await ble.on_event(_frame(ACTIVITY_BREWING))
    await ble.on_event(_frame(HOME))
    await entry.tasks[0]
    [stopped] = _fired(hass, "xbloom_brew_stopped")
    assert stopped["ground"] is True and stopped["dose_g"] == 20


async def test_a_stop_before_grinding_says_so(brewing):
    hass, entry, handlers, _r = await brewing()
    await handlers["stop_brew"](MagicMock(data={}))
    [stopped] = _fired(hass, "xbloom_brew_stopped")
    assert stopped["ground"] is False
