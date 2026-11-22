"""Brew Stage — what a brew is doing between Brew Status's phases.

Brew Status says `brewing` from the first pour to the end, and Current Pour
keeps the last pour's number through the wait after it, so a brew reads as
"pour 2" while nothing is pouring. Brew Stage splits `brewing` into:

  * `pouring` — from a pour's start (RD_BLOOM, 40510);
  * `waiting` — once the water reading (RD_WATER_VOLUME, 40523) reaches that
    pour's running total in the recipe, with the time the next pour starts;
  * `draining` — from the machine's brew end (40511) to the coffee being ready.

`idle`, `grinding` and `done` are Brew Status's own, followed rather than
re-derived, so the two never disagree about when a brew begins or ends.

The end of a pour is told from the recipe, so only a brew whose recipe Home
Assistant knows has waits: one it started, or one it prepared and the machine's
button started. A brew from the machine's own recipe slots shows `pouring` until
it drains.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .ble_entities import CMD_BLOOM, CMD_BREW_END, _device_info, signal_event
from .const import DOMAIN
from xbloom.ble import NOTIFY_WATER_VOLUME

EV_BREW_STARTED = "xbloom_brew_started"

STAGES = ["idle", "grinding", "pouring", "waiting", "draining", "done"]
# Brew Status values Brew Stage shows as they are.
_FOLLOWED = {"idle", "grinding", "done"}

# The agitation step a pour may end with runs inside the wait after it. On the
# measured brew the one pour with it waited 42 s against a 35 s pause; the
# pours without it waited exactly their pause.
AGITATE_AFTER_S = 7
_AGITATE_ON = 1

# The water reading is whole millilitres; a pour's total in the recipe need not
# be (42.5 ml was read as 43, but could as well stop at 42).
_WATER_SLACK_ML = 1.0


def pour_plan(recipe: dict) -> list[dict[str, float]]:
    """Each pour's running water total and the wait after it, from a recipe."""
    plan: list[dict[str, float]] = []
    total = 0.0
    for pour in recipe.get("pours") or []:
        total += float(pour.get("volume_ml") or 0)
        wait = int(pour.get("pause_s") or 0)
        if pour.get("agitate_after") == _AGITATE_ON:
            wait += AGITATE_AFTER_S
        plan.append({"water_ml": total, "wait_s": wait})
    return plan


def _entity_id(hass, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def _follow(hass, domain: str, unique_id: str, handler):
    """Call `handler` on each state change of one of this integration's entities.

    The entity is found when its changes arrive, not now: a platform set up
    after this one (the binary sensors) has registered nothing yet on a new
    install, and a lookup made now would follow nothing until a restart.
    """
    found: list[str] = []

    @callback
    def _is_it(event_data) -> bool:
        if not found and (entity_id := _entity_id(hass, domain, unique_id)) is not None:
            found.append(entity_id)
        return bool(found) and event_data.get("entity_id") == found[0]

    return hass.bus.async_listen(EVENT_STATE_CHANGED, handler, event_filter=_is_it)


class XBloomBrewStageSensor(SensorEntity):
    """Pouring, waiting or draining, within a brew. Live only, never restored."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "brew_stage"
    _attr_unique_id = "xbloom_brew_stage"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STAGES

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = "idle"
        self._brewing = False
        self._plan: list[dict[str, float]] | None = None
        self._pour: int | None = None
        self._next_pour_at = None
        # The last pour the machine started. Brew Status turns brewing on the
        # first pour's own frame, so that frame reaches here before brewing.
        self._heard_pour: int | None = None

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "pour": self._pour,
            "pours": len(self._plan) if self._plan else None,
            "next_pour_at": self._next_pour_at.isoformat() if self._next_pour_at else None,
        }

    @callback
    def _set(self, stage: str, pour: int | None, next_pour_at=None) -> None:
        if (stage, pour, next_pour_at) == (
                self._attr_native_value, self._pour, self._next_pour_at):
            return
        self._attr_native_value = stage
        self._pour = pour
        self._next_pour_at = next_pour_at
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_started(event) -> None:
            self._plan = event.data.get("pours") or None

        @callback
        def _on_status(event) -> None:
            new = event.data.get("new_state")
            status = new.state if new is not None else None
            self._brewing = status == "brewing"
            if self._brewing:
                if self._attr_native_value in _FOLLOWED:
                    self._set("pouring", self._heard_pour)
                return
            if status in _FOLLOWED:
                # A pour from before this brew (a standalone pour on the
                # brewer screen) is not this brew's.
                self._heard_pour = None
            if status in ("idle", "done"):
                self._plan = None
            if status in _FOLLOWED:
                self._set(status, None)

        @callback
        def _on_paused(event) -> None:
            new = event.data.get("new_state")
            if new is not None and new.state == "on" and self._next_pour_at is not None:
                self._set(self._attr_native_value, self._pour)

        @callback
        def _on_frame(decoded: dict) -> None:
            cmd = decoded.get("cmd")
            if cmd == CMD_BLOOM and "pour_index" in decoded:
                self._heard_pour = int(decoded["pour_index"]) + 1
            if not self._brewing:
                return
            if cmd == CMD_BLOOM and "pour_index" in decoded:
                self._set("pouring", self._heard_pour)
            elif cmd == CMD_BREW_END:
                self._set("draining", self._pour)
            elif (cmd == NOTIFY_WATER_VOLUME and self._attr_native_value == "pouring"
                    and self._plan and self._pour and self._pour <= len(self._plan)
                    and "water_ml" in decoded):
                step = self._plan[self._pour - 1]
                if float(decoded["water_ml"]) >= step["water_ml"] - _WATER_SLACK_ML:
                    next_at = None
                    if self._pour < len(self._plan):
                        next_at = dt_util.utcnow() + timedelta(seconds=step["wait_s"])
                    self._set("waiting", self._pour, next_at)

        self.async_on_remove(self.hass.bus.async_listen(EV_BREW_STARTED, _on_started))
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_event(self._entry.entry_id), _on_frame))
        self.async_on_remove(_follow(self.hass, "sensor", "xbloom_brew_status", _on_status))
        self.async_on_remove(
            _follow(self.hass, "binary_sensor", "xbloom_brew_paused", _on_paused))


class XBloomNextPourSensor(SensorEntity):
    """When the next pour starts, while a brew waits between pours.

    A timestamp, so a dashboard shows "in 15 seconds" and counts it down
    itself, with no state written each second. Empty at any other time.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "next_pour"
    _attr_unique_id = "xbloom_next_pour"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = None

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_stage(event) -> None:
            new = event.data.get("new_state")
            raw = new.attributes.get("next_pour_at") if new is not None else None
            value = dt_util.parse_datetime(raw) if raw else None
            if value != self._attr_native_value:
                self._attr_native_value = value
                self.async_write_ha_state()

        self.async_on_remove(_follow(self.hass, "sensor", "xbloom_brew_stage", _on_stage))
