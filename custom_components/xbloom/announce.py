"""One announcement at a time, for every xBloom blueprint.

Each blueprint is its own automation, and a speaker given a second message
cuts the first off. So the blueprints hand their messages to this queue
(`xbloom.announce`) instead of calling Alexa, a TTS engine or a notify service
themselves, and it speaks them one after another. Alexa reports nothing when
it finishes speaking, so the next message waits for the time the last one
takes to say, estimated from its length.

Brew, fault and live-session messages go first; a brew story part waits
behind them, only the newest one waits at all, and one that waited past its
moment is dropped rather than spoken late. A notification is silent and holds
nothing up.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Speaking pace, characters a second, and the floor and gap around a message.
# Estimates: a speaker gives no signal when it has finished.
CHARS_PER_S = 14.0
MIN_SPEAK_S = 2.0
GAP_S = 1.5
# A story part that waited longer than this has missed the part of the brew
# it belongs to.
STORY_STALE_S = 30.0
STORY = "story"


def speak_seconds(message: str) -> float:
    """How long a message takes to say, with the pause after it."""
    return max(MIN_SPEAK_S, len(message) / CHARS_PER_S) + GAP_S


class AnnouncementQueue:
    def __init__(
        self, call: Callable[..., Awaitable[Any]], *,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] | None = None,
        create_task: Callable[[Awaitable[Any]], asyncio.Future] = asyncio.ensure_future,
    ) -> None:
        self._call, self._sleep, self._create_task = call, sleep, create_task
        self._clock = clock or (lambda: asyncio.get_running_loop().time())
        self._waiting: deque[dict[str, Any]] = deque()
        self._story: dict[str, Any] | None = None
        self._task: asyncio.Future | None = None
        self._quiet = asyncio.Event()
        self._quiet.set()

    def add(self, item: dict[str, Any]) -> None:
        item = {**item, "queued_at": self._clock()}
        if item.get("kind") == STORY:
            self._story = item
        else:
            self._waiting.append(item)
        self._quiet.clear()
        if self._task is None or self._task.done():
            self._task = self._create_task(self._run())

    async def async_wait_quiet(self, timeout: float) -> None:
        """Until nothing is waiting or being said, or `timeout` seconds."""
        try:
            await asyncio.wait_for(self._quiet.wait(), timeout)
        except TimeoutError:
            _LOGGER.debug("xbloom announcements still speaking after %s s", timeout)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self._waiting.clear()
        self._story = None
        self._quiet.set()

    def _next(self) -> dict[str, Any] | None:
        if self._waiting:
            return self._waiting.popleft()
        item, self._story = self._story, None
        return item

    async def _run(self) -> None:
        try:
            while (item := self._next()) is not None:
                if item.get("kind") == STORY and self._clock() - item["queued_at"] > STORY_STALE_S:
                    _LOGGER.debug("xbloom: a story part waited past its moment and was dropped")
                    continue
                if await self._speak(item) and item.get("method") != "notify":
                    await self._sleep(speak_seconds(item["message"]))
        finally:
            if not self._waiting and self._story is None:
                self._quiet.set()

    async def _speak(self, item: dict[str, Any]) -> bool:
        message, method = item["message"], item.get("method")
        targets = item.get("targets") or []
        try:
            if method == "alexa" and targets:
                await self._call("notify", "alexa_media", {
                    "target": targets, "data": {"type": item.get("alexa_type") or "tts"},
                    "message": message}, blocking=True)
            elif method == "tts" and targets and item.get("tts_engine"):
                await self._call("tts", "speak", {
                    "entity_id": item["tts_engine"], "media_player_entity_id": targets,
                    "message": message}, blocking=True)
            elif method == "notify" and "." in (item.get("notify_service") or ""):
                domain, service = item["notify_service"].split(".", 1)
                await self._call(domain, service, {"message": message}, blocking=True)
            else:
                return False
        except Exception as err:  # noqa: BLE001 — one speaker failing must not stop the rest
            _LOGGER.warning("xbloom: an announcement was not delivered (%s: %s)",
                            type(err).__name__, err)
            return False
        return True
