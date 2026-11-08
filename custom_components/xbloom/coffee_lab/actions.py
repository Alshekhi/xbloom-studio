"""Coffee Lab's actions, shared by its services and its AI tool.

Each takes the lab and its arguments and returns facts, or raises a translated
refusal. The tool and the services are thin wrappers over these, so a rule —
which bag a name means, when a bag may be finished — exists once.

A bag is named by its name, or by its id when two bags share one. A name that
matches more than one open or unopened bag is refused rather than guessed:
two bags of the same coffee are two physical bags.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from homeassistant.exceptions import ServiceValidationError

from xbloom.exceptions import XBloomAPIError

from ..tool_common import refuse
from .lab import STORE_UNREACHABLE, CoffeeLab, Consumption
from .models import TASTE_NOTES, TASTE_SCALES, VERDICT_OF, Bean, Brew
from .stats import PERIODS, UNKNOWN_BREWER as OTHER_BREWER, Totals
from .store import UnknownBean, UnknownBrew

DEFAULT_BREW_HISTORY = 10
# Asked for no period, stats answer for the month so far.
DEFAULT_STATS_PERIOD = "this_month"

# A bag's descriptive fields, which add_bean and update_bean both take.
DESCRIPTIVE = ("roaster", "country", "region", "process", "roaster_notes")


def bean_facts(bean: Bean) -> dict[str, Any]:
    """A bag as facts. An untracked bag has no amount left — not zero, unknown."""
    facts: dict[str, Any] = {
        "id": bean.id,
        "name": bean.name,
        "status": bean.status,
        "tracked": bean.tracked,
        "remaining_g": bean.remaining_g if bean.tracked else None,
        "bag_size_g": bean.bag_size_g,
        "opened_on": bean.opened_on or None,
        "finished_on": bean.finished_on or None,
        "buy_again": bean.buy_again or None,
    }
    facts.update({key: getattr(bean, key) for key in DESCRIPTIVE if getattr(bean, key)})
    return facts


async def resolve_bean(
    lab: CoffeeLab, args: dict[str, Any], *, selectable_only: bool = True
) -> Bean:
    """The one bag `bean` (a name) or `bean_id` means, or a refusal."""
    if bean_id := args.get("bean_id"):
        try:
            bean = await lab.store.async_get_bean(bean_id)
        except UnknownBean:
            raise refuse("bag_not_found", name=bean_id) from None
        if selectable_only and bean.status not in ("open", "unopened"):
            raise refuse("bag_not_found", name=bean_id)
        return bean
    name = str(args.get("bean") or "").strip()
    wanted = name.lower()
    beans = await lab.store.async_list_beans(selectable_only=selectable_only)
    matches = [b for b in beans if b.name.lower() == wanted]
    if not matches:
        raise refuse("bag_not_found", name=name)
    if len(matches) > 1:
        raise refuse("bag_ambiguous", name=name)
    return matches[0]


async def _bag_for_counting(lab: CoffeeLab, args: dict[str, Any]) -> tuple[str, Bean | None]:
    """The bag a brew is counted against: its id, and the bag when it can be read.

    A store that cannot be reached must not stop a brew from being queued,
    or the brew is lost before the queue ever sees it. When the id is known —
    given, or the bag in use — the brew is queued against it unread, and the
    bag is checked when the brew is counted. A refusal (no such bag) is still
    a refusal.
    """
    try:
        bean = await resolve_bean(lab, args)
    except ServiceValidationError:
        raise
    except STORE_UNREACHABLE:
        if not args.get("bean_id"):
            raise
        return args["bean_id"], None
    return bean.id, bean


def _consumption_facts(result: Consumption, bean: Bean | None) -> dict[str, Any]:
    facts = {k: v for k, v in asdict(result).items() if v not in (None, {}, False)}
    if bean is not None:
        facts["bag"] = bean.name
    return facts


# ── Reading ──────────────────────────────────────────────────────────────────


async def list_beans(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    return {"bags": [bean_facts(b) for b in await lab.store.async_list_beans()]}


async def active_bean(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    bean = await lab.async_active_bean()
    facts: dict[str, Any] = {"bag": bean_facts(bean) if bean else None}
    if questions := lab.rating_questions_due():
        facts["rating_questions"] = [question_facts(q) for q in questions]
    if (bag := lab.bag_question) is not None:
        facts["bag_question"] = {"bean_id": bag["bean_id"], "bag": bag["name"]}
    return facts


async def rate_bag(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """Would this coffee be bought again: the finished bag in question, unless named."""
    bean_id = None
    if args.get("bean") or args.get("bean_id"):
        bean_id = (await resolve_bean(lab, args, selectable_only=False)).id
    try:
        bean = await lab.async_rate_bag(args["buy_again"], bean_id)
    except UnknownBean:
        raise refuse("bag_required") from None
    return {"bag": bean_facts(bean)}


def question_facts(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "brew_id": question["brew_id"], "recipe": question["recipe"], "bag": question["bag"],
        "changed_from_recipe": question.get("changes") or [],
        "cups": len(question.get("brew_ids") or [question["brew_id"]]),
    }


async def rate_brew(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """What someone said about a brew: a verdict, how it tasted, what to change.

    Only what was said is written; nothing is filled in on their behalf.
    """
    tasting = {k: str(args[k]).strip().lower() for k in TASTE_SCALES if args.get(k)}
    tasting |= {k: str(args[k]).strip() for k in TASTE_NOTES if args.get(k)}
    next_change = str(args["next_change"]).strip() if args.get("next_change") else None
    if not (args.get("verdict") or tasting or next_change):
        raise refuse("rate_brew_empty")
    try:
        brew = await lab.async_rate(
            verdict=args.get("verdict"), brew_id=args.get("brew_id"),
            tasting=tasting or None, next_change=next_change,
        )
    except UnknownBrew:
        raise refuse("brew_not_found", brew=args.get("brew_id") or "") from None
    return {"brew": _brew_facts(brew, {})}


def _brew_facts(brew: Brew, names: dict[str, str]) -> dict[str, Any]:
    when = brew.brewed_at or None
    if when and (parsed := dt_util.parse_datetime(when)) is not None:
        when = dt_util.as_local(parsed).isoformat(timespec="minutes")
    facts = {
        "brewed_at": when,
        "recipe": brew.recipe,
        "bag": names.get(brew.bean_id) if brew.bean_id else None,
        "dose_g": brew.dose_g,
        "brewer": brew.brewer,
        "dripper": brew.dripper,
        "outcome": brew.outcome,
        "water_ml": brew.water_ml,
        # How it was brewed — grind, ratio, temperature_c, flow_rate, and
        # duration_s from the first pour to the end — as the record holds it.
        **brew.settings,
    }
    if brew.review is not None:
        facts["needs_review"] = {"reason": brew.review.reason, **brew.review.detail}
    if brew.rating is not None:
        facts["verdict"] = VERDICT_OF.get(brew.rating)
    if brew.tasting:
        facts["tasting"] = dict(brew.tasting)
    if brew.next_change:
        facts["next_change"] = brew.next_change
    facts["id"] = brew.id
    return {k: v for k, v in facts.items() if v is not None}


async def brew_history(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """What was brewed, newest first, with the bag it came from."""
    since = None
    if days := args.get("days"):
        since = dt_util.now() - timedelta(days=int(days))
    brews = await lab.store.async_list_brews(
        since=since, limit=int(args.get("limit") or DEFAULT_BREW_HISTORY)
    )
    names = {b.id: b.name for b in await lab.store.async_list_beans(selectable_only=False)}
    return {"brews": [_brew_facts(b, names) for b in brews]}


def _totals_facts(totals: Totals) -> dict[str, Any]:
    return {
        "brews": totals.brews,
        "coffee_g": totals.coffee_g,
        "water_ml": totals.water_ml if totals.brews_with_water else None,
        "by_brewer": dict(totals.by_brewer),
    }


async def stats(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    period = args.get("period") or DEFAULT_STATS_PERIOD
    if period not in PERIODS:
        raise refuse("value_not_accepted", argument="period", accepted=", ".join(PERIODS))
    report = await lab.async_stats(period)
    return {
        "period": period,
        **_totals_facts(report.now),
        "previous_period": _totals_facts(report.before),
        "change_in_brews": report.change_in_brews,
    }


# ── Changing ─────────────────────────────────────────────────────────────────


async def set_active_bean(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    bean = await resolve_bean(lab, args)
    await lab.async_select(bean.id)
    return {"active_bag": bean_facts(bean)}


async def consume(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """Coffee used by a brewer other than the xBloom — a V60, say.

    An xBloom brew counts itself when it completes; reporting it here too
    would take its coffee twice.
    """
    brewer = args.get("brewer")
    # Kept as a select option in Notion, which refuses a comma; a name it
    # refuses would wait in the queue to be saved and never be.
    if brewer is not None and ("," in str(brewer) or len(str(brewer)) > 100):
        raise refuse("brewer_invalid")
    bean_id, bean = await _bag_for_counting(lab, args)
    result = await lab.async_consume(
        bean_id=bean_id, grams=args["grams"],
        # No brewer named is recorded as none, never as the xBloom.
        brewer=args.get("brewer"), recipe_source=args.get("source"),
    )
    return _consumption_facts(result, bean)


async def start_tracking(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """Count a bag down from an amount someone measured — never an estimate."""
    bean = await resolve_bean(lab, args)
    return {"bag": bean_facts(await lab.async_start_tracking(bean.id, float(args["grams"])))}


async def finish_bag(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    bean = await resolve_bean(lab, args)
    if (why := CoffeeLab.finish_refusal(bean)) is not None:
        raise refuse(why, name=bean.name, remaining_g=f"{bean.remaining_g or 0:g}")
    finished = await lab.async_finish(bean.id)
    # Its brews stay in the record; the amount it showed stays as it was.
    return {"finished": bean_facts(finished)}


def _bag_values(args: dict[str, Any]) -> dict[str, Any]:
    values = {key: args[key] for key in DESCRIPTIVE if args.get(key) is not None}
    for key in ("bag_size_g", "status"):
        if args.get(key) is not None:
            values[key] = args[key]
    return values


async def in_hub_words(lab: CoffeeLab, values: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a bag's country and process to the hub's names, in place.

    Returns what the caller should hear: `not_on_hub`, the names the hub does
    not list (kept as typed), and `unchecked`, the fields the hub could not be
    asked about.
    """
    from ..coffee_names import LISTS

    names, not_on_hub, unchecked = lab.hub_names, {}, []
    for field in LISTS:
        text = str(values.get(field) or "").strip()
        if not text or names is None:
            continue
        try:
            canonical = await names.async_canonical(field, text)
        except (XBloomAPIError, aiohttp.ClientError, TimeoutError):
            unchecked.append(field)
            continue
        if canonical:
            values[field] = canonical
        else:
            not_on_hub[field] = text
    return {k: v for k, v in (("not_on_hub", not_on_hub), ("unchecked", unchecked)) if v}


async def add_bean(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """A new bag. Given how much is in it, it is counted down from there."""
    values = {"status": "unopened", **_bag_values(args)}
    if args.get("remaining_g") is not None:
        values.update(tracked=True, remaining_g=float(args["remaining_g"]))
    checked = await in_hub_words(lab, values)
    bean = await lab.store.async_add_bean(name=str(args["name"]).strip(), **values)
    lab.on_change()
    return {"added": bean_facts(bean), **checked}


async def update_bean(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """Correct a bag's details. Its amount changes through start_tracking."""
    bean = await resolve_bean(lab, args, selectable_only=False)
    changes = _bag_values(args)
    if args.get("new_name"):
        changes["name"] = str(args["new_name"]).strip()
    checked = await in_hub_words(lab, changes)
    updated = await lab.store.async_update_bean(bean.id, **changes)
    lab.on_change()
    return {"updated": bean_facts(updated), **checked}


async def record_manual_brew(lab: CoffeeLab, args: dict[str, Any]) -> dict[str, Any]:
    """The dashboard's dose and brewer, against the active bag.

    Each press is its own brew, so two presses are two brews.
    """
    if lab.manual_dose_g is None:
        raise refuse("manual_dose_required")
    # The bag in use is known here even when the store cannot be reached.
    if lab.active_bean_id is None:
        raise refuse("bag_required")
    try:
        bean = await lab.async_active_bean()
    except STORE_UNREACHABLE:
        bean = None
    else:
        if bean is None:  # finished or removed since it was chosen
            raise refuse("bag_required")
    result = await lab.async_consume(
        bean_id=bean.id if bean else lab.active_bean_id,
        grams=lab.manual_dose_g, run_id=f"manual-{uuid.uuid4().hex}",
        # `other` is recorded as no brewer, which the stats count as other.
        brewer=lab.manual_brewer if lab.manual_brewer != OTHER_BREWER else None,
        recipe_source="dashboard",
    )
    return _consumption_facts(result, bean)
