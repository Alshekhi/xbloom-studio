"""How a person brews, read from a stretch of the record.

Pure, like stats: it reads brew records and bags and says what they show —
the days brewed, the usual dose for a hot and an iced cup, the coffee and
recipe reached for most, how the verdicts went. Nothing here is guessed: a
habit needs enough brews behind it, and where they say too little the answer
is left out rather than made up.

A brew stopped once its coffee was ground is not a cup, so it counts toward
none of this. Tea is a brew but not a coffee, so it never sets a coffee dose
or becomes the top coffee.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from ..const import ICED_RATIO_MAX
from .models import VERDICT_OF, Bean, Brew
from .stats import TEA, made_coffee, moment

# A usual dose needs this many brews of that drink behind it.
MIN_USUAL = 3
# A time of day is named only from this many brews, and only when it holds
# this share of them; otherwise the brews are spread and there is no habit.
MIN_TIMED = 5
TIME_SHARE = 0.6
# Each part of the day by the hour it starts; night runs past midnight.
_PARTS = ((5, "morning"), (12, "afternoon"), (17, "evening"), (21, "night"))


def _part_of_day(hour: int) -> str:
    part = "night"
    for start, name in _PARTS:
        if hour >= start:
            part = name
    return part


def _drink(record: Brew) -> str | None:
    """Hot or iced by the brew's ratio; None for tea or a brew with no ratio."""
    if record.dripper == TEA:
        return None
    ratio = record.settings.get("ratio")
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        return None
    return "iced" if ratio <= ICED_RATIO_MAX else "hot"


def _most(values: list[Any]) -> Any:
    """The most common value; a tie goes to the larger, so it is stable."""
    counts = Counter(values)
    return max(counts, key=lambda v: (counts[v], v))


def _longest_run(days: set[date]) -> int:
    best = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def _top(counts: Counter) -> dict[str, Any] | None:
    if not counts:
        return None
    # Ties go to the name, so the answer does not change between reads.
    name, n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"name": name, "brews": n}


def habits(records: list[Brew], beans: list[Bean], start: datetime, end: datetime) -> dict[str, Any]:
    """What the brews from `start` to `end` show; `beans` every bag, finished too."""
    zone = start.tzinfo
    cups = [
        (r, when) for r in records
        if made_coffee(r)
        and (when := moment(r.brewed_at or r.recorded_at, zone)) is not None
        and start <= when < end
    ]
    by_id = {b.id: b for b in beans}
    days = {when.date() for _, when in cups}
    # The calendar days the window touches: a rolling week from 10:00 seven
    # days ago touches eight dates, any of which can hold a brew. The end is
    # exclusive, so a window ending at midnight does not reach the next day.
    first_day = start.date()
    last_day = (end - timedelta(microseconds=1)).date()
    days_in_period = max(1, (last_day - first_day).days + 1)

    usual: dict[str, dict[str, Any]] = {}
    for drink in ("hot", "iced"):
        mine = [r for r, _ in cups if _drink(r) == drink and r.dose_g]
        if len(mine) >= MIN_USUAL:
            usual[drink] = {
                "dose_g": float(_most([float(r.dose_g) for r in mine])),
                "ratio": float(_most([float(r.settings["ratio"]) for r in mine])),
                "brews": len(mine),
            }

    # A coffee bought again is a second bag of the same coffee: counted as
    # one, as Bean.same_coffee has it, under the name of the first bag seen.
    per_coffee: Counter = Counter()
    first_bag: dict[tuple[str, str], Bean] = {}
    for r, _ in cups:
        bean = by_id.get(r.bean_id or "")
        if bean is not None and bean.kind == "coffee":
            key = (bean.name.strip().casefold(), bean.roaster.strip().casefold())
            first_bag.setdefault(key, bean)
            per_coffee[key] += 1
    # Two roasters' coffees can share a name; the roaster tells them apart.
    shared = Counter(name for name, _ in per_coffee)
    coffees: Counter = Counter()
    for key, n in per_coffee.items():
        bag = first_bag[key]
        label = f"{bag.name} ({bag.roaster})" if shared[key[0]] > 1 and bag.roaster else bag.name
        coffees[label] += n
    recipes = Counter(r.recipe for r, _ in cups if r.recipe)
    verdicts = Counter(VERDICT_OF[r.rating] for r, _ in cups if r.rating in VERDICT_OF)

    time_of_day = None
    if len(cups) >= MIN_TIMED:
        parts = Counter(_part_of_day(when.hour) for _, when in cups)
        part, n = parts.most_common(1)[0]
        if n / len(cups) >= TIME_SHARE:
            time_of_day = part

    opened = sorted({
        b.name for b in beans
        if b.kind == "coffee" and b.opened_on and first_day.isoformat() <= b.opened_on <= last_day.isoformat()
    })

    return {
        "days_brewed": len(days),
        "days_in_period": days_in_period,
        "longest_streak_days": _longest_run(days),
        "cups_per_brewing_day": round(len(cups) / len(days), 1) if days else None,
        "usual": usual,
        "top_coffee": _top(coffees),
        "top_recipe": _top(recipes),
        "verdicts": dict(verdicts),
        "time_of_day": time_of_day,
        "bags_opened": opened,
    }
