"""Asking how a brew was of whoever started it, once it can have been tasted.

A brew an agent started gets its ending by callback — "your coffee is ready".
The question about how it was is not part of that: nobody can rate a coffee
they have not tasted. So when Coffee Lab opens the question for such a brew,
this waits until the question is due — when the dashboard's card appears too —
and, if it is still unanswered, sends the caller a message of its own,
`xbloom.rating.due`. The caller asks the person (a second call, a second
message) and keeps the answer with the coffee_lab tool, which closes the card.
Unanswered, the card simply stays.

Several cups in one sitting are one message: it waits until 15 minutes
after the caller's last cup and covers each question still open — one per
recipe, bag and version — so two or three cups never ring two or three times.

Who to ask is kept on each question, so a restart in between loses nothing;
once sent, a question is marked so it is never sent twice.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .callbacks import Callbacks
from .coffee_lab.lab import CoffeeLab

_LOGGER = logging.getLogger(__name__)


def _key(ask: dict[str, Any]) -> str:
    """Who a question is to be asked of: the target, and the context it was started with."""
    return json.dumps([ask.get("target"), ask.get("context")], sort_keys=True, default=str)


class RatingAsker:
    def __init__(self, hass: HomeAssistant, lab: CoffeeLab, callbacks: Callbacks) -> None:
        self._hass = hass
        self._lab = lab
        self._callbacks = callbacks
        self._cancels: dict[str, Any] = {}

    def start(self) -> None:
        """Take over from the lab's questions; pick up any open before a restart."""
        self._lab.on_question = self._on_question
        self._schedule()

    def stop(self) -> None:
        self._lab.on_question = lambda question: None
        for cancel in self._cancels.values():
            cancel()
        self._cancels.clear()

    @callback
    def _on_question(self, question: dict[str, Any]) -> None:
        caller = self._callbacks.caller_of(question.get("run_id"))
        if caller is None:
            # Started on the dashboard or at the machine: the card asks. It
            # may still be another cup of a question an agent will ask about,
            # now due later.
            self._schedule()
            return
        target, context = caller
        self._hass.async_create_task(self._async_keep_caller(question, target, context))

    async def _async_keep_caller(self, question: dict[str, Any], target: str, context: Any) -> None:
        # A later cup of the same coffee, started by this caller, is asked
        # about again only if the earlier message has not gone yet.
        await self._lab.async_note_question(
            question["brew_id"], ask={"target": target, "context": context},
        )
        self._schedule()

    def _waiting(self) -> dict[str, list[dict[str, Any]]]:
        """The questions still to be sent, by whom they are to be asked of."""
        waiting: dict[str, list[dict[str, Any]]] = {}
        for question in self._lab.rating_questions:
            if question.get("ask") and not question.get("asked"):
                waiting.setdefault(_key(question["ask"]), []).append(question)
        return waiting

    def _schedule(self) -> None:
        for cancel in self._cancels.values():
            cancel()
        self._cancels.clear()
        now = dt_util.utcnow()
        for key, questions in self._waiting().items():
            due = max(dt_util.parse_datetime(q["due_at"]) or now for q in questions)

            @callback
            def _due(_now, key=key) -> None:
                self._cancels.pop(key, None)
                self._hass.async_create_task(self._async_ask(key))

            # Questions already due when Home Assistant came back are asked now.
            self._cancels[key] = async_track_point_in_utc_time(self._hass, _due, max(due, now))

    async def _async_ask(self, key: str) -> None:
        # Answered on the dashboard meanwhile, lapsed, or already asked: those
        # are not in the list, and with none left nothing is sent.
        questions = self._waiting().get(key) or []
        if not questions:
            return
        ask = questions[-1]["ask"]
        if ask.get("target") not in self._callbacks.targets:
            _LOGGER.warning("xbloom: the brew's caller %s is no longer a target", ask.get("target"))
            return
        self._callbacks.send_rating_due(ask["target"], ask.get("context"), questions)
        for question in questions:
            await self._lab.async_note_question(question["brew_id"], asked=True)
