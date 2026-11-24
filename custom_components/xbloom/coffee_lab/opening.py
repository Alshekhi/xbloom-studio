"""When to open the next bag of coffee, and when an open one is past its best.

Roasted coffee fades once its bag is open, so only a few are kept open at a
time and each is finished while it is good. A sealed bag is named to open next
only when there is room under the limit and the open ones are nearly done —
or none of them holds a dose. Which one: the oldest roast that has rested;
coffee just roasted needs some days before it tastes its best.

Pure, and coffee only: tea and xPod boxes keep differently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .habits import habits
from .models import Bean, Brew
from .stats import TEA, made_coffee, moment

# Over this stretch the usual dose is read, as the stock's pace is.
USUAL_DAYS = 30
# With no brews to read it from.
FALLBACK_DOSE_G = 15.0
# The open bags together nearly done: this many doses left or fewer.
DOSES_LEFT = 2


@dataclass(frozen=True)
class Opening:
    limit: int = 2
    rest_days: int = 7
    fade_days: int = 28


def _day(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def _coffee(beans: list[Bean]) -> list[Bean]:
    return [b for b in beans if b.kind == "coffee"]


def usual_dose(brews: list[Brew], now: datetime) -> float:
    """The hot dose brewed most over the last 30 days; else their average; else 15 g."""
    start = now - timedelta(days=USUAL_DAYS)
    usual = habits(brews, [], start, now)["usual"].get("hot")
    if usual:
        return float(usual["dose_g"])
    doses = [
        float(r.dose_g) for r in brews
        if r.dose_g and r.dripper != TEA and made_coffee(r)
        and (when := moment(r.brewed_at or r.recorded_at, now.tzinfo)) is not None
        and start <= when < now
    ]
    return round(sum(doses) / len(doses), 1) if doses else FALLBACK_DOSE_G


def fading(bean: Bean, now: datetime, opening: Opening) -> bool:
    """An open bag of coffee open longer than it keeps its best."""
    opened = _day(bean.opened_on)
    return (bean.kind == "coffee" and bean.status == "open" and opened is not None
            and (now.date() - opened).days > opening.fade_days)


def holds_a_dose(bean: Bean, dose: float) -> bool:
    """Whether a bag has a dose left; one whose amount is not known may well."""
    if not bean.tracked or bean.remaining_g is None:
        return True
    return bean.remaining_g >= dose


def open_next(beans: list[Bean], dose: float, now: datetime, opening: Opening) -> Bean | None:
    """The sealed bag to open now, or None while it is not yet time."""
    coffee = _coffee(beans)
    open_ = [b for b in coffee if b.status == "open"]
    sealed = [b for b in coffee if b.status == "unopened"]
    if not sealed:
        return None
    with_a_dose = [b for b in open_ if holds_a_dose(b, dose)]
    # What the open bags hold for brewing: a bag under a dose holds none. One
    # whose amount is not known may hold plenty, so with it they are never
    # nearly done — naming a bag to open too soon is what this exists to stop.
    unknown = any(not b.tracked or b.remaining_g is None for b in with_a_dose)
    left = sum(b.remaining_g or 0.0 for b in with_a_dose if b.tracked)
    nearly_done = not unknown and left <= DOSES_LEFT * dose
    if with_a_dose and not (len(open_) < opening.limit and nearly_done):
        return None

    def key(b: Bean) -> tuple:
        roasted = _day(b.roast_date)
        if roasted is None:
            return (1, True, date.max)
        rested = (now.date() - roasted).days >= opening.rest_days
        return (0, not rested, roasted)

    return min(sealed, key=key)
