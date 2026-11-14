"""The entities carry the water tracker's decisions.

The brew task publishes `(event_type, attributes, state)` on `signal_water`.
The brew event entity fires the water events; Machine Status carries the
amounts while the switch has tripped; Brew Paused says when a pause is a
wait for water.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.xbloom.binary_sensor as bs
from custom_components.xbloom.binary_sensor import XBloomBrewPausedSensor
from custom_components.xbloom.ble_entities import (
    XBloomBrewEventBleEntity,
    XBloomMachineStatusBleSensor,
    signal_brew_lifecycle,
    signal_event,
    signal_water,
)

STATE = {"water_left_ml": 270, "water_needed_ml": 388,
         "water_short_ml": 118, "enough_to_finish": False}
LOW = {"cmd": 40522, "water_enough": 0}


async def _wired(entity, module="custom_components.xbloom.ble_entities"):
    entity.hass = MagicMock()
    entity.hass.bus.async_listen = lambda *_a: (lambda: None)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    sig: dict[str, callable] = {}

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch(f"{module}.async_dispatcher_connect", _connect):
        await entity.async_added_to_hass()
    return sig


async def _event_entity():
    ent = XBloomBrewEventBleEntity(MagicMock(entry_id="test_entry"))
    ent._trigger_event = MagicMock()
    return ent, await _wired(ent)


def _fired(ent):
    return [(c.args[0], c.args[1] if len(c.args) > 1 else {})
            for c in ent._trigger_event.call_args_list]


@pytest.mark.asyncio
async def test_water_events_are_fired_with_their_amounts():
    ent, sig = await _event_entity()
    for event_type in ("water_low", "water_paused", "water_refilled"):
        assert event_type in ent._attr_event_types
    sig[signal_water("test_entry")](("water_low", STATE, STATE))
    sig[signal_water("test_entry")]((None, {}, STATE))
    assert _fired(ent) == [("water_low", STATE)]


@pytest.mark.asyncio
async def test_error_no_water_is_quiet_during_a_followed_brew_and_heard_outside_it():
    ent, sig = await _event_entity()
    sig[signal_brew_lifecycle("test_entry")]("started")
    sig[signal_event("test_entry")](LOW)
    assert _fired(ent) == []
    sig[signal_brew_lifecycle("test_entry")]("ended")
    sig[signal_event("test_entry")](LOW)
    assert [name for name, _ in _fired(ent)] == ["error_no_water"]


@pytest.mark.asyncio
async def test_machine_status_carries_the_amounts_and_drops_them_when_the_brew_ends():
    sensor = XBloomMachineStatusBleSensor(MagicMock(entry_id="test_entry"))
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    sig = await _wired(sensor)
    sig[signal_water("test_entry")](("water_low", STATE, STATE))
    attrs = sensor._attr_extra_state_attributes
    assert attrs["water_left_ml"] == 270
    assert attrs["water_needed_ml"] == 388
    assert attrs["water_enough_to_finish"] is False
    sig[signal_water("test_entry")]((None, {}, None))
    attrs = sensor._attr_extra_state_attributes or {}
    assert not {"water_left_ml", "water_needed_ml", "water_enough_to_finish"} & set(attrs)


@pytest.mark.asyncio
async def test_brew_paused_says_it_is_waiting_for_water():
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
    on_frame = handlers[0]

    for frame in ({"cmd": 40502}, {"cmd": 8023, "activity": 35}, {"cmd": 40515},
                  {"cmd": 8023, "activity": 12}):
        on_frame(frame)
    assert entity._attr_is_on is True
    assert entity.extra_state_attributes == {"reason": "water"}
    on_frame({"cmd": 8023, "activity": 31})      # refilled, still waiting
    assert entity.extra_state_attributes == {"reason": "water"}
    on_frame({"cmd": 9011})
    assert entity._attr_is_on is False
    assert entity.extra_state_attributes == {"reason": None}


@pytest.mark.asyncio
async def test_a_followed_brew_finishes_once_with_its_tank():
    """The finish waits for the completion, which knows the tank.

    Fired on the machine's ENJOY, it went out a moment before the completion
    and the tank had to follow as a second announcement, which could be
    heard first.
    """
    ent = XBloomBrewEventBleEntity(MagicMock(entry_id="test_entry"))
    ent._trigger_event = MagicMock()
    ent.hass = MagicMock()
    bus: dict = {}
    ent.hass.bus.async_listen = lambda name, handler: (bus.__setitem__(name, handler), lambda: None)[1]
    ent.async_write_ha_state = MagicMock()
    ent.async_on_remove = MagicMock()
    sig: dict = {}

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await ent.async_added_to_hass()

    sig[signal_brew_lifecycle("test_entry")]("started")
    for frame in ({"cmd": 40502}, {"cmd": 40510, "pour_index": 0}, {"cmd": 40512}):
        sig[signal_event("test_entry")](frame)
    assert "brew_done" not in [name for name, _ in _fired(ent)]

    bus["xbloom_brew_completed"](MagicMock(data={
        "outcome": "confirmed", "recipe_name": "K", "duration_s": 181.0,
        "tank_low": True, "water_left_ml": 196}))
    done = [attrs for name, attrs in _fired(ent) if name == "brew_done"]
    assert done == [{"recipe_name": "K", "duration_s": 181.0,
                     "tank_low": True, "water_left_ml": 196}]
