"""What a stretch of brews adds up to.

Pure: it reads brew records and says nothing about where they came from. It
counts what reached the record — a brew started at the machine by hand never
does — and water is the water brewed, not what was drunk.

Every period is on the clock of the `now` it is given: a brew at 02:30 local on
the first belongs to that day and month even though it was the day before in
UTC. A record with no brew time is placed by when it was recorded.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta, tzinfo

from .models import Brew

# A brew with no brewer still happened; it is counted under this rather than
# dropped, so a period's total and its breakdown agree.
UNKNOWN_BREWER = "other"

# Rolling windows end now; calendar ones are the whole day, month or year.
PERIODS = (
    "today", "yesterday", "last_7_days", "last_30_days",
    "this_month", "last_month", "this_year",
)
DEFAULT_PERIOD = "last_7_days"
# A brew's dripper when it was tea (models.Brew.dripper, the cup's label).
TEA = "Tea"


@dataclass(frozen=True)
class Totals:
    brews: int
    coffee_g: float
    water_ml: float
    brews_with_water: int
    by_brewer: tuple[tuple[str, int], ...]   # most used first

    @property
    def top_brewer(self) -> str | None:
        return self.by_brewer[0][0] if self.by_brewer else None


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    before_start: datetime
    before_end: datetime


@dataclass(frozen=True)
class Report:
    period: str
    now: Totals
    before: Totals
    # How the period's brews were made (habits.habits), when the bags were
    # at hand to read them with.
    habits: dict[str, Any] = field(default_factory=dict)

    @property
    def change_in_brews(self) -> int:
        return self.now.brews - self.before.brews


def moment(raw: str, zone: tzinfo) -> datetime | None:
    """A record's timestamp as an instant on `zone`'s clock.

    A value with no offset — a date typed by hand — is read as already local:
    reading it as UTC would move a time that may never have been UTC.
    """
    if not raw or not raw.strip():
        return None
    try:
        # Home Assistant renders a timestamp with a space, not a T.
        parsed = datetime.fromisoformat(raw.strip().replace(" ", "T", 1))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _when(record: Brew, zone: tzinfo) -> datetime | None:
    return moment(record.brewed_at or record.recorded_at, zone)


def made_coffee(record: Brew) -> bool:
    """False for a brew stopped once its coffee was ground: used, not made."""
    return record.review is None or record.review.reason != "stopped_after_grinding"


def totals(records: list[Brew], start: datetime, end: datetime) -> Totals:
    zone = start.tzinfo
    inside = [r for r in records if (m := _when(r, zone)) is not None and start <= m < end]
    # Brews count what made coffee; grams count all the coffee used.
    made = [r for r in inside if made_coffee(r)]
    watered = [r.water_ml for r in inside if r.water_ml is not None]
    tools = Counter(r.brewer or UNKNOWN_BREWER for r in made)
    return Totals(
        brews=len(made),
        # An xPod is coffee; tea's grams are tea.
        coffee_g=float(sum(r.dose_g or 0 for r in inside if r.dripper != TEA)),
        water_ml=float(sum(watered)),
        brews_with_water=len(watered),
        # Ties go to the name, so the answer does not change between reads.
        by_brewer=tuple(sorted(tools.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def _month_start(moment_: datetime, back: int = 0) -> datetime:
    year, month = moment_.year, moment_.month - back
    while month < 1:
        year, month = year - 1, month + 12
    return moment_.replace(year=year, month=month, day=1, hour=0, minute=0,
                           second=0, microsecond=0)


def window(period: str, now: datetime) -> Window:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return Window(midnight, now, midnight - timedelta(days=1), midnight)
    if period == "yesterday":
        day = midnight - timedelta(days=1)
        return Window(day, midnight, day - timedelta(days=1), day)
    if period in ("last_7_days", "last_30_days"):
        days = 7 if period == "last_7_days" else 30
        start = now - timedelta(days=days)
        return Window(start, now, start - timedelta(days=days), start)
    if period == "this_month":
        start = _month_start(now)
        return Window(start, now, _month_start(now, 1), start)
    if period == "last_month":
        end = _month_start(now)
        start = _month_start(now, 1)
        return Window(start, end, _month_start(now, 2), start)
    if period == "this_year":
        start = midnight.replace(month=1, day=1)
        return Window(start, now, start.replace(year=start.year - 1), start)
    raise ValueError(f"unknown period: {period}")


def period_report(records: list[Brew], period: str, now: datetime) -> Report:
    w = window(period, now)
    return Report(period, totals(records, w.start, w.end),
                  totals(records, w.before_start, w.before_end))


def earliest_needed(period: str, now: datetime) -> datetime:
    """How far back a report for `period` reads, its comparison included."""
    return window(period, now).before_start


def _row(records: list[Brew], start: datetime, end: datetime) -> dict:
    t = totals(records, start, end)
    return {"start": start.date().isoformat(), "brews": t.brews,
            "coffee_g": round(t.coffee_g, 1), "water_ml": round(t.water_ml, 1)}


def by_month(records: list[Brew], now: datetime, months: int = 12) -> list[dict]:
    """Brews, coffee and water for each of the last `months` months, this one
    first: the numbers the history charts draw, to be read. Months before the
    first brew in the record are left out."""
    zone = now.tzinfo
    first = min((m for r in records if (m := moment(r.brewed_at or r.recorded_at, zone)) is not None),
                default=None)
    if first is None:
        return []
    rows = []
    for i in range(months):
        start = _month_start(now, i)
        if start < _month_start(first):
            break
        rows.append(_row(records, start, _month_start(now, i - 1) if i else now))
    return rows


def by_week(records: list[Brew], now: datetime, weeks: int = 8) -> list[dict]:
    """The same for each of the last `weeks` weeks, Monday to Sunday, this one
    first; none with no brews at all."""
    if not records:
        return []
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    return [_row(records, monday - timedelta(weeks=i), monday - timedelta(weeks=i - 1) if i else now)
            for i in range(weeks)]
