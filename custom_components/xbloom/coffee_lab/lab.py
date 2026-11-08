"""Coffee Lab at runtime: the store, the active bag, and counting brews.

Every source of a brew — an xBloom completion, a manual brew on the dashboard,
an agent reporting a V60 — goes through the same `async_consume`, so the
inventory rules exist in one place.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from xbloom import spec

from ..const import DOMAIN
from .inventory import Deduct, Flag, Skip, decide_consumption, kind_of_cup
from .models import SELECTABLE, VERDICTS, Bean, Brew, Review
from .pending import PendingBrews
from .stats import DEFAULT_PERIOD, PERIODS, Report, earliest_needed, period_report
from .store import (
    STORAGE_VERSION, CoffeeLabStore, ProcessedRuns, Storage, StoreRefused, UnknownBean,
    UnknownBrew,
    async_local_store, async_processed_runs,
)

_LOGGER = logging.getLogger(__name__)

STATE_KEY = f"{DOMAIN}.coffee_lab_state"
PENDING_KEY = f"{DOMAIN}.coffee_lab_pending"

# The state key holding the item in use for each kind. The coffee one is the
# key this has always used.
ACTIVE_KEYS = {"coffee": "active_bean_id", "xpod": "active_xpod_id", "tea": "active_tea_id"}

# What a store that cannot be reached raises. Anything else is a fault in
# this code, not a reason to wait and try again.
STORE_UNREACHABLE = (HomeAssistantError, aiohttp.ClientError, asyncio.TimeoutError, OSError)

# What an xBloom brew is recorded as in a brew's `brewer`: the product's name.
XBLOOM_BREWER = "xBloom Studio"

# A tracked bag may be finished only once its record shows less than a dose
# left. Above it, one mistaken finish would retire a bag that still holds
# coffee; a bag emptier than its record is weighed and re-based first.
FINISH_BELOW_G = 20.0

# The question about a brew: due this long after it, so it is not asked with
# the cup in hand; gone this long after, unanswered. Earlier verdicts are
# looked for this far back.
QUESTION_DELAY = timedelta(minutes=15)
QUESTION_LAPSE = timedelta(days=1)
QUESTION_LOOKBACK = timedelta(days=365)
BAG_QUESTION_LAPSE = timedelta(days=7)
# Questions open at once; a busy morning drops the oldest rather than piling up.
MAX_OPEN_QUESTIONS = 3


def _rounded(value: Any, digits: int) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def brew_version(dose: Any, settings: dict[str, Any]) -> dict[str, float | None]:
    """What tells two brews of one recipe apart: grind, ratio and dose.

    The record keeps the grind as text ("50" or "50.0"), so all three are
    compared as rounded numbers.
    """
    return {
        "grind": _rounded(settings.get("grind"), 1),
        "ratio": _rounded(settings.get("ratio"), 2),
        "dose_g": _rounded(dose, 1),
    }


def version_changes(version: dict[str, Any], saved: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Where this version differs from the saved recipe, setting by setting."""
    if not saved:
        return []
    ratio = normalize_ratio(saved)
    saved_version = {
        "grind": _rounded(saved.get("grinder_size", saved.get("grind_size")), 1),
        "ratio": _rounded(ratio, 2),
        "dose_g": _rounded(saved.get("dose_g"), 1),
    }
    return [
        {"setting": key, "value": value, "saved": saved_version[key]}
        for key, value in version.items()
        if value is not None and saved_version[key] is not None and value != saved_version[key]
    ]


def question_brews(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open questions as a message carries them: each coffee, and its cups."""
    from ..community import hub_text

    # Names typed by people, read by other agents: one capped line each.
    return [
        {"brew_id": q["brew_id"], "recipe": hub_text(q["recipe"]), "bag": hub_text(q["bag"]),
         "changes": q.get("changes") or [], "cups": len(q.get("brew_ids") or [q["brew_id"]])}
        for q in questions
    ]


def change_label(changes: list[dict[str, Any]]) -> str:
    """What a version changed, in a few words: "grind 52, ratio 1:15"."""
    def number(value: Any) -> str:
        return f"{float(value):g}"

    words = {
        "grind": lambda v: f"grind {number(v)}",
        "ratio": lambda v: f"ratio 1:{number(v)}",
        "dose_g": lambda v: f"{number(v)} g",
    }
    return ", ".join(words[c["setting"]](c["value"]) for c in changes if c["setting"] in words)


def normalize_ratio(recipe: dict[str, Any]) -> float | None:
    """The saved recipe's ratio denominator, whichever shape it is in."""
    from xbloom.recipe_validate import normalize_recipe

    try:
        return float(str(normalize_recipe(recipe).get("ratio")).split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


def _drawn_from(cup_type: Any, bean_id: str | None, xpod_id: str | None, tea_id: str | None) -> str | None:
    """The item a brew draws from: its cup type's kind decides which."""
    return {"xpod": xpod_id, "tea": tea_id}.get(kind_of_cup(cup_type), bean_id)


def _brew_day(brewed_at: str | None) -> str:
    """The local date a brew happened on; today when its time is unknown."""
    when = dt_util.parse_datetime(brewed_at) if brewed_at else None
    return dt_util.as_local(when).date().isoformat() if when else dt_util.now().date().isoformat()


@dataclass(frozen=True)
class Consumption:
    """What counting one brew did, as facts.

    `result` is `counted` (subtracted from the bag), `recorded` (the brew is in
    the record but nothing was subtracted), `skipped` (nothing written — a
    duplicate), `flagged` (recorded for review, the bag left alone) or
    `queued` (the store could not be reached; the brew waits in Home
    Assistant and is counted once it can be, `reason` saying why).
    """

    result: str
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    bean_id: str | None = None
    grams: float | None = None
    remaining_g: float | None = None
    opened: bool = False
    finished: bool = False
    # The brew's row, when this count wrote one.
    brew_id: str | None = None


def cup_label(cup_type: Any) -> str | None:
    try:
        return spec.CUP_API_TO_LABEL.get(int(cup_type))
    except (TypeError, ValueError):
        return None


def _grams(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CoffeeLab:
    """One install's Coffee Lab."""

    def __init__(
        self, store: CoffeeLabStore, runs: ProcessedRuns, state: Storage,
        on_change: Callable[[], None] = lambda: None,
        brewers: tuple[str, ...] = (),
        pending: PendingBrews | None = None,
    ) -> None:
        self.store = store
        self.pending = pending if pending is not None else PendingBrews(_MemoryStorage())
        # What the manual-brew picker offers besides `other`.
        self.brewers = brewers
        self._runs = runs
        self._state_storage = state
        self._state: dict[str, Any] = {}
        # Entities subscribe to this; anything that changes what they show calls it.
        self.on_change = on_change
        # The saved recipe of a name, from the integration's library: what the
        # question compares a brew's grind, ratio and dose against.
        self.recipe_lookup: Callable[[str], dict[str, Any] | None] = lambda name: None
        # The community hub's names for a bag's country and process
        # (coffee_names.HubNames); None leaves them as typed.
        self.hub_names: Any = None
        # Told when the bag in use changes, with its id or None, so what was
        # suggested for the last one is not shown for the next.
        self.on_bag_chosen: Callable[[str | None], None] = lambda bean_id: None
        # Told of each question opened, so it can be asked of whoever started
        # the brew once it is due (rating_calls.py).
        self.on_question: Callable[[dict[str, Any]], None] = lambda question: None
        # One brew at a time: two deliveries of one completion, handled
        # together, would both pass the duplicate check while the first waits
        # on the store, and subtract twice.
        self._counting = asyncio.Lock()

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, brewers: tuple[str, ...] = (),
        store: CoffeeLabStore | None = None,
    ) -> CoffeeLab:
        pending = PendingBrews(Store(hass, STORAGE_VERSION, PENDING_KEY))
        await pending.async_load()
        lab = cls(
            store or await async_local_store(hass),
            await async_processed_runs(hass),
            Store(hass, STORAGE_VERSION, STATE_KEY),
            brewers=brewers,
            pending=pending,
        )
        await lab.async_load_state()
        return lab

    async def async_load_state(self) -> None:
        self._state = dict(await self._state_storage.async_load() or {})

    async def _async_set_state(self, **values: Any) -> None:
        chosen = (
            "active_bean_id" in values
            and values["active_bean_id"] != self._state.get("active_bean_id")
        )
        self._state = {**self._state, **values}
        await self._state_storage.async_save(self._state)
        self.on_change()
        if chosen:
            self.on_bag_chosen(values["active_bean_id"])

    # ── The active bag ───────────────────────────────────────────────────

    @property
    def active_bean_id(self) -> str | None:
        """The bag of coffee in use."""
        return self._state.get(ACTIVE_KEYS["coffee"])

    def active_id(self, kind: str) -> str | None:
        """The item of this kind in use: a bag of coffee, an xPod box, a tea."""
        return self._state.get(ACTIVE_KEYS[kind])

    async def async_active_bean(self, kind: str = "coffee") -> Bean | None:
        """The item of a kind the xBloom draws from, or None if none can be.

        A selection whose item has since been finished, or removed, is cleared
        rather than brewed against.
        """
        bean_id = self.active_id(kind)
        if not bean_id:
            return None
        try:
            bean = await self.store.async_get_bean(bean_id)
        except UnknownBean:
            bean = None
        if bean is None or bean.status not in SELECTABLE or bean.kind != kind:
            await self._async_set_state(**{ACTIVE_KEYS[kind]: None})
            return None
        return bean

    async def async_select(self, bean_id: str | None, kind: str = "coffee") -> Bean | None:
        """Choose the item the xBloom draws from, for its kind; the inventory is not touched.

        None clears the choice for `kind`.
        """
        if bean_id is None:
            await self._async_set_state(**{ACTIVE_KEYS[kind]: None})
            return None
        bean = await self.store.async_get_bean(bean_id)
        if bean.status not in SELECTABLE:
            raise UnknownBean(bean_id)
        await self._async_set_state(**{ACTIVE_KEYS[bean.kind]: bean.id})
        return bean

    async def async_card_read(self, pod_id: str) -> Bean | None:
        """A pod's recipe card was read: the xPod box it belongs to, put in use.

        A box already known by this card id is chosen. Failing that, the box
        in use learns the id if it has none, so the first brew from a box
        teaches it and the next box of the same coffee is found by itself.
        """
        pod_id = str(pod_id or "").strip()
        if not pod_id:
            return None
        boxes = [b for b in await self.store.async_list_beans() if b.kind == "xpod"]
        known = next((b for b in boxes if b.pod_id == pod_id), None)
        if known is not None:
            if self.active_id("xpod") != known.id:
                await self.async_select(known.id)
            return known
        active = await self.async_active_bean("xpod")
        if active is not None and not active.pod_id:
            learnt = await self.store.async_update_bean(active.id, pod_id=pod_id)
            self.on_change()
            return learnt
        return None

    async def async_matching(self, name: str) -> list[Bean]:
        """The open or unopened bags called `name`, ignoring case.

        Two bags of the same coffee are two records on purpose, so more than
        one match is answered with the candidates, never a guess.
        """
        wanted = name.strip().lower()
        return [b for b in await self.store.async_list_beans() if b.name.lower() == wanted]

    # ── The dashboard's settings ─────────────────────────────────────────

    @property
    def stats_period(self) -> str:
        period = self._state.get("stats_period")
        return period if period in PERIODS else DEFAULT_PERIOD

    async def async_set_stats_period(self, period: str) -> None:
        if period not in PERIODS:
            raise ValueError(period)
        await self._async_set_state(stats_period=period)

    @property
    def manual_dose_g(self) -> float | None:
        return self._state.get("manual_dose_g")

    async def async_set_manual_dose(self, grams: float) -> None:
        await self._async_set_state(manual_dose_g=grams)

    @property
    def manual_brewer(self) -> str | None:
        return self._state.get("manual_brewer")

    async def async_set_manual_brewer(self, brewer: str) -> None:
        await self._async_set_state(manual_brewer=brewer)

    # ── How it was ───────────────────────────────────────────────────────
    #
    # A question per recipe, bag and version (grind, ratio, dose) that has no
    # verdict yet. Cups of the same one brewed close together share their
    # question, and the answer is kept on each of them; a different recipe,
    # bag or version gets its own. Each is due a while after its last cup, so
    # it is not asked while the cup is in hand, and lapses after a day
    # unanswered. They are asked one at a time, oldest first.

    def _open_questions(self) -> list[dict[str, Any]]:
        now = dt_util.utcnow()
        questions = self._state.get("rating_questions")
        if questions is None and self._state.get("rating_question"):
            questions = [self._state["rating_question"]]  # kept by an earlier version
        open_ = []
        for question in questions or []:
            expires = dt_util.parse_datetime(question["expires_at"])
            if expires is None or now < expires:
                open_.append({"brew_ids": [question["brew_id"]], **question})
        return open_

    async def _async_set_questions(self, questions: list[dict[str, Any]], **values: Any) -> None:
        await self._async_set_state(rating_questions=questions, rating_question=None, **values)

    @property
    def rating_questions(self) -> list[dict[str, Any]]:
        """Every open question, whether due yet or not, oldest first."""
        return [dict(q) for q in self._open_questions()]

    @property
    def rating_question(self) -> dict[str, Any] | None:
        """The oldest open question, whether due yet or not."""
        questions = self._open_questions()
        return dict(questions[0]) if questions else None

    def rating_questions_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or dt_util.utcnow()
        due = []
        for question in self._open_questions():
            when = dt_util.parse_datetime(question["due_at"])
            if when is None or now >= when:
                due.append(dict(question))
        return due

    def rating_question_due(self, now: datetime | None = None) -> dict[str, Any] | None:
        """The question to ask now: the oldest that is due."""
        due = self.rating_questions_due(now)
        return due[0] if due else None

    def question_of(self, brew_id: str) -> dict[str, Any] | None:
        """The open question a brew is one of the cups of."""
        return next((dict(q) for q in self._open_questions() if brew_id in q["brew_ids"]), None)

    async def async_note_question(self, brew_id: str, **changes: Any) -> None:
        """Keep something about the open question this brew is a cup of."""
        questions = self._open_questions()
        for i, question in enumerate(questions):
            if brew_id in question["brew_ids"]:
                questions[i] = {**question, **changes}
                await self._async_set_questions(questions)
                return

    async def _async_maybe_ask(self, run_id: str, args: dict[str, Any], done: Consumption) -> None:
        """Open, or join, the question for this brew, when it is worth asking about.

        Never lets counting fail: whatever goes wrong here is logged and the
        brew stands as counted.
        """
        if (
            done.result not in ("counted", "recorded") or not done.brew_id
            or args.get("brewer") != XBLOOM_BREWER or not args.get("recipe")
            or not done.bean_id
        ):
            return
        try:
            recipe = args["recipe"]
            version = brew_version(args.get("grams"), args.get("settings") or {})
            since = dt_util.utcnow() - QUESTION_LOOKBACK
            for brew in await self.store.async_list_brews(since=since):
                if (
                    brew.rating is not None and brew.bean_id == done.bean_id
                    and (brew.recipe or "").casefold() == recipe.casefold()
                    and brew_version(brew.dose_g, brew.settings) == version
                ):
                    return
            now = dt_util.utcnow()
            timing = {
                "brewed_at": args.get("brewed_at"),
                "due_at": (now + QUESTION_DELAY).isoformat(),
                "expires_at": (now + QUESTION_LAPSE).isoformat(),
            }
            # Read before the open questions are: an answer given while the
            # store is asked would otherwise be overwritten by this write.
            bean = await self.store.async_get_bean(done.bean_id)
            questions = self._open_questions()
            same = next((
                q for q in questions
                if q["bean_id"] == done.bean_id and q["version"] == version
                and q["recipe"].casefold() == recipe.casefold()
            ), None)
            if same is not None:
                # Another cup of the same coffee: one question for both, due
                # after the later one.
                question = {
                    **same, **timing, "brew_id": done.brew_id, "run_id": run_id,
                    "brew_ids": [*same["brew_ids"], done.brew_id],
                }
                questions[questions.index(same)] = question
            else:
                question = {
                    "brew_id": done.brew_id, "brew_ids": [done.brew_id], "run_id": run_id,
                    "recipe": recipe, "bean_id": done.bean_id, "bag": bean.name,
                    "version": version,
                    "changes": version_changes(version, self.recipe_lookup(recipe)),
                    **timing,
                }
                questions = [*questions, question][-MAX_OPEN_QUESTIONS:]
            await self._async_set_questions(questions)
            self.on_question(question)
        except Exception:  # noqa: BLE001 — asking must never undo a count
            _LOGGER.exception("Coffee Lab: could not open the question for brew %s", done.brew_id)

    async def async_rate(
        self, *, verdict: str | None = None, brew_id: str | None = None,
        tasting: dict[str, str] | None = None, next_change: str | None = None,
    ) -> Brew:
        """Keep what was said about a brew: the oldest due question's, unless named.

        A question's answer is kept on every cup it covers. With no question
        and no brew named, the most recent brew.
        """
        question = self.question_of(brew_id) if brew_id else (
            self.rating_question_due() or self.rating_question
        )
        if question is not None:
            targets = question["brew_ids"]
        elif brew_id is not None:
            targets = [brew_id]
        else:
            latest = await self.store.async_list_brews(limit=1)
            if not latest:
                raise UnknownBrew("")
            targets = [latest[0].id]
        named = brew_id or targets[-1]
        rated = None
        for target in [t for t in targets if t != named] + [named]:
            try:
                rated = await self.store.async_rate_brew(
                    target, rating=VERDICTS[verdict] if verdict else None,
                    tasting=tasting, next_change=next_change,
                )
            except UnknownBrew:
                # A cup removed from the record since: the others are rated.
                if target == named:
                    raise
        if question is not None and verdict:
            questions = [q for q in self._open_questions() if q["brew_id"] != question["brew_id"]]
            keeps = self.versions_to_keep
            changes = question.get("changes") or []
            # A changed version liked enough to brew again is offered to keep,
            # as the recipe or beside it; the saved recipe is never changed
            # without being asked. Several are offered in turn.
            if verdict == "again" and changes and not any(
                k["recipe"] == question["recipe"] and k["version"] == question["version"]
                for k in keeps
            ):
                keeps.append({"recipe": question["recipe"], "version": question["version"],
                              "changes": changes, "label": change_label(changes)})
            await self._async_set_questions(questions, versions_to_keep=keeps, version_to_keep=None)
        self.on_change()
        return rated

    @property
    def versions_to_keep(self) -> list[dict[str, Any]]:
        """Changed versions rated Again, until each is kept or dismissed."""
        keeps = self._state.get("versions_to_keep")
        if keeps is None and self._state.get("version_to_keep"):
            keeps = [self._state["version_to_keep"]]  # kept by an earlier version
        return [dict(k) for k in keeps or []]

    @property
    def version_to_keep(self) -> dict[str, Any] | None:
        """The changed version to offer now: the first rated Again."""
        keeps = self.versions_to_keep
        return keeps[0] if keeps else None

    async def async_clear_version_to_keep(self) -> None:
        await self._async_set_state(versions_to_keep=self.versions_to_keep[1:], version_to_keep=None)

    # The one question a bag gets, when it is finished: would it be bought
    # again. Open for a week, and replaced by the next bag finished.

    @property
    def bag_question(self) -> dict[str, Any] | None:
        question = self._state.get("bag_question")
        if not question:
            return None
        expires = dt_util.parse_datetime(question["expires_at"])
        if expires is not None and dt_util.utcnow() >= expires:
            return None
        return dict(question)

    async def _async_ask_about_bag(self, bean: Bean) -> None:
        if bean.buy_again:
            return
        await self._async_set_state(bag_question={
            "bean_id": bean.id, "name": bean.name,
            "expires_at": (dt_util.utcnow() + BAG_QUESTION_LAPSE).isoformat(),
        })

    async def async_rate_bag(self, answer: str, bean_id: str | None = None) -> Bean:
        """Would this coffee be bought again: the finished bag's, unless named."""
        question = self.bag_question
        target = bean_id or (question or {}).get("bean_id")
        if target is None:
            raise UnknownBean("")
        bean = await self.store.async_update_bean(target, buy_again=answer)
        if question and question["bean_id"] == target:
            await self._async_set_state(bag_question=None)
        self.on_change()
        return bean

    # ── Counting ─────────────────────────────────────────────────────────

    async def async_consume(
        self, *, bean_id: str | None, grams: Any, run_id: str | None = None,
        cup_type: Any = None, recipe: str | None = None,
        brewer: str | None = XBLOOM_BREWER, brewed_at: str | None = None,
        recipe_source: str | None = None, outcome: str | None = None,
        settings: dict[str, Any] | None = None, unattributed: bool = False,
        xpod_id: str | None = None, tea_id: str | None = None,
    ) -> Consumption:
        """Apply one brew to its bag and the record.

        The brew is queued first and counted from the queue, so a store that
        cannot be reached leaves it waiting rather than lost; see pending.py.
        `xpod_id` and `tea_id` are the xPod box and tea in use when it started:
        its cup type picks which of the three it draws from.
        """
        return await self._async_queue_and_count("brew", run_id, {
            "bean_id": _drawn_from(cup_type, bean_id, xpod_id, tea_id), "grams": grams, "cup_type": cup_type, "recipe": recipe,
            "brewer": brewer, "brewed_at": brewed_at, "recipe_source": recipe_source,
            "outcome": outcome, "settings": settings, "unattributed": unattributed,
        })

    async def _async_queue_and_count(
        self, kind: str, run_id: str | None, args: dict[str, Any],
    ) -> Consumption:
        # A brew reported with no id of its own gets one, so its row can be
        # found again and a retry cannot write it twice.
        run_id = run_id or f"lab-{uuid.uuid4().hex}"
        # When it happened is fixed now, not when a retry finally writes it.
        args = {**args, "brewed_at": args.get("brewed_at") or dt_util.utcnow().isoformat()}
        async with self._counting:
            if self.pending.contains(run_id):
                result = Consumption("skipped", reason="already_queued")
            else:
                await self.pending.async_add(run_id, kind, args, dt_util.utcnow().isoformat())
                result = await self._async_drain(run_id)
            # Kept so a flagged or queued brew stays visible after a restart.
            # Also tells the entities to re-read.
            await self._async_set_state(last_count={
                **asdict(result), "run_id": run_id, "at": dt_util.utcnow().isoformat(),
            })
            return result

    async def async_retry_pending(self) -> int:
        """Count what is waiting, oldest first; how many are still waiting."""
        if not len(self.pending):
            return 0
        async with self._counting:
            await self._async_drain(None)
        self.on_change()
        return len(self.pending)

    async def _async_drain(self, wanted: str | None) -> Consumption:
        """Count the queue in order, stopping at the first that cannot be.

        Order is kept because each subtraction reads the bag the one before it
        left. `wanted` is the run whose result is returned; it is `queued`
        when it, or a brew ahead of it, could not reach the store.
        """
        result = Consumption("queued")
        for entry in self.pending.entries:
            try:
                if entry["kind"] == "stopped":
                    done = await self._async_stopped(entry["run_id"], **entry["args"])
                else:
                    done = await self._async_consume(entry["run_id"], entry, **entry["args"])
            except StoreRefused as err:
                # The store refused this brew: kept, and tried again later,
                # but stepped past like a fault in this code.
                _LOGGER.warning("Coffee Lab: the store refused brew %s: %s", entry["run_id"], err)
                reason = str(err) or type(err).__name__
                await self.pending.async_update(
                    entry["run_id"], attempts=entry["attempts"] + 1, last_error=reason,
                )
                if entry["run_id"] == wanted:
                    result = Consumption("queued", reason=reason)
                continue
            except STORE_UNREACHABLE as err:
                reason = str(err) or type(err).__name__
                await self.pending.async_update(
                    entry["run_id"], attempts=entry["attempts"] + 1, last_error=reason,
                )
                if wanted is not None:
                    result = Consumption("queued", reason=reason)
                break
            except Exception as err:  # noqa: BLE001
                # A fault in this code, not the store: kept and tried again
                # later, but stepped past, so one brew that cannot be counted
                # does not hold back every brew after it.
                _LOGGER.exception("Coffee Lab: brew %s could not be counted", entry["run_id"])
                reason = f"{type(err).__name__}: {err}"
                await self.pending.async_update(
                    entry["run_id"], attempts=entry["attempts"] + 1, last_error=reason,
                )
                if entry["run_id"] == wanted:
                    result = Consumption("queued", reason=reason)
                continue
            await self.pending.async_remove(entry["run_id"])
            if entry["kind"] == "brew":
                await self._async_maybe_ask(entry["run_id"], entry["args"], done)
            if entry["run_id"] == wanted:
                result = done
            elif (self.last_count or {}).get("run_id") == entry["run_id"]:
                # The last brew shown as waiting is saved now: show what it did.
                await self._async_set_state(last_count={
                    **asdict(done), "run_id": entry["run_id"], "at": dt_util.utcnow().isoformat(),
                })
        return result

    @property
    def last_count(self) -> dict[str, Any] | None:
        """The last brew counted, as `Consumption`'s fields plus when."""
        return self._state.get("last_count")

    async def _async_consume(
        self, run_id: str, entry: dict[str, Any], *, bean_id: str | None, grams: Any,
        cup_type: Any, recipe: str | None, brewer: str | None,
        brewed_at: str | None, recipe_source: str | None, outcome: str | None,
        settings: dict[str, Any] | None, unattributed: bool,
    ) -> Consumption:
        def record(bag: str | None, review: Review | None = None) -> Brew:
            return Brew(
                id="",
                brewed_at=brewed_at or dt_util.utcnow().isoformat(),
                recorded_at=dt_util.utcnow().isoformat(),
                # An xPod or unattributed brew may arrive with no dose.
                dose_g=_grams(grams), brewer=brewer, bean_id=bag,
                water_ml=_grams((settings or {}).get("water_ml")),
                dripper=cup_label(cup_type), recipe=recipe,
                recipe_source=recipe_source, outcome=outcome, run_id=run_id,
                settings={k: v for k, v in (settings or {}).items() if v is not None},
                review=review,
            )

        # The bag's new amount was sent on an earlier try and its answer lost
        # — a timeout after Notion had written it. Read back, the amount shows
        # whether it landed: if it did, only the row is left to write.
        sent = entry.get("bag_sent")
        if sent and not entry.get("bag"):
            try:
                read = await self.store.async_get_bean(sent["bean_id"])
                now_g = read.pods_left if sent.get("unit") == "pods" else read.remaining_g
            except UnknownBean:
                now_g = None
            if now_g is not None and now_g == sent["remaining_g"] != sent["from_g"]:
                entry = {**entry, "bag": {k: v for k, v in sent.items() if k != "from_g"}}
                await self.pending.async_update(run_id, bag=entry["bag"])

        # The bag was taken from on an earlier try and only the row is
        # missing: finish that, without deciding the subtraction again.
        if entry.get("bag"):
            bag = entry["bag"]
            written = None
            if not await self.store.async_has_run(run_id):
                written = await self.store.async_create_brew(record(bag["bean_id"]))
            await self._runs.async_add(run_id)
            if bag.get("finished"):
                try:
                    await self._async_ask_about_bag(await self.store.async_get_bean(bag["bean_id"]))
                except UnknownBean:
                    pass
            self.on_change()
            return Consumption(
                "counted", bean_id=bag["bean_id"], grams=bag["grams"],
                remaining_g=bag["remaining_g"], opened=bag["opened"], finished=bag["finished"],
                brew_id=written.id if written else None,
            )

        # Read the bag fresh: a cached amount is exactly what must not be stale
        # when subtracting from it.
        bean: Bean | None = None
        if bean_id:
            try:
                bean = await self.store.async_get_bean(bean_id)
            except UnknownBean:
                bean = None
        # Counted here before, or already in the record: Home Assistant's own
        # list of counted runs can be lost, the store's record of a brew cannot.
        already = self._runs.contains(run_id) or bool(
            run_id and await self.store.async_has_run(run_id)
        )
        decision = decide_consumption(
            bean=bean, grams=grams, cup_type=cup_type,
            already_processed=already, unattributed=unattributed,
        )

        if isinstance(decision, Skip):
            # A skipped subtraction is not a skipped brew: an untracked bag's
            # brew still happened, with a real dose, against a real bag.
            written = None
            if decision.record_brew:
                written = await self.store.async_create_brew(record(decision.bean_id))
            # Marked after writing: had the write failed, the queue retries it.
            await self._runs.async_add(run_id)
            self.on_change()
            return Consumption(
                "recorded" if decision.record_brew else "skipped",
                reason=decision.reason, bean_id=decision.bean_id,
                brew_id=written.id if written else None,
            )

        if isinstance(decision, Flag):
            # Recorded for review with the arithmetic left alone: a brew missing
            # from the record cannot be reconciled later by looking.
            await self.store.async_create_brew(
                record(bean_id if bean else None, Review(decision.reason, decision.detail))
            )
            await self._runs.async_add(run_id)
            self.on_change()
            return Consumption(
                "flagged", reason=decision.reason, detail=decision.detail, bean_id=bean_id,
            )

        assert isinstance(decision, Deduct)
        # Noted before it is sent: if the answer is lost, the next try reads
        # the bag back to learn whether this landed, rather than taking the
        # dose a second time.
        pods = decision.new_pods is not None
        await self.pending.async_update(run_id, bag_sent={
            "bean_id": decision.bean_id, "grams": decision.grams,
            "unit": "pods" if pods else "g",
            "from_g": (bean.pods_left if pods else bean.remaining_g) if bean else None,
            "remaining_g": decision.new_pods if pods else decision.new_remaining_g,
            "opened": decision.open_bag, "finished": decision.finish,
        })
        await self.store.async_apply_bean_update(
            decision.bean_id, remaining_g=decision.new_remaining_g,
            open_bag=decision.open_bag, finish=decision.finish,
            # The day it was brewed, not the day a waiting brew was saved.
            today=_brew_day(brewed_at), pods_left=decision.new_pods,
        )
        # Noted at once, so a retry after a failed row write does not take
        # from the bag again.
        await self.pending.async_update(run_id, bag={
            "bean_id": decision.bean_id, "grams": decision.grams,
            "remaining_g": decision.new_remaining_g,
            "opened": decision.open_bag, "finished": decision.finish,
        })
        written = await self.store.async_create_brew(record(decision.bean_id))
        # Marked once both writes are in; until then the queue holds the run,
        # and a second delivery of it is refused there.
        await self._runs.async_add(run_id)
        if decision.finish and bean is not None:
            await self._async_ask_about_bag(bean)
        self.on_change()
        return Consumption(
            "counted", bean_id=decision.bean_id, grams=decision.grams,
            remaining_g=decision.new_remaining_g,
            opened=decision.open_bag, finished=decision.finish, brew_id=written.id,
        )

    async def async_record_stopped(
        self, *, bean_id: str | None, grams: Any, run_id: str | None,
        cup_type: Any = None, recipe: str | None = None, brewed_at: str | None = None,
        unattributed: bool = False, xpod_id: str | None = None, tea_id: str | None = None,
    ) -> Consumption:
        """A brew stopped after grinding: its coffee is used, none was made.

        Recorded for someone to decide, with the bag left as it is — whether
        the grounds were brewed some other way or thrown out is not something
        the machine can say. Queued like a finished brew.
        """
        return await self._async_queue_and_count("stopped", run_id, {
            "bean_id": _drawn_from(cup_type, bean_id, xpod_id, tea_id), "grams": grams, "cup_type": cup_type,
            "recipe": recipe, "brewed_at": brewed_at, "unattributed": unattributed,
        })

    async def _async_stopped(
        self, run_id: str, *, bean_id: str | None, grams: Any, cup_type: Any,
        recipe: str | None, brewed_at: str | None, unattributed: bool,
    ) -> Consumption:
        if self._runs.contains(run_id) or await self.store.async_has_run(run_id):
            return Consumption("skipped", reason="already_counted")
        if unattributed or kind_of_cup(cup_type) != "coffee":
            # No bag to put right: the coffee was in a pod, or it was tea, or
            # it came from none.
            return Consumption("skipped", reason="no_bag_used")
        await self.store.async_create_brew(Brew(
            id="", brewed_at=brewed_at or dt_util.utcnow().isoformat(),
            recorded_at=dt_util.utcnow().isoformat(), dose_g=_grams(grams),
            brewer=XBLOOM_BREWER, bean_id=bean_id, dripper=cup_label(cup_type),
            recipe=recipe, outcome="stopped", run_id=run_id,
            review=Review("stopped_after_grinding", {"grams": _grams(grams)}),
        ))
        await self._runs.async_add(run_id)
        return Consumption(
            "flagged", reason="stopped_after_grinding",
            detail={"grams": _grams(grams)}, bean_id=bean_id,
        )

    async def async_start_tracking(
        self, bean_id: str, remaining_g: float | None = None, pods: int | None = None,
    ) -> Bean:
        """Count a bag down from an amount someone measured — an xPod box from its pods.

        Accounting runs forward from this number and claims nothing about the
        bag before it.
        """
        amount = {"pods_left": int(pods)} if pods is not None else {"remaining_g": remaining_g}
        bean = await self.store.async_update_bean(bean_id, tracked=True, **amount)
        self.on_change()
        return bean

    @staticmethod
    def finish_refusal(bean: Bean) -> str | None:
        """Why a bag may not be marked finished, as a code, or None."""
        if bean.status == "unopened":
            # With a coffee bought twice, the unopened bag is the one easiest
            # to finish by mistake.
            return "bag_unopened"
        if bean.kind == "xpod":
            if bean.tracked and bean.pods_left is not None and bean.pods_left >= 1:
                return "box_not_empty"
        elif bean.tracked and bean.remaining_g is not None and bean.remaining_g >= FINISH_BELOW_G:
            return "bag_not_empty"
        return None

    async def async_finish(self, bean_id: str) -> Bean:
        bean = await self.store.async_finish_bag(bean_id, dt_util.now().date().isoformat())
        for key in ACTIVE_KEYS.values():
            if self._state.get(key) == bean_id:
                await self._async_set_state(**{key: None})
        await self._async_ask_about_bag(bean)
        self.on_change()
        return bean

    # ── Reading ──────────────────────────────────────────────────────────

    async def async_stats(self, period: str, now: datetime | None = None) -> Report:
        now = now or dt_util.now()
        # A day earlier than the window needs: a brew stored in UTC can already
        # be the next day locally.
        since = earliest_needed(period, now) - timedelta(days=1)
        return period_report(await self.store.async_list_brews(since=since), period, now)


class _MemoryStorage:
    """Storage that lives only in memory: for a lab built without Home Assistant."""

    def __init__(self) -> None:
        self._data: Any = None

    async def async_load(self) -> Any:
        return self._data

    async def async_save(self, data: Any) -> None:
        self._data = data
