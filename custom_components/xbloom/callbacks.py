"""Telling whoever started a brew how it went, by signed webhook.

Off unless targets are configured. A caller names a target when it starts a
brew; letting it pass a URL instead would let anything point this integration
at an address of its choosing with a signed request. The target then receives
that brew's endings — and, if asked, its progress — each carrying the caller's
`context` back unchanged, so the receiver knows where the news belongs.

Automations suit "any brew ends → do X"; a callback belongs to one brew and one
caller. Both are built on the same events, so they cannot disagree.

Signed to the Standard Webhooks spec (standardwebhooks.com), so any receiver
can verify it with an off-the-shelf library: HMAC-SHA256 over
"{id}.{timestamp}.{body}" with the secret's decoded bytes, sent as
"v1,<base64>". A message keeps its id across retries, so a receiver can drop a
duplicate. Payloads are facts; the receiver words them.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from xbloom import spec

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9_]+$")
SECRET_PREFIX = "whsec_"

# Seconds before each retry. A receiver restarting is the common case; one gone
# for minutes is not coming back for a brew.
RETRY_DELAYS = (2.0, 10.0, 30.0)
TIMEOUT_S = 10

# The endings, each carrying the brew's run_id. After one, nothing more is sent.
FINAL = {
    "xbloom_brew_completed": "completed",
    "xbloom_brew_failed": "failed",
    "xbloom_brew_stopped": "stopped",
    "xbloom_brew_timeout": "timeout",
}


@dataclass(frozen=True)
class Target:
    name: str
    url: str
    # "whsec_" + base64 of the key bytes.
    secret: str


def target_problem(name: str, url: str, secret: str) -> dict[str, str]:
    """What is wrong with a target, as form errors keyed by field."""
    errors: dict[str, str] = {}
    if not NAME.match(name):
        errors["name"] = "callback_name_invalid"
    if not url.startswith(("http://", "https://")):
        errors["url"] = "callback_url_invalid"
    try:
        key = base64.b64decode(secret.removeprefix(SECRET_PREFIX), validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if not secret.startswith(SECRET_PREFIX) or len(key) < 24:
        errors["secret"] = "callback_secret_invalid"
    return errors


def targets_from(data: dict[str, Any]) -> dict[str, Target]:
    return {name: Target(name, t["url"], t["secret"]) for name, t in data.items()}


def signature(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix(SECRET_PREFIX))
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def headers_for(target: Target, msg_id: str, body: bytes, now: int | None = None) -> dict[str, str]:
    # Taken per attempt: receivers reject a signature older than their replay
    # window, and retries can outlast it.
    ts = int(time.time()) if now is None else now
    return {
        "content-type": "application/json",
        "webhook-id": msg_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": signature(target.secret, msg_id, ts, body),
    }


@dataclass
class Message:
    target: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex}")


async def deliver(
    session: aiohttp.ClientSession, target: Target, message: Message,
    delays: tuple[float, ...] = RETRY_DELAYS,
) -> bool:
    """POST one message, retrying what is worth retrying. True when accepted."""
    body = json.dumps(message.payload, ensure_ascii=False).encode()
    kind = message.payload.get("type", "")
    for attempt in range(len(delays) + 1):
        if attempt:
            await asyncio.sleep(delays[attempt - 1])
        try:
            async with session.post(
                target.url, data=body, headers=headers_for(target, message.id, body),
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
            ) as resp:
                if 200 <= resp.status < 300:
                    _LOGGER.debug("%s → %s accepted (%s)", kind, target.name, resp.status)
                    return True
                if resp.status < 500 and resp.status != 429:
                    # Will not change on retry: a wrong secret or route.
                    _LOGGER.error(
                        "Callback %s to %s refused with %s; check its URL and secret",
                        kind, target.name, resp.status,
                    )
                    return False
                _LOGGER.warning("Callback %s to %s answered %s", kind, target.name, resp.status)
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.warning("Callback %s to %s unreachable: %s", kind, target.name, err)
    _LOGGER.error("Callback %s to %s not delivered after %d attempts", kind, target.name, len(delays) + 1)
    return False


@dataclass
class Pending:
    """One brew's callback: where it goes, and what to send back with it."""

    target: str
    context: Any = None
    progress: bool = False
    recipe: str | None = None
    total_pours: int | None = None
    fault: str | None = None


class Callbacks:
    """The callbacks of one install: armed per brew, sent in order."""

    def __init__(
        self, hass: HomeAssistant, targets: dict[str, Target],
        send: Callable[[Target, Message], Any] | None = None,
    ) -> None:
        self.hass = hass
        self.targets = targets
        self._pending: dict[str, Pending] = {}
        # The brew the machine is on now, which progress and faults belong to.
        self._running: str | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._send = send

    # -- arming ------------------------------------------------------------

    def arm(self, run_id: str, target: str, context: Any, progress: bool) -> None:
        """Before the brew is dispatched, so no early event is missed."""
        self._pending[run_id] = Pending(target=target, context=context, progress=progress)

    # -- what happens ------------------------------------------------------

    def _enqueue(self, run_id: str, pending: Pending, event: str, final: bool, data: dict) -> None:
        # The context goes once, beside data; the recipe once, as `recipe`.
        facts = {
            k: v for k, v in data.items()
            if k not in ("context", "recipe_name") and v is not None
        }
        self._queue.put_nowait(Message(pending.target, {
            # type / timestamp / data is the envelope Standard Webhooks recommends.
            "type": f"xbloom.brew.{event}",
            "timestamp": dt_util.utcnow().isoformat(),
            "data": {"event": event, "final": final, "run_id": run_id,
                     "recipe": pending.recipe, **facts},
            "context": pending.context,
        }))

    @callback
    def on_event(self, event: Event) -> None:
        run_id = event.data.get("run_id")
        pending = self._pending.get(run_id)
        if pending is None:
            return
        if event.event_type == "xbloom_brew_started":
            pending.recipe = event.data.get("recipe_name")
            pending.total_pours = event.data.get("total_pours")
            self._running = run_id
            return
        pending.recipe = pending.recipe or event.data.get("recipe_name")
        self._enqueue(run_id, pending, FINAL[event.event_type], True, dict(event.data))
        del self._pending[run_id]
        if self._running == run_id:
            self._running = None

    def _current(self) -> tuple[str, Pending] | None:
        if self._running is None or self._running not in self._pending:
            return None
        return self._running, self._pending[self._running]

    @callback
    def on_brew_status(self, before: str | None, after: str | None) -> None:
        if (current := self._current()) and after == "grinding" and before != after:
            run_id, pending = current
            if pending.progress:
                self._enqueue(run_id, pending, "grinding", False, {})

    @callback
    def on_brew_event(self, attributes: dict[str, Any]) -> None:
        current = self._current()
        if current is None or attributes.get("event_type") != "pour_started":
            return
        run_id, pending = current
        index = attributes.get("pour_index")
        if pending.progress and isinstance(index, int):
            self._enqueue(run_id, pending, "pour", False,
                          {"pour": index + 1, "pours": pending.total_pours})

    @callback
    def on_machine_status(self, before: str | None, after: str | None) -> None:
        current = self._current()
        if current is None or after in (None, "unknown", "unavailable") or before == after:
            return
        run_id, pending = current
        if after == spec.MACHINE_OK:
            if pending.fault is not None:
                self._enqueue(run_id, pending, "fault_cleared", False, {"status": pending.fault})
                pending.fault = None
            return
        pending.fault = after
        # The machine waits on a person over a fault, so it is sent whether or
        # not progress was asked for.
        self._enqueue(run_id, pending, "fault", False, {"status": after})

    # -- sending -----------------------------------------------------------

    async def async_run(self) -> None:
        """One worker, so a fault never overtakes the ending that follows it."""
        session = async_get_clientsession(self.hass)
        while True:
            message = await self._queue.get()
            target = self.targets.get(message.target)
            if target is None:
                _LOGGER.error("No callback target called %s", message.target)
                continue
            if self._send is not None:
                await self._send(target, message)
            else:
                await deliver(session, target, message)

    def async_listen(self) -> Callable[[], None]:
        """Listen to the brew's events and entities; returns the call that stops it."""
        hass = self.hass
        unsubs = [hass.bus.async_listen(name, self.on_event)
                  for name in ("xbloom_brew_started", *FINAL)]
        registry = er.async_get(hass)
        watched = {
            registry.async_get_entity_id(platform, DOMAIN, unique_id): handler
            for platform, unique_id, handler in (
                ("sensor", "xbloom_brew_status", "status"),
                ("sensor", "xbloom_machine_status", "machine"),
                ("event", "xbloom_brew_event", "event"),
            )
        }
        watched.pop(None, None)

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if new is None:
                return
            kind = watched[event.data["entity_id"]]
            before = old.state if old is not None else None
            if kind == "status":
                self.on_brew_status(before, new.state)
            elif kind == "machine":
                self.on_machine_status(before, new.state)
            elif before not in (None, "unknown", "unavailable"):
                # An event entity's state is when it fired; one restored from
                # unavailable is not a firing.
                self.on_brew_event(dict(new.attributes))

        if watched:
            unsubs.append(async_track_state_change_event(hass, list(watched), _changed))

        def stop() -> None:
            for unsub in unsubs:
                unsub()

        return stop
