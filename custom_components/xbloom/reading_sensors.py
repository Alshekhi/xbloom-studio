"""xBloom Studio "reading" sensors — the machine's live values as entities.

These surface every value the integration observes as a normal HA sensor, so a
user with no Alexa speakers (or who never installs the announcement blueprints)
can still see the whole operation on a dashboard. They subscribe **directly** to
what the integration itself emits — the ``xbloom.start_brew`` service and the
live-session listener — never to anything a blueprint produces, so they populate
with zero blueprints installed. Display and audio are independent choices.

Only values that stay TRUE when read are kept as sensors. On-change-only knob
readings (grinder speed, pour pattern, brew temperature, brew ratio) were
removed: they are not in the machine's heartbeat, so a sensor could never
reflect the current setting — it would show a stale value forever, which is
worse than absent for a screen-reader user. Voice announcements (the
live-session blueprint) still report those knob turns correctly, as events —
the honest medium for on-change-only data.

What remains:
  * Recipe-brew progress (``current_recipe``, ``current_pour``) — live during
    an ``xbloom.start_brew`` brew; ``current_pour`` starts at 0 and resets to 0
    when the brew ends (never a standing stale value).
  * ``grind_size`` and ``last_recipe_card`` — grind size is synced from the
    heartbeat, so it is correct on any connection, not only on a knob-turn.
  * ``current_module`` — LIVE only: which module you are on while a Connect
    session streams, and unknown when no session is active (never stale). This
    is the honest gate a dashboard uses to reveal the module you are on.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .ble_entities import (
    CMD_BLOOM,
    _device_info,
    signal_brew_lifecycle,
    signal_event,
)
from xbloom import spec

_LOGGER = logging.getLogger(__name__)

# Bus events fired by the integration's listeners (live_session / start_brew).
EV_GRINDER_KNOB = "xbloom_grinder_knob_changed"
EV_BREWER_SETTING = "xbloom_brewer_setting_changed"
EV_MODULE_ENTERED = "xbloom_module_entered"
EV_RECIPE_CARD = "xbloom_recipe_card_scanned"
EV_BREW_STARTED = "xbloom_brew_started"


class _XBloomReadingSensor(RestoreSensor, SensorEntity):
    """Base for a sensor whose value comes from integration-fired bus events.

    Subclasses set ``_events`` (bus event types to listen to) and implement
    ``_extract`` to pull the new value from an event (returning ``None`` to
    ignore it). The value is restored across restarts and retained between
    updates.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _events: tuple[str, ...] = ()
    # Optional heartbeat field (from ble.decode_notification, delivered via
    # signal_event) this sensor also syncs from — so it reflects the machine's
    # real value on any connection, not just a live-session knob-turn.
    _signal_field: str | None = None

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value

        @callback
        def _on_event(event) -> None:
            value = self._extract(event.event_type, event.data)
            if value is not None and value != self._attr_native_value:
                self._attr_native_value = value
                self.async_write_ha_state()

        for ev in self._events:
            self.async_on_remove(self.hass.bus.async_listen(ev, _on_event))

        if self._signal_field is not None:
            @callback
            def _on_signal(decoded: dict) -> None:
                value = decoded.get(self._signal_field)
                if value is not None and value != self._attr_native_value:
                    self._attr_native_value = value
                    self.async_write_ha_state()

            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, signal_event(self._entry.entry_id), _on_signal,
                )
            )

    def _extract(self, event_type: str, data: dict) -> Any:
        raise NotImplementedError


class XBloomGrindSizeSensor(_XBloomReadingSensor):
    _attr_translation_key = "grind_size"
    _attr_unique_id = "xbloom_grind_size"
    _attr_icon = "mdi:dots-grid"
    _events = (EV_GRINDER_KNOB, EV_BREWER_SETTING)
    # Also synced from the heartbeat (grind_size_current) so it's correct on any
    # connection, not only when the grind knob is turned during a live session.
    _signal_field = "grind_size_current"

    def _extract(self, event_type: str, data: dict) -> Any:
        if event_type == EV_GRINDER_KNOB and data.get("parameter") == "size":
            return int(data["value"])
        if event_type == EV_BREWER_SETTING and data.get("setting") == "size":
            return int(data["value"])
        return None


# NOTE: The on-change-only knob sensors (grind_speed, pour_pattern,
# brew_temperature, brew_ratio) were removed — they are not in the machine's
# heartbeat, so as sensors they could only ever show a stale value. Their knob
# turns are still announced (voice) via the live-session blueprint, which is the
# correct medium for on-change data. See the module docstring.


class XBloomCurrentModuleSensor(SensorEntity):
    """Which machine module you are on — LIVE only, never stale.

    Reflects the module (home / grinder / scale / brewer / auto) while a Connect
    session is streaming, and goes ``unknown`` the moment the session ends —
    idle timeout, connection failure, or manual disconnect — because once we
    stop streaming we no longer know where the machine is. Deliberately NOT a
    RestoreSensor: a module remembered across a restart (or a disconnect) would
    be a lie. This is the honest gate a dashboard uses to reveal the section for
    the module you are actually on.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "current_module"
    _attr_unique_id = "xbloom_current_module"
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(spec.MODULES)

    # Any of these means the live session has ended → module is unknown again.
    _SESSION_END_EVENTS = (
        "xbloom_connect_failed",
        "xbloom_connect_auto_stopped",
        "xbloom_connect_stopped",
    )

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = None

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_module(event) -> None:
            module = event.data.get("module")
            new = module if module in self._attr_options else None
            if new is not None and new != self._attr_native_value:
                self._attr_native_value = new
                self.async_write_ha_state()

        @callback
        def _on_session_end(_event) -> None:
            if self._attr_native_value is not None:
                self._attr_native_value = None
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(EV_MODULE_ENTERED, _on_module)
        )
        for ev in self._SESSION_END_EVENTS:
            self.async_on_remove(self.hass.bus.async_listen(ev, _on_session_end))


class XBloomLastRecipeCardSensor(_XBloomReadingSensor):
    _attr_translation_key = "last_recipe_card"
    _attr_unique_id = "xbloom_last_recipe_card"
    _attr_icon = "mdi:card-text-outline"
    _events = (EV_RECIPE_CARD,)

    def _extract(self, event_type: str, data: dict) -> Any:
        pod = data.get("pod_id")
        return pod or None


class XBloomCurrentRecipeSensor(_XBloomReadingSensor):
    """Name of the recipe currently being brewed (with its pour count)."""

    _attr_translation_key = "current_recipe"
    _attr_unique_id = "xbloom_current_recipe"
    _attr_icon = "mdi:coffee-outline"
    _events = (EV_BREW_STARTED,)

    def __init__(self, entry) -> None:
        super().__init__(entry)
        self._attr_extra_state_attributes = {"total_pours": None}

    def _extract(self, event_type: str, data: dict) -> Any:
        self._attr_extra_state_attributes = {"total_pours": data.get("total_pours")}
        return data.get("recipe_name")


class XBloomCurrentPourSensor(SensorEntity):
    """Current pour number within the in-progress brew (1-based; 0 when idle).

    Live brew progress, not a standing value: starts at 0, advances on each
    RD_BLOOM (``CMD_BLOOM``) notification during the brew, and resets to 0 when
    the brew ends (``signal_brew_lifecycle`` "ended"). Deliberately NOT a
    RestoreSensor — a pour number left over after the brew finished (or restored
    across a restart) would misreport a brew that is not running.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "current_pour"
    _attr_unique_id = "xbloom_current_pour"
    _attr_icon = "mdi:cup-water"

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = 0
        self._total_pours: int | None = None

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {"total_pours": self._total_pours}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_started(event) -> None:
            self._total_pours = event.data.get("total_pours")
            self._attr_native_value = 0
            self.async_write_ha_state()

        @callback
        def _on_signal(decoded: dict) -> None:
            if decoded.get("cmd") == CMD_BLOOM and "pour_index" in decoded:
                self._attr_native_value = int(decoded["pour_index"]) + 1
                self.async_write_ha_state()

        @callback
        def _on_lifecycle(phase: str) -> None:
            # Brew finished (completed or timed out) — clear the standing value.
            if phase == "ended":
                self._attr_native_value = 0
                self._total_pours = None
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(EV_BREW_STARTED, _on_started)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry.entry_id), _on_signal
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_brew_lifecycle(self._entry.entry_id),
                _on_lifecycle,
            )
        )


READING_SENSORS = [
    XBloomCurrentRecipeSensor,
    XBloomCurrentPourSensor,
    XBloomGrindSizeSensor,
    XBloomCurrentModuleSensor,
    XBloomLastRecipeCardSensor,
]
