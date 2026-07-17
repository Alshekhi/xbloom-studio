"""BLE protocol implementation for the xBloom Studio coffee machine.

Builds and sends the EasyMode (Auto Mode A) brew command sequence over BLE.
Protocol details were determined by observing the machine's own BLE traffic.

Usage (from an async context, e.g. HA service handler):
    client = XBloomBleClient(bluetooth_name="XBLOOM ABC123")
    async with client:
        await client.brew(recipe, the_code, the_max, the_min)

Public API:
    XBloomBleClient(bluetooth_name, *, timeout=10.0)
    async brew(recipe, the_code_hex, the_max, the_min)
    async disconnect()

Events fired on FFE3:
    RD_ENJOY (40512) — brew complete; caller should listen via on_enjoy callback.
"""
from __future__ import annotations

import logging
import struct
from typing import Callable, Awaitable

from . import spec

log = logging.getLogger("xbloom.ble")

# ---------------------------------------------------------------------------
# BLE characteristic UUIDs / handles (from the device's GATT table)
# ---------------------------------------------------------------------------
FFE1_UUID    = "0000ffe1-0000-1000-8000-00805f9b34fb"   # TXD  — phone → machine (write)
FFE2_UUID    = "0000ffe2-0000-1000-8000-00805f9b34fb"   # RXD  — machine → phone (notify, silent)

# The command codes written to FFE1 are defined canonically below as CMD_*
# (CMD_HANDSHAKE 8100, CMD_BYPASS_DOSE 8102, CMD_SET_CUP 8104, CMD_RECIPE_GRIND
# 8001, CMD_EXECUTE 8002); the FFE3 notification codes as NOTIFY_* (40502 …).

# NOTE: the machine-activity (cmd 8023) state codes live in ble_entities.py as
# ACTIVITY_BREWING/BREW_DONE (34/36) — the only place they're used.
# Confirmed live on 2026-07-12: 1=home/idle, 3=brewer, 65=auto, 4/5=scale settle,
# 29=session start, 30/34/35/16/36=brew-phase transitions. No "7" observed.


# ---------------------------------------------------------------------------
# CRC16-Kermit (confirmed against all 5 captured BLE frames)
# Polynomial: 0x8408 (reflected 0x1021), init=0x0000
# ---------------------------------------------------------------------------
def _crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


# ---------------------------------------------------------------------------
# Frame builder
# Format: 58 01 01 [code 2B LE] [total_len 4B LE] 01 [data N×4B LE] [CRC16 2B LE]
# total_len = 12 + len(data_bytes)   (min frame = 12 bytes with zero data ints)
# data may be N integers (each 4B LE) OR raw bytes (for the recipe blob).
# ---------------------------------------------------------------------------
def _build_frame(
    code: int,
    data_ints: list[int] | None = None,
    raw_bytes: bytes | None = None,
    *,
    frame_type: int = 1,
) -> bytes:
    """Build a complete BLE command frame for FFE1.

    Args:
        code: Command code (e.g. CMD_HANDSHAKE = 8100).
        data_ints: Optional list of integers; each encoded as 4-byte little-endian.
        raw_bytes: Optional raw byte payload (used for CMD_RECIPE_GRIND / theCode
                   and Type-2 packets like mode switch / slot write).
                   Mutually exclusive with data_ints.
        frame_type: 1 (default) for Type-1 packets — `58 01 01 …` header. Most
                    commands. 2 for Type-2 packets — `58 01 02 …` header. Used
                    for mode switch (cmd 11511) and slot writer (cmd 11510).

    Returns:
        Complete frame bytes including CRC16.
    """
    if raw_bytes is not None:
        data_body = raw_bytes
    elif data_ints:
        data_body = b"".join(struct.pack("<I", i & 0xFFFFFFFF) for i in data_ints)
    else:
        data_body = b""

    total_len = 12 + len(data_body)
    header = (
        bytes([0x58, 0x01, frame_type & 0xFF])
        + struct.pack("<H", code)
        + struct.pack("<I", total_len)
        + bytes([0x01])
    )
    payload = header + data_body
    crc = _crc16(payload)
    return payload + struct.pack("<H", crc)


# ---------------------------------------------------------------------------
# Constants in command 8100 (handshake/MTU). Originally we thought these
# were a derived "grind step" — they are not. The official Android app sends
# the literal pair [185, 1] on every brew regardless of grinder settings.
# Source: https://github.com/brAzzi64/xbloom-ble (PROTOCOL.md, MIT licensed)
# ---------------------------------------------------------------------------
HANDSHAKE_DATA = [185, 1]


# ---------------------------------------------------------------------------
# Local recipe encoder — produces the BLE recipe blob (theCode equivalent)
# WITHOUT calling the cloud tuGetRecipeCode endpoint.
#
# Ported from brAzzi64/xbloom-ble (MIT) — the trailing 2 bytes that we
# couldn't crack as a CRC are actually [grinder_size, ratio × 10] metadata.
# Sources of truth in that repo:
#   PROTOCOL.md   — wire format & per-pour byte layout
#   xbloom.py     — encode_recipe(), build_packet_type1*, cup-type ranges
# ---------------------------------------------------------------------------

# Pattern code: xBloom API `pattern` integer -> BLE wire byte. The mapping and
# its confirmation (app UI + live voice-box announcements) live in spec.py.
_API_PATTERN_TO_BLE = spec.PATTERN_API_TO_BYTE


def _vibration_code(before: bool, after: bool) -> int:
    """Encode the per-pour vibration flags into one byte.
    Bit 0 = vibrate before pour, bit 1 = vibrate after pour."""
    return (1 if before else 0) | (2 if after else 0)


# Cup-type weight range defaults (theMax, theMin floats) sent via command 8104.
# In the official app these come from the cloud tuGetRecipeCode response, but
# the values are tied to cup type only and the machine brews correctly with
# the defaults below. Values from brAzzi64/xbloom-ble HCI captures.
# Recipe API cupType:  1=xPod, 2=Omni dripper, 3=Other, 4=Tea
#
# NOT the same as spec.CUP_DOSE — these are the machine's cup weight-range
# BYTES for the 8104 frame, a different quantity that merely shares the cup-type
# key. Do not fold this into the spec's dose ranges.
_CUP_TYPE_RANGES: dict[int, tuple[float, float]] = {
    1: (200.0, 80.0),    # xPod (default; no HCI capture)
    2: (110.0, 90.0),    # Omni dripper (HCI confirmed)
    3: (200.0, 80.0),    # Other / Free Solo (HCI confirmed)
    4: (200.0, 80.0),    # Tea (default; no HCI capture)
}


def encode_recipe_blob(
    pours: list[dict],
    *,
    grinder_size: int = 0,
    dose_g: float = 0,
    rpm: int = 0,
) -> bytes:
    """Build the recipe blob the machine reads (the `theCode` payload).

    Args:
        pours: list of pour dicts using xBloom API field names:
                 volume_ml (float), temperature_c (float|int),
                 pause_s (int seconds AFTER this pour),
                 pattern (int 1-3 from API; 1=centered, 2=spiral, 3=circular),
                 flow_rate (float; e.g. 3.0, 3.5),
                 agitate_before (int; 1=ON, 2=OFF),
                 agitate_after  (int; 1=ON, 2=OFF).
        grinder_size: 0 = grinder OFF, 1-100 = grind size.
        dose_g: coffee dose in grams (used to compute the ratio tail byte).
        rpm: grinder RPM. Goes into byte[2] of the FIRST pour's timing block;
             other pours get 0.

    Returns:
        Raw bytes (length-prefixed payload + 2 trailing metadata bytes), ready
        to drop into a CMD_RECIPE_GRIND / CMD_RECIPE_NO_GRIND frame.
    """
    total_water = sum(p.get("volume_ml", 0) for p in pours)

    parts: list[int] = []
    for i, pour in enumerate(pours):
        volume = int(pour.get("volume_ml", 0))
        temp = int(pour.get("temperature_c", 93))
        api_pattern = int(pour.get("pattern", 1))
        pattern = _API_PATTERN_TO_BLE.get(api_pattern, 0)
        vib = _vibration_code(
            int(pour.get("agitate_before", 2)) == 1,
            int(pour.get("agitate_after", 2)) == 1,
        )
        flow_byte = int(round(float(pour.get("flow_rate", 3.0)) * 10)) & 0xFF
        post_wait = int(pour.get("pause_s", 0))

        # SubStep block: encode volume in ≤127 ml chunks (machine limit).
        if volume > 127:
            for _ in range(volume // 127):
                parts.extend([127, temp, pattern, vib])
            remainder = volume % 127
            if remainder:
                parts.extend([remainder, temp, pattern, vib])
        else:
            parts.extend([volume, temp, pattern, vib])

        # Timing block: [post_wait_neg, 0x00, rpm_or_0, flow_rate × 10]
        post_wait_neg = (-post_wait) & 0xFF
        rpm_byte = (int(rpm) & 0xFF) if i == 0 else 0
        parts.extend([post_wait_neg, 0, rpm_byte, flow_byte])

    data_bytes = bytes(parts)
    length_byte = len(data_bytes) & 0xFF
    # Trailing metadata: [grinder_size, grandWater × 10]. The official app's
    # GetRecipeCodeService writes grandWater × 10 here (grandWater = total pour
    # volume), NOT ratio × 10 — our earlier code used ratio, producing a wrong
    # last byte (0xA5 vs the app's 0x9A for "Omni 20g 5 pours"). This byte is
    # machine metadata, not the grind toggle (grind is the 8001/8004 command),
    # but it should match the app exactly.
    grinder_byte = int(grinder_size) & 0xFF
    water_byte = int(round(total_water * 10)) & 0xFF
    return bytes([length_byte]) + data_bytes + bytes([grinder_byte, water_byte])


# ---------------------------------------------------------------------------
# Additional commands beyond the EasyMode-only set above
# ---------------------------------------------------------------------------
CMD_BYPASS_DOSE     = 8102   # 0x1FA6 — bypass volume/temp + dose (3 ints)
CMD_SET_CUP         = 8104   # 0x1FA8 — cup weight range theMax/theMin (2 floats as int bits)
CMD_RECIPE_GRIND    = 8001   # 0x1F41 — recipe blob WHEN grinder is enabled
CMD_RECIPE_NO_GRIND = 8004   # 0x1F44 — recipe blob WHEN grinder is disabled
CMD_EXECUTE         = 8002   # 0x1F42 — start brew (no data)
CMD_HANDSHAKE       = 8100   # 0x1FA4 — initial handshake / MTU
CMD_BREWER_START    = 4506   # 0x11AA — standalone brewer start


def cup_type_range(cup_type: int) -> tuple[float, float]:
    """Return (theMax, theMin) defaults for a recipe's cupType integer."""
    return _CUP_TYPE_RANGES.get(int(cup_type), (200.0, 80.0))


def _float_to_int_bits(f: float) -> int:
    """Reinterpret float bits as unsigned int (Java Float.floatToIntBits equivalent)."""
    return struct.unpack("<I", struct.pack("<f", float(f)))[0]


def build_brewer_standalone_frame(
    flow_rate_mls: float,
    volume_ml: float,
    temp_c: float,
    water_feed: int,   # 0=tank, 1=tap
    pattern_code: int, # 0=centered, 1=circular, 2=spiral
) -> bytes:
    """Build the BLE frame for a standalone brewer command (CMD_BREWER_START / 4506).

    Args:
        flow_rate_mls: Flow rate in ml/s (e.g. 3.0). Encoded as float bits of (value × 10).
        volume_ml: Target brew volume in ml (e.g. 250.0). Encoded as float bits of (value × 10).
        temp_c: Brew temperature in °C (e.g. 93.0). Encoded as float bits of (value × 10).
        water_feed: Water source — 0 = tank, 1 = tap.
        pattern_code: Pour pattern — 0 = centered, 1 = circular, 2 = spiral.

    Returns:
        Complete BLE frame bytes (header + payload + CRC16) for FFE1.
    """
    params = [
        _float_to_int_bits(flow_rate_mls * 10),
        _float_to_int_bits(volume_ml * 10),
        _float_to_int_bits(temp_c * 10),
        int(water_feed),
        int(pattern_code),
    ]
    return _build_frame(CMD_BREWER_START, params)


# ---------------------------------------------------------------------------
# Build the brew packet sequence ENTIRELY LOCALLY — no cloud call needed.
# Frame order matches the official Android app's HCI capture (see
# brAzzi64/xbloom-ble PROTOCOL.md "Full Brew Sequence" section).
# ---------------------------------------------------------------------------
def build_brew_frames(recipe: dict) -> list[bytes]:
    """Return the ordered BLE frames to brew `recipe`. No cloud call needed.

    Required recipe keys (from xBloom API or share-link recipe):
        dose_g (float), grinder_size (float|int), rpm (int),
        cup_type (int 1-4), pours: [
            {volume_ml, temperature_c, pattern, flow_rate,
             pause_s, agitate_before, agitate_after}, ...
        ]

    Returns 6 frames in send order:
        1. Handshake (8100, [185, 1])
        2. Bypass + dose (8102, [0, 0, dose_g])
        3. Set cup range (8104, [theMax_bits, theMin_bits])
        4. Recipe blob (8001 if grinder enabled, 8004 if not)
        5. Execute brew (8002, no data)
    """
    dose_g = int(round(float(recipe.get("dose_g", 0))))
    grinder_size = int(float(recipe.get("grinder_size", 0)))
    grinder_enabled = int(recipe.get("grinder_size_enabled", 1))
    rpm = int(recipe.get("rpm", 0))
    cup_type = int(recipe.get("cup_type", 3))  # default 3 = "other"
    pours = recipe.get("pours", []) or []

    # Frame 1: handshake — constant [185, 1] regardless of recipe.
    f_handshake = _build_frame(CMD_HANDSHAKE, list(HANDSHAKE_DATA))

    # Frame 2: bypass + dose. Bypass disabled (0,0); dose communicated to machine.
    f_bypass = _build_frame(CMD_BYPASS_DOSE, [0, 0, dose_g])

    # Frame 3: cup weight range — defaults per cup type.
    cup_max, cup_min = cup_type_range(cup_type)
    cup_max_bits = struct.unpack("<I", struct.pack("<f", float(cup_max)))[0]
    cup_min_bits = struct.unpack("<I", struct.pack("<f", float(cup_min)))[0]
    f_cup = _build_frame(CMD_SET_CUP, [cup_max_bits, cup_min_bits])

    # Frame 4: recipe blob — built locally.
    use_grinder = grinder_enabled == 1 and grinder_size > 0
    blob = encode_recipe_blob(
        pours,
        grinder_size=grinder_size if use_grinder else 0,
        dose_g=dose_g,
        rpm=rpm if use_grinder else 0,
    )
    cmd_recipe = CMD_RECIPE_GRIND if use_grinder else CMD_RECIPE_NO_GRIND
    f_recipe = _build_frame(cmd_recipe, raw_bytes=blob)

    # Frame 5: execute.
    f_execute = _build_frame(CMD_EXECUTE)

    log.debug(
        "Brew frames built for '%s': dose=%dg grinder=%s rpm=%d cup_type=%d "
        "blob=%dB cmd=%d",
        recipe.get("name"), dose_g,
        f"{grinder_size}" if use_grinder else "OFF",
        rpm, cup_type, len(blob), cmd_recipe,
    )
    return [f_handshake, f_bypass, f_cup, f_recipe, f_execute]


# ---------------------------------------------------------------------------
# Simple-command codes (Type-1 packets, no parameters)
# Source: brAzzi64/xbloom-ble PROTOCOL.md (MIT)
# ---------------------------------------------------------------------------
CMD_TARE          = 8500   # 0x2134 — zero the scale
CMD_BACK_TO_HOME  = 8022   # 0x1F56 — return UI to home screen
CMD_BREW_PAUSE    = 40518  # 0x9E46 — pause an in-flight brew
CMD_BREW_RESUME   = 8021   # 0x1F55 — resume a paused brew (APP_BREWER_RESTART)


def packet_tare() -> bytes:
    """Build the BLE frame that zeroes the scale (cmd 8500, no data)."""
    return _build_frame(CMD_TARE)


def packet_back_to_home() -> bytes:
    """Build the BLE frame that returns the machine UI to home (cmd 8022)."""
    return _build_frame(CMD_BACK_TO_HOME)


def packet_brew_pause() -> bytes:
    """Build the BLE frame that pauses an in-flight brew (cmd 40518)."""
    return _build_frame(CMD_BREW_PAUSE)


def packet_brew_resume() -> bytes:
    """Build the BLE frame that resumes a paused brew (cmd 8021)."""
    return _build_frame(CMD_BREW_RESUME)


# ---------------------------------------------------------------------------
# 08-02: Standalone grinder + mode / water source / unit commands
# Source: brAzzi64/xbloom-ble (MIT)
# ---------------------------------------------------------------------------
CMD_GRINDER_ENTER = 8006   # 0x1F46 — enter grinder UI with [size, speed]
CMD_GRINDER_START = 3500   # 0x0DAC — start grind  with [duration_ms, size, speed]
CMD_GRINDER_STOP  = 3505   # 0x0DB1 — stop grind (no data)

CMD_MODE_TYPE     = 11511  # 0x2CF7 — mode switch (Type-2 packet, 4-byte hex payload)
CMD_WATER_SOURCE  = 4508   # 0x119C — water source: 0=tank, 1=tap
CMD_UNIT_WEIGHT   = 8005   # 0x1F45 — display weight unit: 0=g, 1=oz, 2=ml
CMD_UNIT_TEMP     = 8010   # 0x1F4A — display temperature unit: 0=°C, 1=°F

# Mode type-2 payloads (4 bytes each, sent as raw_bytes)
MODE_PRO_HEX  = "00000000"
MODE_EASY_HEX = "91327856"


def packets_grind(
    size: int, speed: int, duration_ms: int = 1000,
) -> tuple[bytes, bytes, bytes]:
    """Return the 3-frame standalone grinder sequence: (enter, start, stop).

    The CALLER controls actual grind length by sleeping `seconds` between
    writing `start` and writing `stop`. `duration_ms` is a fallback the
    machine uses if the stop frame is lost; brAzzi64's CLI hardcodes 1000.

    Args:
        size: 1-100 (lower = finer)
        speed: 60-120 (grinder RPM)
        duration_ms: fallback timeout in milliseconds
    """
    enter = _build_frame(CMD_GRINDER_ENTER, [int(size), int(speed)])
    start = _build_frame(
        CMD_GRINDER_START, [int(duration_ms), int(size), int(speed)],
    )
    stop = _build_frame(CMD_GRINDER_STOP)
    return enter, start, stop


def packet_mode(mode: str) -> bytes:
    """Build the mode-switch frame (Type-2 packet, cmd 11511).

    Args:
        mode: 'auto' (Easy mode) or 'pro' (Pro mode)
    """
    payload = MODE_EASY_HEX if mode.lower() == "auto" else MODE_PRO_HEX
    return _build_frame(
        CMD_MODE_TYPE, raw_bytes=bytes.fromhex(payload), frame_type=2,
    )


def packet_water_source(source: str) -> bytes:
    """Build the water-source frame (cmd 4508).

    Args:
        source: 'tank' (0) or 'tap' (1)
    """
    code = spec.WATER_SOURCE_CODES.get(source.lower(), spec.WATER_SOURCE_CODES["tap"])
    return _build_frame(CMD_WATER_SOURCE, [code])


def packet_temp_unit(unit: str) -> bytes:
    """Build the display-temperature-unit frame (cmd 8010).

    Args:
        unit: 'C' (0) or 'F' (1)
    """
    return _build_frame(CMD_UNIT_TEMP, [spec.TEMP_UNIT_CODES.get(unit.upper(), 1)])


def packet_weight_unit(unit: str) -> bytes:
    """Build the display-weight-unit frame (cmd 8005).

    Args:
        unit: 'g' (0), 'oz' (1), or 'ml' (2)
    """
    return _build_frame(CMD_UNIT_WEIGHT, [spec.WEIGHT_UNIT_CODES[unit.lower()]])


# ---------------------------------------------------------------------------
# 08-03: Easy Mode slot writer (Type-2 packet, cmd 11510)
#
# Writes a recipe to one of the three on-device slots A/B/C. After this, the
# user can trigger that brew from the machine's physical UI alone, no HA
# needed. Source: brAzzi64/xbloom-ble PROTOCOL.md (MIT).
# ---------------------------------------------------------------------------
CMD_SLOT_RECIPE_SEND = 11510   # 0x2CF6 — write recipe to slot (Type-2)

SLOT_INDEX = {"A": 0, "B": 1, "C": 2}


def slot_flags(scale_on: bool, grinder_on: bool) -> int:
    """Encode the slot-write flag byte.

    Bit 4 (0x10) = scale ON.
    Lower nibble: 0x02 = grinder ON, 0x04 = grinder OFF.
    """
    flags = 0x10 if scale_on else 0x00
    flags |= 0x02 if grinder_on else 0x04
    return flags


def packet_slot_write(
    slot_index: int, recipe: dict, *, scale_on: bool = True,
) -> bytes:
    """Build a slot-write Type-2 frame (cmd 11510).

    Payload layout: ``[slot_index 1B][flags 1B][recipe_blob N B]`` where the
    recipe blob is the same bytes ``encode_recipe_blob`` produces for the
    in-flight brew flow. Slot writes don't trigger a brew — they install the
    recipe on the machine for the user to trigger from the physical UI later.

    Args:
        slot_index: 0=A, 1=B, 2=C
        recipe: parsed Recipe dict (same shape ``build_brew_frames`` consumes)
        scale_on: whether the slot should activate the scale at brew time
    """
    grinder_size = int(float(recipe.get("grinder_size", 0)))
    grinder_enabled = int(recipe.get("grinder_size_enabled", 1)) == 1
    use_grinder = grinder_enabled and grinder_size > 0

    blob = encode_recipe_blob(
        recipe.get("pours", []) or [],
        grinder_size=grinder_size if use_grinder else 0,
        dose_g=float(recipe.get("dose_g", 0)),
        rpm=int(recipe.get("rpm", 0)) if use_grinder else 0,
    )
    flags = slot_flags(scale_on, use_grinder)
    payload = bytes([slot_index & 0xFF, flags & 0xFF]) + blob
    return _build_frame(CMD_SLOT_RECIPE_SEND, raw_bytes=payload, frame_type=2)


# ---------------------------------------------------------------------------
# Notification command codes we surface to callers via on_event
# (subset — see brAzzi64/xbloom-ble PROTOCOL.md for the full set)
# ---------------------------------------------------------------------------
NOTIFY_MACHINE_ACTIVITY = 8023
NOTIFY_WEIGHT_2         = 20501
NOTIFY_WEIGHT_ALT       = 10507
NOTIFY_WATER_VOLUME     = 40523
NOTIFY_BLOOM            = 40510
NOTIFY_ENJOY            = 40512
NOTIFY_MACHINE_INFO     = 40521  # RD_MachineInfo — periodic status heartbeat

# Decoded live during 08-05 capture sessions on firmware V12.0D.500.
# All four payloads are LE uint32 in the first 4 bytes.
NOTIFY_GRIND_SIZE       = 8105   # 0x1FA9 — grinder size knob change
NOTIFY_GRIND_SPEED      = 8106   # 0x1FAA — grinder RPM knob change
NOTIFY_BREW_PATTERN     = 8107   # 0x1FAB — pour pattern knob change
NOTIFY_BREW_TEMP        = 8108   # 0x1FAC — pour temperature knob change
NOTIFY_BREW_RATIO       = 8109   # 0x1FAD — brew ratio central knob (LE float, 15.0 = 1:15)

# Recipe-card scan. Payload is the ASCII pod id (e.g. "SAU012"). Confirmed on
# the xbloom-voice-box ESP firmware, which announces "recipe card scanned".
NOTIFY_PODS             = 40501  # recipe card / xPod scanned; payload = ASCII pod id

NOTIFY_TARE             = 9007   # scale tared via the tare button (no payload).
                                 # Confirmed live: one 9007 per press, each
                                 # followed by 8023 activity=4 → 5 (re-zero/settle).
                                 # Sibling cradle events: 9002 = cup on, 9008 = cup off.

# Pattern-byte mapping. The machine reports the pour pattern on cmd 8107 as a
# raw 0/1/2 code; the byte -> name order (centered/circular/spiral) lives in
# spec.py, confirmed live via the voice-box announcements.
PATTERN_NAMES = spec.PATTERN_BYTE_TO_NAME


def parse_ffe3_packet(data: bytes) -> dict | None:
    """Parse a raw 5802 notification frame.

    Returns dict with keys: code (int), data_bytes (bytes), data_float (float | None).
    Returns None if the packet is malformed or too short. Same format works for
    both FFE2 and FFE3 — they both emit `58 02 …` notifications.
    """
    if len(data) < 10:
        return None
    if data[0] != 0x58 or data[1] != 0x02:
        return None  # not a standard 5802 frame (may be idle heartbeat)

    code = struct.unpack_from("<H", data, 3)[0]
    # Frame: 58 02 07 [cmd 2] [len 4] [status 1] [payload N] [crc 2]
    # Payload starts at byte 10 (the status byte at index 9 is NOT data).
    # Our prior decoder sliced [9:-2] which included the status byte and made
    # every multi-byte field one byte too low — pour_index decoded as 193
    # (= status byte 0xC1) instead of the real 0/1/2.
    data_bytes = data[10:-2] if len(data) > 12 else b""

    data_float: float | None = None
    if len(data_bytes) >= 4:
        data_float = struct.unpack_from("<f", data_bytes, 0)[0]

    return {"code": code, "data_bytes": data_bytes, "data_float": data_float}


def decode_notification(data: bytes) -> dict | None:
    """Higher-level decode: returns a flat dict ready for entity consumption.

    Output schema: ``{"cmd": int, ...}`` plus optional, cmd-specific fields:
      * weight_g  (float)  — for weight/scale notifications
      * water_ml  (float)  — for water-volume notifications
      * activity  (int)    — for machine-activity (cmd 8023)
      * pour_index (int)   — for RD_BLOOM
    Returns None for non-5802 frames.
    """
    pkt = parse_ffe3_packet(data)
    if pkt is None:
        return None
    cmd = pkt["code"]
    payload = pkt["data_bytes"]
    out: dict = {"cmd": cmd}

    if cmd in (NOTIFY_WEIGHT_2, NOTIFY_WEIGHT_ALT) and len(payload) >= 4:
        out["weight_g"] = round(struct.unpack_from("<f", payload, 0)[0], 2)
    elif cmd == NOTIFY_WATER_VOLUME and len(payload) >= 4:
        out["water_ml"] = round(struct.unpack_from("<f", payload, 0)[0], 1)
    elif cmd == NOTIFY_MACHINE_ACTIVITY and len(payload) >= 4:
        out["activity"] = struct.unpack_from("<I", payload, 0)[0]
    elif cmd == NOTIFY_BLOOM and len(payload) >= 4:
        out["pour_index"] = struct.unpack_from("<I", payload, 0)[0]
    # 08-05 — knob change notifications. All four are LE uint32.
    elif cmd == NOTIFY_GRIND_SIZE and len(payload) >= 4:
        out["grind_size"] = struct.unpack_from("<I", payload, 0)[0]
    elif cmd == NOTIFY_GRIND_SPEED and len(payload) >= 4:
        out["grind_speed"] = struct.unpack_from("<I", payload, 0)[0]
    elif cmd == NOTIFY_BREW_PATTERN and len(payload) >= 4:
        v = struct.unpack_from("<I", payload, 0)[0]
        out["pattern"] = v
        out["pattern_name"] = PATTERN_NAMES.get(v, f"pattern_{v}")
    elif cmd == NOTIFY_BREW_TEMP and len(payload) >= 4:
        out["temperature_c"] = struct.unpack_from("<I", payload, 0)[0]
    elif cmd == NOTIFY_BREW_RATIO and len(payload) >= 4:
        # Central knob — brew ratio as an LE IEEE-754 float (e.g. 15.0 = 1:15).
        out["brew_ratio"] = round(struct.unpack_from("<f", payload, 0)[0], 1)
    elif cmd == NOTIFY_PODS and len(payload) >= 1:
        # Recipe card scanned — payload is a null-padded ASCII pod id.
        out["pod_id"] = payload.split(b"\x00")[0].decode("ascii", "ignore").strip()
    elif cmd == NOTIFY_MACHINE_INFO and len(payload) >= 35:
        # Periodic status heartbeat. Field offsets match the Android
        # MachineInfoBleModel parse (cross-confirmed by brAzzi64/xbloom-ble):
        #   byte 33 = waterEnough (0 = low/needs water, 1 = ok)
        #   byte 34 = systemStatus (0/4 = idle/standby; other values undecoded)
        #   byte 37 = grinder size (raw - 30, min 1)
        #   byte 39 = voltage
        out["water_enough"] = payload[33]
        out["system_status"] = payload[34]
        if len(payload) >= 40:
            out["grind_size_current"] = max(payload[37] - 30, 1)
            out["voltage"] = payload[39]

    return out


# ---------------------------------------------------------------------------
# BLE client
# ---------------------------------------------------------------------------
class XBloomBleClient:
    """Async BLE client for the xBloom Studio.

    Connects to the machine by BLE name, sends the EasyMode brew sequence,
    and notifies the caller when each pour starts and when the brew is done.

    Args:
        bluetooth_name: Advertised BLE name, e.g. "XBLOOM ABC123".
        timeout: BLE scan / connect timeout in seconds.
        on_pour: Optional async callback(pour_index: int) fired on each pour.
        on_enjoy: Optional async callback() fired when brew is fully complete.
    """

    def __init__(
        self,
        device_or_name,
        *,
        timeout: float = 15.0,
        on_event: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        """Connect-on-demand BLE client.

        Args:
            device_or_name: Either a bleak `BLEDevice` (preferred — get one
                from HA's `bluetooth.async_ble_device_from_address` /
                `async_discovered_service_info`) or a string BLE advertiser
                name (we'll fall back to a `BleakScanner.find_device_by_name`
                scan, which is less reliable when other Bluetooth consumers
                are active).
            timeout: BLE scan / connect timeout in seconds.
            on_event: Optional async callback invoked for every decoded
                notification arriving on FFE2. The argument is the dict
                returned by `decode_notification` — at minimum
                `{"cmd": int, ...}`. Callback runs on the asyncio event loop.
        """
        import asyncio

        # Detect whether we got a BLEDevice or a name string.
        if isinstance(device_or_name, str):
            self._name = device_or_name
            self._device = None
        else:
            self._device = device_or_name
            self._name = getattr(device_or_name, "name", None) or "<BLEDevice>"
        self._timeout = timeout
        self._on_event = on_event
        self._client = None  # bleak.BleakClient set on connect
        self._enjoy = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "XBloomBleClient":
        await self._connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()

    async def _connect(self) -> None:
        import asyncio

        self._loop = asyncio.get_running_loop()

        # Resolve a BLEDevice if we only have a name. Prefer the device
        # passed in by the caller — it carries the right transport (local
        # adapter vs. proxy) info and avoids racing other BLE consumers.
        device = self._device
        if device is None:
            from bleak import BleakScanner
            log.debug("Scanning for BLE device '%s'", self._name)
            device = await BleakScanner.find_device_by_name(self._name, timeout=self._timeout)
            if device is None:
                raise RuntimeError(
                    f"xBloom machine '{self._name}' not found via BLE scan"
                )

        # Use bleak_retry_connector to clean up stale connections and retry
        # transparently — the bare BleakClient was getting "Notify acquired"
        # and connect timeouts when other HA components touched the same MAC.
        # use_services_cache=False forces a fresh GATT discovery every brew,
        # avoiding the failure mode where a "cached" connection succeeds in
        # 12ms but writes silently drop because the underlying transport is dead.
        try:
            from bleak_retry_connector import establish_connection
            self._client = await establish_connection(
                client_class=__import__("bleak").BleakClient,
                device=device,
                name=self._name,
                max_attempts=3,
                use_services_cache=False,
            )
        except ImportError:
            # bleak_retry_connector is bundled with HA, but allow a plain
            # BleakClient fallback so this module is testable outside HA.
            from bleak import BleakClient
            self._client = BleakClient(device)
            await self._client.connect()

        if not self._client.is_connected:
            raise RuntimeError(f"BLE connect to {self._name} returned but is_connected=False")
        log.debug("BLE connected to %s (verified)", self._name)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
            log.debug("BLE disconnected from %s", self._name)
        self._client = None

    @property
    def is_connected(self) -> bool:
        """True while the underlying BLE link is actually up. Bleak flips its
        own is_connected the moment the machine drops (power-off, out of
        range), so holders can poll this to detect link loss."""
        return bool(self._client is not None and self._client.is_connected)

    def _on_notify(self, _characteristic: object, data: bytes) -> None:
        """Synchronous BLE notification handler — dispatched by bleak."""
        decoded = decode_notification(bytes(data))
        if decoded is None:
            return
        cmd = decoded["cmd"]
        log.debug("BLE notify cmd=%d (%s)", cmd, decoded)

        # Fire the user's callback (schedule onto the connect-time loop so
        # we work even if bleak invokes us from a different thread).
        if self._on_event and self._loop is not None:
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(self._on_event(decoded), self._loop)
            except Exception:  # noqa: BLE001
                log.exception("on_event callback failed for cmd=%s", cmd)

        # Mark brew completion so wait_for_completion() can return.
        if cmd == NOTIFY_ENJOY:
            log.info("xBloom brew complete (RD_ENJOY)")
            self._enjoy.set()

    async def brew(self, recipe: dict) -> None:
        """Send the 6-frame brew sequence to FFE1 (handshake, back-to-home,
        bypass+dose, set-cup, recipe, execute).

        Subscribes to FFE2 + FFE3 notifications first, so any decoded events
        arriving before the brew finishes are delivered to `on_event`. Returns
        immediately after the frames are written — call `wait_for_completion`
        to block until `RD_ENJOY` arrives.
        """
        import asyncio

        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected — call connect() or use async context manager")

        self._enjoy.clear()
        self._loop = asyncio.get_running_loop()

        # All notifications (scale, water, machine info, brew progress events)
        # arrive on FFE2. Subscribing is BEST-EFFORT: if BlueZ refuses (we
        # frequently see `[org.bluez.Error.NotPermitted] Notify acquired`
        # when other Bluetooth consumers on the host hold the same notify
        # handle), we log a warning and continue. The brew frames (sent on
        # FFE1) work regardless — the machine brews autonomously once it
        # receives them. We just won't get live entity updates this run.
        self._notify_active = False
        try:
            await self._client.start_notify(FFE2_UUID, self._on_notify)
            self._notify_active = True
            log.debug("FFE2 notifications enabled")
        except Exception as err:  # noqa: BLE001
            log.warning(
                "FFE2 start_notify failed (%s) — proceeding without live "
                "status updates; brew dispatch is not affected", err
            )

        # Brief settle before the first write, mirroring the Live Mode
        # listener: yield to the loop so bleak's notification reader spins up,
        # then a short sleep so the machine acknowledges the handshake (the
        # audible connect tone) instead of the reader missing the first
        # response burst. This is a one-off pre-handshake pause, not per-frame
        # pacing — it does not slow the brew sequence itself.
        for _ in range(5):
            await asyncio.sleep(0)
        await asyncio.sleep(0.3)

        # Build and send the 5-frame brew sequence to FFE1. The machine's
        # FFE1 characteristic only supports Write Without Response — using
        # response=True triggers ATT error 0x0e ("Unlikely Error"). A small
        # inter-frame delay matches the official Android app's pacing and
        # gives the machine time to process each command before the next.
        # We verify is_connected after the burst so silent drops surface.
        import asyncio
        frames = build_brew_frames(recipe)
        # Force EASY (Auto) mode before the recipe. THE grind fix: the J15
        # recipe brew (8001) only GRINDS when the machine is in EASY mode; in
        # PRO mode it accepts the recipe and pours WITHOUT grinding. The
        # official app guarantees EASY mode via its machine-settings toggle
        # (BleCodeFactory.easyModeSwitch → cmd RD_EASYMODE_TYPE 11511, payload
        # "91327856"), which our packet_mode("auto") reproduces byte-for-byte —
        # but the app never re-sends it per brew, relying on the machine already
        # being EASY. HA has no such guarantee, so we send the switch on every
        # brew (idempotent if already EASY). Root cause of the 2026-07-16
        # grind-skip: the machine was sitting in PRO mode, and a VoiceOver user
        # can't see the mode indicator to catch it.
        #
        # No Back-to-Home (8022): it was our June addition; live testing on
        # 2026-07-16 showed it did not help, and the official app's brew is just
        # the handshake + these frames, so we match it.
        frames.insert(1, packet_mode("auto"))
        sends = [
            ("handshake", 0.5),
            ("easy_mode", 1.0),   # let the mode change register before the recipe
            ("bypass+dose", 0.5),
            ("set_cup", 0.5),
            ("recipe", 0.5),
            ("execute", 0.5),
        ]
        for (name, delay), frame in zip(sends, frames):
            log.info("BLE write '%s' (%d bytes): %s", name, len(frame), frame.hex())
            await self._client.write_gatt_char(FFE1_UUID, frame, response=False)
            await asyncio.sleep(delay)

        if not self._client.is_connected:
            raise RuntimeError(
                "BLE link dropped during brew-frame burst — frames may not "
                "have been transmitted"
            )
        log.info(
            "xBloom brew sequence sent for recipe '%s' (%d pours, link still up)",
            recipe.get("name"), recipe.get("pour_count", "?"),
        )

    async def wait_for_completion(self, timeout: float = 600.0) -> bool:
        """Block until `RD_ENJOY` arrives or `timeout` seconds elapse.

        Returns True if the brew completed (enjoy fired), False on timeout
        OR if notifications never started (we have no way to know when the
        brew actually ends, so we just hold the connection briefly to let
        the frames take effect, then return).
        """
        import asyncio

        if not getattr(self, "_notify_active", False):
            # Without notifications, we can't observe RD_ENJOY. Hold the link
            # for a short moment so the writes settle, then let the caller
            # disconnect. The machine continues the brew autonomously.
            await asyncio.sleep(2)
            return False

        try:
            await asyncio.wait_for(self._enjoy.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            log.warning("brew did not complete within %ds — disconnecting anyway", timeout)
            return False
