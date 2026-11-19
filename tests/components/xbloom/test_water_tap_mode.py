"""With the water source on the tap, the tank's low-water switch means nothing.

The switch sits in the tank and keeps reporting it — empty or removed — while
the machine draws from the tap and brews normally. Machine Status and the brew
event entity read the source from the Water Source select, which follows both
what Home Assistant sets and what the machine reports. On the machine, setting
the tap sent no status report at all, so the select is what knows it.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    WATER_STATUS,
    XBloomMachineStatusBleSensor,
    signal_event,
)

from .test_water_unfollowed import _event_entity, _wired

SOURCE = "select.xbloom_studio_water_source"
LOW = {"cmd": 40522, "water_enough": 0}


class _Source:
    """The Water Source select's state, as the entities read it."""

    def __init__(self, hass, value="tank"):
        self.value = value
        hass.states.get = lambda eid: SimpleNamespace(state=self.value) if eid == SOURCE else None


def _registry():
    registry = MagicMock()
    registry.async_get_entity_id = lambda platform, domain, uid: (
        SOURCE if uid == "xbloom_water_source_select" else None)
    return patch("custom_components.xbloom.ble_entities.er.async_get", return_value=registry)


async def _status():
    sensor = XBloomMachineStatusBleSensor(MagicMock(entry_id="test_entry"))
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    tracked: list = []
    with patch("custom_components.xbloom.ble_entities.async_track_state_change_event",
               lambda _h, ids, action: tracked.append((ids, action)) or (lambda: None)):
        on_event = (await _wired(sensor))[signal_event("test_entry")]
    source = _Source(sensor.hass)
    return sensor, on_event, source, tracked


@pytest.mark.asyncio
async def test_on_the_tap_an_empty_tank_is_not_low_water():
    with _registry():
        sensor, on_event, source, _ = await _status()
        source.value = "tap"
        on_event(LOW)
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_choosing_the_tap_clears_low_water_with_no_report_from_the_machine():
    with _registry():
        sensor, on_event, source, tracked = await _status()
        on_event(LOW)
        assert sensor._attr_native_value == WATER_STATUS
        [(ids, action)] = tracked
        assert ids == [SOURCE]
        source.value = "tap"
        action(None)
    assert sensor._attr_native_value == "ok"


@pytest.mark.asyncio
async def test_back_on_the_tank_low_water_is_reported_again():
    with _registry():
        sensor, on_event, source, _ = await _status()
        source.value = "tap"
        on_event(LOW)
        source.value = "tank"
        on_event(LOW)
    assert sensor._attr_native_value == WATER_STATUS


@pytest.mark.asyncio
async def test_on_the_tap_the_heartbeat_still_updates_its_readings():
    with _registry():
        sensor, on_event, source, _ = await _status()
        source.value = "tap"
        on_event({"cmd": 40521, "water_enough": 0, "voltage": 220, "system_status": 0})
    assert sensor._attr_native_value == "ok"
    assert sensor._attr_extra_state_attributes == {"voltage": 220, "system_status": 0}


@pytest.mark.asyncio
async def test_on_the_tap_the_low_water_fault_is_not_fired():
    with _registry():
        ent, sig = await _event_entity()
        source = _Source(ent.hass, "tap")
        on_event = sig[signal_event("test_entry")]
        on_event(LOW)
        assert [c.args[0] for c in ent._trigger_event.call_args_list] == []
        source.value = "tank"
        on_event(LOW)
    assert [c.args[0] for c in ent._trigger_event.call_args_list] == ["error_no_water"]
