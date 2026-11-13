"""Whether the tank will last the brew, from the machine's low-water switch.

The machine has no water-level reading: one switch says "water" or "low",
and it trips with about `spec.WATER_RESERVE_ML` left. From that moment the
water the brew has poured (RD_WATER_VOLUME, in ml) says how much is left,
and the recipe says how much the brew still needs. A brew that runs the
tank dry pauses on the water-shortage screen until it is refilled and the
knob is pressed.

`WaterTracker` follows one brew Home Assistant started. It knows nothing of
Home Assistant: the brew task feeds it decoded frames with a monotonic
clock and publishes what it decides.
"""
from __future__ import annotations

from xbloom import spec
from xbloom.ble import (
    NOTIFY_BLOOM,
    NOTIFY_BREW_RESUMED,
    NOTIFY_LACK_OF_WATER,
    NOTIFY_MACHINE_ACTIVITY,
    NOTIFY_MACHINE_INFO,
    NOTIFY_MACHINE_RESUMED,
    NOTIFY_WATER_VOLUME,
)

from .ble_entities import ACTIVITY_WATER_SHORTAGE

# The switch has no debounce, so water sloshing while pouring can flick it
# back to "water" for a moment. The firmware itself counts a refill only
# after the switch has read "water" for over 20 of its 100 ms polls.
WATER_REFILL_HOLD_S = 2.0

_RESUMED = (NOTIFY_MACHINE_RESUMED, NOTIFY_BREW_RESUMED)   # the knob, or Home Assistant


def recipe_water_ml(recipe: dict) -> float:
    """The water a recipe pours: its pours only, since bypass is sent as zero."""
    return sum(float(p.get("volume_ml") or 0) for p in recipe.get("pours") or [])


class WaterTracker:
    """The tank during one brew: tripped, paused for water, refilled."""

    def __init__(self, recipe_water_ml: float) -> None:
        self._recipe_ml = float(recipe_water_ml)
        self._dispensed = 0.0
        self._pouring = False
        self._switch_low: bool | None = None
        self._tripped_at: float | None = None
        self._high_since: float | None = None
        self._paused_since: float | None = None
        self._refilled = False
        self._paused_total = 0.0

    def feed(self, decoded: dict, now: float) -> tuple[str, dict] | None:
        """Take one frame; return the decision it led to, if any."""
        cmd = decoded.get("cmd")
        if cmd == NOTIFY_WATER_VOLUME and "water_ml" in decoded:
            self._dispensed = float(decoded["water_ml"])
        elif cmd == NOTIFY_BLOOM:
            self._pouring = True

        decision = None
        if cmd in (NOTIFY_LACK_OF_WATER, NOTIFY_MACHINE_INFO) and "water_enough" in decoded:
            decision = self._switch(decoded["water_enough"] == 0, now)
        elif cmd == NOTIFY_MACHINE_ACTIVITY and decoded.get("activity") == ACTIVITY_WATER_SHORTAGE:
            if self._paused_since is None:
                self._paused_since = now
                self._refilled = False
                decision = ("water_paused", {"water_needed_ml": round(self._needed())})
        elif cmd in _RESUMED and self._paused_since is not None:
            self._paused_total += now - self._paused_since
            self._paused_since = None

        # A "water" reading that held is a refill made while still pouring.
        if self._tripped_at is not None and self._water_held(now):
            self._tripped_at = None
        return decision

    def _water_held(self, now: float) -> bool:
        return (self._switch_low is False and self._high_since is not None
                and now - self._high_since >= WATER_REFILL_HOLD_S)

    def _switch(self, low: bool, now: float) -> tuple[str, dict] | None:
        # A low reading trips the switch only after a steady "water" — or
        # with no reading before it. A "water" blip shorter than the hold is
        # slosh, whether the tank had already tripped or started out low.
        steady = self._switch_low is None or self._water_held(now)
        was_low = self._switch_low
        self._switch_low = low
        if low:
            self._high_since = None
            if (steady and self._pouring and self._tripped_at is None
                    and self._paused_since is None):
                self._tripped_at = self._dispensed
                return ("water_low", self.state)
            return None
        if was_low is not False:
            self._high_since = now
        if self._paused_since is not None:
            self._tripped_at = None
            if not self._refilled:
                self._refilled = True
                return ("water_refilled", {})
        return None

    def _needed(self) -> float:
        return max(0.0, self._recipe_ml - self._dispensed)

    def _left(self) -> float:
        return max(0.0, spec.WATER_RESERVE_ML - (self._dispensed - self._tripped_at))

    @property
    def state(self) -> dict | None:
        """The amounts while the switch has tripped in this brew, else None."""
        if self._tripped_at is None:
            return None
        needed, left = self._needed(), self._left()
        short = max(0.0, needed - left)
        return {
            "water_left_ml": round(left),
            "water_needed_ml": round(needed),
            "water_short_ml": round(short),
            "enough_to_finish": round(short) == 0,
        }

    def paused_seconds(self, now: float) -> float:
        """How long the brew has waited for water, including a wait under way."""
        ongoing = now - self._paused_since if self._paused_since is not None else 0.0
        return self._paused_total + ongoing

    def completion_fields(self) -> dict:
        """What the finished brew says about the tank."""
        if not self._switch_low:
            return {}
        if self._tripped_at is None:
            return {"tank_low": True}
        return {"tank_low": True, "water_left_ml": round(self._left())}
