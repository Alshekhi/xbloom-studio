"""Asking how a brew was of whoever started it, once it can have been tasted.

A brew an agent started gets its ending by callback — "your coffee is ready".
The question about how it was is not part of that: nobody can rate a coffee
they have not tasted. So when Coffee Lab opens the question for such a brew,
this waits until the question is due — when the dashboard's card appears too —
and, if it is still unanswered, sends the caller a message of its own,
`xbloom.rating.due`. The caller asks the person (a second call, a second
message) and keeps the answer with the coffee_lab tool, which closes the card.
Unanswered, the card simply stays.

Who to ask is kept on the question itself, so a restart in between loses
nothing; once sent, the question is marked so it is never sent twice.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .callbacks import Callbacks
from .coffee_lab.lab import CoffeeLab

_LOGGER = logging.getLogger(__name__)


class RatingAsker:
    def __init__(self, hass: HomeAssistant, lab: CoffeeLab, callbacks: Callbacks) -> None:
        self._hass = hass
        self._lab = lab
        self._callbacks = callbacks
        self._cancel = None

    def start(self) -> None:
        """Take over from the lab's questions; pick up one open before a restart."""
        self._lab.on_question = self._on_question
        question = self._lab.rating_question
        if question and question.get("ask") and not question.get("asked"):
            self._schedule(question)

    def stop(self) -> None:
        self._lab.on_question = lambda question: None
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    @callback
    def _on_question(self, question: dict[str, Any]) -> None:
        caller = self._callbacks.caller_of(question.get("run_id"))
        if caller is None:  # started on the dashboard or at the machine: the card asks
            return
        target, context = caller
        self._hass.async_create_task(self._async_keep_caller(question, target, context))

    async def _async_keep_caller(self, question: dict[str, Any], target: str, context: Any) -> None:
        ask = {"target": target, "context": context}
        await self._lab.async_note_question(question["brew_id"], ask=ask)
        self._schedule({**question, "ask": ask})

    def _schedule(self, question: dict[str, Any]) -> None:
        if self._cancel is not None:
            self._cancel()
        due = dt_util.parse_datetime(question["due_at"]) or dt_util.utcnow()
        brew_id = question["brew_id"]

        @callback
        def _due(_now) -> None:
            self._cancel = None
            self._hass.async_create_task(self._async_ask(brew_id))

        # A question already due when Home Assistant came back is asked now.
        self._cancel = async_track_point_in_utc_time(self._hass, _due, max(due, dt_util.utcnow()))

    async def _async_ask(self, brew_id: str) -> None:
        question = self._lab.rating_question
        # Answered on the dashboard meanwhile, replaced by a newer brew, or
        # already asked: nothing to send.
        if not question or question["brew_id"] != brew_id or question.get("asked"):
            return
        ask = question.get("ask") or {}
        if ask.get("target") not in self._callbacks.targets:
            _LOGGER.warning("xbloom: the brew's caller %s is no longer a target", ask.get("target"))
            return
        self._callbacks.send_rating_due(ask["target"], ask.get("context"), question)
        await self._lab.async_note_question(brew_id, asked=True)
