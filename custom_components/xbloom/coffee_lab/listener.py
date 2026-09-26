"""Counting a finished xBloom brew against its bag, and noting a stopped one.

Listens to the integration's own `xbloom_brew_completed`, which is fired for
both a `confirmed` and a `presumed` finish — both made coffee. The bag rode on
the event from the moment the brew started. A brew started at the machine
itself runs no Home Assistant brew and fires no completion, so it is not
counted.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.core import Event, HomeAssistant

from .lab import CoffeeLab

_LOGGER = logging.getLogger(__name__)

# What the completion says the machine was told, kept on the brew record.
SETTINGS = ("grind", "ratio", "water_ml", "temperature_c", "flow_rate", "duration_s")


def async_count_completed_brews(hass: HomeAssistant, lab: CoffeeLab) -> Callable[[], None]:
    """Start counting completions; returns the call that stops it."""

    async def _count(event: Event) -> None:
        data = event.data
        if data.get("outcome") not in ("confirmed", "presumed"):
            return
        result = await lab.async_consume(
            bean_id=data.get("bean_id"),
            grams=data.get("dose_g"),
            run_id=data.get("run_id"),
            cup_type=data.get("cup_type"),
            recipe=data.get("recipe_name"),
            brewed_at=data.get("ended_at"),
            outcome=data.get("outcome"),
            settings={key: data.get(key) for key in SETTINGS},
            unattributed=bool(data.get("unattributed")),
        )
        _LOGGER.info("Coffee Lab: brew %s %s (%s)", data.get("run_id"), result.result, result.reason)

    async def _stopped(event: Event) -> None:
        data = event.data
        if not data.get("ground"):
            # Stopped before the grinder ran: no coffee was used.
            return
        result = await lab.async_record_stopped(
            bean_id=data.get("bean_id"), grams=data.get("dose_g"),
            run_id=data.get("run_id"), cup_type=data.get("cup_type"),
            recipe=data.get("recipe_name"), brewed_at=data.get("ended_at"),
            unattributed=bool(data.get("unattributed")),
        )
        _LOGGER.info("Coffee Lab: stopped brew %s %s", data.get("run_id"), result.result)

    unsubs = [
        hass.bus.async_listen("xbloom_brew_completed", _count),
        hass.bus.async_listen("xbloom_brew_stopped", _stopped),
    ]

    def stop() -> None:
        for unsub in unsubs:
            unsub()

    return stop
