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
