"""Unified Live Control listener — merges scale + grinder + brewer feedback.

When ``switch.xbloom_studio_live_control`` is ON, holds a single BLE
connection and fires an HA event per reading. The spoken text and its
language live in the live_control_announce blueprint, not here:
    - Scale weight (debounced 2s, +/-1g)
    - Grinder knob: size (BLE -30 -> UI 1-80) and speed (60-120 RPM)
    - Brewer knob: pour pattern, temperature, and ratio (if reachable)
    - Scale tare (cmd 9007), module entry, and recipe-card scan

All values are range-validated; out-of-spec values are dropped silently.
Replaces the previous three separate mode switches.
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from .vendor.xbloom.ble import (
    NOTIFY_BREW_PATTERN, NOTIFY_BREW_RATIO, NOTIFY_BREW_TEMP,
    NOTIFY_GRIND_SIZE, NOTIFY_GRIND_SPEED,
    NOTIFY_PODS,
    NOTIFY_TARE,
    NOTIFY_WEIGHT_2, NOTIFY_WEIGHT_ALT,
    PATTERN_NAMES,
)
from .vendor.xbloom.mode_listener import XBloomModeListener

_LOGGER = logging.getLogger(__name__)

# Range guards
SIZE_BLE_MIN, SIZE_BLE_MAX = 31, 110   # BLE raw → UI 1-80
SPEED_RPM_MIN, SPEED_RPM_MAX = 60, 120
TEMP_C_MIN, TEMP_C_MAX = 40, 98
RATIO_MIN, RATIO_MAX = 1.0, 30.0       # brew ratio 1:N

# Scale debounce
SCALE_STABLE_DELTA_G = 1.0
SCALE_STABLE_HOLD_SEC = 2.0
SCALE_RE_ANNOUNCE_DELTA_G = 1.0

# Guard against any duplicate tare (9007) frame; real presses are seconds apart.
TARE_DEDUP_SEC = 0.5


def _ble_size_to_ui(ble_value: int) -> int:
    """Per brAzzi64 PROTOCOL.md: UI = max(1, BLE − 30)."""
    return max(1, int(ble_value) - 30)


def voice_filter(decoded: dict) -> dict | None:
    """Map every interesting cmd to a structured event payload."""
    cmd = decoded.get("cmd")

    if cmd in (NOTIFY_WEIGHT_2, NOTIFY_WEIGHT_ALT) and "weight_g" in decoded:
        return {"kind": "weight", "weight_g": float(decoded["weight_g"])}

    if cmd == NOTIFY_GRIND_SIZE and "grind_size" in decoded:
        v = int(decoded["grind_size"])
        if not (SIZE_BLE_MIN <= v <= SIZE_BLE_MAX):
            return None
        return {"kind": "grinder", "parameter": "size", "value": _ble_size_to_ui(v)}

    if cmd == NOTIFY_GRIND_SPEED and "grind_speed" in decoded:
        v = int(decoded["grind_speed"])
        if not (SPEED_RPM_MIN <= v <= SPEED_RPM_MAX):
            return None
        return {"kind": "grinder", "parameter": "speed", "value": v}

    if cmd == NOTIFY_BREW_PATTERN and "pattern" in decoded:
        v = int(decoded["pattern"])
        if v not in PATTERN_NAMES:
            return None
        return {
            "kind": "brewer",
            "setting": "pattern",
            "value": v,
            "value_name": PATTERN_NAMES[v],
        }

    if cmd == NOTIFY_BREW_TEMP and "temperature_c" in decoded:
        v = int(decoded["temperature_c"])
        if not (TEMP_C_MIN <= v <= TEMP_C_MAX):
            return None
        return {"kind": "brewer", "setting": "temperature", "value": v}

    if cmd == NOTIFY_BREW_RATIO and "brew_ratio" in decoded:
        v = float(decoded["brew_ratio"])
        if not (RATIO_MIN <= v <= RATIO_MAX):
            return None
        return {"kind": "brewer", "setting": "ratio", "value": v}

    # Recipe card / xPod scanned — announce it was recognised.
    if cmd == NOTIFY_PODS and decoded.get("pod_id"):
        return {"kind": "recipe_card", "pod_id": decoded["pod_id"]}

    # Scale tare. The dedicated tare button emits cmd 9007 — confirmed live:
    # exactly one 9007 per press, each followed by activity=4 → activity=5 as
    # the scale re-zeroes and settles. Announce it explicitly.
    if cmd == NOTIFY_TARE:
        return {"kind": "tare"}

    # Module / activity detection (confirmed against live frames):
    #   cmd 8023 activity=1   → returned to home / idle screen (the physical
    #                           "home" button; correct to announce as home)
    #   cmd 8023 activity=3   → Brewer (drip/brew) screen entered
    #   cmd 8023 activity=65  → Auto/EasyMode screen (triple-press, recipes A/B/C)
    #   cmd 8023 activity=4/5 → scale settling states — left silent (noise if
    #                           spoken; they fire on scale entry and each tare)
    #   cmd 9000              → Grinder module entered (left knob press)
    #   cmd 9002              → Scale module entered / cup on cradle (right knob)
    if cmd == 8023:
        activity = decoded.get("activity")
        if activity == 1:
            return {"kind": "module", "module": "home"}
        if activity == 3:
            return {"kind": "module", "module": "brewer"}
        if activity == 65:
            return {"kind": "module", "module": "auto"}
    elif cmd == 9000:
        return {"kind": "module", "module": "grinder"}
    elif cmd == 9002:
        return {"kind": "module", "module": "scale"}

    return None


class _ScaleDebouncer:
    """Debounce a noisy weight stream — only fire on a settled reading."""

    def __init__(self, fire: Callable[[float], Awaitable[None]]) -> None:
        self._fire = fire
        self._last_weight: float | None = None
        self._stable_since: float | None = None
        self._announced_weight: float | None = None

    async def feed(self, weight_g: float) -> None:
        now = time.monotonic()
        if (
            self._last_weight is None
            or abs(weight_g - self._last_weight) > SCALE_STABLE_DELTA_G
        ):
            self._stable_since = now
            self._last_weight = weight_g
            return
        self._last_weight = weight_g
        if self._stable_since is None:
            self._stable_since = now
            return
        if (now - self._stable_since) < SCALE_STABLE_HOLD_SEC:
            return
        if (
            self._announced_weight is not None
            and abs(weight_g - self._announced_weight) <= SCALE_RE_ANNOUNCE_DELTA_G
        ):
            return
        self._announced_weight = weight_g
        await self._fire(weight_g)


class VoiceModeListener(XBloomModeListener):
    """Single listener that fires the right event per cmd type."""

    def __init__(self, hass, ble_device_resolver) -> None:
        self._scale_debouncer = _ScaleDebouncer(self._fire_weight)
        # Dedup state for grinder + brewer + module entries
        self._last_grinder: dict[str, tuple[int, float]] = {}
        self._last_brewer: dict[str, tuple[int, float]] = {}
        self._last_module: str | None = None
        # Collapse any duplicate tare frame within this window.
        self._last_tare: float = 0.0
        super().__init__(
            hass=hass,
            ble_device_resolver=ble_device_resolver,
            mode_name="live_control",
            notification_filter=voice_filter,
            on_event=self._dispatch,
        )

    async def _dispatch(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "weight":
            await self._scale_debouncer.feed(event["weight_g"])
        elif kind == "grinder":
            await self._fire_grinder(event["parameter"], int(event["value"]))
        elif kind == "brewer":
            await self._fire_brewer(event)
        elif kind == "module":
            await self._fire_module(event["module"])
        elif kind == "tare":
            await self._fire_tare()
        elif kind == "recipe_card":
            await self._fire_recipe_card(event["pod_id"])

    async def _fire_weight(self, weight_g: float) -> None:
        self.hass.bus.async_fire(
            "xbloom_scale_weight_announced",
            {"weight_g": round(weight_g, 1), "unit": "g"},
        )

    async def _fire_grinder(self, parameter: str, value: int) -> None:
        # Suppress repeats within 500ms (machine echoes some changes).
        now = time.monotonic()
        last = self._last_grinder.get(parameter)
        if last is not None and last[0] == value and (now - last[1]) < 0.5:
            return
        self._last_grinder[parameter] = (value, now)
        self.hass.bus.async_fire(
            "xbloom_grinder_knob_changed",
            {"parameter": parameter, "value": value},
        )

    async def _fire_brewer(self, event: dict) -> None:
        setting = event["setting"]
        # Keep the native type — ratio is a float (e.g. 15.0), the rest are ints.
        value = event["value"]
        now = time.monotonic()
        last = self._last_brewer.get(setting)
        if last is not None and last[0] == value and (now - last[1]) < 0.5:
            return
        self._last_brewer[setting] = (value, now)
        payload = {"setting": setting, "value": value}
        if "value_name" in event:
            payload["value_name"] = event["value_name"]
        self.hass.bus.async_fire("xbloom_brewer_setting_changed", payload)

    async def _fire_module(self, module: str) -> None:
        # Suppress repeats — the machine emits the same activity transition
        # several times when navigating.
        if self._last_module == module:
            return
        self._last_module = module
        self.hass.bus.async_fire(
            "xbloom_module_entered", {"module": module},
        )

    async def _fire_tare(self) -> None:
        # cmd 9007 = scale tared. Collapse any duplicate within the window.
        now = time.monotonic()
        if (now - self._last_tare) < TARE_DEDUP_SEC:
            return
        self._last_tare = now
        self.hass.bus.async_fire("xbloom_scale_tared", {})

    async def _fire_recipe_card(self, pod_id: str) -> None:
        self.hass.bus.async_fire(
            "xbloom_recipe_card_scanned", {"pod_id": pod_id},
        )
