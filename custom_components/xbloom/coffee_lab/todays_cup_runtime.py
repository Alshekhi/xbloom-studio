"""Today's cup, kept current: read once, picked (todays_cup.py), and used.

Recomputed when Coffee Lab changes, when the Drink setting changes, at local
midnight, and when a brew ends — never while one runs, so what was picked for
it stays put. Each recompute reads the bags and a year of brews once; a store
that cannot be reached leaves the last pick as it was.

Using it picks the bag, then the recipe (adding a community one to the library
first), then the dose — the same picks made by hand on the Brew tab, which
prepare the machine. The brew itself is started by the person.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util
from xbloom import spec

from ..community import of_drink
from ..suggestions import HISTORY_DAYS, rank
from ..tool_common import fail
from .habits import habits
from .lab import STORE_UNREACHABLE, CoffeeLab
from .opening import USUAL_DAYS, usual_dose
from .todays_cup import OwnRecipe, Pick, candidates

_LOGGER = logging.getLogger(__name__)

SIGNAL_TODAYS_CUP = "xbloom_todays_cup"
BREW_STATUS = "sensor.xbloom_studio_brew_status"
RECIPE_SELECT = "select.xbloom_studio_recipe"
DOSE_NUMBER = "number.xbloom_studio_brew_dose"
BUSY = ("grinding", "brewing")
# How long the dose slider is given to follow the recipe just picked.
SEED_WAIT_S = 2.0
# A refresh waits this long for a burst of changes to settle.
SETTLE_S = 5
# Routine refreshes no closer together than this.
MIN_INTERVAL_S = 600


def refresh_delay(last: float | None, now: float, force: bool) -> float:
    """Seconds until the next refresh: a routine one waits its turn.

    Every Coffee Lab change asks for a refresh — and with Notion so does the
    re-read every few minutes — while each refresh reads a year of brews.
    """
    if force or last is None or now - last >= MIN_INTERVAL_S:
        return SETTLE_S
    return MIN_INTERVAL_S - (now - last)


class TodaysCup:
    def __init__(self, hass: HomeAssistant, lab: CoffeeLab, browser: Any,
                 library: Callable[[], list[dict[str, Any]]]) -> None:
        self.hass = hass
        self.lab = lab
        self.browser = browser
        self._library = library
        self.picks: list[Pick] = []
        self.index = 0
        # A refresh asked for during a brew, run once it ends.
        self.waiting = False
        self._refreshing = asyncio.Lock()
        self._pending: Callable[[], None] | None = None
        self._last_refresh: float | None = None

    def schedule(self, *_: Any) -> None:
        """Refresh after a routine change: at most every MIN_INTERVAL_S."""
        self._schedule(force=False)

    def schedule_now(self, *_: Any) -> None:
        """Refresh after a brew ends, the drink changes or the day turns."""
        self._schedule(force=True)

    def _schedule(self, force: bool) -> None:
        if self._pending is not None:
            self._pending()
        delay = refresh_delay(self._last_refresh, time.monotonic(), force)
        self._pending = async_call_later(self.hass, delay, self._run)

    async def _run(self, _now: Any) -> None:
        self._pending = None
        try:
            await self.async_refresh()
        except Exception:  # noqa: BLE001 — a failed pick must not stop anything else
            _LOGGER.exception("Coffee Lab: today's cup could not be worked out")

    def stop(self) -> None:
        if self._pending is not None:
            self._pending()
            self._pending = None

    @property
    def pick(self) -> Pick | None:
        return self.picks[self.index] if self.picks else None

    def busy(self) -> bool:
        state = self.hass.states.get(BREW_STATUS)
        return state is not None and state.state in BUSY

    def _changed(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_TODAYS_CUP)

    async def async_refresh(self) -> None:
        if self.busy():
            self.waiting = True
            return
        async with self._refreshing:
            self.waiting = False
            now = dt_util.now()
            try:
                beans = await self.lab.store.async_list_beans(selectable_only=False)
                brews = await self.lab.store.async_list_brews(since=now - timedelta(days=HISTORY_DAYS))
            except STORE_UNREACHABLE as err:
                _LOGGER.warning("Coffee Lab: today's cup kept as it was: %s", err)
                return
            drink = "iced" if getattr(self.browser, "drink", "any") == "iced" else "hot"
            library = of_drink(self._library() or [], drink)
            own = {
                b.id: [OwnRecipe(o.name, any(v.get("verdict") == "again" for v in o.versions), o.matched)
                       for o in rank(b, beans, brews, library)]
                for b in beans if b.kind == "coffee" and b.status in ("open", "unopened")
            }
            dose = self._dose(drink, brews, now)
            rules = self.lab.opening
            per_day = habits(brews, beans, now - timedelta(days=USUAL_DAYS), now)["cups_per_brewing_day"]
            daily_g = (dose or 15.0) * (per_day or 1.0)
            picks = candidates(beans, brews, own, {}, drink, now, rules, dose or 15.0, daily_g)
            first = picks[0] if picks else None
            if first is not None and first.recipe is None:
                bag = next(b for b in beans if b.id == first.bag_id)
                try:
                    hub = await self.browser.async_community_for(bag, drink)
                except Exception as err:  # noqa: BLE001 — the hub is optional here
                    _LOGGER.info("Coffee Lab: no community recipe for today's cup: %s", err)
                    hub = None
                if hub:
                    picks = candidates(beans, brews, own, {bag.id: hub}, drink, now, rules,
                                       dose or 15.0, daily_g)
            chosen = self.pick
            self.picks = [self._fit_dose(p, dose) for p in picks]
            # A cup chosen with Another stays while it is still on offer.
            self.index = next((i for i, p in enumerate(self.picks) if chosen is not None
                               and (p.bag_id, p.recipe) == (chosen.bag_id, chosen.recipe)), 0)
            self._last_refresh = time.monotonic()
            self._changed()

    def _dose(self, drink: str, brews: list, now: datetime) -> float | None:
        """The usual dose for the drink; None for iced with no habit: the recipe's then."""
        if drink == "hot":
            return usual_dose(brews, now)
        usual = habits(brews, [], now - timedelta(days=USUAL_DAYS), now)["usual"].get("iced")
        return float(usual["dose_g"]) if usual else None

    def _fit_dose(self, pick: Pick, dose: float | None) -> Pick:
        """The dose within what the recipe's cup takes; a recipe's own without a usual one."""
        recipe = next((r for r in self._library() or [] if r.get("name") == pick.recipe), None)
        value = dose if dose is not None else float((recipe or {}).get("dose_g") or 15.0)
        try:
            window = spec.CUP_DOSE.get(int(recipe["cup_type"])) if recipe else None
        except (TypeError, ValueError, KeyError):
            window = None
        if window is not None:
            value = min(max(value, float(window.min)), float(window.max))
        return replace(pick, dose_g=float(value))

    async def async_another(self) -> None:
        """The next cup on offer; the one passed over is counted for later."""
        if not self.picks:
            return
        await self.lab.async_count_skip(self.pick.bag_id, self.pick.recipe)
        self.index = (self.index + 1) % len(self.picks)
        self._changed()

    async def async_use(self) -> None:
        """Pick the bag, the recipe and the dose on the Brew tab; nothing is started."""
        pick = self.pick
        if pick is None:
            raise fail("suggestion_none")
        if self.busy():
            raise fail("refused_machine_busy")
        await self.lab.async_select(pick.bag_id)
        if pick.recipe is None:
            return
        if pick.recipe_source == "community":
            await self.browser.async_add_and_use_recipe({"id": pick.hub_id, "name": pick.recipe})
        else:
            await self.browser.async_use(pick.recipe)
        # The dose slider takes the recipe's dose when the recipe is picked;
        # the usual dose is set once it has.
        for _ in range(int(SEED_WAIT_S / 0.1)):
            state = self.hass.states.get(RECIPE_SELECT)
            if state is not None and state.state == pick.recipe:
                break
            await asyncio.sleep(0.1)
        await self.hass.services.async_call(
            "number", "set_value", {"entity_id": DOSE_NUMBER, "value": pick.dose_g}, blocking=True,
        )
