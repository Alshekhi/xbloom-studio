"""Tests for the firmware OTA encoder (vendor/xbloom/ota.py).

Pure-logic, no BLE. ble.py imports bleak lazily, so importing the encoder needs
no BLE stack. The byte-exactness against a real captured OTA is proven
separately against the (gitignored) capture; here we lock in the structure and
the encode→reconstruct round-trip so a regression can't silently corrupt the
stream.
"""
from __future__ import annotations

import os
import struct
import sys

_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor")
)
sys.path.insert(0, _VENDOR)

from xbloom import ota  # noqa: E402
from xbloom.ble import _crc16  # noqa: E402

# Deterministic synthetic firmware spanning 3 blocks (1024 + 1024 + 452).
FW = bytes((i * 7 + 3) & 0xFF for i in range(2500))
VERSION = "V12.0D.500"


def test_header_structure_and_crc():
    hdr = ota.build_header(FW, VERSION, "J15")
    assert hdr.startswith(b"\x01\x00\xff")
    assert hdr.endswith(b"\x02\x00\xff")
    # 3 (start) + 128 (content) + 2 (crc) + 3 (data marker)
    assert len(hdr) == 136
    content = hdr[3:3 + 128]
    assert content.startswith(b"FW_J15V12.0D.500.bin\x00109396"[:20])  # name prefix
    assert b"FW_J15V12.0D.500.bin\x00" in content
    assert str(len(FW)).encode() + b"\x00" in content
    # CRC is CRC16-Kermit of the 128-byte content, big-endian, before 02 00 ff.
    assert hdr[3 + 128:3 + 128 + 2] == struct.pack(">H", _crc16(content))


def test_block_frames_count_and_markers():
    frames = list(ota.iter_block_frames(FW))
    assert len(frames) == 3  # 1024 + 1024 + 452

    # Full blocks: 1024 data + [crc BE][0x02][seq][~seq]
    for k in (0, 1):
        frame = frames[k]
        block, marker = frame[:1024], frame[1024:]
        assert len(marker) == 5
        assert marker[:2] == struct.pack(">H", _crc16(block))
        assert marker[2] == 0x02
        assert marker[3] == k + 1                 # 1-based seq
        assert marker[4] == (~(k + 1)) & 0xFF     # one's complement

    # Final (partial) block: 452 data + all-0xFF end marker.
    last = frames[2]
    assert last[:-5] == FW[2048:]
    assert len(last[:-5]) == 452
    assert last[-5:] == b"\xff\xff\xff\xff\xff"


def test_round_trip_reconstructs_firmware():
    # Stripping the 5-byte marker off every block must rebuild the image exactly.
    frames = list(ota.iter_block_frames(FW))
    recon = b"".join(f[:-5] for f in frames)
    assert recon == FW


def test_encode_ota_stream_is_header_plus_frames():
    stream = ota.encode_ota_stream(FW, VERSION, "J15")
    expected = ota.build_header(FW, VERSION, "J15") + b"".join(ota.iter_block_frames(FW))
    assert stream == expected


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
