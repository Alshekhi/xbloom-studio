"""Which saved recipe to brew with a bag: the brew record's answer.

The record says which recipe each xBloom brew used and from which bag, and
each bag says where it was grown and how it was processed. So the recipes
brewed with this very bag, or with coffee like it, are the ones already
proven on this machine. A recipe counts for a brew with:

  * this bag                      — weight 3
  * a bag of the same origin and process — weight 2
  * a bag of the same origin      — weight 1

and the recipes still in the library are ranked by that total, then by how
recently they were brewed. A verdict moves it: each brew rated Again adds 2,
each rated Not again takes 1 away, and a recipe whose latest verdict with this
very bag is Not again is not suggested for it at all. Nothing is suggested
from a coffee with nothing in common with the bag; that is the community's to
answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .coffee_lab.lab import XBLOOM_BREWER
from .coffee_names import name_key
from .coffee_lab.models import Bean, Brew
from .coffee_lab.stats import made_coffee
from .versions import versions_of

# How far back the record is read: a year of brews is enough to know what a
# coffee is liked with, and keeps the read bounded.
HISTORY_DAYS = 365
# How many of your own recipes are offered.
OWN_SUGGESTIONS = 3

SAME_BAG, SAME_KIND, SAME_ORIGIN = "this_bag", "origin_process", "origin"
_WEIGHT = {SAME_BAG: 3, SAME_KIND: 2, SAME_ORIGIN: 1}
# What a verdict adds to a recipe's total: Again, Fine, Not again.
_VERDICT_BONUS = {3: 2, 2: 0, 1: -1}
NOT_AGAIN = 1


@dataclass(frozen=True)
class OwnSuggestion:
    name: str
    brews: int           # brews of it at the closest match — with this bag, if any
    matched: str         # that closest match: SAME_BAG, SAME_KIND or SAME_ORIGIN
    last_brewed: str     # the newest of them, as the record has it
    # Its rated versions with this bag, newest first (versions.versions_of).
    versions: list[dict[str, Any]] = field(default_factory=list)


def _same(a: str, b: str) -> bool:
    """One country or process however it was typed (coffee_names.name_key)."""
    return bool(name_key(a)) and name_key(a) == name_key(b)


def _match(bag: Bean, other: Bean | None, bean_id: str | None) -> str | None:
    if bean_id == bag.id:
        return SAME_BAG
    if other is None or not _same(bag.country, other.country):
        return None
    return SAME_KIND if _same(bag.process, other.process) else SAME_ORIGIN


def rank(
    bag: Bean, beans: list[Bean], brews: list[Brew], library: list[dict[str, Any]],
) -> list[OwnSuggestion]:
    """Your saved recipes for this bag, best first. Pure: no I/O."""
    by_id = {b.id: b for b in beans}
    in_library = {str(r.get("name") or "").casefold(): str(r.get("name")) for r in library if r.get("name")}
    scores: dict[str, dict[str, Any]] = {}
    for brew in brews:
        if brew.brewer != XBLOOM_BREWER or not brew.recipe or not made_coffee(brew):
            continue
        name = in_library.get(brew.recipe.casefold())
        if name is None:  # renamed or deleted since: nothing to brew
            continue
        matched = _match(bag, by_id.get(brew.bean_id or ""), brew.bean_id)
        if matched is None:
            continue
        entry = scores.setdefault(
            name, {"score": 0, "counts": {}, "best": matched, "last": "", "bag_verdict": None},
        )
        entry["score"] += _WEIGHT[matched] + _VERDICT_BONUS.get(brew.rating, 0)
        # Brews come newest first, so the first rated one with this bag is
        # its latest verdict with it.
        if matched == SAME_BAG and brew.rating is not None and entry["bag_verdict"] is None:
            entry["bag_verdict"] = brew.rating
        entry["counts"][matched] = entry["counts"].get(matched, 0) + 1
        if _WEIGHT[matched] > _WEIGHT[entry["best"]]:
            entry["best"] = matched
        when = brew.brewed_at or brew.recorded_at
        entry["last"] = max(entry["last"], when or "")
    scores = {n: e for n, e in scores.items() if e["bag_verdict"] != NOT_AGAIN}
    ranked = sorted(scores.items(), key=lambda kv: (kv[1]["score"], kv[1]["last"]), reverse=True)
    return [
        # Ranked on every brew that counted, but the count said is the closest
        # match's alone: "3 times with this bag" must not include other bags.
        OwnSuggestion(
            name, e["counts"][e["best"]], e["best"], e["last"], versions_of(brews, name, bag.id),
        )
        for name, e in ranked[:OWN_SUGGESTIONS]
    ]


async def async_own_suggestions(lab: Any, bag: Bean | None, library: list[dict[str, Any]]) -> list[OwnSuggestion]:
    """`rank`, reading the record and every bag (finished ones too)."""
    if lab is None or bag is None:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    brews = await lab.store.async_list_brews(since=since)
    beans = await lab.store.async_list_beans(selectable_only=False)
    return rank(bag, beans, brews, library)
