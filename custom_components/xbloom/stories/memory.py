"""What Brew Stories has told, kept across brews and restarts.

Each bag's story moves one chapter per brew and never tells a part twice.
The big story moves one chapter each time a bag is brewed for the first time,
and one part each brew that told it. Nothing moves until a brew is recorded,
so a brew that never ran advances nothing.
"""
from __future__ import annotations

from typing import Any, Protocol

STORAGE_VERSION = 1
STORAGE_KEY = "xbloom.stories.{entry_id}"
# The texts a story agent told a bag that the next request lists, newest kept.
AGENT_TOLD_KEEP = 20


class Storage(Protocol):
    async def async_load(self) -> dict[str, Any] | None: ...
    async def async_save(self, data: dict[str, Any]) -> None: ...


def _empty() -> dict[str, Any]:
    return {
        "bags": {},
        # chapter -1: no bag opened yet, so the first one opens chapter 0.
        "big_story": {"chapter": -1, "part": 0, "tasted": [], "bags_seen": []},
        "facts_seen": [],
        "teaser": None,
        "brews": 0,
        # The Story language picked; None until one is, so Home Assistant's
        # own is followed.
        "language": None,
        # Per bag, what a story agent told it, oldest first.
        "agent_told": {},
    }


class StoryMemory:
    def __init__(self, store: Storage) -> None:
        self._store = store
        self._data = _empty()

    async def async_load(self) -> None:
        self._data = {**_empty(), **(await self._store.async_load() or {})}

    def bag(self, bean_id: str | None) -> dict[str, Any]:
        found = self._data["bags"].get(bean_id or "")
        return {"chapter": found["chapter"], "told": list(found["told"])} if found else {
            "chapter": 0, "told": []}

    def big_story(self) -> dict[str, Any]:
        return dict(self._data["big_story"])

    def big_story_position(self, bean_id: str | None) -> tuple[int, int]:
        """The chapter and part a brew of `bean_id` would tell now."""
        story = self._data["big_story"]
        if bean_id and bean_id not in story["bags_seen"]:
            return story["chapter"] + 1, 0
        return max(story["chapter"], 0), story["part"]

    @property
    def facts_seen(self) -> set[str]:
        return set(self._data["facts_seen"])

    @property
    def facts_order(self) -> list[str]:
        """The facts told, least recently told first."""
        return list(self._data["facts_seen"])

    @property
    def teaser(self) -> dict[str, Any] | None:
        return self._data["teaser"]

    @property
    def brews(self) -> int:
        return self._data["brews"]

    def agent_told(self, bean_id: str | None) -> list[str]:
        return list(self._data["agent_told"].get(bean_id or "", []))

    @property
    def language(self) -> str | None:
        return self._data["language"]

    async def async_set_language(self, language: str) -> None:
        self._data["language"] = language
        await self._store.async_save(self._data)

    async def async_record_brew(
        self, bean_id: str | None, *, told: list[str], facts: list[str],
        big_story_part_told: bool, country: str | None, teaser: dict[str, Any] | None,
        agent_texts: list[str] | None = None, advance_bag: bool = True,
    ) -> None:
        story = self._data["big_story"]
        chapter, part = self.big_story_position(bean_id)
        if bean_id and bean_id not in story["bags_seen"]:
            story["bags_seen"].append(bean_id)
        story["chapter"], story["part"] = chapter, part + (1 if big_story_part_told else 0)
        if country and country.casefold() not in {c.casefold() for c in story["tasted"]}:
            story["tasted"].append(country)
        if bean_id:
            bag = self._data["bags"].setdefault(bean_id, {"chapter": 0, "told": []})
            # A brew whose bag part a story agent wrote told no chapter.
            if advance_bag:
                bag["chapter"] += 1
            bag["told"].extend(t for t in told if t not in bag["told"])
            if agent_texts:
                kept = self._data["agent_told"].setdefault(bean_id, [])
                kept.extend(agent_texts)
                del kept[:-AGENT_TOLD_KEEP]
        # Least recently told first: a fact told again moves to the end.
        seen = self._data["facts_seen"]
        for fact in facts:
            if fact in seen:
                seen.remove(fact)
            seen.append(fact)
        self._data["teaser"] = teaser
        self._data["brews"] += 1
        await self._store.async_save(self._data)

    async def async_forget_bag(self, bean_id: str) -> None:
        told = self._data["agent_told"].pop(bean_id, None)
        if self._data["bags"].pop(bean_id, None) is not None or told is not None:
            await self._store.async_save(self._data)
