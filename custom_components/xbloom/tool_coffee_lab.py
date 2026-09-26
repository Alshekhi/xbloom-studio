"""The `coffee_lab` AI tool: the bags of coffee, and what was brewed from them.

Offered only while Coffee Lab is switched on. Its actions are Coffee Lab's
shared actions, so the tool and the services cannot disagree. The open and
unopened bags are named in the description, rebuilt on every request — a hint
only: a client that caches the tool list may show an old one, and every action
resolves a name against the bags as they are now.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from .coffee_lab import actions
from .coffee_lab.lab import CoffeeLab
from .coffee_lab.models import STATUSES, Bean
from .coffee_lab.stats import PERIODS
from .tool_common import Spec, check_arguments as _check, describe as _describe

BAG = ("bean", "bean_id")

ACTIONS: dict[str, Spec] = {
    "list_beans": Spec(actions.list_beans, "every open or unopened bag, with what is left"),
    "active_bean": Spec(actions.active_bean, "the bag the xBloom draws from when none is named"),
    "brew_history": Spec(
        actions.brew_history,
        "what was brewed, newest first — recipe, bag, dose, brewer (limit, days)",
    ),
    "stats": Spec(
        actions.stats,
        "brews, coffee, water and brews per brewer over a period, with the period "
        "before (period)",
    ),
    "set_active_bean": Spec(
        actions.set_active_bean, "choose the bag the xBloom draws from; nothing is counted",
        one_of=BAG,
    ),
    "consume": Spec(
        actions.consume,
        "record coffee used by a brewer other than the xBloom (brewer). An xBloom "
        "brew counts itself; never report one here",
        ("grams",), BAG,
    ),
    "start_tracking": Spec(
        actions.start_tracking,
        "count a bag down from an amount the person measured — never an estimate",
        ("grams",), BAG,
    ),
    "finish_bag": Spec(
        actions.finish_bag,
        "mark a bag used up, only when the person says it is empty. It leaves the "
        "list; its brews stay. Refused for an unopened bag, or a tracked one still "
        "showing a dose or more",
        one_of=BAG,
    ),
    "add_bean": Spec(
        actions.add_bean,
        "a new bag (bag_size_g, remaining_g to count it down, status, roaster, "
        "country, region, process, roaster_notes)",
        ("name",),
    ),
    "update_bean": Spec(
        actions.update_bean,
        "correct a bag's details (new_name, bag_size_g, status, roaster, country, "
        "region, process, roaster_notes)",
        one_of=BAG,
    ),
}

INTRO = (
    "Coffee Lab: the bags of coffee on hand and what each brew used. Name a bag "
    "by its name; when two bags share a name, by the id list_beans gives. Never "
    "guess which bag was used — ask. Each line names what that action cannot "
    "run without."
)

ARGUMENTS: dict[str, tuple[Any, str]] = {
    "bean": (str, "A bag, by its name."),
    "bean_id": (str, "A bag, by its id, when two bags share a name."),
    "grams": (vol.All(vol.Coerce(float), vol.Range(min=0)), "Grams of coffee."),
    "brewer": (str, "For consume: what made the coffee, such as V60."),
    "period": (vol.In(list(PERIODS)), "For stats; this month unless given."),
    "limit": (vol.All(vol.Coerce(int), vol.Range(min=1, max=100)), "For brew_history."),
    "days": (vol.All(vol.Coerce(int), vol.Range(min=1)), "For brew_history."),
    "name": (str, "For add_bean: the new bag's name."),
    "new_name": (str, "For update_bean: the bag's new name."),
    "bag_size_g": (vol.All(vol.Coerce(float), vol.Range(min=0)), "The bag's size in grams."),
    "remaining_g": (
        vol.All(vol.Coerce(float), vol.Range(min=0)),
        "For add_bean: grams in the bag now, measured; given, the bag is counted down.",
    ),
    "status": (vol.In(list(STATUSES)), "The bag's stage."),
    "roaster": (str, "Who roasted it."),
    "country": (str, "Where it was grown."),
    "region": (str, "The region within the country."),
    "process": (str, "How it was processed, such as washed or natural."),
    "roaster_notes": (str, "The roaster's tasting notes."),
}


def describe(beans: list[Bean]) -> str:
    text = _describe(INTRO, ACTIONS)
    if not beans:
        return text
    names = "; ".join(
        f"{b.name}{' (unopened)' if b.status == 'unopened' else ''}" for b in beans
    )
    return f"{text}\nBags now: {names}."


def check_arguments(action: str, args: dict[str, Any]) -> None:
    _check(ACTIONS, action, args)


def parameters() -> vol.Schema:
    return vol.Schema({
        vol.Required("action", description="Which action to run; see the tool description."):
            vol.In(list(ACTIONS)),
        **{
            vol.Optional(key, description=text): validator
            for key, (validator, text) in ARGUMENTS.items()
        },
    })


async def run(lab: CoffeeLab, action: str, args: dict[str, Any]) -> dict[str, Any]:
    check_arguments(action, args)
    if action == "consume":
        args = {**args, "source": "assistant"}
    return await ACTIONS[action].run(lab, args)
