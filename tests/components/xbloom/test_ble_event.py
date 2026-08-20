"""Tests for ble_entities.XBloomBrewEventBleEntity — bypass event wiring.

The shared conftest injects the homeassistant stubs into sys.modules at import
time, so ble_entities can be imported and its class contract exercised without a
live hass instance.

Covers the bypass-pour lifecycle event: the machine emits FFE3 notification
cmd 40520 (RD_BYPASS) during the bypass/dilution pour; the brew event entity
must surface it as a `bypass_started` event, alongside the existing granular
pour/grinder events.
"""
from custom_components.xbloom.ble_entities import (  # noqa: E402
    CMD_BYPASS,
    XBloomBrewEventBleEntity,
    XBloomMachineStatusBleSensor,
)
from custom_components.xbloom.vendor.xbloom import spec  # noqa: E402

# The fault table used to live in ble_entities as module-level CMD_ERR_*
# constants plus _FAULTS. PR #2 moved it into the portable spec module so the
# HA layer and the vendor protocol layer share one source of truth.
#
# The aliases below are resolved OUT of spec.FAULTS by status name rather than
# hardcoded, so the wire-code assertions further down still guard the real
# table. A renamed status raises KeyError here — loudly, at collection time.
_FAULTS = spec.FAULTS
_CMD_BY_STATUS = {status: cmd for cmd, (status, _event) in _FAULTS.items()}
CMD_ERR_NO_WATER = _CMD_BY_STATUS["no_water"]
CMD_ERR_NO_BEANS = _CMD_BY_STATUS["no_beans"]
CMD_ERR_DOSE_WATER = _CMD_BY_STATUS["dose_water_error"]
CMD_ERR_GEAR = _CMD_BY_STATUS["gear_position_error"]


def test_bypass_cmd_constant_is_40520() -> None:
    """RD_BYPASS notification code, per discovery/notes/ble-protocol.md."""
    assert CMD_BYPASS == 40520


def test_bypass_started_declared_in_event_types() -> None:
    """The event entity must advertise the new bypass_started event type."""
    assert "bypass_started" in XBloomBrewEventBleEntity._attr_event_types


def test_bypass_cmd_maps_to_bypass_started() -> None:
    """cmd 40520 must dispatch as the granular bypass_started event."""
    assert XBloomBrewEventBleEntity._CMD_TO_GRANULAR[CMD_BYPASS] == "bypass_started"


def test_no_water_cmd_constant_is_40522() -> None:
    """RD_ErrorLackOfWater notification code, per discovery/notes/ble-protocol.md."""
    assert CMD_ERR_NO_WATER == 40522


def test_error_no_water_declared_and_mapped() -> None:
    """cmd 40522 must surface as the error_no_water fault event."""
    assert "error_no_water" in XBloomBrewEventBleEntity._attr_event_types
    assert XBloomBrewEventBleEntity._CMD_TO_GRANULAR[CMD_ERR_NO_WATER] == "error_no_water"


def test_all_fault_codes() -> None:
    """The four machine-fault notification codes, per the errors catalog."""
    assert CMD_ERR_NO_WATER == 40522
    assert CMD_ERR_NO_BEANS == 40517
    assert CMD_ERR_DOSE_WATER == 8204
    assert CMD_ERR_GEAR == 8203


def test_every_fault_fires_a_distinct_event() -> None:
    """Each fault in _FAULTS is declared as an event type and mapped from its cmd."""
    for cmd, (_status, event_type) in _FAULTS.items():
        assert event_type in XBloomBrewEventBleEntity._attr_event_types
        assert XBloomBrewEventBleEntity._CMD_TO_GRANULAR[cmd] == event_type


def test_machine_status_options_cover_all_faults() -> None:
    """Every fault status value must be a valid option on the machine-status sensor."""
    for cmd, (status, _event) in _FAULTS.items():
        assert status in XBloomMachineStatusBleSensor._attr_options
    assert "ok" in XBloomMachineStatusBleSensor._attr_options
    assert XBloomMachineStatusBleSensor._attr_unique_id == "xbloom_machine_status"
