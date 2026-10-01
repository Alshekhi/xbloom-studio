"""Brew Paused follows the machine's own pause and resume frames.

A paused recipe brew sends 40515 and a resumed one 40516, whoever paused it.
The dashboard shows Pause or Resume by it, so it must never outlive the brew.
"""
from unittest.mock import MagicMock, patch

import pytest

import custom_components.xbloom.binary_sensor as bs
from custom_components.xbloom.binary_sensor import XBloomBrewPausedSensor

PAUSED, RESUMED, ENJOY = 40515, 40516, 40512


async def _wired():
    entity = XBloomBrewPausedSensor(MagicMock(entry_id="test_entry"))
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    handlers: list = []

    def _connect(_hass, _signal, handler):
        handlers.append(handler)
        return lambda: None

    with patch.object(bs, "async_dispatcher_connect", _connect):
        await entity.async_added_to_hass()
    on_frame, on_lifecycle = handlers
    return entity, on_frame, on_lifecycle


@pytest.mark.asyncio
async def test_paused_and_resumed_by_the_machines_frames():
    entity, on_frame, _ = await _wired()
    assert entity._attr_is_on is False
    on_frame({"cmd": PAUSED})
    assert entity._attr_is_on is True
    on_frame({"cmd": RESUMED})
    assert entity._attr_is_on is False


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["enjoy", "ended", "started"])
async def test_a_pause_does_not_outlive_its_brew(end):
    entity, on_frame, on_lifecycle = await _wired()
    on_frame({"cmd": PAUSED})
    if end == "enjoy":
        on_frame({"cmd": ENJOY})
    else:
        on_lifecycle(end)
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_other_frames_leave_it_alone():
    entity, on_frame, _ = await _wired()
    on_frame({"cmd": PAUSED})
    writes = entity.async_write_ha_state.call_count
    on_frame({"cmd": 8023, "activity": 31})
    on_frame({"cmd": PAUSED})
    assert entity._attr_is_on is True
    assert entity.async_write_ha_state.call_count == writes


GRINDER_PAUSED, BREWER_PAUSED, MACHINE_RESUMED, ABANDONED = 9009, 9010, 9011, 40513


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [GRINDER_PAUSED, BREWER_PAUSED])
async def test_a_pause_made_at_the_machine_is_followed_too(pause):
    # The machine's own knob sends its own frames, not 40515 and 40516.
    entity, on_frame, _ = await _wired()
    on_frame({"cmd": pause})
    assert entity._attr_is_on is True
    on_frame({"cmd": MACHINE_RESUMED})
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_a_paused_brew_left_for_the_home_screen_is_not_paused():
    entity, on_frame, _ = await _wired()
    on_frame({"cmd": BREWER_PAUSED})
    on_frame({"cmd": ABANDONED})
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_the_standalone_grinder_stopping_is_not_a_brew_paused():
    entity, on_frame, _ = await _wired()
    on_frame({"cmd": 8023, "activity": 2})    # grinder screen
    on_frame({"cmd": GRINDER_PAUSED})
    assert entity._attr_is_on is False


# Seen live 2026-10-01: a pause from Home Assistant during grinding brought only
# the command's echo (40518) and the pause screen, and the resume after a pause
# during pouring brought the echo (40524) and the pouring screen, but no 40516.
PAUSE_ECHO, RESUME_ECHO = 40518, 40524


def _screen(code):
    return {"cmd": 8023, "activity": code}


@pytest.mark.asyncio
async def test_the_pause_screen_during_a_brew_is_a_pause_whoever_paused_it():
    entity, on_frame, _ = await _wired()
    for frame in ({"cmd": 40502}, _screen(30), _screen(34), {"cmd": PAUSE_ECHO}, {"cmd": 40507}):
        on_frame(frame)
    assert entity._attr_is_on is False
    on_frame(_screen(31))
    assert entity._attr_is_on is True
    on_frame(_screen(34))           # resumed, grinding again
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_a_resume_without_40516_still_ends_the_pause():
    entity, on_frame, _ = await _wired()
    for frame in ({"cmd": 40502}, _screen(35), {"cmd": PAUSE_ECHO}, {"cmd": PAUSED}, _screen(31)):
        on_frame(frame)
    assert entity._attr_is_on is True
    on_frame({"cmd": RESUME_ECHO})
    on_frame(_screen(35))
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_a_recipe_waiting_for_its_start_is_not_paused():
    # The same recipe screen shows a prepared recipe before any brew.
    entity, on_frame, _ = await _wired()
    on_frame(_screen(31))
    assert entity._attr_is_on is False
