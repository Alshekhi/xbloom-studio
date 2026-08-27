"""Tests for decode_notification — MachineInfo (40521) status decode.

Verifies the byte offsets of the periodic status heartbeat against the Android
MachineInfoBleModel parse:
byte 33 = waterEnough, byte 34 = systemStatus, byte 37 = grinder, byte 39 = voltage.
The conftest injects homeassistant stubs so the vendor import path resolves.
"""
import struct

from custom_components.xbloom.vendor.xbloom.ble import (  # noqa: E402
    NOTIFY_MACHINE_INFO,
    decode_notification,
)


def _machine_info_frame(
    water_enough: int, system_status: int, grinder_raw: int = 95, voltage: int = 120
) -> bytes:
    """Build a synthetic 5802 MachineInfo notification frame."""
    payload = bytearray(40)
    payload[33] = water_enough
    payload[34] = system_status
    payload[37] = grinder_raw
    payload[39] = voltage
    header = (
        bytes([0x58, 0x02, 0x07])
        + struct.pack("<H", NOTIFY_MACHINE_INFO)  # cmd
        + struct.pack("<I", 0)                    # length (unused by parser)
        + bytes([0x00])                           # status byte
    )
    return header + bytes(payload) + bytes([0x00, 0x00])  # + CRC placeholder


def test_machine_info_water_low() -> None:
    d = decode_notification(_machine_info_frame(water_enough=0, system_status=4))
    assert d["cmd"] == NOTIFY_MACHINE_INFO
    assert d["water_enough"] == 0
    assert d["system_status"] == 4
    assert d["grind_size_current"] == 95 - 30
    assert d["voltage"] == 120


def test_machine_info_water_ok() -> None:
    d = decode_notification(_machine_info_frame(water_enough=1, system_status=0))
    assert d["water_enough"] == 1
    assert d["system_status"] == 0


def test_machine_info_grinder_floor() -> None:
    """grinder = max(raw - 30, 1) — never below 1."""
    d = decode_notification(_machine_info_frame(1, 0, grinder_raw=10))
    assert d["grind_size_current"] == 1
