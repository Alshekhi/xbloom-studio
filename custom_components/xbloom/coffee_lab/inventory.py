"""What a confirmed brew does to a bag.

Pure, so the part that can quietly corrupt months of purchase history is
testable without a store or a brew.

Every rule refuses to guess. An inventory that attributes coffee to the wrong
bag, or drifts negative, is harder to trust and harder to repair than one that
stops and says it does not know. Outcomes are codes with their details, never
sentences: whoever shows them words them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xbloom import spec

from .models import Bean

# At or below this, a bag has nothing a normal brew could use. Not zero: 3 g
# left is a finished bag, not a usable one.
DEFAULT_FINISHED_BELOW_G = 5.0


@dataclass(frozen=True)
class Deduct:
    bean_id: str
    grams: float
    new_remaining_g: float | None
    open_bag: bool     # the first use of an unopened bag opens it
    finish: bool       # nothing usable left
    # An xPod box is counted in pods: the pods left after this brew, else None.
    new_pods: int | None = None


@dataclass(frozen=True)
class Skip:
    """Nothing to subtract, and nothing wrong.

    `record_brew` is the distinction that matters: a brew from an untracked bag
    still happened and belongs in the record with its real dose. A duplicate
    completion was already recorded and must not be written twice.
    """

    reason: str
    record_brew: bool = False
    bean_id: str | None = None


@dataclass(frozen=True)
class Flag:
    """Inconsistent: touch nothing, and surface it."""

    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


Decision = Deduct | Skip | Flag


def is_xpod(cup_type: Any) -> bool:
    """Whether the coffee came sealed in a pod rather than out of a bag.

    Read from `spec`'s cup vocabulary, not a remembered number.
    """
    try:
        api = int(cup_type)
    except (TypeError, ValueError):
        return False
    return spec.CUP_API_TO_LABEL.get(api, "").lower() == "xpod"


# The cup type that draws from an xPod box or a tea (spec.CUP_API_TO_LABEL).
CUP_OF_KIND = {
    label.lower(): api for api, label in spec.CUP_API_TO_LABEL.items()
    if label.lower() in ("xpod", "tea")
}


def kind_of_cup(cup_type: Any) -> str:
    """The kind of item a brew in this cup draws from: xpod, tea, or coffee."""
    try:
        label = spec.CUP_API_TO_LABEL.get(int(cup_type), "").lower()
    except (TypeError, ValueError):
        return "coffee"
    return {"xpod": "xpod", "tea": "tea"}.get(label, "coffee")


def _decide_pod(bean: Bean) -> Decision:
    """One pod from an xPod box."""
    if bean.status in ("finished", "archived"):
        return Flag("bag_closed", {"bag": bean.name, "status": bean.status})
    if not bean.tracked or bean.pods_left is None:
        return Skip("untracked", record_brew=True, bean_id=bean.id)
    if bean.pods_left < 1:
        return Flag("more_than_left", {"bag": bean.name, "pods_left": bean.pods_left, "pods": 1})
    left = bean.pods_left - 1
    return Deduct(
        bean_id=bean.id, grams=0.0, new_remaining_g=None,
        open_bag=bean.status == "unopened", finish=left == 0, new_pods=left,
    )


def decide_consumption(
    *,
    bean: Bean | None,
    grams: Any,
    cup_type: Any = None,
    already_processed: bool = False,
    unattributed: bool = False,
    finished_below_g: float = DEFAULT_FINISHED_BELOW_G,
) -> Decision:
    # Idempotency first: a completion can arrive twice, and subtracting the
    # same dose twice is silent, permanent damage.
    if already_processed:
        return Skip("already_counted")

    # Said at the start to come from no bag. Recorded, and never flagged as a
    # brew whose bag was forgotten.
    if unattributed:
        return Skip("unattributed", record_brew=True)

    # An xPod or tea brew draws from an item of its own kind, never from a bag
    # of coffee. With none of its kind in use it is recorded against nothing:
    # a pod or tea nobody keeps count of is not worth flagging.
    kind = kind_of_cup(cup_type)
    if kind != "coffee" and (bean is None or bean.kind != kind):
        return Skip(kind, record_brew=True)
    if kind == "xpod":
        return _decide_pod(bean)

    try:
        grams = float(grams)
    except (TypeError, ValueError):
        return Skip("no_dose")
    if grams <= 0:
        return Skip("no_dose")

    # Never guess which bag: attributing coffee to the wrong one is the one
    # outcome that cannot be undone by looking.
    if bean is None:
        return Flag("no_bag", {"grams": grams})
    # A coffee brew charged to an xPod box or a tea: the coffee's bag was not
    # chosen.
    if bean.kind != kind:
        return Flag("no_bag", {"grams": grams, "bag": bean.name})

    if bean.status in ("finished", "archived"):
        return Flag("bag_closed", {"bag": bean.name, "status": bean.status})

    # Untracked is a deliberate state, not a fault: record the brew against the
    # bag and leave its unknown balance unknown. Flagging it would nag forever.
    if not bean.tracked:
        return Skip("untracked", record_brew=True, bean_id=bean.id)

    # Tracked with no balance is inconsistent: something cleared it, or the bag
    # was marked tracked before it was weighed.
    if bean.remaining_g is None:
        return Flag("tracked_without_amount", {"bag": bean.name})

    new_remaining = round(bean.remaining_g - grams, 1)

    # Real inventory drifts — manual brews, spills, a missed entry. Correcting
    # it silently would erase the evidence that it drifted.
    if new_remaining < 0:
        return Flag(
            "more_than_left",
            {"bag": bean.name, "remaining_g": bean.remaining_g, "grams": grams},
        )

    return Deduct(
        bean_id=bean.id,
        grams=grams,
        new_remaining_g=new_remaining,
        open_bag=bean.status == "unopened",
        finish=new_remaining <= finished_below_g,
    )
