"""How much a coffee is liked, from what was already asked — never a new question.

A verdict is about a recipe with a bag, not about the coffee: one recipe that
does not suit it says nothing against the coffee. So a coffee is liked when
any recipe was rated *Keep it like this* with it, not liked when every recipe
tried was rated *Doesn't suit this coffee*, and not known otherwise. Bags of
the same coffee bought again count together. A finished bag's *Buy it again*
answer is about the coffee itself, and settles it.
"""
from __future__ import annotations

from .models import VERDICTS, Bean, Brew

NOT_LIKED, NOT_KNOWN, LIKED = 0, 1, 2
_AGAIN, _NOT_AGAIN = VERDICTS["again"], VERDICTS["not_again"]


def liking(bean: Bean, beans: list[Bean], brews: list[Brew]) -> int:
    same = [b for b in beans if b.id == bean.id or b.same_coffee(bean)]
    answered = sorted((b for b in same if b.buy_again in ("yes", "no")),
                      key=lambda b: b.finished_on or "")
    if answered:
        return LIKED if answered[-1].buy_again == "yes" else NOT_LIKED
    ids = {b.id for b in same}
    latest: dict[str, tuple[str, int]] = {}
    for r in brews:
        if r.bean_id in ids and r.recipe and r.rating is not None:
            when = r.brewed_at or r.recorded_at
            if r.recipe not in latest or when >= latest[r.recipe][0]:
                latest[r.recipe] = (when, r.rating)
    verdicts = [rating for _, rating in latest.values()]
    if _AGAIN in verdicts:
        return LIKED
    if verdicts and all(v == _NOT_AGAIN for v in verdicts):
        return NOT_LIKED
    return NOT_KNOWN
