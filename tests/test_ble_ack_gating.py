"""Tests for the BLE send-and-confirm (ACK-gating) layer in vendor/xbloom/ble.py.

Mirrors the official app's AppBleManager: every command written to FFE1 is
echoed back on FFE2, and the next frame is sent only once that echo arrives
(re-sending on timeout). Confirmed from live brew captures — see
discovery/analysis/ACK_GATING_EVIDENCE.md.

These use a fake BleakClient (no hardware, no bleak import needed — ble.py
imports bleak lazily) that records writes and simulates the machine echoing
selected command codes back through the client's own notification handler.
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys
from unittest.mock import patch

_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor")
)
sys.path.insert(0, _VENDOR)

from xbloom import ble  # noqa: E402


def _echo_frame(code: int) -> bytes:
    """A minimal, well-formed 58 02 notification echoing `code`."""
    return (
        bytes([0x58, 0x02, 0x07])
        + struct.pack("<H", code)
        + bytes([0, 0, 0, 0, 0xC1])   # len(4) + status(0xC1)
        + bytes([0, 0])               # crc (not validated by the parser)
    )


class FakeClient:
    """Records FFE1 writes; echoes chosen codes back via the notify callback.

    `echo_codes=None` echoes every command; a set echoes only those codes;
    an empty set echoes nothing (dead-stream / sleeping machine).
    """

    def __init__(self, echo_codes=None, notify_fails=False):
        self.is_connected = True
        self.echo_codes = echo_codes
        self.notify_fails = notify_fails
        self.notify_cb = None
        self.loop = None
        self.events: list[tuple[str, int]] = []   # ("W", code) / ("E", code)

    async def start_notify(self, uuid, cb):
        if self.notify_fails:
            raise RuntimeError("org.bluez.Error.NotPermitted: Notify acquired")
        self.notify_cb = cb

    async def write_gatt_char(self, uuid, frame, response=False):
        code = ble.frame_command_code(frame)
        self.events.append(("W", code))
        if self.notify_cb is not None and (
            self.echo_codes is None or code in self.echo_codes
        ):
            self.loop.call_soon(self._deliver, code)

    def _deliver(self, code: int):
        self.events.append(("E", code))
        if self.notify_cb is not None:
            self.notify_cb(None, _echo_frame(code))

    @property
    def writes(self):
        return [c for kind, c in self.events if kind == "W"]


def _mk_client(fake: FakeClient) -> ble.XBloomBleClient:
    c = ble.XBloomBleClient("XBLOOM TEST")
    c._client = fake
    c._loop = asyncio.get_event_loop()
    fake.loop = c._loop
    return c


_RECIPE = {
    "name": "unit-test",
    "dose_g": 18,
    "grinder_size": 65,
    "grinder_size_enabled": 1,
    "rpm": 60,
    "cup_type": 3,
    "pours": [
        {"volume_ml": 60, "temperature_c": 93, "pattern": 1,
         "flow_rate": 3.0, "pause_s": 0, "agitate_before": 2, "agitate_after": 2},
    ],
}


# --------------------------------------------------------------------------- #
# frame_command_code                                                          #
# --------------------------------------------------------------------------- #
def test_frame_command_code_reads_le_code():
    frame = ble._build_frame(ble.CMD_EXECUTE)          # 8002
    assert ble.frame_command_code(frame) == 8002
    recipe = ble._build_frame(ble.CMD_RECIPE_GRIND, raw_bytes=b"\x01\x02")
    assert ble.frame_command_code(recipe) == 8001


def test_frame_command_code_rejects_garbage():
    assert ble.frame_command_code(b"") is None
    assert ble.frame_command_code(b"\x00\x01\x02\x03\x04") is None


# --------------------------------------------------------------------------- #
# write_confirmed                                                             #
# --------------------------------------------------------------------------- #
def test_write_confirmed_returns_true_on_echo():
    async def go():
        fake = FakeClient()          # echoes everything
        c = _mk_client(fake)
        c._notify_active = True
        fake.notify_cb = c._on_notify
        frame = ble._build_frame(ble.CMD_TARE)   # 8500
        ok = await c.write_confirmed("tare", frame, timeout=0.5)
        assert ok is True
        assert fake.writes == [8500]             # one write, no retry
    asyncio.run(go())


def test_write_confirmed_retries_then_gives_up_without_echo():
    async def go():
        fake = FakeClient(echo_codes=set())   # echo nothing
        c = _mk_client(fake)
        c._notify_active = True
        fake.notify_cb = c._on_notify
        frame = ble._build_frame(ble.CMD_TARE)
        ok = await c.write_confirmed("tare", frame, timeout=0.02, max_attempts=3)
        assert ok is False
        assert fake.writes == [8500, 8500, 8500]   # 3 sends (initial + 2 retries)
    asyncio.run(go())


def test_write_confirmed_app_exact_no_retry_when_awake():
    async def go():
        fake = FakeClient(echo_codes=set())   # echo nothing
        c = _mk_client(fake)
        c._notify_active = True
        c._sleeping = False                    # awake
        fake.notify_cb = c._on_notify
        frame = ble._build_frame(ble.CMD_TARE)
        ok = await c.write_confirmed(
            "tare", frame, timeout=0.02, max_attempts=3,
            retry_only_when_sleeping=True,
        )
        assert ok is False
        assert fake.writes == [8500]           # app-exact: one send, no retry
    asyncio.run(go())


def test_write_confirmed_app_exact_retries_when_sleeping():
    async def go():
        fake = FakeClient(echo_codes=set())
        c = _mk_client(fake)
        c._notify_active = True
        c._sleeping = True                     # sleeping → retries allowed
        fake.notify_cb = c._on_notify
        frame = ble._build_frame(ble.CMD_TARE)
        ok = await c.write_confirmed(
            "tare", frame, timeout=0.02, max_attempts=3,
            retry_only_when_sleeping=True,
        )
        assert ok is False
        assert fake.writes == [8500, 8500, 8500]
    asyncio.run(go())


def test_write_confirmed_stops_retrying_once_echo_arrives():
    async def go():
        # Echo only the second attempt: withhold on write #1, deliver on #2.
        fake = FakeClient(echo_codes=set())
        c = _mk_client(fake)
        c._notify_active = True
        fake.notify_cb = c._on_notify
        state = {"n": 0}
        orig = fake.write_gatt_char

        async def counting_write(uuid, frame, response=False):
            state["n"] += 1
            await orig(uuid, frame, response=response)
            if state["n"] == 2:      # let the 2nd attempt's echo through
                fake.loop.call_soon(fake._deliver, ble.frame_command_code(frame))
        fake.write_gatt_char = counting_write

        frame = ble._build_frame(ble.CMD_TARE)
        ok = await c.write_confirmed("tare", frame, timeout=0.05, max_attempts=3)
        assert ok is True
        assert fake.writes == [8500, 8500]   # stopped after the confirmed 2nd
    asyncio.run(go())


# --------------------------------------------------------------------------- #
# send_command (the one-shot convenience path all services use)               #
# --------------------------------------------------------------------------- #
def test_send_command_subscribes_and_confirms_echo():
    async def go():
        fake = FakeClient()               # echoes everything
        c = _mk_client(fake)
        # send_command must subscribe to FFE2 itself (notify_cb starts None).
        assert fake.notify_cb is None
        ok = await c.send_command("tare", ble._build_frame(ble.CMD_TARE))
        assert ok is True
        assert fake.notify_cb is not None   # it subscribed
        assert fake.writes == [8500]        # default max_attempts=1, one write
    asyncio.run(go())


def test_send_command_default_no_retry_when_awake():
    # App-exact default (retry_only_when_sleeping=True): awake + no echo → the
    # command is not re-sent, even for max_attempts=3. This is what keeps a
    # not-echo-verified motion command from double-actuating.
    async def go():
        fake = FakeClient(echo_codes=set())   # never echoes
        c = _mk_client(fake)
        c._sleeping = False                   # awake
        with patch.object(ble, "ECHO_TIMEOUT_S", 0.02):
            ok = await c.send_command("tare", ble._build_frame(ble.CMD_TARE))
        assert ok is False
        assert fake.writes == [8500]          # exactly one write — no re-send
    asyncio.run(go())


def test_send_command_default_retries_when_sleeping():
    # App-exact default: sleeping + no echo → re-send up to max_attempts (3).
    async def go():
        fake = FakeClient(echo_codes=set())
        c = _mk_client(fake)
        c._sleeping = True                    # sleeping → retries allowed
        with patch.object(ble, "ECHO_TIMEOUT_S", 0.02):
            ok = await c.send_command("tare", ble._build_frame(ble.CMD_TARE))
        assert ok is False
        assert fake.writes == [8500, 8500, 8500]
    asyncio.run(go())


def test_send_command_degrades_when_notify_unavailable():
    async def go():
        fake = FakeClient(notify_fails=True)  # BlueZ refuses the subscription
        c = _mk_client(fake)
        real_sleep = asyncio.sleep
        with patch("asyncio.sleep", lambda _s: real_sleep(0)):
            ok = await c.send_command("tare", ble._build_frame(ble.CMD_TARE))
        assert ok is False
        assert c._notify_active is False
        assert fake.writes == [8500]          # written fire-and-forget, degraded
    asyncio.run(go())


# --------------------------------------------------------------------------- #
# read_status_snapshot (on-demand heartbeat capture)                          #
# --------------------------------------------------------------------------- #
def _machine_info_frame() -> bytes:
    """A minimal RD_MachineInfo (40521) notification with a 63-byte payload."""
    payload = bytearray(63)
    payload[0:13] = b"FAKESERIAL000"
    payload[19:29] = b"V12.0D.500"
    payload[33] = 1          # water enough
    payload[37] = 85         # grind raw -> 55
    payload[39] = 220        # voltage
    payload[36] = 1          # water source = tap
    return (
        bytes([0x58, 0x02, 0x07]) + struct.pack("<H", 40521)
        + struct.pack("<I", len(payload)) + bytes([0xC1]) + bytes(payload)
        + bytes([0, 0])
    )


def test_read_status_snapshot_returns_heartbeat():
    async def go():
        fake = FakeClient()
        c = _mk_client(fake)
        fake.notify_cb = c._on_notify
        # When the handshake nudge is written, deliver a heartbeat frame.
        orig = fake.write_gatt_char

        async def write_then_heartbeat(uuid, frame, response=False):
            await orig(uuid, frame, response=response)
            if ble.frame_command_code(frame) == ble.CMD_HANDSHAKE:
                fake.loop.call_soon(lambda: fake.notify_cb(None, _machine_info_frame()))
        fake.write_gatt_char = write_then_heartbeat

        snap = await c.read_status_snapshot(timeout=1.0)
        assert snap is not None
        assert snap["cmd"] == 40521
        assert snap["water_enough"] == 1
        assert snap["grind_size_current"] == 55
        assert snap["water_source"] == "tap"
    asyncio.run(go())


def test_read_status_snapshot_times_out_without_heartbeat():
    async def go():
        fake = FakeClient(echo_codes=set())   # never delivers anything
        c = _mk_client(fake)
        fake.notify_cb = c._on_notify
        with patch.object(ble, "ECHO_TIMEOUT_S", 0.02):
            snap = await c.read_status_snapshot(timeout=0.1)
        assert snap is None
    asyncio.run(go())


# --------------------------------------------------------------------------- #
# brew() end-to-end ordering                                                  #
# --------------------------------------------------------------------------- #
def test_brew_gates_execute_on_recipe_echo():
    async def go():
        fake = FakeClient()   # echoes every command
        c = _mk_client(fake)
        with patch.object(ble, "SETTLE_AFTER_ECHO_S", 0):
            await c.brew(_RECIPE)
        # Full ordered command sequence, each echo-gated. App-faithful: no 11511
        # mode switch and no injected 8006 — grind rides in the 8001 blob, and
        # 8002 is sent only after the machine echoes (accepts) 8001.
        assert fake.writes == [8100, 8102, 8104, 8001, 8002]
        # The critical invariant: EXECUTE (8002) is written only AFTER the
        # recipe (8001) echo has been received.
        seq = fake.events
        e8001 = seq.index(("E", 8001))
        w8002 = seq.index(("W", 8002))
        assert e8001 < w8002, f"8002 written before 8001 echo: {seq}"
    asyncio.run(go())


def test_brew_degrades_to_fixed_delay_when_no_handshake_echo():
    async def go():
        fake = FakeClient(echo_codes=set())   # dead echo stream
        c = _mk_client(fake)
        # Make the timeout tiny and the degraded fixed sleeps a no-op so the
        # test is fast; the handshake canary must trip and the rest still send.
        real_sleep = asyncio.sleep

        async def fast_sleep(_s):
            await real_sleep(0)
        with patch.object(ble, "ECHO_TIMEOUT_S", 0.01), \
             patch("asyncio.sleep", fast_sleep):
            await c.brew(_RECIPE)
        # Handshake retried up to max, then every remaining frame sent once
        # (degraded). So handshake appears ECHO_MAX_ATTEMPTS times, the rest once.
        assert fake.writes[:ble.ECHO_MAX_ATTEMPTS] == [8100] * ble.ECHO_MAX_ATTEMPTS
        tail = fake.writes[ble.ECHO_MAX_ATTEMPTS:]
        assert tail == [8102, 8104, 8001, 8002]
    asyncio.run(go())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
