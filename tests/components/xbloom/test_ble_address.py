"""The machine is found by its Bluetooth address once that is known.

It used to be found by name only, and the name arrives in the scan response,
not in the advertisement itself. For minutes after Home Assistant restarts its
Bluetooth may have seen the machine without its name, and every action failed
as "machine not found" meanwhile. The address is in every advertisement, and
this machine's is public, so it does not change: learn it once, keep it on the
entry, and look the machine up by it from then on.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom import _resolve_ble_device
from custom_components.xbloom.const import CONF_BLE_ADDRESS, CONF_BLE_NAME

BLE_NAME = "XBLOOM ABC123"
ADDRESS = "AA:BB:CC:00:00:01"


def _entry(**data):
    entry = MagicMock()
    entry.data = {CONF_BLE_NAME: BLE_NAME, **data}
    return entry


def _info(name, address):
    info = MagicMock()
    info.name = name
    info.address = address
    info.device = MagicMock(name=f"device {address}")
    return info


def _bluetooth(*, seen=(), by_address=None):
    """Patch Home Assistant's bluetooth lookups for one call."""
    from homeassistant.components import bluetooth
    return (
        patch.object(bluetooth, "async_discovered_service_info",
                     MagicMock(return_value=list(seen))),
        patch.object(bluetooth, "async_ble_device_from_address",
                     MagicMock(return_value=by_address)),
    )


@pytest.mark.asyncio
async def test_a_known_address_finds_the_machine_without_its_name():
    hass = MagicMock()
    device = MagicMock()
    scan, lookup = _bluetooth(seen=[], by_address=device)
    with scan, lookup as by_address:
        found = await _resolve_ble_device(hass, _entry(**{CONF_BLE_ADDRESS: ADDRESS}), BLE_NAME)
    assert found is device
    by_address.assert_called_once_with(hass, ADDRESS, connectable=True)


@pytest.mark.asyncio
async def test_a_known_address_that_is_not_in_range_is_not_found():
    # No name scan behind it: the entry is one machine, and its address is fixed.
    hass = MagicMock()
    scan, lookup = _bluetooth(seen=[_info(BLE_NAME, "AA:BB:CC:DD:EE:FF")], by_address=None)
    with scan as by_name, lookup:
        found = await _resolve_ble_device(hass, _entry(**{CONF_BLE_ADDRESS: ADDRESS}), BLE_NAME)
    assert found is None
    by_name.assert_not_called()


@pytest.mark.asyncio
async def test_the_address_is_saved_the_first_time_the_name_finds_the_machine():
    hass = MagicMock()
    entry = _entry()
    info = _info(BLE_NAME, ADDRESS)
    scan, lookup = _bluetooth(seen=[_info("XBLOOM OTHER1", "11:22:33:44:55:66"), info])
    with scan, lookup:
        found = await _resolve_ble_device(hass, entry, BLE_NAME)
    assert found is info.device
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={CONF_BLE_NAME: BLE_NAME, CONF_BLE_ADDRESS: ADDRESS},
    )


@pytest.mark.asyncio
async def test_nothing_is_saved_when_the_name_is_not_seen():
    hass = MagicMock()
    scan, lookup = _bluetooth(seen=[_info("XBLOOM OTHER1", "11:22:33:44:55:66")])
    with scan, lookup:
        found = await _resolve_ble_device(hass, _entry(), BLE_NAME)
    assert found is None
    hass.config_entries.async_update_entry.assert_not_called()
