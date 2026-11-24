"""Reminding to buy: watching each kind's stock against its level.

Worked out again whenever Coffee Lab changes. A kind crossing below its level
fires `xbloom_stock_low` and, when they are set in Coffee Lab's options, adds
an item to a shopping list and sends a phone notification; rising back fires
`xbloom_stock_restored` and ticks off the item Coffee Lab added, never one
someone else wrote. A finished coffee answered buy again: yes, with no other
bag of it on hand, fires `xbloom_buy_again` and goes on the list by name.

A crossing is stored before anything is delivered, so a list or phone that
fails is not tried again on every brew, and a restart does not remind twice.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, SIGNAL_COFFEE_LAB_STOCK
from .lab import STORE_UNREACHABLE, CoffeeLab
from .models import KINDS, Bean
from .stock import PACE_DAYS, Stock, crossing, figure, floor, stock_of

_LOGGER = logging.getLogger(__name__)

EV_LOW = "xbloom_stock_low"
EV_RESTORED = "xbloom_stock_restored"
EV_BUY_AGAIN = "xbloom_buy_again"
_ON_HAND = ("open", "unopened")
# A store that could not be read is tried again after this, so a startup
# while Notion is down does not leave the stock empty until the next brew.
RETRY_S = 300
# An item added whose uid could not be read back is remembered by its name.
_BY_NAME = "name:"
# Where the reminders' words are kept: one selector's options, per language.
_TEXTS = f"component.{DOMAIN}.selector.stock_text.options."


def _shown(value: float | None) -> str:
    return f"{round(value):d}" if value is not None else "?"


class StockWatch:
    def __init__(
        self, hass, lab: CoffeeLab, *, todo_list: str | None = None,
        notify: str | None = None, texts: dict[str, str] | None = None,
    ) -> None:
        self.hass, self.lab = hass, lab
        self.todo_list = todo_list or None
        self.notify = notify or None
        self._texts = texts
        self._task: asyncio.Task | None = None
        self._again = False
        self._retry = None

    # ── When to look ────────────────────────────────────────────────────

    @callback
    def schedule(self) -> None:
        """Look again soon; calls while a look is under way make one more.

        A callback: the dispatcher runs a plain function in a worker thread,
        where creating the task is unsafe.
        """
        if self._task is not None and not self._task.done():
            self._again = True
            return
        self._task = self.hass.async_create_task(self._run())

    async def _run(self) -> None:
        self._again = True
        while self._again:
            self._again = False
            try:
                await self.async_refresh()
            except Exception:  # noqa: BLE001 — the next change looks again
                _LOGGER.exception("Coffee Lab: stock could not be worked out")

    @callback
    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._retry is not None:
            self._retry()
            self._retry = None

    @callback
    def _try_again(self, _now=None) -> None:
        self._retry = None
        self.schedule()

    # ── Looking ─────────────────────────────────────────────────────────

    async def async_refresh(self) -> None:
        now = dt_util.now()
        try:
            beans = await self.lab.store.async_list_beans(selectable_only=False)
            brews = await self.lab.store.async_list_brews(since=now - timedelta(days=PACE_DAYS + 1))
        except STORE_UNREACHABLE as err:
            _LOGGER.info("Coffee Lab: stock not worked out (%s); trying again in %s s", err, RETRY_S)
            if self._retry is None:
                self._retry = async_call_later(self.hass, RETRY_S, self._try_again)
            return
        self.lab.stock = {kind: stock_of(kind, beans, brews, now) for kind in KINDS}
        # The very first look, after this is installed, only records where
        # each kind stands. After it, a kind with no state yet — one the home
        # has just begun to keep, or whose figure just became known — counts
        # as not low, so finding it low reminds.
        first = not self.lab.stock_seeded
        try:
            await self._look(first)
        finally:
            # Told even when a kind failed part-way: the state written so
            # far is what the entities show.
            async_dispatcher_send(self.hass, SIGNAL_COFFEE_LAB_STOCK)

    async def _look(self, first: bool) -> None:
        for kind, stock in self.lab.stock.items():
            if not stock.kept:
                continue
            measure, level = self.lab.stock_measure(kind), self.lab.stock_level(kind)
            value = figure(stock, measure)
            stored = self.lab.stock_low_state(kind)
            low, event = crossing(stored if stored is not None or first else False, value, level,
                                  floor(stock, measure))
            # Written only when it changed: a write is a Coffee Lab change,
            # which schedules one more look, and that one finds nothing new.
            if low != stored:
                await self.lab.async_set_stock_low_state(kind, low)
            if event == "low":
                self._fire(EV_LOW, kind, stock, measure, level, value)
                await self._remind_low(kind, stock, measure)
            elif event == "restored":
                self._fire(EV_RESTORED, kind, stock, measure, level, value)
                await self._tick_off(kind)
        if first:
            await self.lab.async_mark_stock_seeded()

    def _fire(self, event: str, kind: str, stock: Stock, measure: str, level: float,
              value: float | None) -> None:
        self.hass.bus.async_fire(event, {
            "kind": kind, "measure": measure, "level": level, "value": value,
            "pods" if kind == "xpod" else "grams": stock.amount,
            "bags": stock.bags, "cups": stock.cups,
            "days": stock.days, "unknown": list(stock.unknown),
        })

    # ── Telling ─────────────────────────────────────────────────────────

    async def _words(self) -> dict[str, str]:
        if self._texts is not None:
            return self._texts
        from homeassistant.helpers.translation import async_get_translations
        strings = await async_get_translations(
            self.hass, self.hass.config.language, "selector", {DOMAIN})
        return {k[len(_TEXTS):]: v for k, v in strings.items() if k.startswith(_TEXTS)}

    def _list_name(self) -> str:
        state = self.hass.states.get(self.todo_list) if self.todo_list else None
        return (state.attributes.get("friendly_name") if state else None) or self.todo_list or ""

    async def _open_items(self) -> list[dict[str, Any]]:
        reply = await self.hass.services.async_call(
            "todo", "get_items", {"entity_id": self.todo_list, "status": ["needs_action"]},
            blocking=True, return_response=True)
        return list(((reply or {}).get(self.todo_list) or {}).get("items") or [])

    async def _add(self, name: str) -> str | None:
        """Add `name` unless an open item already has it; the new item's uid, if added."""
        if not self.todo_list:
            return None
        try:
            if any((i.get("summary") or "").strip().casefold() == name.casefold()
                   for i in await self._open_items()):
                return None
            await self.hass.services.async_call(
                "todo", "add_item", {"entity_id": self.todo_list, "item": name}, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Coffee Lab: %s was not added to %s (%s)", name, self.todo_list, err)
            return None
        try:
            added = [i for i in await self._open_items() if i.get("summary") == name]
        except HomeAssistantError:
            added = []
        # Added either way; one whose uid cannot be read is found by its name.
        return (added[-1].get("uid") if added else None) or f"{_BY_NAME}{name}"

    async def _send(self, message: str) -> None:
        if not self.notify:
            return
        try:
            await self.hass.services.async_call(
                "notify", self.notify.split(".", 1)[1], {"message": message}, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Coffee Lab: the reminder did not reach %s (%s)", self.notify, err)

    async def _remind_low(self, kind: str, stock: Stock, measure: str) -> None:
        words = await self._words()
        uid = await self._add(words[f"item_{kind}"])
        if uid:
            await self.lab.async_set_stock_item(kind, uid)
        # Tea in tins and pouches: packs, never "bags" taken for tea bags.
        said = "packs" if kind == "tea" and measure == "bags" else measure
        parts = [words["running_low"].format(kind=words[f"kind_{kind}"]),
                 words[f"left_{said}"].format(n=_shown(floor(stock, measure)))]
        if uid is not None:
            parts.append(words["added"].format(list=self._list_name()))
        await self._send(" ".join(parts))

    async def _tick_off(self, kind: str) -> None:
        uid = self.lab.stock_item(kind)
        if not uid:
            return
        if not self.todo_list:
            await self.lab.async_set_stock_item(kind, None)
            return
        try:
            items = await self._open_items()
            if uid.startswith(_BY_NAME):
                name = uid[len(_BY_NAME):].casefold()
                found = next((i.get("uid") for i in items
                              if (i.get("summary") or "").strip().casefold() == name), None)
            else:
                found = uid if any(i.get("uid") == uid for i in items) else None
            if found:
                await self.hass.services.async_call(
                    "todo", "update_item",
                    {"entity_id": self.todo_list, "item": found, "status": "completed"},
                    blocking=True)
        except HomeAssistantError as err:
            # Kept, to be ticked off at the next rise back.
            _LOGGER.warning("Coffee Lab: the list item was not ticked off (%s)", err)
            return
        await self.lab.async_set_stock_item(kind, None)

    async def async_buy_again(self, bean: Bean) -> None:
        """A finished coffee answered buy again: yes. On the list, unless already on hand."""
        if bean.status != "finished" or self.lab.buy_again_told(bean.id):
            return
        try:
            beans = await self.lab.store.async_list_beans(selectable_only=False)
        except STORE_UNREACHABLE as err:
            _LOGGER.info("Coffee Lab: buy again not checked (%s)", err)
            return
        if any(b.id != bean.id and b.status in _ON_HAND and b.same_coffee(bean) for b in beans):
            return
        await self.lab.async_mark_buy_again_told(bean.id)
        self.hass.bus.async_fire(EV_BUY_AGAIN, {
            "bean_id": bean.id, "name": bean.name, "roaster": bean.roaster or None})
        words = await self._words()
        name = f"{bean.name}, {bean.roaster}" if bean.roaster else bean.name
        uid = await self._add(name)
        parts = [words["buy_again"].format(name=name)]
        if uid is not None:
            parts.append(words["added"].format(list=self._list_name()))
        await self._send(" ".join(parts))
