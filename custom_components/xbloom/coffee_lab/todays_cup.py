"""Today's cup: the bag, the recipe and the dose to brew next, and why.

Few bags are kept open (opening.py); among them the best cup wins and it
changes from day to day. A liked coffee comes first; between coffees liked
alike, not the one brewed last; a bag that would pass its best before it is
finished at that pace is brewed more. A bag past its best is offered only when
nothing else qualifies. With no open bag holding a dose, the sealed bag it is
time to open.

The recipe: those rated *Keep it like this* with the bag, rotating so the same
one is not brewed twice running; then the bag's other proven recipes; else a
community one; else the bag alone.

Pure: the runtime reads the store and the hub and hands everything in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .liking import LIKED, liking
from .models import Bean, Brew
from .opening import Opening, _day, fading, holds_a_dose, open_next
from .stats import TEA, made_coffee, moment


@dataclass(frozen=True)
class OwnRecipe:
    name: str
    rated_again: bool   # rated Keep it like this with this bag
    matched: str        # suggestions' closest match: this_bag, origin_process or origin


@dataclass(frozen=True)
class Pick:
    bag_id: str
    bag: str
    recipe: str | None
    recipe_source: str | None   # "own" or "community"
    hub_id: int | None
    drink: str
    dose_g: float
    reasons: tuple[str, ...]


def _last_brewed(brews: list[Brew], now: datetime) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for r in brews:
        when = moment(r.brewed_at or r.recorded_at, now.tzinfo)
        if r.bean_id and when is not None and when <= now and (r.bean_id not in out or when > out[r.bean_id]):
            out[r.bean_id] = when
    return out


def _rotated(bag: Bean, recipes: list[OwnRecipe], brews: list[Brew]) -> list[OwnRecipe]:
    """Rated-again recipes, the one used last with this bag at the end; then the rest."""
    again = [r for r in recipes if r.rated_again]
    used = {r.recipe.casefold(): (r.brewed_at or r.recorded_at) for r in sorted(
        (b for b in brews if b.bean_id == bag.id and b.recipe),
        key=lambda b: b.brewed_at or b.recorded_at)}
    if len(again) > 1:
        again.sort(key=lambda r: used.get(r.name.casefold(), ""))
    return again + [r for r in recipes if not r.rated_again]


def _recipe_reason(recipe: OwnRecipe) -> str:
    if recipe.rated_again:
        return "rated_again"
    return "brewed_with_bag" if recipe.matched == "this_bag" else "like_this_coffee"


def candidates(
    beans: list[Bean], brews: list[Brew], own: dict[str, list[OwnRecipe]],
    community: dict[str, dict[str, Any]], drink: str, now: datetime, opening: Opening, dose: float,
    daily_g: float | None = None,
) -> list[Pick]:
    """Every cup on offer, best first: the first is today's cup.

    `daily_g` is the coffee usually brewed in a day; one dose when not given.
    """
    coffee = [b for b in beans if b.kind == "coffee"]
    usable = [b for b in coffee if b.status == "open" and holds_a_dose(b, dose)]
    fresh = [b for b in usable if not fading(b, now, opening)]
    past = [b for b in usable if fading(b, now, opening)]
    # Variety is between coffees: a tea or xPod brewed since does not count.
    coffee_ids = {b.id for b in coffee}
    last = _last_brewed([r for r in brews if r.bean_id in coffee_ids], now)
    newest = max(last, key=last.get) if last else None
    liked = {b.id: liking(b, beans, brews) for b in usable}
    sharing = max(1, sum(1 for b in fresh if liked[b.id] == LIKED))

    def use_soon(b: Bean) -> bool:
        opened = _day(b.opened_on)
        if opened is None or not b.tracked or b.remaining_g is None or dose <= 0:
            return False
        days_left = opening.fade_days - (now.date() - opened).days
        # At the pace of taking turns: the day's coffee shared across the liked bags.
        return b.remaining_g / ((daily_g or dose) / sharing) > days_left

    def rank_key(b: Bean) -> tuple:
        return (-liked[b.id], not use_soon(b), b.id == newest, b.opened_on or "9999")

    ranked = sorted(fresh, key=rank_key)

    def bag_reason(i: int, b: Bean) -> tuple[str, ...]:
        if i > 0:
            return ("liked",) if liked[b.id] == LIKED else ()
        other = ranked[1] if len(ranked) > 1 else None
        if other is not None and liked[b.id] > liked[other.id]:
            return ("liked",)
        if use_soon(b):
            return ("use_soon",)
        if other is not None and other.id == newest:
            return ("not_yesterday",)
        return ("liked",) if liked[b.id] == LIKED else ()

    bags: list[tuple[Bean, tuple[str, ...]]] = [(b, bag_reason(i, b)) for i, b in enumerate(ranked)]
    # Past their best: offered after the others, but ranked the same way.
    bags += [(b, ("past_best",)) for b in sorted(past, key=rank_key)]
    if not usable and (nxt := open_next(beans, dose, now, opening)) is not None:
        bags.append((nxt, ("open_next",)))

    picks: list[Pick] = []
    for bag, why in bags:
        def cup(recipe: str | None, source: str | None, hub_id: int | None, more: tuple[str, ...]) -> Pick:
            return Pick(bag.id, bag.name, recipe, source, hub_id, drink, dose, why + more)
        recipes = _rotated(bag, own.get(bag.id, []), brews)
        if recipes:
            picks += [cup(r.name, "own", None, (_recipe_reason(r),)) for r in recipes]
        elif (hub := community.get(bag.id)) is not None:
            picks.append(cup(hub.get("name"), "community", int(hub["id"]), ("community",)))
        else:
            picks.append(cup(None, None, None, ()))
    return picks


# When the card is offered: once a day, until the day's first coffee, and —
# when the first cup of the day has a habit — from shortly before it.
HABIT_DAYS = 30
HABIT_MIN_DAYS = 10
# Most first cups (the middle 60 %) within this many hours of each other is a habit.
HABIT_SPREAD_H = 4
SHOW_BEFORE_H = 1


def _coffee_cups(brews: list[Brew], zone, *, timed: bool = False) -> list[datetime]:
    """When each coffee was brewed; `timed` leaves out a brew given a date alone,
    which says the day but not the hour."""
    return [
        when for r in brews
        if made_coffee(r) and r.dripper != TEA and r.dose_g
        and not (timed and len((r.brewed_at or r.recorded_at).strip()) <= 10)
        and (when := moment(r.brewed_at or r.recorded_at, zone)) is not None
    ]


def shows_from(brews: list[Brew], now: datetime) -> datetime | None:
    """When today's card appears, from the usual first cup of the day; None
    while there is no such habit (too few days, or first cups spread out)."""
    first: dict = {}
    since = (now - timedelta(days=HABIT_DAYS)).date()
    for when in _coffee_cups(brews, now.tzinfo, timed=True):
        day = when.date()
        if since <= day < now.date() and (day not in first or when < first[day]):
            first[day] = when
    if len(first) < HABIT_MIN_DAYS:
        return None
    hours = sorted(w.hour + w.minute / 60 for w in first.values())
    # The middle 60 %: the 20th and 80th percentiles, rounded alike.
    low = hours[round(0.2 * (len(hours) - 1))]
    high = hours[round(0.8 * (len(hours) - 1))]
    if high - low > HABIT_SPREAD_H:
        return None
    minutes = max(0, round((low - SHOW_BEFORE_H) * 60))
    return now.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)


def due(brews: list[Brew], now: datetime, last_coffee: datetime | None = None) -> bool:
    """Whether today's cup is offered now: not yet brewed today, and past the
    usual time when there is one. `last_coffee` is a coffee recorded since the
    brews were read."""
    start = shows_from(brews, now) or now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now < start:
        return False
    cups = _coffee_cups(brews, now.tzinfo) + ([last_coffee.astimezone(now.tzinfo)] if last_coffee else [])
    return not any(when.date() == now.date() and when <= now for when in cups)
