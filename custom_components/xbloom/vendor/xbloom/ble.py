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


def _f32(value: float) -> float:
    """Round a Python (float64) value to IEEE-754 single precision.

    The machine's firmware does its recipe-consistency arithmetic in float32,
    so we must emulate that exact precision to predict what it will accept.
    """
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _gate_consistent_volumes(
    src_vols: list[float], dose_i: int
) -> tuple[list[int], int]:
    """Quantise pour volumes so the recipe blob PASSES the firmware's gate.

    The machine only commits a recipe — including its grind-size target — when
    the blob is internally consistent in the firmware's own float32 math
    (recipe handler ~fw:2195-2214):

        trunc( (ratio_byte / 10) * dose ) == Σ(wire pour volumes)

    If it fails, the machine keeps its PREVIOUS grind target and brews the new
    pours at the STALE grind size (the grind-size bug). The cloud/app always
    send self-consistent blobs; so must we.

    Returns ``(integer wire volumes, ratio_byte)``. With dose/volumes unknown
    it falls back to plain rounding and a 0 ratio byte.
    """
    total_water = sum(src_vols)
    if dose_i <= 0 or total_water <= 0 or not src_vols:
        return [int(round(v)) for v in src_vols], 0

    # 1) Pick a ratio byte whose float32 product is an UNAMBIGUOUS integer
    #    (floor == round-half-up → identical whether the firmware truncates or
    #    rounds), and take that integer as the target wire-volume total. Search
    #    outward from the ideal ratio×10 so the water shift stays sub-ml.
    r0 = int(round((total_water / dose_i) * 10))
    chosen_r, target_total = None, None
    for r in (r0, r0 + 1, r0 - 1, r0 + 2, r0 - 2):
        if r <= 0 or r > 0xFF:
            continue
        prod = _f32(_f32(_f32(r) / _f32(10.0)) * _f32(dose_i))
        if int(prod) == int(prod + 0.5):          # floor == round-half-up
            chosen_r, target_total = r, int(prod)
            break
    if target_total is None:                       # fall back to firmware trunc
        chosen_r = max(1, min(0xFF, r0))
        target_total = int(_f32(_f32(_f32(chosen_r) / _f32(10.0)) * _f32(dose_i)))

    # 2) Apportion that integer total across the pours by largest remainder,
    #    so each pour keeps its share (brew shape) and the wire volumes sum to
    #    EXACTLY the gate's target.
    ideal = [v * target_total / total_water for v in src_vols]
    int_vols = [int(x) for x in ideal]             # floor (all non-negative)
    deficit = target_total - sum(int_vols)
    if deficit > 0:
        order = sorted(
            range(len(ideal)), key=lambda i: ideal[i] - int_vols[i], reverse=True
        )
        for i in order[:deficit]:
            int_vols[i] += 1
    return int_vols, chosen_r & 0xFF




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
        grinder_size: 0 = grinder OFF, 1-80 = grind size (firmware requires
                      size+30 < 111, i.e. size ≤ 80; clamped below).
        dose_g: coffee dose in grams — REQUIRED to compute the ratio tail byte.
        rpm: grinder RPM. Goes into byte[2] of the FIRST pour's timing block;
             other pours get 0.

    Returns:
        Raw bytes (length-prefixed payload + 2 trailing metadata bytes), ready
        to drop into a CMD_RECIPE_GRIND / CMD_RECIPE_NO_GRIND frame.
    """
    # Quantise the pour volumes so the finished blob passes the firmware's
    # float32 recipe-consistency gate (see _gate_consistent_volumes). The dose
    # here MUST match the value sent in the 8102 frame — build_brew_frames sends
    # int(round(dose_g)) — so we round identically. This replaces the old
    # per-pour int() truncation, which desynced Σ(volumes) from the ratio byte
    # and made the machine silently reject the recipe (keeping the stale grind).
    dose_i = int(round(float(dose_g))) if dose_g else 0
    src_vols = [max(0.0, float(p.get("volume_ml", 0) or 0)) for p in pours]
    int_vols, ratio_x10 = _gate_consistent_volumes(src_vols, dose_i)

    parts: list[int] = []
    for i, pour in enumerate(pours):
        volume = int_vols[i] if i < len(int_vols) else 0
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
    # Trailing metadata: [grinder_size, ratio_byte]. The ratio byte is chosen by
    # _gate_consistent_volumes so that trunc((ratio_byte/10) * dose) == Σ(wire
    # volumes) in the firmware's float32 math — the condition the machine gates
    # the grind-size commit on. No 8006 pre-position frame is used (or wanted:
    # it corrupts machine state, fw:2637-2646); repositioning is EXECUTE's job
    # once the recipe commits.
    grinder_byte = min(int(grinder_size), 80) & 0xFF   # fw requires size ≤ 80
    return bytes([length_byte]) + data_bytes + bytes([grinder_byte, ratio_x10 & 0xFF])


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
    """Return (theMax, theMin) cup weight-range defaults for a cupType integer."""
    return spec.CUP_WEIGHT_RANGE.get(int(cup_type), spec.CUP_WEIGHT_RANGE_DEFAULT)


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
CMD_BACK_TO_HOME  = 8022   # 0x1F56 — home, but ONLY from home/standby: the fw
                           #   handler is state-gated and SILENTLY REJECTS 8022
                           #   from a live module screen (fw:1847-1867). To leave
                           #   a module, use the QUIT commands below.
CMD_QUIT_GRINDER  = 8012   # 0x1F4C — leave grinder screen → home (app back-press)
CMD_QUIT_BREWER   = 8013   # 0x1F4D — leave brewer screen → home
CMD_QUIT_SCALE    = 8014   # 0x1F4E — leave scale screen → home
# Full-process (recipe/auto) brew controls — confirmed from the Android app's
# AppJ15AutoManager (pause/restart/stop), which drives exactly the kind of brew
# start_brew runs. These are DISTINCT from the standalone-brewer controls
# (APP_BREWER_PAUSE 8019 / APP_BREWER_RESTART 8021 / APP_BREWER_STOP 4507),
# which apply to manual water pours, not a recipe. Pausing our recipe brew with
# 40518 but resuming/stopping with the standalone codes was a mismatch.
CMD_BREW_PAUSE    = 40518  # 0x9E46 — 全流程冲泡暂停 (full-process brew pause)
CMD_BREW_RESUME   = 40524  # 0x9E4C — 暂停之后开始 (resume after pause)
CMD_BREW_STOP     = 40519  # 0x9E47 — 全流程冲泡停止 (full-process brew stop)


def packet_tare() -> bytes:
    """Build the BLE frame that zeroes the scale (cmd 8500, no data)."""
    return _build_frame(CMD_TARE)


def packet_back_to_home() -> bytes:
    """Build the BLE frame that returns the machine UI to home (cmd 8022).

    NOTE: 8022 is only accepted from home/standby — the firmware rejects it from
    a live module screen. Use packet_quit_{grinder,brewer,scale}() to leave a
    module. Callers that don't know the current screen should prefer the quit
    matching sensor.xbloom_studio_current_module (see handle_back_to_home).
    """
    return _build_frame(CMD_BACK_TO_HOME)


def packet_quit_grinder() -> bytes:
    """Leave the grinder screen → home (cmd 8012, the app's grinder back-press).
    Unlike 8022 this IS accepted while on a module screen (fw:1769-1783)."""
    return _build_frame(CMD_QUIT_GRINDER)


def packet_quit_brewer() -> bytes:
    """Leave the brewer screen → home (cmd 8013, the app's brewer back-press)."""
    return _build_frame(CMD_QUIT_BREWER)


def packet_quit_scale() -> bytes:
    """Leave the scale screen → home (cmd 8014, the app's scale back-press)."""
    return _build_frame(CMD_QUIT_SCALE)


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



def packets_grind(
    size: int, speed: int, duration_ms: int = spec.GRIND_START_DURATION_MS,
) -> tuple[bytes, bytes, bytes]:
    """Return the 3-frame standalone grinder sequence: (enter, start, stop).

    Matches the official app's GrinderActivity: enter (8006) with [size, speed],
    start (3500) with [duration_ms, size, speed], stop (3505). The CALLER
    controls actual grind length by sleeping between writing `start` and `stop`;
    the grinder otherwise runs until its single-dose chamber is empty.
    `duration_ms` is the app's fixed 1000 (spec.GRIND_START_DURATION_MS), not a
    computed value.

    Args:
        size: grind size (lower = finer) — see spec.field("grind_size")
        speed: grinder RPM — see spec.field("grinder_speed_rpm")
        duration_ms: grind-start param 0 (default = the app's constant)
    """
    enter = _build_frame(CMD_GRINDER_ENTER, [int(size), int(speed)])
    start = _build_frame(
        CMD_GRINDER_START, [int(duration_ms), int(size), int(speed)],
    )
    stop = _build_frame(CMD_GRINDER_STOP)
    return enter, start, stop


def packet_grinder_set(size: int, speed: int) -> bytes:
    """Frame that sets the grinder's digital size/speed values (cmd 8006).

    This is the "enter grind page" frame from `packets_grind`, on its own — the
    same one the app fires on every grind-page knob change. The grind knobs are
    infinite digital encoders (the value is a screen number, set now; the gear
    only moves at grind time), so this just updates those values — no motor
    movement, no grinding. Used for live slider → machine sync (no start/stop).
    """
    return _build_frame(CMD_GRINDER_ENTER, [int(size), int(speed)])


# ---------------------------------------------------------------------------
# Module-ENTER (navigation) commands — route the machine's screen to a module,
# exactly like tapping Grinder/Brewer/Scale on the app's home screen
# (HomeActivity operator1/2/3). These NAVIGATE only — none of them grind
# (3500), brew (4506) or heat; they're safe to send for routing.
#   Grinder → 8006 APP_GRINDER_IN "进入磨豆页面"  [size, speed]
#   Brewer  → 8007 RD_BREWER_IN   "进入浇水页面"  [pattern, floatBits(temp×10)]
#   Scale   → 8003                "电子秤功能进入指令" (no data)
# (The LIVE per-knob SETTERS on the brewer screen are different codes — 4510
# temp / 8016 pattern — handled by the separate drive path, not here.)
# ---------------------------------------------------------------------------
CMD_BREWER_ENTER = 8007   # 0x1F47 — enter brew page + [pattern, temp×10]
CMD_SCALE_ENTER  = 8003   # 0x1F43 — enter scale page (no data)


def packet_brewer_set(pattern_byte: int, temp_c: float) -> bytes:
    """Frame that ENTERS the brew page carrying an initial pour pattern +
    temperature (cmd 8007), matching the app's home-screen Brewer button and
    `doBrewer`:
        CodeModule(RD_BREWER_IN, patternMachine, floatToIntBits(temp × 10))

    This is the brewer NAVIGATION command (routes the machine to the brewer
    screen). `pattern_byte` is the machine's 0/1/2 code (spec.PATTERN_*_TO_BYTE);
    `temp_c` is the WIRE °C (RT=20 / BP=98 / literal — use
    spec.brew_temp_display_to_wire on a display value first), encoded as float
    bits of (°C × 10).
    """
    return _build_frame(
        CMD_BREWER_ENTER, [int(pattern_byte), _float_to_int_bits(temp_c * 10)],
    )


def packet_scale_enter() -> bytes:
    """Frame that routes the machine to the scale screen (cmd 8003, no data)."""
    return _build_frame(CMD_SCALE_ENTER)


# ---------------------------------------------------------------------------
# LIVE brewer-screen setters — the per-knob commands the app's BrewerActivity
# fires on a slider drag. Distinct from 8007 (enter brewer page): these set ONE
# value each, independently, and are what the HA live sliders should drive.
#   Temp    → 4510 APP_BREWER_SET_TEMPERATURE  [int(round(°C × 10))]  (plain int!)
#   Pattern → 8016 APP_BREWER_SET_PATTERN      [patternByte]
# (Confirmed from BrewerActivity.checkAndSetTemperature / checkAndSetSpiral.)
# ---------------------------------------------------------------------------
CMD_BREWER_SET_TEMP    = 4510   # 0x119E — live temperature set (temp only)
CMD_BREWER_SET_PATTERN = 8016   # 0x1F50 — live pour-pattern set (pattern only)


def packet_brewer_temp(temp_c: float) -> bytes:
    """Live brewer temperature set (cmd 4510) — the brewer-screen temp slider.

    Temp-only; payload is a single PLAIN int = round(WIRE °C × 10) (NOT float
    bits, NOT bundled with pattern). ``temp_c`` is the WIRE value (RT=20 /
    BP=98 / literal — run spec.brew_temp_display_to_wire on a display value
    first).
    """
    return _build_frame(CMD_BREWER_SET_TEMP, [int(round(temp_c * 10))])


def packet_brewer_pattern(pattern_byte: int) -> bytes:
    """Live brewer pour-pattern set (cmd 8016), pattern-only. ``pattern_byte``
    is the machine's 0/1/2 code (spec.PATTERN_*_TO_BYTE)."""
    return _build_frame(CMD_BREWER_SET_PATTERN, [int(pattern_byte)])


def packet_mode(mode: str) -> bytes:
    """Build the mode-switch frame (Type-2 packet, cmd 11511).

    Args:
        mode: 'auto' (Easy mode) or 'pro' (Pro mode)
    """
    payload = spec.MODE_PAYLOADS.get(mode.lower(), spec.MODE_PAYLOADS["pro"])
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

# Machine sleep state — used by the send-and-confirm layer's retry decision,
# mirroring the app's AppDeviceManager.isSleeping() gate.
NOTIFY_SLEEPING         = 8009   # RD_MachineSleeping — machine dozed off
NOTIFY_AWAKE            = 8011   # RD_MachineNotSleeping — machine woke


# ---------------------------------------------------------------------------
# Send-and-confirm (ACK-gating) — mirrors the official app's AppBleManager.
#
# The machine echoes every command code it receives back on FFE2
# (`58 02 07 <same code> …`); the app pushes each sent code onto a `codeList`,
# starts a 1500 ms timer, and sends the next frame only once a notification
# echoing that code arrives — re-sending on timeout while the machine is
# sleeping (retryCount < 3). Home Assistant previously fired all frames
# fire-and-forget on fixed 0.5 s delays, so a slow-to-accept machine (e.g. just
# after a power-cycle) could receive EXECUTE (8002) before it had accepted the
# recipe (8001) → grind runs against an unset gear reference → wedge.
#
# Confirmed on real wire data from two live brew captures — each command echoed
# ~0.38-0.57 s after its write, next write firing 1-6 ms after the echo; 8002
# never precedes the 8001 echo. See discovery/analysis/ACK_GATING_EVIDENCE.md.
# ---------------------------------------------------------------------------
ECHO_TIMEOUT_S      = 1.5    # app's DefaultTimeOut (1500 ms) per command
ECHO_MAX_ATTEMPTS   = 3      # app resends until retryCount reaches 3 (3 sends)
SETTLE_AFTER_ECHO_S = 0.1    # small margin after an echo before the next write
                             # (app fires within ~1-6 ms; we stay conservative)


def frame_command_code(frame: bytes) -> int | None:
    """Return the command code (LE uint16) carried by a built FFE1 frame.

    Frame layout: ``58 <type> <subtype> <code_lo> <code_hi> …``. Returns None
    for anything that isn't a well-formed ``58…`` frame.
    """
    if len(frame) < 5 or frame[0] != 0x58:
        return None
    return frame[3] | (frame[4] << 8)


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


def _ascii_field(payload: bytes, start: int, end: int) -> str | None:
    """Decode a fixed-width ASCII field from a payload, fail-safe.

    Returns the trimmed string, or None if the slice is short, empty, or not
    printable ASCII. Used for the serial/model/firmware strings the machine
    packs at the front of RD_MachineInfo — the offsets are inferred from the
    Android MachineInfoBleModel layout, not a raw capture, so anything that
    doesn't look like clean ASCII is discarded rather than shown as garbage.
    """
    if len(payload) < end:
        return None
    raw = payload[start:end].split(b"\x00", 1)[0]
    text = raw.decode("ascii", "ignore").strip()
    if not text or not all(32 <= ord(ch) < 127 for ch in text):
        return None
    return text


def decode_notification(data: bytes) -> dict | None:
    """Higher-level decode: returns a flat dict ready for entity consumption.

    Output schema: ``{"cmd": int, ...}`` plus optional, cmd-specific fields:
      * weight_g  (float)  — for weight/scale notifications
      * water_ml  (float)  — for water-volume notifications
      * activity  (int)    — for machine-activity (cmd 8023)
      * pour_index (int)   — for RD_BLOOM
      * fw_version (str)   — installed firmware, from RD_MachineInfo
      * serial / model (str) — machine identity, from RD_MachineInfo
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
        # Periodic status heartbeat. Byte offsets are the AUTHORITATIVE map from
        # the official app's MachineInfoBleModel parser (hex-char offsets there,
        # halved to bytes here) and the firmware builder FUN_00022d48:
        #   0..12  serialNumber (ASCII)      29..32 areaAp (LE float, air pressure)
        #   13..18 model (ASCII)             33     waterEnough (0 low / 1 ok)
        #   19..28 theVersion (ASCII)        34     systemStatus
        #   35     userCount                 36     waterFeed (0 tank / 1 tap)
        #   37     grinder size (raw-30)     38     ledType
        #   39     voltage                   40     tempUnit (0 C / 1 F)
        #   41     weightUnit (0 g/1 oz/2 ml) 42    UI/activity state (fw +0x198)*
        #   51..54 modeType ("91327856"=EASY/auto, else PRO)
        #   55..58 pouringRadiusInit         59..62 vibrationInit
        # (*byte 42 is written by the firmware but NOT read by the app, which
        #  uses RD_MachineActivity 8023 instead — so we surface it as
        #  experimental ``ui_state`` to validate live before trusting it. NOTE:
        #  there is NO live water-temperature field here — only tempUnit, the
        #  °C/°F display toggle. The machine does not report water temp over BLE.)
        serial = _ascii_field(payload, 0, 13)
        if serial:
            out["serial"] = serial
        model = _ascii_field(payload, 13, 19)
        if model:
            out["model"] = model
        fw_version = _ascii_field(payload, 19, 29)
        # A version string must contain a digit — guards against a shifted or
        # zero-filled field decoding to something spurious.
        if fw_version and any(ch.isdigit() for ch in fw_version):
            out["fw_version"] = fw_version
        if len(payload) >= 33:
            out["area_ap"] = round(struct.unpack_from("<f", payload, 29)[0], 2)
        out["water_enough"] = payload[33]
        out["system_status"] = payload[34]
        if len(payload) >= 37:
            out["water_source"] = "tap" if payload[36] else "tank"
        if len(payload) >= 40:
            out["grind_size_current"] = max(payload[37] - 30, 1)
            out["voltage"] = payload[39]
        if len(payload) >= 42:
            # CONFIRMED wire codes (app): tempUnit 0=°F / 1=°C; weight ml=0/g=1/oz=2.
            out["temp_unit"] = "C" if payload[40] else "F"
            out["weight_unit"] = {0: "ml", 1: "g", 2: "oz"}.get(payload[41])
        if len(payload) >= 43:
            out["ui_state"] = payload[42]  # experimental — validate live
        if len(payload) >= 55:
            out["mode"] = (
                "auto" if payload[51:55].hex() == spec.MODE_PAYLOADS["auto"]
                else "pro"
            )

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

        # Send-and-confirm state. `_notify_active` is set True in brew() once
        # FFE2 start_notify succeeds; without it there is no echo stream and the
        # layer degrades to fixed delays. `_echo_waiters` maps an awaited command
        # code → the Event set when its echo arrives on FFE2. `_sleeping` tracks
        # RD_MachineSleeping/NotSleeping for the retry decision.
        self._notify_active = False
        self._echo_waiters: dict[int, "asyncio.Event"] = {}
        self._sleeping = False
        # Resolved by _on_notify with the next RD_MachineInfo heartbeat, so
        # read_status_snapshot() can await a fresh status frame.
        self._snapshot_future: "asyncio.Future | None" = None

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
        # Raw frame hex — lets us characterise reply/NACK layouts after the fact
        # (e.g. the status/error byte a rejected recipe carries). Zero-risk: log
        # only. bleak hands us a bytearray; hex() it verbatim.
        log.debug("BLE raw notify frame: %s", bytes(data).hex())
        log.debug("BLE notify cmd=%d (%s)", cmd, decoded)

        # Send-and-confirm: if this notification echoes a command code we're
        # waiting on, release the waiter. bleak may call us from a worker
        # thread, so hop to the connect-time loop to touch the asyncio.Event.
        waiter = self._echo_waiters.get(cmd)
        if waiter is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(waiter.set)

        # Track sleep state for the retry decision (mirrors AppDeviceManager).
        if cmd == NOTIFY_SLEEPING:
            self._sleeping = True
        elif cmd == NOTIFY_AWAKE:
            self._sleeping = False

        # Resolve a pending status-snapshot request on the next heartbeat.
        if cmd == NOTIFY_MACHINE_INFO and self._loop is not None:
            fut = self._snapshot_future
            if fut is not None and not fut.done():
                self._loop.call_soon_threadsafe(fut.set_result, decoded)

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

    async def write_confirmed(
        self,
        name: str,
        frame: bytes,
        *,
        timeout: float = ECHO_TIMEOUT_S,
        max_attempts: int = ECHO_MAX_ATTEMPTS,
        retry_only_when_sleeping: bool = False,
    ) -> bool:
        """Write one FFE1 frame and wait for the machine's echo on FFE2.

        Mirrors the app's AppBleManager: the machine echoes the command code
        back (`58 02 07 <code> …`); we send, then await that echo for up to
        ``timeout`` seconds, re-sending on timeout up to ``max_attempts`` total
        writes. Returns True if the echo arrived (command confirmed accepted),
        False if it never did after all attempts (caller proceeds anyway).

        Requires ``self._notify_active`` — the caller must have subscribed to
        FFE2 and must degrade to a plain write + fixed delay when notifications
        aren't available (there is no echo stream to wait on).

        Retry policy — ``retry_only_when_sleeping``:
          * ``False`` (default, safer for autonomous HA): re-send on any timeout
            up to ``max_attempts``. A retry only ever happens when *no* echo
            arrived — i.e. the machine did not process the command — so a resend
            is safe, and HA can't fall back on a human to press retry.
          * ``True`` (app-exact): re-send only while the machine is sleeping
            (``RD_MachineSleeping``), matching AppBleManager, which otherwise
            hard-fails with a "BLE ACK timeout" for the user to retry manually.
        Either way the sleep state is logged for context.
        """
        import asyncio

        if self._client is None:
            raise RuntimeError("write_confirmed called without a connection")

        code = frame_command_code(frame)
        if code is None:
            # Not a decodable command frame — just write it and move on.
            await self._client.write_gatt_char(FFE1_UUID, frame, response=False)
            return False

        event = asyncio.Event()
        # Register the waiter BEFORE writing so an echo can't race ahead of us.
        self._echo_waiters[code] = event
        try:
            for attempt in range(1, max_attempts + 1):
                event.clear()
                log.info(
                    "BLE write '%s' (%d bytes, attempt %d/%d): %s",
                    name, len(frame), attempt, max_attempts, frame.hex(),
                )
                await self._client.write_gatt_char(FFE1_UUID, frame, response=False)
                try:
                    await asyncio.wait_for(event.wait(), timeout=timeout)
                    log.debug("BLE '%s' (code %d) echo confirmed", name, code)
                    return True
                except asyncio.TimeoutError:
                    can_retry = attempt < max_attempts and (
                        self._sleeping or not retry_only_when_sleeping
                    )
                    if not can_retry:
                        break
                    log.warning(
                        "BLE '%s' (code %d): no echo in %.1fs — re-sending "
                        "(%d/%d, sleeping=%s)",
                        name, code, timeout, attempt + 1, max_attempts,
                        self._sleeping,
                    )
            log.warning(
                "BLE '%s' (code %d): no echo after %d attempt(s) (sleeping=%s) — "
                "proceeding without confirmation",
                name, code, attempt, self._sleeping,
            )
            return False
        finally:
            self._echo_waiters.pop(code, None)

    async def _ensure_notify(self) -> bool:
        """Best-effort FFE2 subscribe so command echoes can be observed.

        Idempotent — subscribes only once per connection. On the first
        successful subscribe it also runs the one-off settle (yield to the loop
        so bleak's notification reader spins up, then a short pause) so the
        reader doesn't miss the first echo burst. Returns ``_notify_active``.
        """
        import asyncio

        self._loop = asyncio.get_running_loop()
        if self._notify_active or self._client is None:
            return self._notify_active
        try:
            await self._client.start_notify(FFE2_UUID, self._on_notify)
            self._notify_active = True
            log.debug("FFE2 notifications enabled")
            # Let bleak's reader task initialize before the first write.
            for _ in range(5):
                await asyncio.sleep(0)
            await asyncio.sleep(0.3)
        except Exception as err:  # noqa: BLE001
            log.warning(
                "FFE2 start_notify failed (%s) — commands will use fixed-delay "
                "pacing (no echo confirmation this session)", err,
            )
        return self._notify_active

    async def send_command(
        self,
        name: str,
        frame: bytes,
        *,
        timeout: float = ECHO_TIMEOUT_S,
        max_attempts: int = 3,
        fallback_delay: float = 0.5,
        retry_only_when_sleeping: bool = True,
    ) -> bool:
        """Send one FFE1 command through the send-and-confirm layer.

        Subscribes to FFE2 (best-effort, idempotent) then echo-gates the write,
        degrading to a plain write + ``fallback_delay`` when the echo stream is
        unavailable. Use this for every one-shot command so nothing goes out
        fire-and-forget.

        Defaults mirror the official app's AppBleManager exactly:
        ``max_attempts=3`` with ``retry_only_when_sleeping=True`` — wait for the
        echo, and re-send only while the machine is *sleeping* (up to 3 sends),
        otherwise proceed. This is safe for EVERY command, including motion
        commands whose echo behavior isn't capture-verified: a retry fires only
        when the machine is asleep, which means it hasn't processed the command,
        so a resend can't double-actuate; and in the awake-but-no-echo case it
        simply proceeds (no blind re-send). Pass ``retry_only_when_sleeping=
        False`` to retry on any timeout — appropriate only for commands
        confirmed to echo (``brew()`` does this for its verified sequence).
        """
        import asyncio

        if self._client is None:
            raise RuntimeError("send_command called without a connection")
        await self._ensure_notify()
        if self._notify_active:
            return await self.write_confirmed(
                name, frame, timeout=timeout, max_attempts=max_attempts,
                retry_only_when_sleeping=retry_only_when_sleeping,
            )
        log.info(
            "BLE write '%s' (degraded, %d bytes): %s", name, len(frame), frame.hex(),
        )
        await self._client.write_gatt_char(FFE1_UUID, frame, response=False)
        await asyncio.sleep(fallback_delay)
        return False

    async def read_status_snapshot(self, timeout: float = 3.0) -> dict | None:
        """Wait for one RD_MachineInfo (40521) heartbeat and return its decode.

        The machine streams the heartbeat periodically the moment it's
        connected; we subscribe to FFE2, nudge it with a handshake, and await
        the next one. If ``on_event`` is wired (it is for every integration
        connection now), the same heartbeat is also dispatched to the entities
        during the wait — so this both *returns* the snapshot (for an awaitable
        refresh) and *refreshes* the sensors as a side effect.

        Returns the decoded dict, or None if no heartbeat arrived in time (e.g.
        FFE2 notify unavailable). Requires an open connection.
        """
        import asyncio

        if self._client is None or not self._client.is_connected:
            raise RuntimeError("read_status_snapshot called without a connection")
        self._loop = asyncio.get_running_loop()
        if not await self._ensure_notify():
            return None  # no echo/notify stream — can't observe the heartbeat
        self._snapshot_future = self._loop.create_future()
        try:
            # Kick the machine so it emits the heartbeat promptly (plain write —
            # we don't need to confirm the handshake echo for a status read).
            try:
                hs = _build_frame(CMD_HANDSHAKE, list(HANDSHAKE_DATA))
                await self._client.write_gatt_char(FFE1_UUID, hs, response=False)
            except Exception as err:  # noqa: BLE001
                log.debug("snapshot handshake nudge failed: %s", err)
            try:
                decoded = await asyncio.wait_for(self._snapshot_future, timeout=timeout)
                log.info("BLE status snapshot: %s", decoded)
                return decoded
            except asyncio.TimeoutError:
                log.warning(
                    "BLE status snapshot: no heartbeat within %.1fs", timeout,
                )
                return None
        finally:
            self._snapshot_future = None

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
        # AND command echoes arrive on FFE2. Subscribing is BEST-EFFORT: if
        # BlueZ refuses (we frequently see `[org.bluez.Error.NotPermitted]
        # Notify acquired` when other Bluetooth consumers on the host hold the
        # same notify handle), _ensure_notify logs a warning and leaves
        # _notify_active False — the send loop below then degrades to fixed
        # delays. The brew frames (sent on FFE1) work regardless; we just lose
        # echo confirmation and live entity updates for the run.
        self._notify_active = False
        await self._ensure_notify()

        # Build and send the 5-frame brew sequence to FFE1. The machine's
        # FFE1 characteristic only supports Write Without Response — using
        # response=True triggers ATT error 0x0e ("Unlikely Error"). A small
        # inter-frame delay matches the official Android app's pacing and
        # gives the machine time to process each command before the next.
        # We verify is_connected after the burst so silent drops surface.
        frames = build_brew_frames(recipe)
        # App-faithful sequence (2026-07-22). The official app's recipe brew is
        # only: bypass+dose(8102) → set-cup(8104) → recipe(8001/8004) →
        # execute(8002). It does NOT switch mode. We used to force Auto/Easy mode
        # (11511) here believing "8001 only grinds in Auto" — that was WRONG: the
        # firmware's 11511 handler only stores a mode flag and never touches the
        # grind path or the activity-state gate; grinding is selected by
        # 8001-vs-8004 and by the machine being idle/ready (true on Home), not by
        # Auto/Pro. So we no longer flip the user's mode. (The handshake 8100 is
        # kept — it's our connection kickstart + ACK-gating canary, not a brew
        # behaviour. The real 2026-07-16 grind-skip was fixed by ACK-gating, not
        # by the mode switch that rode along with it.)
        #
        # Grind SIZE rides INSIDE the 8001 recipe blob — we do NOT inject a
        # separate 8006 (APP_GRINDER_IN). App + firmware RE (2026-07-22): the
        # stock recipe brew never sends 8006; the 8002 EXECUTE handler itself
        # positions the burrs to the committed grind and grinds+brews
        # autonomously (no knob press). An injected 8006 writes the grind
        # registers AND bumps the work-state out-of-band, leaving the recipe
        # commit inconsistent → the machine rejects with an abnormal-gear error
        # (seen live at both grind 1 and 50). The recipe's size is applied by the
        # 8001 validation committing 0x11c→0x124 (needs the blob's ratio×10 tail,
        # fixed separately) and then 8002. The ACK-gated loop below only sends
        # 8002 after the machine echoes (accepts) 8001, exactly like the app.
        #
        # (name, fixed_delay) — fixed_delay is the DEGRADED fallback (no echo
        # stream). In the echo-gated path each frame waits for the machine's echo;
        # 8002 fires only after the 8001 accept, so EXECUTE can't outrun the recipe.
        sends = [
            ("handshake", 0.5),
            ("bypass+dose", 0.5),
            ("set_cup", 0.5),
            ("recipe", 0.5),
            ("execute", 0.5),
        ]

        # Echo-gated send. The handshake is the canary: it is always the first
        # frame and is always echoed on a live link (confirmed in both brew
        # captures), so if even its echo never arrives despite start_notify
        # having "succeeded" (the BlueZ "Notify acquired" failure mode, where
        # the subscription is silently dead), we conclude the echo stream is
        # unavailable and degrade the remaining frames to fixed-delay pacing
        # rather than paying a full timeout on every one.
        echo_gated = self._notify_active
        for (name, delay), frame in zip(sends, frames):
            if echo_gated:
                # write_confirmed() writes the frame (with retries) and waits
                # for its echo. The handshake is the canary — if its echo never
                # comes, the stream is dead; degrade the REMAINING frames.
                confirmed = await self.write_confirmed(name, frame)
                if name == "handshake" and not confirmed:
                    echo_gated = False
                    log.warning(
                        "No handshake echo on FFE2 — echo stream appears "
                        "unavailable; falling back to fixed-delay pacing for "
                        "the remaining brew frames"
                    )
                    continue  # handshake already written; degrade what's left
                # Confirmed → fire the next frame promptly (app waits ~1-6 ms);
                # unconfirmed on a live stream → conservative fixed settle.
                await asyncio.sleep(SETTLE_AFTER_ECHO_S if confirmed else delay)
                continue
            # Degraded path: plain fire-and-forget write + fixed delay.
            log.info(
                "BLE write '%s' (degraded, %d bytes): %s",
                name, len(frame), frame.hex(),
            )
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
