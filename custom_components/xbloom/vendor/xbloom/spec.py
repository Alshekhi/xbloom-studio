"""Single source of truth for xBloom domain facts.

This module is the one place recipe/brew constants live: pour patterns, cup
types and their dose ranges, per-field numeric bounds, the ratio grid, and the
small brew enums. Everything that used to hardcode these — the recipe
validator, the BLE encoders, and the Home Assistant adapter (config flow,
dashboard card) — derives from here instead, so a machine limit, an API enum,
or a wire byte changes in exactly one place.

Platform-agnostic on purpose: NO Home Assistant imports. `vendor.xbloom` is a
portable core that other home-automation bridges can consume; HA talks to it
through the plain data structures below (e.g. a `NumRange` an adapter turns
into whatever slider its UI framework uses) rather than reaching in for magic
numbers. Keep it dependency-free.

Scope: recipe/brew domain facts. Raw BLE command/notify codes stay in
`ble.py` (they are already single-sourced there and are protocol-level, not
recipe-level); this module owns the *semantic* maps those frames carry.
"""
from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# Numeric field spec — one per user-settable number. UI sliders AND range     #
# validation both derive from these, so they can never drift apart again.     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NumRange:
    """Canonical bounds for one numeric field.

    An adapter builds its input control from this (e.g. HA's NumberSelector)
    and the validator checks against the same object. `unit` is a display
    hint the core does not interpret.
    """

    min: float
    max: float
    step: float
    default: float
    unit: str = ""

    def contains(self, value: object) -> bool:
        """True if `value` is numeric and within [min, max]. Step alignment is
        deliberately NOT enforced here — the machine tolerates off-grid values
        and the validator's field rules decide where stepping matters (e.g.
        rpm). Callers wanting grid-snapping use `snap`."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return self.min <= value <= self.max

    def snap(self, value: float) -> float:
        """Clamp to [min, max] and round to the nearest `step`."""
        value = max(self.min, min(self.max, value))
        if self.step:
            steps = round((value - self.min) / self.step)
            value = self.min + steps * self.step
        return round(value, 6)


# --------------------------------------------------------------------------- #
# Pour patterns — canonical name <-> API integer <-> BLE wire byte.           #
#                                                                             #
#   API integer : value in a RecipeDetail/share payload. Confirmed against    #
#                 the xBloom app UI (recipe 803560 pours read back exactly).  #
#   BLE byte    : value the machine reads in the recipe blob and reports on   #
#                 the pattern-knob event. Confirmed live via the voice-box    #
#                 announcements (pattern_<byte>.wav: 0=centered, 1=circular,   #
#                 2=spiral).                                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Pattern:
    name: str
    api: int
    byte: int


PATTERNS: tuple[Pattern, ...] = (
    Pattern("centered", api=1, byte=0),
    Pattern("spiral", api=2, byte=2),
    Pattern("circular", api=3, byte=1),
)

PATTERN_API_TO_NAME: dict[int, str] = {p.api: p.name for p in PATTERNS}
PATTERN_NAME_TO_API: dict[str, int] = {p.name: p.api for p in PATTERNS}
PATTERN_API_TO_BYTE: dict[int, int] = {p.api: p.byte for p in PATTERNS}
PATTERN_BYTE_TO_NAME: dict[int, str] = {p.byte: p.name for p in PATTERNS}
PATTERN_NAME_TO_BYTE: dict[str, int] = {p.name: p.byte for p in PATTERNS}
VALID_PATTERN_APIS: frozenset[int] = frozenset(p.api for p in PATTERNS)
PATTERN_NAMES: tuple[str, ...] = tuple(p.name for p in PATTERNS)


# --------------------------------------------------------------------------- #
# Cup types — API integer, human label, and per-cup dose range (grams).       #
# The dose NumRange is the ONE source for both the validator's accept/reject   #
# bounds and the UI stepper. xPod is locked (min==max==15).                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CupType:
    api: int
    label: str
    dose: NumRange


CUP_TYPES: tuple[CupType, ...] = (
    CupType(1, "xPod", NumRange(15.0, 15.0, 0.5, 15.0, "g")),
    CupType(2, "Omni dripper", NumRange(5.0, 18.0, 0.5, 18.0, "g")),
    CupType(3, "Other", NumRange(5.0, 25.0, 0.5, 18.0, "g")),
    CupType(4, "Tea", NumRange(1.0, 5.0, 0.5, 3.0, "g")),
)

CUP_API_TO_LABEL: dict[int, str] = {c.api: c.label for c in CUP_TYPES}
CUP_LABEL_TO_API: dict[str, int] = {c.label: c.api for c in CUP_TYPES}
CUP_DOSE: dict[int, NumRange] = {c.api: c.dose for c in CUP_TYPES}
VALID_CUP_TYPES: frozenset[int] = frozenset(c.api for c in CUP_TYPES)
# Default cup when none given, by both label and api (Omni dripper).
DEFAULT_CUP_LABEL = "Omni dripper"


# --------------------------------------------------------------------------- #
# Ratio grid — grandWater denominator N of "1:N". One rule for all cups.       #
# --------------------------------------------------------------------------- #
RATIO_DENOM = NumRange(min=5.0, max=25.0, step=0.5, default=16.0)


# --------------------------------------------------------------------------- #
# Per-field numeric ranges (non-cup, non-ratio). Keyed name -> NumRange.       #
#                                                                             #
# Temperature: the range is 20-98, where the two ends are the sentinels the
# xBloom app calls RT and BP (see ROOM_TEMP_C / BOILING_POINT_C below) — a pour
# at 20 shows "RT", at 98 shows "BP", and the app's numeric slider runs 40-95
# between them. Validation accepts the whole inclusive span. (An earlier version
# floored this at 40, which wrongly rejected RT pours — corrected after reading
# the app's TemperatureConstant.)
# --------------------------------------------------------------------------- #
FIELDS: dict[str, NumRange] = {
    "grind_size": NumRange(1, 80, 1, 40),
    "grinder_speed_rpm": NumRange(60, 120, 10, 90, "RPM"),
    "pour_count": NumRange(1, 9, 1, 3),
    "pour_volume_ml": NumRange(0, 240, 1, 60, "ml"),
    "pour_temperature_c": NumRange(20, 98, 1, 92, "°C"),
    "pour_flow_rate": NumRange(3.0, 3.5, 0.1, 3.0),
    "pour_pause_s": NumRange(0, 59, 1, 0, "s"),
    "bypass_volume_ml": NumRange(5, 100, 1, 30, "ml"),
    "bypass_temp_c": NumRange(20, 98, 1, 92, "°C"),
}

# Temperature sentinels, from the xBloom app's TemperatureConstant. A pour whose
# temperature equals one of these is shown as text ("RT"/"BP") instead of a
# number; both are inside pour_temperature_c's range so they validate.
ROOM_TEMP_C = 20.0      # "RT" — room temperature
BOILING_POINT_C = 98.0  # "BP" — boiling point (the app derives the real value
                        # from altitude; the transmitted sentinel is 98)


# --------------------------------------------------------------------------- #
# Unified brewer-temperature model — the single source of truth for the two    #
# temperature number spaces and how to move between them. Everything else       #
# (live_session filter, the brew-temperature number entity, the drive path)     #
# routes through here so no divergence can creep in.                            #
#                                                                              #
# There are TWO domains, confirmed three ways (firmware 7-segment renderer      #
# thresholds, app CoffeeConstantUtil.getTemperatureJ15RTBP, app BrewerActivity):#
#                                                                              #
#  * DISPLAY domain — what the user sees/turns everywhere (on-device screen,    #
#    app brewer screen, app recipe editor) and what the brewer temperature      #
#    KNOB broadcasts on cmd 8108. On the J15 it runs 39..96, where the two      #
#    ends are sentinels, NOT literal degrees: 39 = "RT", 96 = "BP", and 40..95  #
#    are literal °C.                                                            #
#  * WIRE domain — what is transmitted/stored when a value is SET or SAVED: a   #
#    recipe blob byte, a 4510 temp-set, a 4506 brew. Here RT/BP are the         #
#    ROOM_TEMP_C / BOILING_POINT_C sentinels (20 / 98); 40..95 pass through.    #
#                                                                              #
# The ONLY place the raw display value leaks onto the wire is the 8108 knob     #
# REPORT (a knob position, not a saved value) — which is why HA reads 96, not   #
# 98, when the knob is at BP. Recipes are STORED in the wire domain (20/98),    #
# so pour_temperature_c above keeps that 20..98 range; the display domain is    #
# only for the editing widget / knob reflect and converts on the boundary.     #
# --------------------------------------------------------------------------- #
BREW_TEMP_DISPLAY_MIN = 39   # J15 knob/slider floor → "RT" (room temperature)
BREW_TEMP_DISPLAY_MAX = 96   # J15 knob/slider ceiling → "BP" (boiling point)
# The KNOB (cmd 8108) reports in the machine's *display unit*: Celsius gives the
# 39-96 domain above; Fahrenheit gives 103-204 (getTemperatureJ15RTBP's °F
# branch). We normalize F→C so the rest of the model is unit-free.
BREW_TEMP_DISPLAY_F_MIN = 103
BREW_TEMP_DISPLAY_F_MAX = 204


def brew_temp_knob_to_celsius(raw: float) -> int | None:
    """Normalize a raw brewer-temp KNOB value (cmd 8108) to the canonical
    Celsius display domain (39-96), or None if out of range.

    The knob emits in the machine's current display unit — Celsius 39-96 as-is,
    Fahrenheit 103-204 converted to °C. The two ranges don't overlap, so the
    unit is inferred from the value (no state needed).
    """
    r = int(round(raw))
    if BREW_TEMP_DISPLAY_MIN <= r <= BREW_TEMP_DISPLAY_MAX:
        return r
    if BREW_TEMP_DISPLAY_F_MIN <= r <= BREW_TEMP_DISPLAY_F_MAX:
        return int(round((r - 32) / 1.8))
    return None


def brew_temp_sentinel_name(display_value: float) -> str | None:
    """Return "RT"/"BP" if a DISPLAY-domain value is at a sentinel end, else None.

    Consumers (announce blueprint, dashboard) use this to say "room temperature"
    / "boiling point" instead of a bare 39 / 96.
    """
    d = int(round(display_value))
    if d <= BREW_TEMP_DISPLAY_MIN:
        return "RT"
    if d >= BREW_TEMP_DISPLAY_MAX:
        return "BP"
    return None


def brew_temp_display_to_wire(display_value: float) -> float:
    """DISPLAY (39..96) → WIRE °C for SETing/SAVing (recipe byte, 4510, 4506).

    The ends map to the sentinels the machine expects (39→20 RT, 96→98 BP);
    40..95 pass through unchanged.
    """
    d = int(round(display_value))
    if d <= BREW_TEMP_DISPLAY_MIN:
        return ROOM_TEMP_C
    if d >= BREW_TEMP_DISPLAY_MAX:
        return BOILING_POINT_C
    return float(d)


def brew_temp_wire_to_display(wire_value: float) -> int:
    """WIRE °C (as stored in a recipe: 20 / 40..95 / 98) → DISPLAY 39..96.

    Inverse of brew_temp_display_to_wire, for showing a stored recipe temp in a
    display-domain widget. 20→39 (RT), 98→96 (BP); 40..95 pass through.
    """
    w = float(wire_value)
    if w <= ROOM_TEMP_C:
        return BREW_TEMP_DISPLAY_MIN
    if w >= BOILING_POINT_C:
        return BREW_TEMP_DISPLAY_MAX
    return int(round(w))


def field(name: str) -> NumRange:
    """Look up a field's canonical range by name."""
    return FIELDS[name]


# Volumes across a recipe's pours must sum to dose x ratio within this slack.
VOLUME_TOLERANCE_ML = 0.5


# --------------------------------------------------------------------------- #
# Small brew enums carried in BLE frames — name <-> code. These were mirrored  #
# inline in ble.py and select.py; both now derive from here.                   #
# --------------------------------------------------------------------------- #
# Wire codes CONFIRMED against the decompiled app (2026-07-20) — the earlier
# guessed values were WRONG (temp C/F swapped; weight order off), which made HA
# set the opposite unit and misreport the machine's units:
#   * WaterSourceType enum: TANK=0, TAP=1 (correct as-was).
#   * WeightUnitType: ml=0, g=1, oz=2.
#   * temperature (NumberExtendsKt.temperatureUnit): 0 = °F, 1 = °C (default 1).
WATER_SOURCE_CODES: dict[str, int] = {"tank": 0, "tap": 1}
WEIGHT_UNIT_CODES: dict[str, int] = {"g": 1, "ml": 0, "oz": 2}
# Keys match what the select entity offers and the BLE frame expects ("C"/"F").
TEMP_UNIT_CODES: dict[str, int] = {"C": 1, "F": 0}


# --------------------------------------------------------------------------- #
# Machine state / mode enums — protocol facts a bridge must agree on, not UI.  #
# --------------------------------------------------------------------------- #
# Brew lifecycle the machine reports (brew-status sensor).
BREW_STATES: tuple[str, ...] = ("idle", "grinding", "brewing", "done")

# On-machine UI module the user has entered (current-module sensor).
# "auto" here = the Auto-mode home screen (recipes A/B/C); the rest are the
# Pro-mode manual modules. Same naming rule as MODES below.
MODULES: tuple[str, ...] = ("home", "grinder", "scale", "brewer", "auto")

# ---------------------------------------------------------------------------
# Operating mode — CANONICAL NAMING (one token used everywhere in this repo):
#   "auto"  = the machine's two-mode toggle labelled "Auto Mode" on the device
#             screen and in the app UI. Internally the app enum is DeviceMode.
#             EASY and the BLE feature is "EasyMode" (wire code 91327856) — same
#             thing, different name. Auto mode = pick one of three saved recipe
#             slots A/B/C (ship defaults: A Light / B Medium / C Dark, 15 g) and
#             the machine grinds+brews it whole. Recipe brews (8001) only grind
#             in this mode, which is why brew() forces it. Slots are writable via
#             the write_slot service (cmd 11510 RD_EASYMODE_RECIPE_SEND).
#   "pro"   = "Pro Mode": the manual grinder / brewer / scale modules, driven by
#             hand (wire code 00000000).
# Toggle on the machine = three quick presses of the middle knob.
# So: our token "auto" ≡ app enum EASY ≡ user-facing "Auto Mode". Never rename
# the token to "easy" — that would diverge from what the device shows the user.
# ---------------------------------------------------------------------------
MODES: tuple[str, ...] = ("auto", "pro")
MODE_PAYLOADS: dict[str, str] = {"auto": "91327856", "pro": "00000000"}  # hex

# Auto-mode recipe slots on the machine (A/B/C).
SLOTS: tuple[str, ...] = ("A", "B", "C")

# Machine status: "ok" plus the fault conditions. FAULTS maps the fault
# notification command code -> (status enum value, brew-event type). This is
# the machine's fault vocabulary; the HA sensor and event entity derive from it.
MACHINE_OK = "ok"
FAULTS: dict[int, tuple[str, str]] = {
    40522: ("no_water", "error_no_water"),            # RD_ErrorLackOfWater
    40517: ("no_beans", "error_no_beans"),            # RD_ErrorIdling
    8204: ("dose_water_error", "error_dose_water"),   # RD_AbnormalDoseOrWater
    8203: ("gear_position_error", "error_gear_position"),  # RD_AbnormalGearPosition
}
MACHINE_STATUSES: tuple[str, ...] = (MACHINE_OK, *(s for s, _ in FAULTS.values()))


# --------------------------------------------------------------------------- #
# Cup wire weight-range defaults (theMax, theMin) sent in the CMD_SET_CUP /    #
# recipe-blob frame. Keyed by cup api id. DISTINCT from CUP_DOSE (grams) —     #
# these are machine weight-range bytes, not a dose window.                     #
# --------------------------------------------------------------------------- #
CUP_WEIGHT_RANGE: dict[int, tuple[float, float]] = {
    1: (200.0, 80.0),   # xPod (default; no HCI capture)
    2: (110.0, 90.0),   # Omni dripper (HCI confirmed)
    3: (200.0, 80.0),   # Other / Free Solo (HCI confirmed)
    4: (200.0, 80.0),   # Tea (default; no HCI capture)
}
CUP_WEIGHT_RANGE_DEFAULT: tuple[float, float] = (200.0, 80.0)


# --------------------------------------------------------------------------- #
# Canonical defaults — so every implementer falls back the same way. Values    #
# are members of the enums above, not free-floating strings.                   #
# --------------------------------------------------------------------------- #
DEFAULT_PATTERN = "spiral"
DEFAULT_WATER_SOURCE = "tank"

# First parameter of the grind-start frame (cmd 3500): [this, size, speed].
# The official app hardcodes it to 1000 (verified in GrinderActivity's
# CodeModule(3500, ..., 1000, i, i2)); it is NOT computed. The grinder runs
# until its single-dose chamber is empty or a STOP (3505) arrives, so this
# value does not actually time the grind — it's a fixed protocol field we send
# to match the app.
GRIND_START_DURATION_MS = 1000
