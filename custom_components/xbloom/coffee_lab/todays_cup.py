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
from datetime import datetime
from typing import Any

from .liking import LIKED, liking
from .models import Bean, Brew
from .opening import Opening, _day, fading, holds_a_dose, open_next
from .stats import moment


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
    used = {r.recipe: (r.brewed_at or r.recorded_at) for r in sorted(
        (b for b in brews if b.bean_id == bag.id and b.recipe),
        key=lambda b: b.brewed_at or b.recorded_at)}
    if len(again) > 1:
        again.sort(key=lambda r: used.get(r.name, ""))
    return again + [r for r in recipes if not r.rated_again]


def _recipe_reason(recipe: OwnRecipe) -> str:
    if recipe.rated_again:
        return "rated_again"
    return "brewed_with_bag" if recipe.matched == "this_bag" else "like_this_coffee"


def candidates(
    beans: list[Bean], brews: list[Brew], own: dict[str, list[OwnRecipe]],
    community: dict[str, dict[str, Any]], drink: str, now: datetime, opening: Opening, dose: float,
) -> list[Pick]:
    """Every cup on offer, best first: the first is today's cup."""
    coffee = [b for b in beans if b.kind == "coffee"]
    usable = [b for b in coffee if b.status == "open" and holds_a_dose(b, dose)]
    fresh = [b for b in usable if not fading(b, now, opening)]
    past = [b for b in usable if fading(b, now, opening)]
    last = _last_brewed(brews, now)
    newest = max(last, key=last.get) if last else None
    liked = {b.id: liking(b, beans, brews) for b in usable}
    sharing = max(1, sum(1 for b in fresh if liked[b.id] == LIKED))

    def use_soon(b: Bean) -> bool:
        opened = _day(b.opened_on)
        if opened is None or not b.tracked or b.remaining_g is None or dose <= 0:
            return False
        days_left = opening.fade_days - (now.date() - opened).days
        return b.remaining_g / (dose / sharing) > days_left

    ranked = sorted(fresh, key=lambda b: (
        -liked[b.id], not use_soon(b), b.id == newest, b.opened_on or "9999"))

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
    bags += [(b, ("past_best",)) for b in past]
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
