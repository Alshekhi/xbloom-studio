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
# NOTE ON pour_temperature_c: the floor is 40, matching the machine rule the   #
# validator has always enforced. The edit wizard's slider previously allowed   #
# 20, which let a user pick a value the save would then reject. Canonicalising  #
# to 40 makes the control honest; no capability is lost (sub-40 never saved).   #
# --------------------------------------------------------------------------- #
FIELDS: dict[str, NumRange] = {
    "grind_size": NumRange(1, 80, 1, 40),
    "grinder_speed_rpm": NumRange(60, 120, 10, 90, "RPM"),
    "pour_count": NumRange(1, 9, 1, 3),
    "pour_volume_ml": NumRange(0, 240, 1, 60, "ml"),
    "pour_temperature_c": NumRange(40, 98, 1, 92, "°C"),
    "pour_flow_rate": NumRange(3.0, 3.5, 0.1, 3.0),
    "pour_pause_s": NumRange(0, 59, 1, 0, "s"),
    # Bypass water is optional and cooler than a pour, so its own floor (20).
    "bypass_volume_ml": NumRange(5, 100, 1, 30, "ml"),
    "bypass_temp_c": NumRange(20, 98, 1, 92, "°C"),
}


def field(name: str) -> NumRange:
    """Look up a field's canonical range by name."""
    return FIELDS[name]


# Volumes across a recipe's pours must sum to dose x ratio within this slack.
VOLUME_TOLERANCE_ML = 0.5


# --------------------------------------------------------------------------- #
# Small brew enums carried in BLE frames — name <-> code. These were mirrored  #
# inline in ble.py and select.py; both now derive from here.                   #
# --------------------------------------------------------------------------- #
WATER_SOURCE_CODES: dict[str, int] = {"tank": 0, "tap": 1}
WEIGHT_UNIT_CODES: dict[str, int] = {"g": 0, "oz": 1, "ml": 2}
TEMP_UNIT_CODES: dict[str, int] = {"°C": 0, "°F": 1}
