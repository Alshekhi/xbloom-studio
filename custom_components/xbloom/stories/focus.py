"""What to notice in a cup, decided before anything is written about it.

A cup has something to notice only when it differs from what came before in a
way that can be tasted for, by recipe and coffee — every bag of the coffee
(`Bean.same_coffee`), so a coffee bought again keeps its history:

  * `next_change` — the settings asked for after the last cup of the recipe
    with the coffee are the ones brewed now: is what was wrong better?
  * `changed` — the grind, ratio or water temperature differs from that cup;
  * `new_bag` — the same recipe and settings from a new bag of the coffee;
  * `first_time` — the recipe has never been brewed with the coffee.

Anything else has nothing to notice: the same recipe with the same coffee at
the same settings. Nor does the dose make a case — at one ratio it changes how
much is made, not the cup. Built-in, the case is said by a fixed sentence; a
story agent may write that sentence instead, from the same case and details,
and nothing when there is no case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..coffee_lab.models import Bean, Brew
from .content import Content

# The settings compared with the last cup, in the order a sentence names them.
COMPARED = ("grind", "ratio", "temperature_c")


def _number(value: Any) -> float | None:
    # The record may keep a number as text ("50.0").
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Focus:
    case: str
    # setting: (before, now), only those that changed.
    changes: dict[str, tuple[float, float]] = field(default_factory=dict)

    def as_data(self, text: str | None) -> dict[str, Any]:
        """As the brew's events carry it: the case, what changed, and the sentence."""
        return {
            "case": self.case,
            "changes": [{"setting": k, "before": b, "now": n} for k, (b, n) in self.changes.items()],
            "text": text,
        }


def decide(
    recipe: str | None, settings: dict[str, Any], bag: Bean | None,
    beans: list[Bean], brews: list[Brew],
) -> Focus | None:
    """The case this cup is in, or None when there is nothing to notice.

    `brews` newest first, as every store returns them; `beans` every bag,
    finished ones too, so the coffee's earlier bags are known.
    """
    if bag is None or bag.kind != "coffee" or not recipe:
        return None
    from ..versions import parse_next_change

    coffee = {b.id for b in beans if b.same_coffee(bag)} | {bag.id}
    pair = [b for b in brews
            if b.bean_id in coffee and (b.recipe or "").casefold() == recipe.casefold()]
    if not pair:
        return Focus("first_time")
    last = pair[0]
    changes: dict[str, tuple[float, float]] = {}
    for key in COMPARED:
        before, now = _number((last.settings or {}).get(key)), _number(settings.get(key))
        if before is not None and now is not None and before != now:
            changes[key] = (before, now)
    if changes:
        asked = {k: round(v, 2) for k, v in parse_next_change(last.next_change).items()
                 if k in COMPARED}
        if asked and all(k in changes and changes[k][1] == v for k, v in asked.items()):
            return Focus("next_change", changes)
        return Focus("changed", changes)
    if not any(b.bean_id == bag.id for b in pair):
        return Focus("new_bag")
    return None


def _shown(value: float) -> str:
    return f"{value:g}"


def sentence(focus: Focus, content: Content) -> str:
    """The built-in sentence for a case, in the content's language."""
    words = content.entry("focus.changes")
    joiner = content.entry("focus.and")
    named = joiner.join(
        words[k].format(before=_shown(b), now=_shown(n)) for k, (b, n) in focus.changes.items())
    text = content.entry(f"focus.{focus.case}").format(changes=named)
    return text[:1].upper() + text[1:]
