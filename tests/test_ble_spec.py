"""Guard that ble.py derives its pattern/enum maps from the spec.

ble imports bleak (present in the HA runtime). If it is unavailable this test
skips rather than failing, so the pure-spec guards still run anywhere.
"""
from __future__ import annotations

import os
import sys

_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor")
)
sys.path.insert(0, _VENDOR)


def _load():
    from xbloom import ble, spec  # noqa: WPS433
    return ble, spec


def run():
    try:
        ble, spec = _load()
    except Exception as e:  # noqa: BLE001 — dependency-missing = skip, not fail
        print(f"SKIP ble_spec ({type(e).__name__}: {e})")
        return True

    checks = [
        ("api->byte is spec", ble._API_PATTERN_TO_BLE, spec.PATTERN_API_TO_BYTE),
        ("byte->name is spec", ble.PATTERN_NAMES, spec.PATTERN_BYTE_TO_NAME),
        ("api->byte values", ble._API_PATTERN_TO_BLE, {1: 0, 2: 2, 3: 1}),
        ("byte->name values", ble.PATTERN_NAMES, {0: "centered", 1: "circular", 2: "spiral"}),
    ]
    fails = [f"  FAIL {label}: {got!r} != {want!r}" for label, got, want in checks if got != want]
    if fails:
        print("\n".join(fails))
        return False
    print(f"all {len(checks)} ble/spec checks passed")
    return True


def test_ble_spec():
    assert run()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
