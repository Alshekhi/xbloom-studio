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
from .inventory import Deduct, Flag, Skip, decide_consumption, is_xpod
from .models import SELECTABLE, Bean, Brew, Review
from .pending import PendingBrews
from .stats import DEFAULT_PERIOD, PERIODS, Report, earliest_needed, period_report
from .store import (
    STORAGE_VERSION, CoffeeLabStore, ProcessedRuns, Storage, UnknownBean,
    async_local_store, async_processed_runs,
)

_LOGGER = logging.getLogger(__name__)

STATE_KEY = f"{DOMAIN}.coffee_lab_state"
PENDING_KEY = f"{DOMAIN}.coffee_lab_pending"

# What a store that cannot be reached raises. Anything else is a fault in
# this code, not a reason to wait and try again.
STORE_UNREACHABLE = (HomeAssistantError, aiohttp.ClientError, asyncio.TimeoutError, OSError)

# What an xBloom brew is recorded as in a brew's `brewer`: the product's name.
XBLOOM_BREWER = "xBloom Studio"

# A tracked bag may be finished only once its record shows less than a dose
# left. Above it, one mistaken finish would retire a bag that still holds
# coffee; a bag emptier than its record is weighed and re-based first.
FINISH_BELOW_G = 20.0


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
        self._state = {**self._state, **values}
        await self._state_storage.async_save(self._state)
        self.on_change()

    # ── The active bag ───────────────────────────────────────────────────

    @property
    def active_bean_id(self) -> str | None:
        return self._state.get("active_bean_id")

    async def async_active_bean(self) -> Bean | None:
        """The bag the xBloom draws from, or None if none can be.

        A selection whose bag has since been finished, or removed, is cleared
        rather than brewed against.
        """
        bean_id = self.active_bean_id
        if not bean_id:
            return None
        try:
            bean = await self.store.async_get_bean(bean_id)
        except UnknownBean:
            bean = None
        if bean is None or bean.status not in SELECTABLE:
            await self._async_set_state(active_bean_id=None)
            return None
        return bean

    async def async_select(self, bean_id: str | None) -> Bean | None:
        """Choose the bag the xBloom draws from; the inventory is not touched."""
        if bean_id is None:
            await self._async_set_state(active_bean_id=None)
            return None
        bean = await self.store.async_get_bean(bean_id)
        if bean.status not in SELECTABLE:
            raise UnknownBean(bean_id)
        await self._async_set_state(active_bean_id=bean.id)
        return bean

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

    # ── Counting ─────────────────────────────────────────────────────────

    async def async_consume(
        self, *, bean_id: str | None, grams: Any, run_id: str | None = None,
        cup_type: Any = None, recipe: str | None = None,
        brewer: str | None = XBLOOM_BREWER, brewed_at: str | None = None,
        recipe_source: str | None = None, outcome: str | None = None,
        settings: dict[str, Any] | None = None, unattributed: bool = False,
    ) -> Consumption:
        """Apply one brew to its bag and the record.

        The brew is queued first and counted from the queue, so a store that
        cannot be reached leaves it waiting rather than lost; see pending.py.
        """
        return await self._async_queue_and_count("brew", run_id, {
            "bean_id": bean_id, "grams": grams, "cup_type": cup_type, "recipe": recipe,
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

        # The bag was taken from on an earlier try and only the row is
        # missing: finish that, without deciding the subtraction again.
        if entry.get("bag"):
            bag = entry["bag"]
            if not await self.store.async_has_run(run_id):
                await self.store.async_create_brew(record(bag["bean_id"]))
            await self._runs.async_add(run_id)
            self.on_change()
            return Consumption(
                "counted", bean_id=bag["bean_id"], grams=bag["grams"],
                remaining_g=bag["remaining_g"], opened=bag["opened"], finished=bag["finished"],
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
            if decision.record_brew:
                await self.store.async_create_brew(record(decision.bean_id))
            # Marked after writing: had the write failed, the queue retries it.
            await self._runs.async_add(run_id)
            self.on_change()
            return Consumption(
                "recorded" if decision.record_brew else "skipped",
                reason=decision.reason, bean_id=decision.bean_id,
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
        await self.store.async_apply_bean_update(
            decision.bean_id, remaining_g=decision.new_remaining_g,
            open_bag=decision.open_bag, finish=decision.finish,
            today=dt_util.now().date().isoformat(),
        )
        # Noted at once, so a retry after a failed row write does not take
        # from the bag again.
        await self.pending.async_update(run_id, bag={
            "bean_id": decision.bean_id, "grams": decision.grams,
            "remaining_g": decision.new_remaining_g,
            "opened": decision.open_bag, "finished": decision.finish,
        })
        await self.store.async_create_brew(record(decision.bean_id))
        # Marked once both writes are in; until then the queue holds the run,
        # and a second delivery of it is refused there.
        await self._runs.async_add(run_id)
        self.on_change()
        return Consumption(
            "counted", bean_id=decision.bean_id, grams=decision.grams,
            remaining_g=decision.new_remaining_g,
            opened=decision.open_bag, finished=decision.finish,
        )

    async def async_record_stopped(
        self, *, bean_id: str | None, grams: Any, run_id: str | None,
        cup_type: Any = None, recipe: str | None = None, brewed_at: str | None = None,
        unattributed: bool = False,
    ) -> Consumption:
        """A brew stopped after grinding: its coffee is used, none was made.

        Recorded for someone to decide, with the bag left as it is — whether
        the grounds were brewed some other way or thrown out is not something
        the machine can say. Queued like a finished brew.
        """
        return await self._async_queue_and_count("stopped", run_id, {
            "bean_id": bean_id, "grams": grams, "cup_type": cup_type,
            "recipe": recipe, "brewed_at": brewed_at, "unattributed": unattributed,
        })

    async def _async_stopped(
        self, run_id: str, *, bean_id: str | None, grams: Any, cup_type: Any,
        recipe: str | None, brewed_at: str | None, unattributed: bool,
    ) -> Consumption:
        if self._runs.contains(run_id) or await self.store.async_has_run(run_id):
            return Consumption("skipped", reason="already_counted")
        if unattributed or is_xpod(cup_type):
            # No bag to put right: the coffee was in a pod, or came from none.
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

    async def async_start_tracking(self, bean_id: str, remaining_g: float) -> Bean:
        """Count a bag down from an amount someone measured.

        Accounting runs forward from this number and claims nothing about the
        bag before it.
        """
        bean = await self.store.async_update_bean(
            bean_id, tracked=True, remaining_g=remaining_g
        )
        self.on_change()
        return bean

    @staticmethod
    def finish_refusal(bean: Bean) -> str | None:
        """Why a bag may not be marked finished, as a code, or None."""
        if bean.status == "unopened":
            # With a coffee bought twice, the unopened bag is the one easiest
            # to finish by mistake.
            return "bag_unopened"
        if bean.tracked and bean.remaining_g is not None and bean.remaining_g >= FINISH_BELOW_G:
            return "bag_not_empty"
        return None

    async def async_finish(self, bean_id: str) -> Bean:
        bean = await self.store.async_finish_bag(bean_id, dt_util.now().date().isoformat())
        if self.active_bean_id == bean_id:
            await self._async_set_state(active_bean_id=None)
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
