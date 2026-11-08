"""What Coffee Lab records, in terms no store owns.

Each store — Home Assistant's own, or Notion — maps its rows onto these, so the
rules and the stats never see where a record came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# The stages of a physical bag. Finished and Archived bags stay for their
# history, but nothing is brewed from them.
Status = Literal["unopened", "open", "finished", "archived"]
STATUSES: tuple[Status, ...] = ("unopened", "open", "finished", "archived")

# Why a brew was recorded for review: the inventory rules' flags.
REVIEW_REASONS = (
    "no_bag", "more_than_left", "bag_closed", "tracked_without_amount",
    # Not the inventory rules': a brew stopped once its coffee was ground.
    "stopped_after_grinding",
)
SELECTABLE: tuple[Status, ...] = ("open", "unopened")
# What a Coffee Lab item holds: a bag of coffee counted in grams, a box of
# xPods counted in pods, or tea counted in grams. A brew draws from the kind
# its cup type takes (`inventory.kind_of_cup`).
KINDS: tuple[str, ...] = ("coffee", "xpod", "tea")

# A brew's verdict, as asked once per recipe, bag and version, and the number
# it is kept as in a store's Rating column.
VERDICTS: dict[str, int] = {"again": 3, "fine": 2, "not_again": 1}
VERDICT_OF: dict[int, str] = {n: v for v, n in VERDICTS.items()}
# The question asked of a bag once it is finished.
BUY_AGAIN: tuple[str, ...] = ("yes", "maybe", "no")

# What a person may say about how a brew tasted: each one never asked for,
# kept when given. The scales are the Brews database's own options; the
# notes are free text.
TASTE_SCALES: dict[str, tuple[str, ...]] = {
    "body": ("light", "medium", "full"),
    "acidity": ("low", "medium", "high"),
    "sweetness": ("low", "medium", "high"),
    "clarity": ("low", "medium", "high"),
}
TASTE_NOTES = ("hot_notes", "warm_notes", "cool_notes", "overall_notes", "finish")


@dataclass(frozen=True)
class Bean:
    """A physical purchased bag.

    `status` and `tracked` answer different questions: `status` is what stage
    the bag is in, `tracked` is whether its remaining amount can be counted at
    all. A bag opened before tracking began has no trustworthy starting weight;
    it is open and usable, and simply is not counted down.
    """

    id: str          # the identity — two bags can share a name
    name: str
    status: Status
    remaining_g: float | None = None
    bag_size_g: float | None = None
    tracked: bool = False
    roaster: str = ""
    country: str = ""
    region: str = ""
    process: str = ""
    roaster_notes: str = ""
    opened_on: str = ""   # YYYY-MM-DD
    finished_on: str = ""   # YYYY-MM-DD
    # Asked once, when the bag is finished: would it be bought again.
    buy_again: str = ""   # one of BUY_AGAIN, or "" until answered
    kind: str = "coffee"  # one of KINDS
    # An xPod box: how many pods are left (None while it is not counted
    # down), and the id on its pods' recipe cards, learnt from the first
    # card read while the box is in use.
    pods_left: int | None = None
    pod_id: str = ""


@dataclass(frozen=True)
class Review:
    """Why a brew needs a person to look at it, as a code and its details."""

    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Brew:
    """One brew, as the record keeps it.

    `brewed_at` may be empty for a brew entered by hand without a time;
    `recorded_at`, when the record was written, is then the only date it has.
    """

    id: str
    brewed_at: str
    recorded_at: str
    dose_g: float | None
    brewer: str | None = None
    bean_id: str | None = None
    water_ml: float | None = None
    dripper: str | None = None
    recipe: str | None = None
    recipe_source: str | None = None
    outcome: str | None = None
    run_id: str | None = None
    # What the machine was told for this brew — grind, ratio, temperature_c,
    # flow_rate, duration_s — only what the completion carried.
    settings: dict[str, Any] = field(default_factory=dict)
    review: Review | None = None
    # How it was, when someone said: the verdict as VERDICTS' number, the
    # tasting (TASTE_SCALES and TASTE_NOTES keys), and what to change next time.
    rating: int | None = None
    tasting: dict[str, str] = field(default_factory=dict)
    next_change: str = ""
