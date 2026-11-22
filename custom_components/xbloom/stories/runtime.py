"""Brew Stories during a brew.

A brew's texts are written when it starts (`xbloom_brew_started`, or the
machine-started event for a brew from one of the machine's own slots), then
shown as Brew Stage moves: the pour line while a pour runs, a story part from
the wait it was planned for until the next one, the "you" line while the
coffee drains. The brew is remembered once, when it is done.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..brew_stage import _follow
from . import MODES
from .compose import BrewTexts, compose
from .content import Content
from .memory import STORAGE_KEY, STORAGE_VERSION, StoryMemory
from .plan import Slot, plan_slots

_LOGGER = logging.getLogger(__name__)

EV_BREW_STARTED = "xbloom_brew_started"
EV_MACHINE_BREW_STARTED = "xbloom_machine_brew_started"
NOTHING = {"heading": None, "now": None, "story": None, "kind": None}


def signal_story(entry_id: str) -> str:
    return f"xbloom_story_{entry_id}"


class StoryRuntime:
    def __init__(self, hass, entry, *, store=None, content: Content | None = None) -> None:
        self.hass, self.entry = hass, entry
        self.memory = StoryMemory(store or Store(
            hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry.entry_id)))
        self._content = content
        self.mode = "built_in"
        self.current: dict[str, Any] = dict(NOTHING)
        self._texts: BrewTexts | None = None
        self._bag: dict | None = None
        self._recorded = False

    async def async_load(self) -> None:
        await self.memory.async_load()

    async def async_setup(self) -> None:
        """Load what was told, and follow brews."""
        await self.async_load()

        async def _started(event) -> None:
            await self.async_brew_started(dict(event.data))

        async def _machine_started(_event) -> None:
            await self.async_machine_brew_started()

        @callback
        def _stage(event) -> None:
            new = event.data.get("new_state")
            if new is not None:
                self.hass.async_create_task(
                    self.async_on_stage(new.state, new.attributes.get("pour")))

        for unsubscribe in (
            self.hass.bus.async_listen(EV_BREW_STARTED, _started),
            self.hass.bus.async_listen(EV_MACHINE_BREW_STARTED, _machine_started),
            _follow(self.hass, "sensor", "xbloom_brew_stage", _stage),
        ):
            self.entry.async_on_unload(unsubscribe)

    async def _content_now(self) -> Content:
        if self._content is None or self._content.lang != self._language():
            self._content = await self.hass.async_add_executor_job(Content.load, self._language())
        return self._content

    def _language(self) -> str:
        return (getattr(self.hass.config, "language", None) or "en").split("-")[0]

    async def _bag_and_history(self, bean_id: str | None) -> tuple[dict | None, list[dict]]:
        lab = getattr(self.entry.runtime_data, "coffee_lab", None)
        if lab is None or not bean_id:
            return None, []
        from ..coffee_lab.actions import bean_facts
        from ..coffee_lab.lab import STORE_UNREACHABLE
        from ..coffee_lab.store import UnknownBean
        try:
            bean = await lab.store.async_get_bean(bean_id)
            brews = await lab.store.async_list_brews()
        except (UnknownBean, *STORE_UNREACHABLE) as err:
            _LOGGER.info("Brew Stories: bag %s not read (%s); telling no bag story", bean_id, err)
            return None, []
        history = [{"rating": b.rating, "next_change": b.next_change}
                   for b in brews if b.bean_id == bean_id]
        return bean_facts(bean), history

    async def _begin(self, plan: list[dict] | None, bean_id: str | None) -> None:
        self._texts, self._bag, self._recorded = None, None, False
        self._publish(dict(NOTHING))
        if self.mode not in MODES or self.mode == "off":
            return
        content = await self._content_now()
        self._bag, history = await self._bag_and_history(bean_id)
        slots = plan_slots(plan, self._bag is not None)
        self._texts = compose(slots, plan, self._bag, history, self.memory, content,
                              dt_util.now().date())

    async def async_brew_started(self, data: dict[str, Any]) -> None:
        await self._begin(data.get("pours") or None, data.get("bean_id"))

    async def async_machine_brew_started(self) -> None:
        lab = getattr(self.entry.runtime_data, "coffee_lab", None)
        await self._begin(None, lab.active_id("coffee") if lab is not None else None)

    def _story(self, at: str, pour: int) -> tuple[Slot, tuple[str, str]] | None:
        for slot, story in (self._texts.stories.items() if self._texts else ()):
            if slot.at == at and slot.pour == pour:
                return slot, story
        return None

    async def async_on_stage(self, stage: str, pour: int | None) -> None:
        if stage == "idle":
            self._texts = None
            self._publish(dict(NOTHING))
            return
        if self._texts is None:
            return
        shown = dict(self.current)
        if stage == "pouring" and pour:
            shown["now"] = self._texts.pour_lines.get(pour)
            found = self._story("pour", pour)
        elif stage == "waiting" and pour:
            found = self._story("wait", pour)
        elif stage == "draining":
            found = self._story("draining", 0)
        elif stage == "done":
            await self._record()
            return
        else:
            return
        if found:
            slot, (heading, text) = found
            shown.update(heading=heading, story=text, kind=slot.kind)
        self._publish(shown)

    async def _record(self) -> None:
        if self._recorded or self._texts is None:
            return
        self._recorded = True
        texts = self._texts
        await self.memory.async_record_brew(
            self._bag["id"] if self._bag else None, told=texts.told, facts=texts.facts,
            big_story_part_told=texts.big_story_part_told,
            country=(self._bag or {}).get("country"), teaser=texts.teaser,
        )

    def _publish(self, shown: dict[str, Any]) -> None:
        if shown != self.current:
            self.current = shown
            async_dispatcher_send(self.hass, signal_story(self.entry.entry_id))
