"""Brew Stories during a brew.

A brew's texts are written when it starts (`xbloom_brew_started`, or the
machine-started event for a brew from one of the machine's own slots), then
shown as Brew Stage moves: the pour line while a pour runs, a story part from
the wait it was planned for until the next one, the "you" line while the
coffee drains. The brew is remembered once, when it is done.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..brew_stage import _follow
from ..const import CONF_STORY_AGENT
from . import LANGUAGES, MODES
from .agent import AGENT_KINDS, TASK_NAME, build_request, parse_reply, slot_key
from .compose import BrewTexts, compose
from .content import Content
from .memory import STORAGE_KEY, STORAGE_VERSION, StoryMemory
from .plan import Slot, plan_slots

_LOGGER = logging.getLogger(__name__)

EV_BREW_STARTED = "xbloom_brew_started"
EV_MACHINE_BREW_STARTED = "xbloom_machine_brew_started"
NOTHING = {"heading": None, "now": None, "story": None, "kind": None}
# The brews read for a bag's history: newest first, far more than one bag holds.
HISTORY_BREWS = 100
# Rated brews of any bag a story agent is given to find patterns in.
RATED_BREWS = 30
# A story agent's reply later than this would miss nearly every slot of a brew.
AGENT_TIMEOUT_S = 120
# Stages a late-written brew catches up with.
_UNDER_WAY = ("pouring", "waiting", "draining")


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
        # The last stage Brew Stage reported, for a brew whose texts were
        # still being written when it arrived.
        self._stage: tuple[str, int | None] = ("idle", None)
        self.agent_entity: str | None = (entry.data or {}).get(CONF_STORY_AGENT) or None
        # Which brew a story agent's reply belongs to, and the texts it told.
        self._brew_id = 0
        self._agent_task: asyncio.Future | None = None
        self._agent_texts: list[str] = []
        # The built-in texts of an agent brew: its facts, teaser and big story.
        self._built: BrewTexts | None = None

    def set_mode(self, mode: str) -> None:
        """Brew Stories on or off; off clears what a brew under way shows."""
        self.mode = mode
        if mode == "off":
            self._texts = None
            self._publish(dict(NOTHING))

    def set_agent(self, entity_id: str | None) -> None:
        """The AI Task entity that writes stories; none leaves the agent mode."""
        self.agent_entity = entity_id or None
        if self.agent_entity is None and self.mode == "agent":
            self.set_mode("built_in")

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

    async def async_set_language(self, language: str) -> None:
        """The language the next brew's stories are told in, kept from now on."""
        await self.memory.async_set_language(language)

    def _language(self) -> str:
        if self.memory.language in LANGUAGES:
            return self.memory.language
        own = (getattr(self.hass.config, "language", None) or "").split("-")[0]
        return own if own in LANGUAGES else LANGUAGES[0]

    async def _bag_and_history(self, bean_id: str | None) -> tuple[dict | None, list[dict]]:
        lab = getattr(self.entry.runtime_data, "coffee_lab", None)
        if lab is None or not bean_id:
            return None, []
        from ..coffee_lab.actions import bean_facts
        from ..coffee_lab.lab import STORE_UNREACHABLE
        from ..coffee_lab.store import UnknownBean
        try:
            # A brew of this bag still waiting to be saved (one by hand, say)
            # is one of its cups: saved first, it is in what is read next.
            await lab.async_retry_pending()
            bean = await lab.store.async_get_bean(bean_id)
            brews = await lab.store.async_list_brews(bean_id=bean_id, limit=HISTORY_BREWS)
        except (UnknownBean, *STORE_UNREACHABLE) as err:
            _LOGGER.info("Brew Stories: bag %s not read (%s); telling no bag story", bean_id, err)
            return None, []
        return bean_facts(bean), [_brew_facts(b) for b in brews]

    async def _rated(self) -> list[dict]:
        """The latest rated brews of any bag, with the bag each came from."""
        lab = getattr(self.entry.runtime_data, "coffee_lab", None)
        if lab is None:
            return []
        from ..coffee_lab.lab import STORE_UNREACHABLE
        try:
            brews = await lab.store.async_list_brews(limit=HISTORY_BREWS)
            beans = {b.id: b for b in await lab.store.async_list_beans(selectable_only=False)}
        except STORE_UNREACHABLE as err:
            _LOGGER.info("Brew Stories: rated history not read (%s)", err)
            return []
        rated = []
        for brew in (b for b in brews if b.rating is not None):
            bean = beans.get(brew.bean_id)
            rated.append({**_brew_facts(brew), "bag": bean.name if bean else None,
                          "country": bean.country if bean else None,
                          "process": bean.process if bean else None})
        return rated[:RATED_BREWS]

    async def _begin(
        self, plan: list[dict] | None, bean_id: str | None,
        recipe: str | None = None, settings: dict | None = None,
    ) -> None:
        self._texts, self._bag, self._built, self._recorded = None, None, None, False
        self._publish(dict(NOTHING))
        if self.mode not in MODES or self.mode == "off":
            return
        content = await self._content_now()
        self._bag, history = await self._bag_and_history(bean_id)
        slots = plan_slots(plan, self._bag is not None)
        built = compose(slots, plan, self._bag, history, self.memory, content,
                        dt_util.now().date())
        self._brew_id += 1
        self._agent_texts = []
        if self._agent_task is not None and not self._agent_task.done():
            # The last brew's request would only be dropped when it came back.
            self._agent_task.cancel()
        if self.mode == "agent":
            # The agent writes only this cup's parts; everything else stays
            # built-in, and its slots stay empty until the reply arrives.
            self._built = built
            this_cup = content.entry("headings.this_cup")
            asked = BrewTexts(teaser=built.teaser, stories={
                slot: ((this_cup if slot.kind == "bag" else heading), text)
                for slot, (heading, text) in built.stories.items()})
            self._texts = BrewTexts(
                pour_lines=built.pour_lines, facts=list(built.facts), teaser=built.teaser,
                big_story_part_told=built.big_story_part_told,
                stories={s: v for s, v in built.stories.items() if s.kind not in AGENT_KINDS})
            # Tied to the entry: cancelled on unload, never awaited at shutdown.
            self._agent_task = self.entry.async_create_background_task(
                self.hass, self._ask_agent(self._brew_id, asked, plan, recipe, settings or {},
                                           self._bag, history, content.lang),
                "xbloom brew story agent")
        else:
            self._texts = built
        # A brew already under way when its texts were ready (adopted from
        # the machine's button, or a slow Coffee Lab) shows what its stage
        # calls for now, not from the next change on.
        stage, pour = self._stage
        if stage in _UNDER_WAY:
            if stage != "pouring":
                await self.async_on_stage("pouring", pour)
            await self.async_on_stage(stage, pour)

    async def _ask_agent(
        self, brew_id: int, asked: BrewTexts, plan: list[dict] | None, recipe: str | None,
        settings: dict, bag: dict | None, history: list[dict], language: str,
    ) -> None:
        """One request for this cup's parts; a failure leaves them empty."""
        if self.agent_entity is None:
            _LOGGER.warning("Brew Stories: no story agent is set; this cup's parts are left empty")
            return
        instructions, structure = build_request(
            asked, plan, recipe, settings, bag, history, await self._rated(), self.memory,
            language)
        try:
            async with asyncio.timeout(AGENT_TIMEOUT_S):
                response = await self.hass.services.async_call(
                    "ai_task", "generate_data",
                    {"task_name": TASK_NAME, "entity_id": self.agent_entity,
                     "instructions": instructions, "structure": structure},
                    blocking=True, return_response=True)
            data = response.get("data") if isinstance(response, dict) else None
            if not isinstance(data, dict):
                raise ValueError(f"no structured data in the reply: {response!r}"[:200])
        except Exception as err:  # noqa: BLE001 — any failure is that brew without stories
            _LOGGER.warning("Brew Stories: %s did not write this cup's parts (%s: %s); "
                            "they are left empty", self.agent_entity, type(err).__name__, err)
            return
        if brew_id != self._brew_id or self._texts is None or self._recorded:
            _LOGGER.debug("Brew Stories: a story agent reply for an earlier brew was dropped")
            return
        stories = parse_reply(asked, data)
        self._texts.stories.update(stories)
        self._agent_texts = [
            (data.get(slot_key(slot)) or "").strip() for slot in stories
            if isinstance(data.get(slot_key(slot)), str) and data.get(slot_key(slot)).strip()]
        # The part running now, among every story slot: shown only if it is
        # one the agent wrote, so a slot that has passed never shows late.
        if (slot := self._running_story_slot(asked.stories)) is not None and slot in stories:
            heading, text = stories[slot]
            self._publish({**self.current, "heading": heading, "story": text, "kind": slot.kind})

    def _running_story_slot(self, slots) -> Slot | None:
        """Of `slots`, the one that began last and is still on, from the stage now."""
        stage, pour = self._stage
        if stage == "draining":
            now = (float("inf"), 0)
        elif stage in ("pouring", "waiting") and pour:
            now = (pour, 0 if stage == "pouring" else 1)
        else:
            return None

        def position(slot: Slot) -> tuple[float, int]:
            if slot.at == "draining":
                return (float("inf"), 0)
            return (slot.pour, 0 if slot.at == "pour" else 1)

        begun = [s for s in slots if position(s) <= now]
        return max(begun, key=position, default=None)

    async def async_brew_started(self, data: dict[str, Any]) -> None:
        await self._begin(data.get("pours") or None, data.get("bean_id"),
                          data.get("recipe_name"), data.get("settings"))

    async def async_machine_brew_started(self) -> None:
        lab = getattr(self.entry.runtime_data, "coffee_lab", None)
        await self._begin(None, lab.active_id("coffee") if lab is not None else None)

    def _story(self, at: str, pour: int) -> tuple[Slot, tuple[str, str]] | None:
        for slot, story in (self._texts.stories.items() if self._texts else ()):
            if slot.at == at and slot.pour == pour:
                return slot, story
        return None

    async def async_on_stage(self, stage: str, pour: int | None) -> None:
        self._stage = (stage, pour)
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
            # What is on screen stays; the next brew writes its own texts.
            self._texts = None
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
            agent_texts=self._agent_texts, advance_bag=self._built is None,
        )

    def _publish(self, shown: dict[str, Any]) -> None:
        if shown != self.current:
            self.current = shown
            async_dispatcher_send(self.hass, signal_story(self.entry.entry_id))


def _brew_facts(brew) -> dict[str, Any]:
    """A past brew as the stories read it; the verdict as its word."""
    from ..coffee_lab.models import VERDICT_OF
    return {
        "rating": brew.rating, "verdict": VERDICT_OF.get(brew.rating),
        "next_change": brew.next_change, "recipe": brew.recipe,
        "settings": dict(brew.settings or {}), "tasting": dict(brew.tasting or {}),
    }
