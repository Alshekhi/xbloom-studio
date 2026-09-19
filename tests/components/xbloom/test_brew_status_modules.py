"""`brew_status` follows recipe brews, not the grinder, brewer or scale screens.

A standalone grind sends a frame the sensor read as a recipe's pours starting
(40506) and one it read as the grind ending (40507), so it went to `brewing`,
announced "pouring started", showed "Brew in progress" with a stale recipe
name, and stayed there. A standalone pour ended on `done` the same way.

The machine says which screen it is on (8023 activity: 2 grinder, 3 brewer,
4/5 scale, 1/65 home). While it is on a module screen those frames describe
the module, not a brew. Only the home screen ends that — a pour shows the same
"pouring" activity (35) as a recipe brew, so it cannot.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    CMD_BLOOM,
    CMD_BREWER_START,
    CMD_ENJOY,
    CMD_GRINDER_START,
    CMD_GRINDER_STOP,
    CMD_MACHINE_ACTIVITY,
    XBloomBrewStatusBleSensor,
)


def _activity(code: int) -> dict:
    return {"cmd": CMD_MACHINE_ACTIVITY, "activity": code}


async def _sensor():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomBrewStatusBleSensor(entry)
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    sensor.hass = MagicMock()
    sensor.hass.bus.async_listen = MagicMock(return_value=lambda: None)
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()

    handlers: list = []

    def _connect(_hass, _signal, handler):
        handlers.append(handler)
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await sensor.async_added_to_hass()
    on_event, on_lifecycle = handlers[0], handlers[1]
    return sensor, on_event, on_lifecycle


def _feed(on_event, *frames):
    for frame in frames:
        on_event(frame)


@pytest.mark.asyncio
async def test_a_standalone_grind_is_not_a_brew():
    sensor, on_event, _ = await _sensor()
    _feed(on_event,
          _activity(2),                     # grinder screen
          {"cmd": CMD_BREWER_START},        # sent as the grind starts
          {"cmd": CMD_GRINDER_STOP})
    assert sensor._attr_native_value == "idle"


@pytest.mark.asyncio
async def test_a_standalone_pour_is_not_a_brew():
    sensor, on_event, _ = await _sensor()
    _feed(on_event,
          _activity(3),                     # brewer screen
          _activity(35),                    # pouring — same code a recipe shows
          {"cmd": CMD_BLOOM, "pour_index": 0},
          {"cmd": CMD_ENJOY},
          _activity(36))
    assert sensor._attr_native_value == "idle"


@pytest.mark.asyncio
async def test_a_recipe_started_at_the_machine_is_followed_once_home():
    sensor, on_event, _ = await _sensor()
    _feed(on_event, _activity(2), _activity(1), {"cmd": CMD_GRINDER_START})
    assert sensor._attr_native_value == "grinding"


@pytest.mark.asyncio
async def test_a_brew_started_by_home_assistant_is_followed_from_any_screen():
    # A recipe brew closes the Connect session first, which may have left the
    # machine last seen on a module screen.
    sensor, on_event, on_lifecycle = await _sensor()
    _feed(on_event, _activity(2))
    on_lifecycle("started")
    _feed(on_event, {"cmd": CMD_GRINDER_START})
    assert sensor._attr_native_value == "grinding"


@pytest.mark.asyncio
async def test_entering_a_module_screen_clears_a_stale_brew():
    sensor, on_event, _ = await _sensor()
    sensor._attr_native_value = "brewing"
    _feed(on_event, _activity(3))
    assert sensor._attr_native_value == "idle"


@pytest.mark.asyncio
async def test_a_recipe_brew_is_unchanged():
    sensor, on_event, _ = await _sensor()
    _feed(on_event, _activity(1), {"cmd": CMD_GRINDER_START})
    assert sensor._attr_native_value == "grinding"
    _feed(on_event, {"cmd": CMD_BREWER_START}, {"cmd": CMD_GRINDER_STOP})
    assert sensor._attr_native_value == "brewing"
    _feed(on_event, {"cmd": CMD_ENJOY})
    assert sensor._attr_native_value == "done"


# --------------------------------------------------------------------------- #
# The brew-level events and the pour counter follow the same rule             #
# --------------------------------------------------------------------------- #
# The announcement speaks `brew_done` with the last recipe's name. A grind's
# "brewer started" frame re-armed it and a standalone pour's ENJOY fired it, so
# plain water could be announced as a finished recipe.
from custom_components.xbloom.reading_sensors import XBloomCurrentPourSensor  # noqa: E402

from .test_fault_events_are_edges import _entity, fired  # noqa: E402


@pytest.mark.asyncio
async def test_a_grind_then_a_pour_announce_no_brew():
    async with _entity() as (ent, on_event, _lifecycle):
        _feed(on_event,
              _activity(2), {"cmd": CMD_BREWER_START}, {"cmd": CMD_GRINDER_STOP},
              _activity(3), {"cmd": CMD_BLOOM, "pour_index": 0}, {"cmd": CMD_ENJOY})
        assert fired(ent, "brew_started") == []
        assert fired(ent, "brew_done") == []


@pytest.mark.asyncio
async def test_a_recipe_brew_still_announces():
    async with _entity() as (ent, on_event, _lifecycle):
        _feed(on_event,
              _activity(2), _activity(1), {"cmd": CMD_GRINDER_START},
              {"cmd": CMD_BLOOM, "pour_index": 0}, {"cmd": CMD_ENJOY})
        assert fired(ent, "brew_started") == ["brew_started"]
        assert fired(ent, "brew_done") == ["brew_done"]


@pytest.mark.asyncio
async def test_a_brew_home_assistant_starts_announces_from_any_screen():
    async with _entity() as (ent, on_event, lifecycle):
        _feed(on_event, _activity(3))
        lifecycle("started")
        _feed(on_event, {"cmd": CMD_GRINDER_START}, {"cmd": CMD_BLOOM, "pour_index": 0},
              {"cmd": CMD_ENJOY})
        assert fired(ent, "brew_done") == ["brew_done"]


@pytest.mark.asyncio
async def test_a_standalone_pour_does_not_move_the_pour_counter():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomCurrentPourSensor(entry)
    sensor.hass = MagicMock()
    sensor.hass.bus.async_listen = MagicMock(return_value=lambda: None)
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()
    handlers: list = []

    def _connect(_hass, _signal, handler):
        handlers.append(handler)
        return lambda: None

    with patch("custom_components.xbloom.reading_sensors.async_dispatcher_connect", _connect):
        await sensor.async_added_to_hass()
    on_signal = handlers[0]
    before = sensor._attr_native_value
    _feed(on_signal, _activity(3), {"cmd": CMD_BLOOM, "pour_index": 0})
    assert sensor._attr_native_value == before
    _feed(on_signal, _activity(1), {"cmd": CMD_BLOOM, "pour_index": 0})
    assert sensor._attr_native_value == 1
