"""Water during brews Home Assistant did not start, and the status beside it.

A brew started from one of the machine's own recipe slots runs no water
tracker, but it still pauses on the water-shortage screen when the tank
runs dry; that pause is announced too, without amounts. Machine Status
follows the low-water switch, which flicks back to "water" for a moment as
the water sloshes; it treats water as back only once that has held, as the
firmware and the tracker do.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    WATER_STATUS,
    XBloomBrewEventBleEntity,
    XBloomMachineStatusBleSensor,
    signal_brew_lifecycle,
    signal_event,
)
from custom_components.xbloom.water import WATER_REFILL_HOLD_S

PAUSE, WATER_SCREEN, KNOB = {"cmd": 40515}, {"cmd": 8023, "activity": 12}, {"cmd": 9011}


async def _wired(entity):
    entity.hass = MagicMock()
    entity.hass.bus.async_listen = lambda *_a: (lambda: None)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    sig: dict = {}

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await entity.async_added_to_hass()
    return sig


async def _event_entity():
    ent = XBloomBrewEventBleEntity(MagicMock(entry_id="test_entry"))
    ent._trigger_event = MagicMock()
    return ent, await _wired(ent)


def _paused(ent):
    return [c.args for c in ent._trigger_event.call_args_list if c.args[0] == "water_paused"]


@pytest.mark.asyncio
async def test_a_brew_started_at_the_machine_announces_its_water_pause():
    ent, sig = await _event_entity()
    on_event = sig[signal_event("test_entry")]
    for frame in ({"cmd": 40502}, {"cmd": 40510, "pour_index": 0}, PAUSE, WATER_SCREEN):
        on_event(frame)
    assert _paused(ent) == [("water_paused", {})]
    on_event(WATER_SCREEN)                      # still the same pause
    assert len(_paused(ent)) == 1
    on_event(KNOB)
    on_event(WATER_SCREEN)                      # dry again later
    assert len(_paused(ent)) == 2


@pytest.mark.asyncio
async def test_a_brew_home_assistant_started_leaves_its_pause_to_the_tracker():
    ent, sig = await _event_entity()
    sig[signal_brew_lifecycle("test_entry")]("started")
    for frame in ({"cmd": 40502}, {"cmd": 40510, "pour_index": 0}, PAUSE, WATER_SCREEN):
        sig[signal_event("test_entry")](frame)
    assert _paused(ent) == []


@pytest.mark.asyncio
async def test_machine_status_holds_low_through_a_moment_of_water():
    sensor = XBloomMachineStatusBleSensor(MagicMock(entry_id="test_entry"))
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    later: list = []

    def _call_later(_hass, delay, action):
        later.append((delay, action))
        return lambda: later.remove((delay, action)) if (delay, action) in later else None

    with patch("custom_components.xbloom.ble_entities.async_call_later", _call_later):
        on_event = (await _wired(sensor))[signal_event("test_entry")]
        on_event({"cmd": 40522, "water_enough": 0})
        assert sensor._attr_native_value == WATER_STATUS
        on_event({"cmd": 40522, "water_enough": 1})      # slosh
        assert sensor._attr_native_value == WATER_STATUS
        on_event({"cmd": 40522, "water_enough": 0})      # low again: the slosh is over
        assert later == []
        on_event({"cmd": 40522, "water_enough": 1})      # refilled
        assert [delay for delay, _ in later] == [WATER_REFILL_HOLD_S]
        later[0][1](None)
        assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_a_start_refused_at_the_knob_is_not_a_pause_or_a_bare_fault():
    # A prepared recipe on the recipe screen, the knob pressed with the tank
    # low: the machine reports the switch and shows its water screen, with
    # nothing poured. The refusal is announced as a failed start instead.
    ent, sig = await _event_entity()
    on_event = sig[signal_event("test_entry")]
    for frame in ({"cmd": 8023, "activity": 31}, {"cmd": 40522, "water_enough": 0}, WATER_SCREEN):
        on_event(frame)
    assert [c.args[0] for c in ent._trigger_event.call_args_list] == []
