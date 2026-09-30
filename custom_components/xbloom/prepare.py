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
  * What happens when a brew ends: the recipe is unpicked, so the next brew
    starts from a fresh pick. Coffee made or used clears the bag and lets
    Connect go; a brew that made none keeps both, for picking again at once.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

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
# After a brew that made no coffee Connect stays on for the next pick; with no
# pick this long after, it is let go, so the app can have the machine back.
IDLE_RELEASE_S = 300
# Dragging a slider changes it many times; prepare once it has settled.
SETTLE_S = 1.5
# A recipe reaching the machine is announced once the picks have been left
# alone this long, so adjusting the dose, the ratio and the grind one after the
# other is announced once, with all of them, rather than after each.
ANNOUNCE_SETTLE_S = 4
EV_PREPARED = "xbloom_recipe_prepared"
EV_NOT_PREPARED = "xbloom_recipe_not_prepared"
BUSY = ("grinding", "brewing")
UNUSABLE = ("unknown", "unavailable", "")


def signal_prepared(entry_id: str) -> str:
    """Recipe Ready changed: payload (ready, reason, preparing)."""
    return f"xbloom_prepared_{entry_id}"


def changes_from_recipe(
    saved: Mapping[str, Any], dose: float | None, ratio: float | None,
    grind_size: int | None, use_grinder: bool | None,
) -> dict[str, dict[str, Any]]:
    """What a brew changes from the recipe as saved: {field: {saved, now}}.

    The water is not a setting of its own — it follows the dose and the ratio —
    but it is what changes in the cup, so it is given whenever either does.
    """
    changes: dict[str, dict[str, Any]] = {}
    for key, attr, now in (
        ("dose", "dose_g", dose), ("ratio", "water_ratio", ratio), ("grind_size", "grinder_size", grind_size),
    ):
        if now is not None and saved.get(attr) is not None and float(saved[attr]) != float(now):
            changes[key] = {"saved": saved[attr], "now": now}
    if ("dose" in changes or "ratio" in changes) and saved.get("dose_g") and saved.get("water_ratio"):
        changes["water"] = {
            "saved": round(float(saved["dose_g"]) * float(saved["water_ratio"])),
            "now": round(float(dose if dose is not None else saved["dose_g"])
                         * float(ratio if ratio is not None else saved["water_ratio"])),
        }
    # A recipe marks pre-ground coffee as grinder_size_enabled 2.
    saved_grinder = saved.get("grinder_size_enabled") != 2
    if use_grinder is not None and use_grinder != saved_grinder:
        changes["use_grinder"] = {"saved": saved_grinder, "now": use_grinder}
    return changes


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
        prepare: Callable[[dict], Awaitable[dict | None]],
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
        # What Use Grinder was before a preparation changed it: put back when
        # the picks are cleared, so pre-ground for one brew is not every brew.
        self.grinder_before: str | None = None
        self._lock = asyncio.Lock()
        self._timer: CALLBACK_TYPE | None = None
        self._task: asyncio.Task | None = None
        self.ready = False
        self.reason: str | None = None
        # A preparation is waiting to go, or under way.
        self.preparing = False
        # Connect was turned on by this, not by someone, so this turns it off.
        self.owns_connect = False
        # While this changes the picks itself, their changes are not requests.
        self._quiet = False
        # Set while this turns Connect off, so it is not read as an undo.
        self._releasing = False
        # Lets Connect go if nothing is picked after a brew that made no coffee.
        self._idle_timer: CALLBACK_TYPE | None = None
        # What the machine was last sent — the recipe and what differs from it
        # — and the announcement of it, waiting for the picks to settle.
        self._sent_info: dict | None = None
        self._announce_timer: CALLBACK_TYPE | None = None
        self._pending_announcement: tuple[str, dict] | None = None

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
            self._cancel_idle_release()
            self._cancel_announce()
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
        if event.data["entity_id"] == RECIPE and new.state not in UNUSABLE:
            self._cancel_idle_release()
        self._schedule()

    @callback
    def _schedule(self) -> None:
        self._set_ready(False, None, preparing=True)
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
                info = await self._prepare(dashboard_brew(self._hass))
            except Exception as err:  # noqa: BLE001 — the reason is shown, not raised
                key = getattr(err, "translation_key", None) or type(err).__name__
                _LOGGER.warning("xbloom: the picked recipe was not prepared: %s", err)
                self._set_ready(False, key)
                self._announce_failure(err)
                return
            self._set_ready(True, None)
            self._announce_soon(info)

    @callback
    def async_prepare_soon(self) -> None:
        """Start preparing the picks at once, without waiting for it.

        For a caller that should answer straight away and check back: the
        outcome shows in Recipe Ready, and a start waits for it. What stops
        it before anything is sent is raised now.
        """
        if (missing := self._missing()) is not None:
            self._set_ready(False, missing)
            raise PrepareRefused(missing)
        self._cancel_timer()
        self._set_ready(False, None, preparing=True)
        self._task = self._hass.async_create_task(self._prepare_picks())

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
            self._set_ready(False, None, preparing=True)
            self._sent = True
            try:
                info = await self._prepare(dashboard_brew(self._hass))
            except Exception as err:
                self._set_ready(False, getattr(err, "translation_key", None) or type(err).__name__)
                self._announce_failure(err)
                raise
            self._set_ready(True, None)
            self._announce_soon(info)

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
        self._cancel_idle_release()
        self.owns_connect = False
        self._sent = False
        self._sent_info = None
        self._set_ready(False, None)

    # ── Ends ────────────────────────────────────────────────────────────────

    async def async_brew_ended(self, used_coffee: bool) -> None:
        """Unpick after every brew; the bag too once coffee was made or used.

        A brew that made no coffee — no beans, a refusal, a stop before
        grinding — keeps the bag, still the right one, and keeps Connect on:
        the next thing is refilling and picking the recipe again, and
        reconnecting would only delay it. Connect is let go after a while if
        no recipe is picked.
        """
        self._sent = False
        self._sent_info = None
        self._set_ready(False, None)
        await self._clear_picks(bag=used_coffee)
        if used_coffee:
            await self._release()
        elif self.owns_connect:
            self._cancel_idle_release()
            self._idle_timer = async_call_later(self._hass, IDLE_RELEASE_S, self._idle_release)

    @callback
    def _idle_release(self, _now=None) -> None:
        self._idle_timer = None
        recipe = self._hass.states.get(RECIPE)
        if recipe is None or recipe.state in UNUSABLE:
            self._hass.async_create_task(self._release())

    @callback
    def _cancel_idle_release(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer()
            self._idle_timer = None

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
            self._sent_info = None
            self._set_ready(False, None)

    async def _clear_picks(self, bag: bool = True) -> None:
        self._cancel_timer()
        self._quiet = True
        try:
            self.unattributed = False
            async_dispatcher_send(self._hass, signal_clear_recipe(self._entry.entry_id))
            if self.grinder_before is not None:
                before, self.grinder_before = self.grinder_before, None
                await self._hass.services.async_call(
                    "switch", "turn_on" if before == "on" else "turn_off",
                    {"entity_id": USE_GRINDER}, blocking=True,
                )
            lab = self._entry.runtime_data.coffee_lab
            if bag and lab is not None and lab.active_bean_id is not None:
                await lab.async_select(None)
        finally:
            self._quiet = False

    async def _release(self) -> None:
        self._cancel_idle_release()
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

    # ── Announcing ──────────────────────────────────────────────────────────

    @callback
    def _announce_soon(self, info: dict | None) -> None:
        """Announce what the machine holds once the picks have settled.

        `info` is None when nothing had to be sent — the machine already held
        it — and then what was last sent is still what it holds.
        """
        if info is not None:
            self._sent_info = info
        if self._sent_info is not None:
            self._announce_later(EV_PREPARED, self._sent_info)

    @callback
    def _announce_failure(self, err: Exception) -> None:
        """Announce a recipe the machine did not take, if it stays that way.

        An attempt the next one replaces — the link answering late, the picks
        still changing — is not news.
        """
        if (detail := getattr(err, "not_prepared", None)) is not None:
            self._announce_later(EV_NOT_PREPARED, detail)

    @callback
    def _announce_later(self, event: str, data: dict) -> None:
        self._cancel_announce()
        self._pending_announcement = (event, data)
        self._announce_timer = async_call_later(self._hass, ANNOUNCE_SETTLE_S, self._announce)

    @callback
    def _announce(self, _now=None) -> None:
        self._announce_timer = None
        pending, self._pending_announcement = self._pending_announcement, None
        if pending is None:
            return
        event, data = pending
        # A brew started meanwhile announces itself.
        status = self._hass.states.get(BREW_STATUS)
        if self._brew_running() or (status is not None and status.state in BUSY):
            return
        # Still true once the picks have settled, or it is not said.
        if event == EV_PREPARED and not self.ready:
            return
        if event == EV_NOT_PREPARED and (self.ready or self.preparing):
            return
        self._hass.bus.async_fire(event, data)

    @callback
    def _cancel_announce(self) -> None:
        if self._announce_timer is not None:
            self._announce_timer()
            self._announce_timer = None
        self._pending_announcement = None

    # ── State ───────────────────────────────────────────────────────────────

    @callback
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    @callback
    def _set_ready(self, ready: bool, reason: str | None, preparing: bool = False) -> None:
        if not ready:
            # Picks changing again, or anything else that stops it being
            # ready, starts the wait over.
            self._cancel_announce()
        if (ready, reason, preparing) == (self.ready, self.reason, self.preparing):
            return
        self.ready, self.reason, self.preparing = ready, reason, preparing
        async_dispatcher_send(
            self._hass, signal_prepared(self._entry.entry_id), ready, reason, preparing,
        )


class PrepareRefused(Exception):
    """The picks cannot be prepared now; `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def signal_clear_recipe(entry_id: str) -> str:
    """Unpick the recipe."""
    return f"xbloom_clear_recipe_{entry_id}"
