"""Live-session listener (Method 2) — the held/streaming BLE connection.

When ``switch.xbloom_studio_connect`` is ON, holds a single BLE connection
and fires an HA bus event per reading. These events are **voice-agnostic**:
they feed sensors, the dashboard, and — via the live_control_announce
blueprint — optional spoken announcements. Voice is just one consumer; this
listener has no opinion about speech. The spoken text and its language live
in the blueprint, not here:
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

from xbloom.ble import (
    NOTIFY_BREW_PATTERN, NOTIFY_BREW_RATIO, NOTIFY_BREW_TEMP,
    NOTIFY_GRIND_SIZE, NOTIFY_GRIND_SPEED,
    NOTIFY_PODS,
    NOTIFY_TARE,
    NOTIFY_WEIGHT_2, NOTIFY_WEIGHT_ALT,
    PATTERN_NAMES,
)
from xbloom.mode_listener import IDLE_TIMEOUT_SEC, XBloomModeListener
from xbloom import spec

_LOGGER = logging.getLogger(__name__)

# Range guards
SIZE_BLE_MIN, SIZE_BLE_MAX = 31, 110   # BLE raw → UI 1-80
SPEED_RPM_MIN, SPEED_RPM_MAX = 60, 120
RATIO_MIN, RATIO_MAX = 1.0, 30.0       # brew ratio 1:N

# Brewer temperature knob (cmd 8108) domain. The knob broadcasts the *display*
# value (39..96 on the J15), whose two ends are the RT/BP sentinels. The domain
# bounds and the RT/BP naming both live in the library's unified temperature model
# (spec.brew_temp_*) so nothing here can diverge from the recipe/drive paths.
TEMP_C_MIN, TEMP_C_MAX = spec.BREW_TEMP_DISPLAY_MIN, spec.BREW_TEMP_DISPLAY_MAX

# Scale debounce
SCALE_STABLE_DELTA_G = 1.0
SCALE_STABLE_HOLD_SEC = 2.0
SCALE_RE_REPORT_DELTA_G = 1.0

# Guard against any duplicate tare (9007) frame; real presses are seconds apart.
TARE_DEDUP_SEC = 0.5


def _ble_size_to_ui(ble_value: int) -> int:
    """Per brAzzi64 PROTOCOL.md: UI = max(1, BLE − 30)."""
    return max(1, int(ble_value) - 30)


def session_event_filter(decoded: dict) -> dict | None:
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
        # The knob reports in the machine's display unit (°C 39-96 or °F
        # 103-204); normalize to the canonical Celsius display domain so a
        # Fahrenheit machine isn't silently dropped.
        v = spec.brew_temp_knob_to_celsius(decoded["temperature_c"])
        if v is None:
            return None
        event = {"kind": "brewer", "setting": "temperature", "value": v}
        # Tag the two sentinel ends so consumers (announce blueprint, dashboard)
        # can say "room temperature"/"boiling point" instead of "39"/"96".
        name = spec.brew_temp_sentinel_name(v)
        if name is not None:
            event["value_name"] = name
        return event

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

    # Module / activity detection (confirmed against live frames 2026-07-24):
    #   cmd 8023 activity=1   → home / idle screen
    #   cmd 8023 activity=2   → Grinder screen. Fires on BOTH physical left-knob
    #                           entry (right after the 9000 below) AND HA/app
    #                           command entry via 8006 — which does NOT emit 9000.
    #   cmd 8023 activity=3   → Brewer (drip/brew) screen entered
    #   cmd 8023 activity=4/5 → Scale screen (settling). Fires on scale entry —
    #                           incl. HA/app command entry via 8003, which does
    #                           NOT emit 9002 — and again on each tare. Mapped to
    #                           scale; _fire_module's dedup collapses the repeats.
    #   cmd 8023 activity=65  → Auto/EasyMode screen (triple-press, recipes A/B/C)
    #   cmd 9000              → Grinder entered (physical left-knob press only)
    #   cmd 9002              → Scale entered (physical right-knob press only)
    # 9000/9002 fire ONLY on physical entry; the 8023 activity codes fire either
    # way, so we need BOTH to catch dashboard-driven navigation as well.
    if cmd == 8023:
        activity = decoded.get("activity")
        if activity == 1:
            return {"kind": "module", "module": "home"}
        if activity == 2:
            return {"kind": "module", "module": "grinder"}
        if activity == 3:
            return {"kind": "module", "module": "brewer"}
        if activity in (4, 5):
            return {"kind": "module", "module": "scale"}
        if activity == 65:
            return {"kind": "module", "module": "auto"}
    elif cmd == 9000:
        return {"kind": "module", "module": "grinder"}
    elif cmd == 9002:
        return {"kind": "module", "module": "scale"}
    # NB: we deliberately do NOT decode an 8022 echo as "home". 8022 is
    # state-gated (fw:1847-1867) and is REJECTED from a live module screen, so
    # its echo does NOT mean the machine went home — decoding it announced a
    # false "home" while the machine stayed on the module. Leaving a module now
    # uses the QUIT commands (8012/8013/8014), which navigate for real and emit
    # 8023 activity=1 — the genuine home signal handled above.

    return None


class _ScaleDebouncer:
    """Debounce a noisy weight stream — only fire on a settled reading."""

    def __init__(self, fire: Callable[[float], Awaitable[None]]) -> None:
        self._fire = fire
        self._last_weight: float | None = None
        self._stable_since: float | None = None
        self._reported_weight: float | None = None

    def reset(self) -> None:
        """Forget prior state so the next settled reading fires fresh.

        Called when the user leaves the scale module, so that re-entering the
        scale re-announces the current weight instead of being suppressed by
        the re-report dedup below.
        """
        self._last_weight = None
        self._stable_since = None
        self._reported_weight = None

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
            self._reported_weight is not None
            and abs(weight_g - self._reported_weight) <= SCALE_RE_REPORT_DELTA_G
        ):
            return
        self._reported_weight = weight_g
        await self._fire(weight_g)


class LiveSessionListener(XBloomModeListener):
    """Single listener that fires the right event per cmd type."""

    def __init__(
        self, hass, ble_device_resolver, idle_timeout_s: float = IDLE_TIMEOUT_SEC,
        entry_id: str | None = None,
    ) -> None:
        # Integration layer owns the HA handle; the library base is HA-free and
        # reaches the host only through the injected callbacks below.
        self.hass = hass
        self._entry_id = entry_id
        self._scale_debouncer = _ScaleDebouncer(self._fire_weight)
        # Dedup state for grinder + brewer + module entries
        self._last_grinder: dict[str, tuple[int, float]] = {}
        self._last_brewer: dict[str, tuple[int, float]] = {}
        self._last_module: str | None = None
        # Collapse any duplicate tare frame within this window.
        self._last_tare: float = 0.0
        super().__init__(
            ble_device_resolver=ble_device_resolver,
            mode_name="connect",
            notification_filter=session_event_filter,
            on_event=self._dispatch,
            on_lifecycle=self._fire_lifecycle,
            task_factory=self._make_background_task,
            idle_timeout_s=idle_timeout_s,
            on_raw=self._forward_raw,
        )

    def _forward_raw(self, decoded: dict) -> None:
        """Dispatch every decoded notification to the same signal the snapshot /
        brew paths use, so the machine-status sensors and setting selects stay
        in sync with the machine's heartbeat during a held Connect session — the
        integration reflects the machine with no exception, not just via
        Refresh status. Runs on the event loop (scheduled by the library)."""
        if self._entry_id is None:
            return
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .ble_entities import signal_event
        async_dispatcher_send(self.hass, signal_event(self._entry_id), decoded)

    def _fire_lifecycle(self, phase: str, payload: dict) -> None:
        """Bridge the listener's lifecycle transitions onto the HA event bus as
        ``xbloom_connect_<phase>`` (consumed by switch.py + the
        live_control_announce blueprint)."""
        self.hass.bus.async_fire(f"xbloom_{self.mode_name}_{phase}", payload)

    def _make_background_task(self, coro, name):
        """Spawn the library's run loop via HA's background-task helper — the
        only spawn empirically observed to deliver bleak notifications."""
        if hasattr(self.hass, "async_create_background_task"):
            return self.hass.async_create_background_task(coro, name=name)
        return self.hass.loop.create_task(coro)

    async def _dispatch(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "weight":
            # The load cell streams weight continuously, on every module — so
            # without this gate the scale weight would be announced in the
            # grinder, brewer, everywhere. A settled weight is only meaningful
            # (and only wanted as speech) while the user is on the scale module.
            # The scale-weight SENSOR is fed separately in ble_entities and is
            # unaffected by this gate.
            if self._last_module == "scale":
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
            "xbloom_scale_weight_stable",
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
        # Leaving the scale: clear debounce state so the next scale visit
        # re-announces the current weight rather than being deduped away.
        if module != "scale":
            self._scale_debouncer.reset()
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
