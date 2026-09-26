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
