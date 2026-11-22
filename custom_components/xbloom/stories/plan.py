"""Which pour and which wait of a brew carries which text.

Every pour with known details gets a pour line. A story part shows when a wait
begins and stays until the next story part, so a wait gets one only when the
story before it has had `MIN_READ_S` to be read and this one has as long
before draining replaces it. The bloom wait always gets one. Draining always
gets the "you" line with its teaser.

A brew whose recipe is not known (started from one of the machine's own
slots) has no waits that can be told from a pour, so its first story goes on
its first pour.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import MIN_READ_S, POUR_PACE_ML_S


@dataclass(frozen=True)
class Slot:
    at: str     # "pour" | "wait" | "draining"
    pour: int   # 1-based; 0 for draining
    kind: str   # "pour_line" | "bag" | "big_story" | "science" | "you"


def _windows(plan: list[dict]) -> list[float]:
    """Seconds from each wait's start to the next wait's (to draining after the last)."""
    windows = []
    for index, pour in enumerate(plan):
        following = plan[index + 1] if index + 1 < len(plan) else None
        pouring = (following["volume_ml"] or 0) / POUR_PACE_ML_S if following else 0
        windows.append((pour["wait_s"] or 0) + pouring)
    return windows


def plan_slots(plan: list[dict] | None, has_bag: bool) -> list[Slot]:
    first = "bag" if has_bag else "big_story"
    if not plan:
        return [Slot("pour", 1, first), Slot("draining", 0, "you")]
    windows = _windows(plan)
    story_waits: list[int] = []
    since_last = 0.0
    for index in range(len(plan)):
        if index == 0 or (since_last >= MIN_READ_S and sum(windows[index:]) >= MIN_READ_S):
            story_waits.append(index + 1)
            since_last = 0.0
        since_last += windows[index]
    kinds = [first] + (["big_story"] if has_bag else [])
    slots: list[Slot] = []
    for index in range(len(plan)):
        pour = index + 1
        slots.append(Slot("pour", pour, "pour_line"))
        if pour in story_waits:
            order = story_waits.index(pour)
            slots.append(Slot("wait", pour, kinds[order] if order < len(kinds) else "science"))
    slots.append(Slot("draining", 0, "you"))
    return slots
