"""A fault that stops the machine must stop the brew in Home Assistant too.

Observed on a brew started with no beans in the grinder:

    +0.0 s   grinder_started
    +3.1 s   brewer_started
    +7.3 s   error_no_beans     the machine gives up
    +7.4 s   grinder_stopped    0.1 s later

Nothing followed. `grinder_stopped` was read as "the grind finished, pours
next", so `brew_status` moved to `brewing` and the announcement said the brew
was starting — of a brew that had already failed. The brew task then sat
waiting for an RD_ENJOY that was never coming, and the dashboard showed a brew
in progress until it was stopped by hand.

Not every fault ends a brew, and guessing would be worse than the bug. Water
does not: brews have reported `error_no_water` mid-pour and gone on to finish
normally.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    BREW_STOPPING_FAULTS,
    CMD_GRINDER_START,
    CMD_GRINDER_STOP,
    XBloomBrewStatusBleSensor,
    signal_event,
)
from xbloom import spec

_CMD_BY_STATUS = {status: cmd for cmd, (status, _event) in spec.FAULTS.items()}
CMD_NO_BEANS = _CMD_BY_STATUS["no_beans"]
CMD_NO_WATER = _CMD_BY_STATUS["no_water"]


def _make_sensor():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomBrewStatusBleSensor(entry)
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

    sig: dict[str, callable] = {}
    hass = MagicMock()
    hass.bus.async_listen = lambda event_type, handler: (lambda: None)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    return sensor, sig, _connect


async def _sensor_with_frames(*frames):
    sensor, sig, connect = _make_sensor()
    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", connect):
        await sensor.async_added_to_hass()
    on_event = sig[signal_event("test_entry")]
    for frame in frames:
        on_event(frame)
    return sensor


# --- which faults stop a brew ----------------------------------------------


def test_no_beans_stops_a_brew_and_no_water_does_not():
    """Both observed on real brews; neither is a guess."""
    assert "no_beans" in BREW_STOPPING_FAULTS
    assert "no_water" not in BREW_STOPPING_FAULTS


# --- the sensor -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_no_beans_fault_takes_the_brew_out_of_grinding():
    sensor = await _sensor_with_frames(
        {"cmd": CMD_GRINDER_START}, {"cmd": CMD_NO_BEANS}
    )
    assert sensor._attr_native_value == "idle"


@pytest.mark.asyncio
async def test_the_grinder_stopping_after_no_beans_is_not_the_grind_finishing():
    """The 09-07 sequence exactly — this is what announced a brew that failed."""
    sensor = await _sensor_with_frames(
        {"cmd": CMD_GRINDER_START},
        {"cmd": CMD_NO_BEANS},
        {"cmd": CMD_GRINDER_STOP},
    )
    assert sensor._attr_native_value != "brewing"


@pytest.mark.asyncio
async def test_a_water_fault_leaves_the_brew_running():
    """The 09-13 brew reported no water mid-pour and finished anyway."""
    sensor = await _sensor_with_frames(
        {"cmd": CMD_GRINDER_START},
        {"cmd": CMD_GRINDER_STOP},
        {"cmd": CMD_NO_WATER},
    )
    assert sensor._attr_native_value == "brewing"


@pytest.mark.asyncio
async def test_the_grind_still_finishes_normally_into_brewing():
    sensor = await _sensor_with_frames(
        {"cmd": CMD_GRINDER_START}, {"cmd": CMD_GRINDER_STOP}
    )
    assert sensor._attr_native_value == "brewing"
