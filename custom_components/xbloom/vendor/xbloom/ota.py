"""xBloom firmware OTA over BLE — byte-exact encoder + ACK-gated flasher.

Reverse-engineered from a real captured firmware update (V12.0D.500) and
**validated byte-for-byte**: the stream this module writes to
the OTA data characteristic is identical to what the official app sent in a
successful flash, and reconstructs to the same MD5 as the S3 download. See
``discovery/ios/discovery/xbloom-fw-trace-2026-07-18/REVERSE_ENGINEERING.md``.

Transport — a YMODEM-flavoured protocol over a **dedicated** vendor OTA GATT
service (distinct from the command service ``0000e0ff-…`` used for brewing):

  service ``12a24d2e-fe14-488e-93d2-173cffe00000``
    ffe1 (write-without-response) — OTA data, phone → machine (16-byte writes)
    ffe2 (notify)                 — status + per-block ``0x06`` ACK, machine → phone

Sequence:
  1. enable ffe2 notifications
  2. write the two fixed handshake frames (start-A / start-B)
  3. the machine notifies its identity (serial + current version) and a ``0x43``
     ('C') "ready" poll
  4. write the header block: ``01 00 ff`` + ``FW_<model><version>.bin\\0`` +
     ``<size>\\0`` padded to 128 bytes + ``CRC16-Kermit(content)`` (big-endian)
     + ``02 00 ff``
  5. stream the firmware as 1024-byte blocks; after each block write a 5-byte
     marker ``[CRC16-Kermit(block) BE][0x02][seq][~seq]`` (seq is 1-based) and
     wait for a ``0x06`` ACK before the next block. The final (partial) block
     uses an all-``0xFF`` end marker.

The block/header CRC is the **same** CRC16-Kermit already in ``ble.py``.

⚠️ Flashing firmware can brick the machine if the BLE link drops mid-transfer.
This module reproduces a known-good stream and ACK-gates every block, but the
caller must hold an exclusive, stable connection (no other HA BLE activity) and
should only run it on a machine the user has explicitly chosen to update.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Awaitable, Callable

from .ble import _crc16

log = logging.getLogger("xbloom.ota")

# -- GATT (vendor OTA service) ---------------------------------------------- #
OTA_SERVICE_UUID = "12a24d2e-fe14-488e-93d2-173cffe00000"
OTA_DATA_UUID = "12a24d2e-fe14-488e-93d2-173cffe10000"    # ffe1, write-no-resp
OTA_NOTIFY_UUID = "12a24d2e-fe14-488e-93d2-173cffe20000"  # ffe2, notify

# -- framing constants (all verified against the capture) ------------------- #
_BLOCK = 1024
_ATT_CHUNK = 16               # 16-byte ATT writes, matching the app
_HEADER_CONTENT_LEN = 128
_START_MARKER = b"\x01\x00\xff"
_DATA_MARKER = b"\x02\x00\xff"
_END_MARKER = b"\xff\xff\xff\xff\xff"
_ACK = 0x06                   # per-block ACK on ffe2 (YMODEM-style)
_NAK = 0x15
_READY = 0x43                 # 'C' — receiver-ready poll

# Fixed session-start handshake frames. Verified to encode no firmware size/CRC
# (so they are constant across firmware versions); captured verbatim.
_START_A = bytes.fromhex("580101a41f1400000001b900000001000000bdd1")
_START_B = bytes.fromhex("580101a51f0c00000001ff2a")


class XBloomOtaError(Exception):
    """OTA transfer failed."""


# --------------------------------------------------------------------------- #
# Pure encoder (no BLE) — unit-testable, byte-exact                           #
# --------------------------------------------------------------------------- #
def build_header(firmware: bytes, version: str, model: str = "J15") -> bytes:
    """Build the 136-byte OTA header for a firmware image."""
    content = (
        f"FW_{model}{version}.bin".encode() + b"\x00"
        + str(len(firmware)).encode() + b"\x00"
    ).ljust(_HEADER_CONTENT_LEN, b"\x00")
    return (
        _START_MARKER + content
        + struct.pack(">H", _crc16(content)) + _DATA_MARKER
    )


def _block_marker(block: bytes, seq: int, *, last: bool) -> bytes:
    if last:
        return _END_MARKER
    return struct.pack(">H", _crc16(block)) + bytes([0x02, seq & 0xFF, (~seq) & 0xFF])


def iter_block_frames(firmware: bytes):
    """Yield each block's on-wire payload (≤1024 data bytes + 5-byte marker).

    ``build_header(fw, …)`` followed by every yielded frame is exactly the byte
    stream the official app writes to the OTA data characteristic.
    """
    n = (len(firmware) + _BLOCK - 1) // _BLOCK
    for k in range(n):
        block = firmware[k * _BLOCK:(k + 1) * _BLOCK]
        yield block + _block_marker(block, k + 1, last=(k == n - 1))


def encode_ota_stream(firmware: bytes, version: str, model: str = "J15") -> bytes:
    """The full header+payload byte stream (handshake frames excluded).

    Provided for validation/round-trip; the flasher writes the pieces
    incrementally so it can ACK-gate between blocks.
    """
    return build_header(firmware, version, model) + b"".join(iter_block_frames(firmware))


ProgressCb = Callable[[int, int], "Awaitable[None] | None"]


# --------------------------------------------------------------------------- #
# BLE flasher                                                                 #
# --------------------------------------------------------------------------- #
class XBloomOtaFlasher:
    """Drive a firmware flash over BLE against the vendor OTA service.

    Args:
        device: a connectable bleak ``BLEDevice`` for the machine.
        progress: optional callback ``(blocks_done, blocks_total)`` — may be
            sync or async — invoked after each acknowledged block.
        ack_timeout: seconds to wait for a per-block ACK before retrying.
    """

    def __init__(
        self,
        device,
        *,
        progress: ProgressCb | None = None,
        ack_timeout: float = 8.0,
        chunk_delay: float = 0.0,
        block_settle: float = 0.0,
    ) -> None:
        """
        Args:
            chunk_delay: seconds to pause between 16-byte writes. The right value
                is transport-specific (BlueZ backpressures on its own → 0 is fine;
                an ESPHome BLE proxy or a native ESP32 may need a few ms), so the
                integration layer supplies it rather than the vendor hard-coding.
            block_settle: seconds to pause after a block's writes before awaiting
                its ACK (lets the machine finish reassembling before it replies).
        """
        self._device = device
        self._progress = progress
        self._ack_timeout = ack_timeout
        self._chunk_delay = chunk_delay
        self._block_settle = block_settle
        self._client = None
        self._acks: asyncio.Queue[int] = asyncio.Queue()
        self._ready = asyncio.Event()

    def _on_notify(self, _char, data: bytes) -> None:
        if not data:
            return
        # ACK/NAK gate the transfer; a 'C' anywhere in the first 2 bytes is the
        # receiver-ready poll. 58 02 … status frames are ignored here.
        if data[0] in (_ACK, _NAK):
            self._acks.put_nowait(data[0])
        if _READY in data[:2]:
            self._ready.set()

    async def _connect(self) -> None:
        from bleak import BleakClient
        try:
            from bleak_retry_connector import establish_connection
            self._client = await establish_connection(
                BleakClient, self._device, getattr(self._device, "address", "xbloom-ota")
            )
        except ImportError:
            self._client = BleakClient(self._device)
            await self._client.connect()

    async def _write_chunked(self, payload: bytes) -> None:
        for i in range(0, len(payload), _ATT_CHUNK):
            await self._client.write_gatt_char(
                OTA_DATA_UUID, payload[i:i + _ATT_CHUNK], response=False
            )
            if self._chunk_delay:
                await asyncio.sleep(self._chunk_delay)

    async def _await_ack(self) -> int:
        return await asyncio.wait_for(self._acks.get(), self._ack_timeout)

    async def _send_block(self, frame: bytes, *, retries: int = 2) -> None:
        for attempt in range(retries + 1):
            await self._write_chunked(frame)
            if self._block_settle:
                await asyncio.sleep(self._block_settle)
            try:
                tok = await self._await_ack()
            except asyncio.TimeoutError:
                if attempt < retries:
                    log.warning("xbloom ota: ACK timeout — retrying block")
                    continue
                raise XBloomOtaError("timed out waiting for block ACK")
            if tok == _ACK:
                return
            log.warning("xbloom ota: block NAK'd — retrying")
        raise XBloomOtaError("block repeatedly NAK'd")

    async def _emit_progress(self, done: int, total: int) -> None:
        if self._progress is None:
            return
        res = self._progress(done, total)
        if asyncio.iscoroutine(res):
            await res

    async def flash(self, firmware: bytes, version: str, model: str = "J15") -> None:
        """Flash ``firmware`` to the machine. Raises XBloomOtaError on failure.

        The caller is responsible for verifying the firmware's MD5 before
        calling this, and for ensuring no other BLE activity contends for the
        machine during the transfer.
        """
        frames = list(iter_block_frames(firmware))
        total = len(frames)
        log.info("xbloom ota: flashing %s (%d bytes, %d blocks)",
                 version, len(firmware), total)
        await self._connect()
        try:
            await self._client.start_notify(OTA_NOTIFY_UUID, self._on_notify)
            await self._write_chunked(_START_A)
            await self._write_chunked(_START_B)
            # Wait for the receiver-ready 'C' poll (proceed anyway if the machine
            # doesn't send a distinct one).
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.debug("xbloom ota: no explicit 'C' ready poll — proceeding")
            await self._write_chunked(build_header(firmware, version, model))
            # The header is not separately ACK'd (the machine ACKs blocks only).
            for k, frame in enumerate(frames, start=1):
                await self._send_block(frame)
                await self._emit_progress(k, total)
            log.info("xbloom ota: all %d blocks acknowledged", total)
        finally:
            try:
                await self._client.stop_notify(OTA_NOTIFY_UUID)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
