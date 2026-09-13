"""Low water is a live reading, and must not outlive the link that took it.

`sensor.xbloom_studio_machine_status` sat on `no_water` for nine hours after the
2026-09-13 brew — a brew that finished normally. The machine reports the water
level continuously in its MachineInfo heartbeat, but heartbeats only arrive
while Home Assistant is holding the Bluetooth link, which it releases when the
brew ends. So the last reading froze, and the dashboard went on asserting a
condition nobody could still see. The machine is also known to report it
spuriously, which the freeze then preserves.

So a water fault ends with the observation: when the brew ends, or when the
Connect switch releases the link. If the tank really is empty the very next
heartbeat says so again, and the next brew raises it immediately — nothing is
lost by not guessing in between.

The other faults are not continuous readings. `no_beans` is raised once, and
staying visible until the next brew starts is the point of it.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    WATER_STATUS,
    XBloomMachineStatusBleSensor,
    signal_brew_lifecycle,
    signal_event,
)
from xbloom import spec

_CMD_BY_STATUS = {status: cmd for cmd, (status, _event) in spec.FAULTS.items()}
CMD_NO_WATER = _CMD_BY_STATUS["no_water"]
CMD_NO_BEANS = _CMD_BY_STATUS["no_beans"]


async def _sensor():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomMachineStatusBleSensor(entry)
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

    bus: dict[str, callable] = {}
    sig: dict[str, callable] = {}

    hass = MagicMock()
    hass.bus.async_listen = lambda event_type, handler: (
        bus.__setitem__(event_type, handler), lambda: None
    )[1]
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await sensor.async_added_to_hass()

    return (
        sensor,
        sig[signal_event("test_entry")],
        sig[signal_brew_lifecycle("test_entry")],
        bus,
    )


@pytest.mark.asyncio
async def test_a_water_fault_does_not_outlive_the_brew_that_reported_it():
    sensor, on_event, on_lifecycle, _bus = await _sensor()
    on_event({"cmd": CMD_NO_WATER})
    assert sensor._attr_native_value == WATER_STATUS

    on_lifecycle("ended")
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_a_water_fault_clears_when_the_link_is_released_by_hand():
    """Turning Connect off stops the readings just as surely as a brew ending."""
    sensor, on_event, _lifecycle, bus = await _sensor()
    on_event({"cmd": CMD_NO_WATER})
    bus["xbloom_connect_stopped"](MagicMock(data={"reason": "user"}))
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_an_empty_tank_says_so_again_on_the_next_reading():
    """Clearing is not a claim there is water — only that we stopped looking."""
    sensor, on_event, on_lifecycle, _bus = await _sensor()
    on_event({"cmd": CMD_NO_WATER})
    on_lifecycle("ended")
    on_event({"water_enough": 0})
    assert sensor._attr_native_value == WATER_STATUS


@pytest.mark.asyncio
async def test_a_bean_fault_survives_the_brew_so_it_can_still_be_read():
    """Nothing re-reports it, and it is what tells you to fill the hopper."""
    sensor, on_event, on_lifecycle, _bus = await _sensor()
    on_event({"cmd": CMD_NO_BEANS})
    on_lifecycle("ended")
    assert sensor._attr_native_value == "no_beans"


@pytest.mark.asyncio
async def test_a_new_brew_still_clears_everything():
    sensor, on_event, on_lifecycle, _bus = await _sensor()
    on_event({"cmd": CMD_NO_BEANS})
    on_lifecycle("started")
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_a_brew_ending_with_nothing_wrong_changes_nothing():
    sensor, _on_event, on_lifecycle, _bus = await _sensor()
    on_lifecycle("ended")
    assert sensor._attr_native_value == "ok"


# --- and it does not survive a restart either --------------------------------


async def _restored_as(value):
    """A sensor coming back from the recorder holding `value`."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomMachineStatusBleSensor(entry)
    sensor.async_get_last_sensor_data = AsyncMock(
        return_value=MagicMock(native_value=value)
    )
    hass = MagicMock()
    hass.bus.async_listen = lambda event_type, handler: (lambda: None)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()
    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect",
               lambda *_a: (lambda: None)):
        await sensor.async_added_to_hass()
    return sensor


@pytest.mark.asyncio
async def test_a_restart_does_not_bring_a_water_fault_back():
    """Nothing is connected at boot, so nobody is reading the level.

    Home Assistant restored `no_water` at 2026-09-13 23:51 from a brew that had
    finished eleven hours earlier — the same stale assertion the live path had
    just been taught not to make.
    """
    sensor = await _restored_as(WATER_STATUS)
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_a_restart_keeps_a_fault_nothing_re_reports():
    """No beans is still true after a restart, and still worth saying."""
    sensor = await _restored_as("no_beans")
    assert sensor._attr_native_value == "no_beans"


@pytest.mark.asyncio
async def test_a_restored_value_outside_the_options_is_still_ignored():
    sensor = await _restored_as("something else")
    assert sensor._attr_native_value == "ok"
