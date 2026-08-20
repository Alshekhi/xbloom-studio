"""Tests for the recipe-blob firmware-consistency gate (vendor/xbloom/ble.py).

The machine only COMMITS a recipe — including its grind-size target — when the
blob satisfies, in the firmware's own float32 arithmetic (recipe handler
~fw:2195-2214):

    trunc( (ratio_byte / 10) * dose ) == Σ(wire pour volumes)

If it fails, the machine keeps its PREVIOUS grind target and brews the new
pours at the STALE grind size. The customizer used to fail this gate: it
truncated fractional scaled volumes (Σ=224) while deriving the ratio byte from
the un-truncated float total (225/15 → byte 150), so 15.0×15=225 ≠ 224. These
tests lock in that every blob we build passes the gate by construction.
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
from xbloom import brew_scale  # noqa: E402


def _f32(x: float) -> float:
    """IEEE-754 single-precision round — the firmware's ALU precision."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def _firmware_target(ratio_byte: int, dose_i: int) -> int:
    """What the firmware computes for the RHS of the gate (float32 trunc)."""
    return int(_f32(_f32(_f32(ratio_byte) / _f32(10.0)) * _f32(dose_i)))


def _gate_holds(ratio_byte: int, dose_i: int, wire_sum: int) -> bool:
    """The exact condition the machine checks before committing the recipe."""
    return _firmware_target(ratio_byte, dose_i) == wire_sum


# "وصفة زيادة الحلاوة" 872025 shape: dose 20, ratio 15, 300 ml over 5 pours.
_RECIPE = {
    "name": "زيادة الحلاوة",
    "dose_g": 20.0,
    "water_ratio": 15.0,
    "grinder_size": 50,
    "grinder_size_enabled": 1,
    "rpm": 100,
    "cup_type": 3,
    "pours": [
        {"volume_ml": 30, "temperature_c": 92, "pattern": 3, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 90, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 92, "pattern": 2, "flow_rate": 3.2,
         "pause_s": 20, "agitate_before": 2, "agitate_after": 2},
        {"volume_ml": 60, "temperature_c": 85, "pattern": 1, "flow_rate": 3.5,
         "pause_s": 5, "agitate_before": 2, "agitate_after": 2},
    ],
}


def _wire_volume_sum(blob: bytes, pour_count: int) -> int:
    """Sum the per-pour wire volume bytes of a blob whose pours are all ≤127 ml.

    Layout per such pour is 8 bytes: [vol, temp, pattern, vib] + [pw,0,rpm,flow];
    the volume byte sits at data offset 0, 8, 16, … (blob offset 1 + 8*k).
    """
    return sum(blob[1 + 8 * k] for k in range(pour_count))


def test_regression_customizer_dose15_ratio15():
    """The exact brew that failed on hardware: 872025 scaled to dose 15.

    Fable's predicted, gate-passing result: volumes [23,67,45,45,45]=225,
    ratio byte 150, grinder byte 50.
    """
    scaled = brew_scale.scale_recipe(_RECIPE, dose_g=15, ratio=15, grind_size=50)
    # scale_recipe keeps fractional volumes (22.5, 67.5, 45, 45, 45).
    src = [p["volume_ml"] for p in scaled["pours"]]
    assert abs(sum(src) - 225.0) < 1e-6

    int_vols, ratio_byte = ble._gate_consistent_volumes(src, 15)
    assert int_vols == [23, 67, 45, 45, 45]
    assert sum(int_vols) == 225
    assert ratio_byte == 150
    assert _gate_holds(ratio_byte, 15, sum(int_vols))

    blob = ble.encode_recipe_blob(scaled["pours"], grinder_size=50, dose_g=15, rpm=100)
    assert blob[-1] == 150            # ratio byte
    assert blob[-2] == 50             # grinder byte
    assert _wire_volume_sum(blob, 5) == 225
    assert _gate_holds(blob[-1], 15, _wire_volume_sum(blob, 5))


def test_stored_recipe_unscaled_is_unchanged():
    """An exact stored recipe must be byte-stable (no apportionment drift).

    872025 at its own dose 20 / ratio 15 already sums to 300 = 20×15, so the
    quantizer must leave the volumes and ratio byte exactly as before.
    """
    src = [p["volume_ml"] for p in _RECIPE["pours"]]  # 30,90,60,60,60
    int_vols, ratio_byte = ble._gate_consistent_volumes(src, 20)
    assert int_vols == [30, 90, 60, 60, 60]
    assert ratio_byte == 150
    assert _gate_holds(ratio_byte, 20, 300)

    blob = ble.encode_recipe_blob(_RECIPE["pours"], grinder_size=50, dose_g=20, rpm=100)
    assert blob[-1] == 150
    assert _wire_volume_sum(blob, 5) == 300


def test_gate_holds_across_dose_and_ratio_sweep():
    """Every scaled blob must pass the firmware gate, with a sub-ml water shift."""
    ratios = [10.0, 12.5, 15.0, 16.0, 16.5, 18.0, 19.0, 20.0]
    for dose in range(5, 31):                     # 5..30 g
        for ratio in ratios:
            scaled = brew_scale.scale_recipe(_RECIPE, dose_g=dose, ratio=ratio)
            src = [p["volume_ml"] for p in scaled["pours"]]
            int_vols, ratio_byte = ble._gate_consistent_volumes(src, dose)

            # 1) The gate the machine checks must hold exactly.
            assert _gate_holds(ratio_byte, dose, sum(int_vols)), (
                f"gate FAILS dose={dose} ratio={ratio}: "
                f"byte={ratio_byte} target={_firmware_target(ratio_byte, dose)} "
                f"sum={sum(int_vols)}"
            )
            # 2) The delivered water is within ~one tenth-of-dose of intent.
            assert abs(sum(int_vols) - dose * ratio) <= dose / 10.0 + 1.0
            # 3) No negative / nonsense volumes, ratio byte fits one byte.
            assert all(v >= 0 for v in int_vols)
            assert 0 < ratio_byte <= 0xFF


def test_grinder_off_still_gate_consistent():
    """The no-grinder (8004) path shares the gate — it must pass too."""
    scaled = brew_scale.scale_recipe(_RECIPE, dose_g=17, ratio=16.5)
    src = [p["volume_ml"] for p in scaled["pours"]]
    int_vols, ratio_byte = ble._gate_consistent_volumes(src, 17)
    assert _gate_holds(ratio_byte, 17, sum(int_vols))
    # grinder OFF encodes grinder_byte 0 but the volume/ratio gate is identical.
    blob = ble.encode_recipe_blob(scaled["pours"], grinder_size=0, dose_g=17, rpm=0)
    assert blob[-2] == 0
    assert _wire_volume_sum(blob, 5) == _firmware_target(blob[-1], 17)
