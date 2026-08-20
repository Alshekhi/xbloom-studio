"""Tests for the RD_MachineInfo firmware/serial decode in ble.py.

`decode_notification` parses the machine's periodic heartbeat. The identity
strings (serial/model/firmware) sit at the front of the payload; their offsets
are inferred from the Android MachineInfoBleModel, so the decoder validates each
as printable ASCII and drops anything spurious. These tests lock that in.

ble.py imports bleak lazily (inside the client methods), so importing
`decode_notification` needs no BLE stack. Run with:

    uv run pytest tests/test_ble_firmware.py
"""
from __future__ import annotations

import os
import struct
import sys

_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor")
)
sys.path.insert(0, _VENDOR)

from xbloom import ble  # noqa: E402

NOTIFY_MACHINE_INFO = 40521


def _frame(payload: bytes) -> bytes:
    """Wrap a raw RD_MachineInfo payload in the 58 02 notification framing.

    Frame: 58 02 07 [cmd 2 LE] [len 4] [status 1] [payload N] [crc 2].
    decode_notification slices the payload as data[10:-2]; CRC is not checked.
    """
    header = (
        b"\x58\x02\x07"
        + struct.pack("<H", NOTIFY_MACHINE_INFO)
        + struct.pack("<I", len(payload))
        + b"\x00"  # status
    )
    return header + payload + b"\x00\x00"


def _machine_info_payload(
    *, serial=b"ABC12345XYZ99", model=b"J15Pro", version=b"V12.0D.500",
    length=45, water_enough=1, system_status=0, grind_raw=72, voltage=120,
    water_feed=1, temp_unit=0, weight_unit=0, ui_state=1, area_ap=95.5,
    mode_easy=True,
) -> bytes:
    import struct as _struct
    p = bytearray(length)
    p[0:13] = serial
    p[13:19] = model
    p[19:29] = version
    if length >= 33:
        p[29:33] = _struct.pack("<f", area_ap)
    if length > 33:
        p[33] = water_enough
    if length > 34:
        p[34] = system_status
    if length >= 37:
        p[36] = water_feed
    if length > 39:
        p[37] = grind_raw
        p[39] = voltage
    if length >= 42:
        p[40] = temp_unit
        p[41] = weight_unit
    if length >= 43:
        p[42] = ui_state
    if length >= 55:
        p[51:55] = bytes.fromhex("91327856" if mode_easy else "00000000")
    return bytes(p)


def test_decodes_serial_model_firmware_and_numeric_fields():
    out = ble.decode_notification(_frame(_machine_info_payload()))
    assert out["cmd"] == NOTIFY_MACHINE_INFO
    assert out["serial"] == "ABC12345XYZ99"
    assert out["model"] == "J15Pro"
    assert out["fw_version"] == "V12.0D.500"
    # Existing live-confirmed numeric fields are unaffected.
    assert out["water_enough"] == 1
    assert out["system_status"] == 0
    assert out["grind_size_current"] == 42  # 72 - 30
    assert out["voltage"] == 120


def test_firmware_present_even_in_shorter_payload():
    # 35-byte payload: identity strings present (< 29), numeric grind/voltage absent.
    out = ble.decode_notification(_frame(_machine_info_payload(length=35)))
    assert out["fw_version"] == "V12.0D.500"
    assert out["serial"] == "ABC12345XYZ99"
    assert "voltage" not in out  # needs len >= 40


def test_non_ascii_version_is_dropped():
    # A shifted/garbage version field decodes to non-printable bytes → no key.
    out = ble.decode_notification(
        _frame(_machine_info_payload(version=b"\x01\x02\xff\x00\x99\x80\x10\x11\x12\x13"))
    )
    assert "fw_version" not in out
    # Numeric fields still decode fine.
    assert out["water_enough"] == 1


def test_version_without_digit_is_dropped():
    # Printable but not version-like (no digit) → dropped by the digit guard.
    out = ble.decode_notification(
        _frame(_machine_info_payload(version=b"NoDigits.."))
    )
    assert "fw_version" not in out


def test_null_padded_fields_are_trimmed():
    out = ble.decode_notification(
        _frame(_machine_info_payload(
            serial=b"SN01\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            version=b"V9.9\x00\x00\x00\x00\x00\x00",
        ))
    )
    assert out["serial"] == "SN01"
    assert out["fw_version"] == "V9.9"


def test_full_heartbeat_app_confirmed_field_map():
    # Full 63-byte heartbeat with the app-confirmed field map.
    out = ble.decode_notification(_frame(_machine_info_payload(
        length=63, water_feed=1, temp_unit=0, weight_unit=0,
        grind_raw=85, voltage=220, area_ap=95.5, ui_state=1, mode_easy=True,
    )))
    assert out["water_source"] == "tap"        # byte 36 = 1
    assert out["temp_unit"] == "F"             # byte 40 = 0 (0=°F, app-confirmed)
    assert out["weight_unit"] == "ml"          # byte 41 = 0 (0=ml, app-confirmed)
    assert out["grind_size_current"] == 55     # 85 - 30
    assert out["voltage"] == 220
    assert out["area_ap"] == 95.5              # bytes 29-32 LE float
    assert out["ui_state"] == 1                # byte 42 (experimental)
    assert out["mode"] == "auto"               # bytes 51-54 == 91327856


def test_heartbeat_mode_pro_and_tank():
    out = ble.decode_notification(_frame(_machine_info_payload(
        length=63, water_feed=0, temp_unit=1, weight_unit=2, mode_easy=False,
    )))
    assert out["mode"] == "pro"                # bytes 51-54 == 00000000
    assert out["water_source"] == "tank"       # byte 36 = 0
    assert out["temp_unit"] == "C"             # byte 40 = 1 (1=°C, app-confirmed)
    assert out["weight_unit"] == "oz"          # byte 41 = 2 (2=oz, app-confirmed)


def test_heartbeat_new_fields_absent_in_short_payload():
    # A 45-byte payload lacks mode (needs >=55); ui_state/units present (>=43).
    out = ble.decode_notification(_frame(_machine_info_payload(length=45)))
    assert "mode" not in out
    assert out["water_source"] == "tap"        # byte 36 present at len 45


def test_encode_recipe_blob_trailing_byte_is_ratio_x10():
    # The trailing metadata byte is the brew RATIO ×10 (firmware gates the
    # grind-size commit on round((tail/10)×dose) == Σvolumes), NOT total_water×10.
    # 20 g dose, 308 ml total → ratio 15.4 → 0x9A (matches the app), and does NOT
    # overflow the byte the way total_water×10 (3080 & 0xFF = 8) would.
    pours = [{"volume_ml": 308, "temperature_c": 93, "pattern": 2, "flow_rate": 3.0}]
    blob = ble.encode_recipe_blob(pours, grinder_size=50, dose_g=20, rpm=90)
    assert blob[-1] == 0x9A, hex(blob[-1])   # ratio 15.4 × 10
    assert blob[-2] == 50                    # grinder size

    # No dose → tail 0, and no ZeroDivisionError.
    assert ble.encode_recipe_blob(pours, grinder_size=50, dose_g=0)[-1] == 0

    # grinder_size clamped to the firmware max (≤ 80).
    assert ble.encode_recipe_blob(pours, grinder_size=200, dose_g=20)[-2] == 80


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
