"""The low-water report carries the switch, and "water" is not a fault.

The machine sends RD_ErrorLackOfWater (40522) on every change of its
low-water switch, in both directions, and once on connect; the library
decodes the switch as `water_enough` (1 water, 0 low). A report of water
must neither announce an empty tank nor set the status to `no_water`.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    WATER_STATUS,
    XBloomBrewEventBleEntity,
    XBloomLastUpdatedSensor,
    XBloomMachineStatusBleSensor,
    signal_event,
)
from xbloom import spec

CMD_LACK_OF_WATER = 40522
EVENT_NO_WATER = spec.FAULTS[CMD_LACK_OF_WATER][1]


async def _wired(entity):
    entity.hass = MagicMock()
    entity.hass.bus.async_listen = lambda *_a: (lambda: None)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    sig: dict[str, callable] = {}

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await entity.async_added_to_hass()
    return sig[signal_event("test_entry")]


def _entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    return entry


async def _event_entity():
    ent = XBloomBrewEventBleEntity(_entry())
    ent._trigger_event = MagicMock()
    return ent, await _wired(ent)


async def _status_sensor():
    sensor = XBloomMachineStatusBleSensor(_entry())
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    return sensor, await _wired(sensor)


def _fired(ent):
    return [c.args[0] for c in ent._trigger_event.call_args_list]


@pytest.mark.asyncio
async def test_a_report_of_water_announces_nothing():
    ent, on_event = await _event_entity()
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 1})
    assert _fired(ent) == []


@pytest.mark.asyncio
async def test_a_report_of_low_water_is_announced():
    ent, on_event = await _event_entity()
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 0})
    assert _fired(ent) == [EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_low_after_a_refill_is_announced_again():
    ent, on_event = await _event_entity()
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 0})
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 1})
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 0})
    assert _fired(ent) == [EVENT_NO_WATER, EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_a_report_of_water_leaves_the_status_ok():
    sensor, on_event = await _status_sensor()
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 1})
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_the_status_follows_the_switch():
    later: list = []
    with patch("custom_components.xbloom.ble_entities.async_call_later",
               lambda _h, _d, action: (later.append(action), lambda: None)[1]):
        sensor, on_event = await _status_sensor()
        on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 0})
        assert sensor._attr_native_value == WATER_STATUS
        on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 1})
        later[0](None)          # the water reading held
        assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_a_water_report_is_not_a_status_sync():
    """Last Updated marks the heartbeat, which carries the whole status."""
    sensor = XBloomLastUpdatedSensor(_entry())
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    on_event = await _wired(sensor)
    on_event({"cmd": CMD_LACK_OF_WATER, "water_enough": 1})
    sensor.async_write_ha_state.assert_not_called()
