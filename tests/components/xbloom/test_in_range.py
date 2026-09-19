"""`binary_sensor.xbloom_studio_in_range` follows Home Assistant's Bluetooth.

Nothing else could tell whether the machine was there. The status sensors keep
the last thing it reported, so a machine switched off still read "ok", and an
agent asking after it was told it was fine.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom.binary_sensor import XBloomInRangeSensor
from custom_components.xbloom.const import CONF_BLE_ADDRESS, CONF_BLE_NAME

BLE_NAME = "XBLOOM ABC123"
ADDRESS = "68:79:C4:00:00:01"


class _Bluetooth:
    """Home Assistant's bluetooth API, recording who listens to what."""

    def __init__(self, present: bool):
        self.present = present
        self.seen: dict = {}      # matcher key -> advertisement callback
        self.gone: dict = {}      # address -> unavailable callback
        self.stopped: list = []

    def register(self, _hass, cb, matcher, _mode):
        key = matcher.get("address") or matcher.get("local_name")
        self.seen[key] = cb
        return lambda: self.stopped.append(key)

    def track_unavailable(self, _hass, cb, address, connectable):
        assert connectable is True
        self.gone[address] = cb
        return lambda: None

    def patches(self):
        from homeassistant.components import bluetooth
        return (
            patch.object(bluetooth, "async_address_present",
                         MagicMock(side_effect=lambda *_a, **_k: self.present)),
            patch.object(bluetooth, "async_register_callback", self.register),
            patch.object(bluetooth, "async_track_unavailable", self.track_unavailable),
        )


async def _added(bt: _Bluetooth, **data):
    entry = MagicMock()
    entry.data = {CONF_BLE_NAME: BLE_NAME, **data}
    sensor = XBloomInRangeSensor(entry)
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()
    a, b, c = bt.patches()
    with a, b, c:
        await sensor.async_added_to_hass()
    return sensor, entry


def _advert(address=ADDRESS):
    info = MagicMock()
    info.address = address
    return info


@pytest.mark.asyncio
async def test_a_machine_home_assistant_can_see_is_in_range():
    sensor, _ = await _added(_Bluetooth(present=True), **{CONF_BLE_ADDRESS: ADDRESS})
    assert sensor._attr_is_on is True


@pytest.mark.asyncio
async def test_a_machine_home_assistant_cannot_see_is_out_of_range():
    sensor, _ = await _added(_Bluetooth(present=False), **{CONF_BLE_ADDRESS: ADDRESS})
    assert sensor._attr_is_on is False


@pytest.mark.asyncio
async def test_it_goes_out_of_range_when_home_assistant_drops_it_and_back_when_seen():
    bt = _Bluetooth(present=True)
    sensor, _ = await _added(bt, **{CONF_BLE_ADDRESS: ADDRESS})
    bt.gone[ADDRESS](_advert())
    assert sensor._attr_is_on is False
    bt.seen[ADDRESS](_advert(), None)
    assert sensor._attr_is_on is True


@pytest.mark.asyncio
async def test_without_an_address_the_machine_is_recognised_by_name():
    bt = _Bluetooth(present=False)
    sensor, entry = await _added(bt)
    assert sensor._attr_is_on is False
    assert BLE_NAME in bt.seen

    bt.present = True
    a, b, c = bt.patches()
    with a, b, c:
        bt.seen[BLE_NAME](_advert(), None)

    assert sensor._attr_is_on is True
    assert BLE_NAME in bt.stopped, "kept listening by name after the address was known"
    assert ADDRESS in bt.gone, "not following the address it learned"
    sensor.hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={CONF_BLE_NAME: BLE_NAME, CONF_BLE_ADDRESS: ADDRESS},
    )
