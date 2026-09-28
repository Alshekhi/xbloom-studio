"""Prepare the picked recipe ahead, so Start Brew sends only execute.

The official app sends a recipe on its first tap and execute alone on the
second. Here the dashboard's own picks are the first tap: while a recipe is
picked — and, with Coffee Lab on, a bag — the recipe as the brew customizer
would send it is prepared over the Connect session, and prepared again when any
of those picks changes. A start for the same recipe and settings then sends
execute alone; anything else sends the whole brew, as before.

It owns three things besides:
  * Recipe Ready — on only while what the machine holds is what a start now
    would send.
  * The Connect switch, when it turned it on: it turns it off again once the
    brew is over. A session someone turned on themselves is left as it was.
  * What happens when a brew ends: coffee made or used clears the recipe and
    the bag, so the next brew starts from a fresh pick; a brew that failed
    before using any coffee keeps both and is prepared again.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

RECIPE = "select.xbloom_studio_recipe"
BAG = "select.xbloom_studio_coffee_bag"
DOSE = "number.xbloom_studio_brew_dose"
RATIO = "number.xbloom_studio_brew_ratio"
GRIND = "number.xbloom_studio_brew_grind_size"
USE_GRINDER = "switch.xbloom_studio_use_grinder"
CONNECT = "switch.xbloom_studio_connect"
IN_RANGE = "binary_sensor.xbloom_studio_in_range"
BREW_STATUS = "sensor.xbloom_studio_brew_status"

WATCHED = [RECIPE, BAG, DOSE, RATIO, GRIND, USE_GRINDER]
# Dragging a slider changes it many times; prepare once it has settled.
SETTLE_S = 1.5
BUSY = ("grinding", "brewing")
UNUSABLE = ("unknown", "unavailable", "")


def signal_prepared(entry_id: str) -> str:
    """Recipe Ready changed: payload (ready: bool, reason: str | None)."""
    return f"xbloom_prepared_{entry_id}"


def dashboard_brew(hass: HomeAssistant) -> dict:
    """The start_brew data the dashboard's Start Brew button sends now."""
    data: dict = {}
    for key, entity_id, cast in (
        ("ratio", RATIO, float), ("grind_size", GRIND, lambda v: int(float(v))), ("dose", DOSE, float),
    ):
        st = hass.states.get(entity_id)
        if st is None or st.state in UNUSABLE:
            continue
        try:
            data[key] = cast(st.state)
        except (TypeError, ValueError):
            continue
    return data


class BrewPreparer:
    """Keeps the picked recipe prepared on the machine."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        prepare: Callable[[dict], Awaitable[None]],
        brew_running: Callable[[], bool],
        send_quit: Callable[[], Awaitable[None]],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._prepare = prepare
        self._brew_running = brew_running
        self._send_quit = send_quit
        # Coffee Lab on and the coffee from no bag (an xPod), as prepare_brew
        # may say; the dashboard has no way to, so it lasts until the picks
        # are cleared.
        self.unattributed = False
        # Something was sent to the machine that a quit should take back.
        self._sent = False
        self._lock = asyncio.Lock()
        self._timer: CALLBACK_TYPE | None = None
        self._task: asyncio.Task | None = None
        self.ready = False
        self.reason: str | None = None
        # Connect was turned on by this, not by someone, so this turns it off.
        self.owns_connect = False
        # While this changes the picks itself, their changes are not requests.
        self._quiet = False
        # Set while this turns Connect off, so it is not read as an undo.
        self._releasing = False

    # ── Wiring ──────────────────────────────────────────────────────────────

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        unsubs = [
            async_track_state_change_event(self._hass, WATCHED, self._on_change),
            async_track_state_change_event(self._hass, [BREW_STATUS], self._on_status),
        ]

        @callback
        def _stop() -> None:
            self._cancel_timer()
            for unsub in unsubs:
                unsub()

        return _stop

    @callback
    def _on_status(self, event: Event) -> None:
        """A brew started from the machine's own button, after preparing.

        It runs no Home Assistant brew, so nothing else reports its end; the
        status reaching done does. A Home Assistant brew reports its own.
        """
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or old.state not in BUSY or new.state != "done":
            return
        if self._brew_running():
            return
        self._hass.async_create_task(self.async_brew_ended(True))

    @callback
    def _on_change(self, event: Event) -> None:
        old, new = event.data.get("old_state"), event.data.get("new_state")
        # Entities appearing at startup are not someone choosing a recipe.
        if old is None or new is None or old.state == "unavailable" or self._quiet:
            return
        if old.state == new.state and event.data["entity_id"] != RECIPE:
            return
        self._set_ready(False, None)
        self._schedule()

    @callback
    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer()
        self._timer = async_call_later(self._hass, SETTLE_S, self._fire)

    @callback
    def _fire(self, _now=None) -> None:
        self._timer = None
        self._task = self._hass.async_create_task(self._prepare_picks())

    # ── Preparing ───────────────────────────────────────────────────────────

    def _missing(self) -> str | None:
        """Why the picks cannot be prepared now, or None when they can."""
        recipe = self._hass.states.get(RECIPE)
        if recipe is None or recipe.state in UNUSABLE:
            return "no_recipe"
        if self._entry.runtime_data.coffee_lab is not None and not self.unattributed:
            bag = self._hass.states.get(BAG)
            if bag is None or bag.state in UNUSABLE:
                return "no_bag"
        if self._brew_running():
            return "brewing"
        status = self._hass.states.get(BREW_STATUS)
        if status is not None and status.state in BUSY:
            return "brewing"
        in_range = self._hass.states.get(IN_RANGE)
        if in_range is not None and in_range.state == "off":
            return "machine_not_found"
        return None

    async def _prepare_picks(self) -> None:
        async with self._lock:
            if (missing := self._missing()) is not None:
                self._set_ready(False, missing)
                return
            self._sent = True
            try:
                await self._prepare(dashboard_brew(self._hass))
            except Exception as err:  # noqa: BLE001 — the reason is shown, not raised
                key = getattr(err, "translation_key", None) or type(err).__name__
                _LOGGER.warning("xbloom: the picked recipe was not prepared: %s", err)
                self._set_ready(False, key)
                return
            self._set_ready(True, None)

    async def async_prepare_now(self) -> None:
        """Prepare the picks at once and wait; raise what stopped it.

        For prepare_brew: the caller is told the recipe is ready only when the
        machine has accepted it.
        """
        self._cancel_timer()
        async with self._lock:
            if (missing := self._missing()) is not None:
                self._set_ready(False, missing)
                raise PrepareRefused(missing)
            self._sent = True
            try:
                await self._prepare(dashboard_brew(self._hass))
            except Exception as err:
                self._set_ready(False, getattr(err, "translation_key", None) or type(err).__name__)
                raise
            self._set_ready(True, None)

    async def async_settled(self, timeout: float = 20.0) -> None:
        """Finish a preparation that is waiting or under way, for a start.

        A start must never send execute for a recipe older than the picks.
        """
        if self._timer is not None:
            self._cancel_timer()
            self._task = self._hass.async_create_task(self._prepare_picks())
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout)
            except TimeoutError:
                _LOGGER.warning("xbloom: preparation still running at start — sending the whole brew")

    # ── Connect ─────────────────────────────────────────────────────────────

    async def async_hold_link(self) -> None:
        """Turn Connect on for a preparation, remembering it was this."""
        state = self._hass.states.get(CONNECT)
        if state is not None and state.state == "on":
            return
        self.owns_connect = True
        await self._hass.services.async_call(
            "switch", "turn_on", {"entity_id": CONNECT}, blocking=True,
        )

    @property
    def releasing(self) -> bool:
        return self._releasing

    @callback
    def async_link_lost(self) -> None:
        """The session ended: what it held is no longer known to be there."""
        self.owns_connect = False
        self._sent = False
        self._set_ready(False, None)

    # ── Ends ────────────────────────────────────────────────────────────────

    async def async_brew_ended(self, used_coffee: bool) -> None:
        """Clear the picks after coffee was made or used; otherwise prepare again."""
        self._sent = False
        self._set_ready(False, None)
        if not used_coffee:
            if self._missing() is None:
                self._schedule()
            return
        await self._clear_picks()
        await self._release()

    async def async_undo(self) -> None:
        """Connect is being turned off by hand: take back what was sent, unpick.

        Called before the session closes, so the quit can still go over it.
        A session used for nothing but the knobs is closed with the picks left
        as they are: there is nothing to undo.
        """
        if not (self._sent or self.owns_connect):
            return
        await self._take_back()
        self.owns_connect = False
        await self._clear_picks(bag=False)

    async def async_cancel(self) -> None:
        """A change of mind: take back what was sent, unpick the recipe.

        The bag stays picked — changing the recipe is not changing the coffee.
        Connect goes off again only if this turned it on.
        """
        await self._take_back()
        await self._clear_picks(bag=False)
        await self._release()

    async def _take_back(self) -> None:
        self._cancel_timer()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        async with self._lock:
            if self._sent:
                try:
                    await self._send_quit()
                except Exception as err:  # noqa: BLE001 — unpicking goes ahead regardless
                    _LOGGER.warning("xbloom: the prepared recipe was not taken back: %s", err)
            self._sent = False
            self._set_ready(False, None)

    async def _clear_picks(self, bag: bool = True) -> None:
        self._cancel_timer()
        self._quiet = True
        try:
            self.unattributed = False
            async_dispatcher_send(self._hass, signal_clear_recipe(self._entry.entry_id))
            lab = self._entry.runtime_data.coffee_lab
            if bag and lab is not None and lab.active_bean_id is not None:
                await lab.async_select(None)
        finally:
            self._quiet = False

    async def _release(self) -> None:
        if not self.owns_connect:
            return
        self.owns_connect = False
        self._releasing = True
        try:
            await self._hass.services.async_call(
                "switch", "turn_off", {"entity_id": CONNECT}, blocking=True,
            )
        finally:
            self._releasing = False

    # ── State ───────────────────────────────────────────────────────────────

    @callback
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    @callback
    def _set_ready(self, ready: bool, reason: str | None) -> None:
        if (ready, reason) == (self.ready, self.reason):
            return
        self.ready, self.reason = ready, reason
        async_dispatcher_send(self._hass, signal_prepared(self._entry.entry_id), ready, reason)


class PrepareRefused(Exception):
    """The picks cannot be prepared now; `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def signal_clear_recipe(entry_id: str) -> str:
    """Unpick the recipe."""
    return f"xbloom_clear_recipe_{entry_id}"
