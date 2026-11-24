"""What is left of each kind of item, and when it crosses the level set for it.

Each kind — coffee, xPod, tea — is counted over the items on hand, open or
unopened: a tracked item by what is left, an unopened one not yet counted by
its size. An item whose amount cannot be known (opened before it was counted)
is left out and named, and while one is, the amount and what follows from it
are only a floor: never low, since the item left out is usually not empty.
Bags are always known.

Days and cups come from the last 30 days of that kind's brews, every brewer,
the recent ones weighing more, and need a few of them to mean anything. The pace is over the days those
brews span, so a home with only a week of history is not read as brewing a
quarter as much. A kind can turn low only once the
home has had an item of it, so a home without tea never hears about tea.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Bean, Brew
from .stats import moment

MEASURES: dict[str, tuple[str, ...]] = {
    "coffee": ("days", "grams", "cups", "bags"),
    "tea": ("days", "grams", "cups", "bags"),
    "xpod": ("days", "pods", "boxes"),
}
DEFAULT_MEASURE = {"coffee": "days", "tea": "grams", "xpod": "pods"}
DEFAULT_LEVEL: dict[str, float] = {
    "days": 7, "grams": 250, "cups": 10, "bags": 1, "pods": 5, "boxes": 1,
}
# Where a kind's own starting level differs: tea is weighed in far smaller
# amounts than coffee, so 250 g would be low the moment a tin is added.
_KIND_LEVEL: dict[tuple[str, str], float] = {("tea", "grams"): 50}


def default_level(kind: str, measure: str) -> float:
    return _KIND_LEVEL.get((kind, measure), DEFAULT_LEVEL[measure])
PACE_DAYS = 30
# Each brew counts half as much a week older, so the pace follows a change of
# habit within days while one unusual day does not swing it.
HALF_LIFE_DAYS = 7
# Fewer brews than this in the window say too little about a pace.
MIN_BREWS = 5
# The measures counted from the amount, which an item left out makes a floor.
_FROM_AMOUNT = ("days", "grams", "cups", "pods")
_ON_HAND = ("open", "unopened")


@dataclass(frozen=True)
class Stock:
    kind: str
    kept: bool
    # Grams (coffee, tea) or pods (xPod) of the items whose amount is known.
    amount: float | None
    bags: int
    cups: float | None
    days: float | None
    # The items on hand whose amount is not known, by id.
    unknown: tuple[str, ...] = ()


def _weight(age_days: float) -> float:
    return 0.5 ** (max(0.0, age_days) / HALF_LIFE_DAYS)


def _amount(bean: Bean) -> float | None:
    if bean.kind == "xpod":
        return float(bean.pods_left) if bean.tracked and bean.pods_left is not None else None
    if bean.tracked and bean.remaining_g is not None:
        return float(bean.remaining_g)
    if bean.status == "unopened" and bean.bag_size_g:
        return float(bean.bag_size_g)
    return None


def pace(kind: str, beans: list[Bean], brews: list[Brew], now: datetime) -> tuple[float, float] | None:
    """(per cup, per day) a kind is used at — grams, or pods for xPods — or
    None with too few brews to tell. `beans` every item, finished ones too."""
    ids = {b.id for b in beans if b.kind == kind}
    since = now - timedelta(days=PACE_DAYS)
    used = [
        (r, when) for r in brews
        # A brew from no bag, with a dose, was coffee from somewhere: it
        # still says how fast coffee goes.
        if (r.bean_id in ids or (kind == "coffee" and r.bean_id is None and r.dose_g))
        and (when := moment(r.brewed_at or r.recorded_at, now.tzinfo))
        and since <= when <= now
    ]
    if len(used) < MIN_BREWS:
        return None

    def drawn_by(r: Brew) -> float:
        return 1.0 if kind == "xpod" else float(r.dose_g or 0.0)

    weights = [_weight((now - when).total_seconds() / 86400) for _, when in used]
    drawn = sum(w * drawn_by(r) for w, (r, _) in zip(weights, used))
    if drawn <= 0:
        return None
    first = min(when for _, when in used)
    span = min(PACE_DAYS, max(1, math.ceil((now - first).total_seconds() / 86400)))
    # Every day of the span counts, a day without a brew included, weighted
    # as the brews are.
    return drawn / sum(weights), drawn / sum(_weight(d) for d in range(span))


def stock_of(kind: str, beans: list[Bean], brews: list[Brew], now: datetime) -> Stock:
    """`beans` every item, finished ones too; `brews` newest first."""
    mine = [b for b in beans if b.kind == kind]
    on_hand = [b for b in mine if b.status in _ON_HAND]
    known = [(b, _amount(b)) for b in on_hand]
    amount = sum(a for _, a in known if a is not None)
    unknown = tuple(b.id for b, a in known if a is None)
    cups = days = None
    if (rate := pace(kind, beans, brews, now)) is not None:
        per_cup, per_day = rate
        cups = round(amount / per_cup, 1)
        days = round(amount / per_day, 1)
    return Stock(kind, bool(mine), amount if (on_hand or mine) else None, len(on_hand),
                 cups, days, unknown)


def floor(stock: Stock, measure: str) -> float | None:
    """The figure counting only what is known: at least this much."""
    if measure in ("bags", "boxes"):
        return float(stock.bags)
    if measure in ("grams", "pods"):
        return stock.amount
    return stock.cups if measure == "cups" else stock.days


def figure(stock: Stock, measure: str) -> float | None:
    """The figure compared with the level; None when it cannot be known."""
    if measure in _FROM_AMOUNT and stock.unknown:
        return None
    return floor(stock, measure)


def crossing(
    stored: bool | None, value: float | None, level: float, least: float | None = None,
) -> tuple[bool | None, str | None]:
    """The low state after this figure, and "low" or "restored" when it crossed.

    Only a known figure against a level above 0 moves it: one that becomes
    unknown, or a level set to 0, leaves it as it was and tells nothing —
    except that what is counted (`least`) reaching the level already ends a
    low, whatever the items not counted hold. With no state yet — the first
    time — it is set without telling.
    """
    if not level:
        return stored, None
    if value is None:
        if stored and least is not None and least >= level:
            return False, "restored"
        return stored, None
    low = value < level
    if stored is None or stored == low:
        return low, None
    return low, "low" if low else "restored"
