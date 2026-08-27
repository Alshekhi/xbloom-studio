"""BLE-driven status entities — connect-on-demand variant.

Three entities, each a counterpart to its MQTT-mode sibling and using the
same `unique_id` so existing automations and blueprints (which key off
entity_id) keep working when an entry is switched from MQTT to Bluetooth:

  * `XBloomBrewStatusBleSensor`   → entity_id `sensor.xbloom_studio_brew_status`
  * `XBloomScaleWeightBleSensor`  → entity_id `sensor.xbloom_studio_scale_weight`
  * `XBloomBrewEventBleEntity`    → entity_id `event.xbloom_studio_brew_event`

Connect-on-demand model: there is **no long-lived BLE connection**. The
`xbloom.start_brew` service opens BLE only for the duration of a brew,
streams decoded notifications via `async_dispatcher_send`, and disconnects
when `RD_ENJOY` arrives (or on timeout). These entities subscribe to those
signals and update live during the brew, then return to "idle" between
brews. The iOS app has unrestricted BLE access whenever a brew isn't
in flight.

The dropped MQTT-mode entities (`binary_sensor.machine_connected`,
`binary_sensor.bridge_online`, `switch.bridge_toggle`) have no equivalent
in this model — there's no persistent connection to indicate the state of,
and no bridge process to toggle.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfMass
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from xbloom import spec

_LOGGER = logging.getLogger(__name__)


# Signal names. Per-entry so multiple machines (rare) don't cross-talk.
def signal_event(entry_id: str) -> str:
    """Decoded BLE notification: payload dict {cmd, ...optional fields}."""
    return f"xbloom_ble_event_{entry_id}"


def signal_brew_lifecycle(entry_id: str) -> str:
    """Brew started/ended: payload str ('started'|'ended')."""
    return f"xbloom_ble_brewlife_{entry_id}"


async def send_live_frame(entry, frame: bytes) -> bool:
    """Send any pre-built FFE1 frame over the HELD Connect session.

    Returns False (no-op) when no live session holds the link — callers use this
    for actions that only make sense while Connected (e.g. the module-enter
    navigation buttons). Fire-and-forget; the machine echoes but we don't gate.
    """
    listener = getattr(getattr(entry, "runtime_data", None), "live_session_listener", None)
    if listener is None or not getattr(listener, "is_running", False):
        return False
    return await listener.send_live(frame)


async def send_brewer_temp_live(entry, temp_c_wire: float) -> bool:
    """Set the brewer temperature over the HELD Connect session — the app's
    live temp-slider command (cmd 4510, temp-ONLY, plain int ×10). ``temp_c_wire``
    is the WIRE °C (RT=20/BP=98/literal — convert a display value with
    spec.brew_temp_display_to_wire first). No-op when not Connected.
    """
    from xbloom.ble import packet_brewer_temp
    return await send_live_frame(entry, packet_brewer_temp(float(temp_c_wire)))


async def send_brewer_pattern_live(entry, pattern_byte: int) -> bool:
    """Set the brewer pour pattern over the HELD Connect session — the app's
    live pattern command (cmd 8016, pattern-ONLY). No-op when not Connected."""
    from xbloom.ble import packet_brewer_pattern
    return await send_live_frame(entry, packet_brewer_pattern(int(pattern_byte)))


# Notification command codes we care about for entity decoding
CMD_MACHINE_ACTIVITY = 8023
CMD_WEIGHT_2         = 20501
CMD_WEIGHT_ALT       = 10507
CMD_GRINDER_START    = 40502
CMD_BREWER_START     = 40506
CMD_GRINDER_STOP     = 40507
CMD_BLOOM            = 40510
CMD_BREW_END         = 40511
CMD_ENJOY            = 40512
CMD_BYPASS           = 40520  # RD_BYPASS — bypass/dilution pour (see discovery ble-protocol.md)

# The machine's fault vocabulary (cmd -> status, event type) lives in
# spec.FAULTS, the portable single source of truth.

# Machine activity values (cmd 8023 payload as LE uint32)
# These reflect the machine's overall state, NOT individual steps.
# The machine has TWO home/idle screens — one per mode — and the firmware
# treats them as equivalent "at rest" states (fw_decompiled.c line 2849:
# `+0x198 == 1 || +0x198 == 0x41`):
#   1  = Pro-mode home        65 (0x41) = Auto/Easy-mode home (recipes A/B/C)
# Neither can fire mid-brew (brewing is 34, homing 8, done 36), so seeing either
# while brew_status is in-progress means the brew ended.
# 34 = brewing active (fires at recipe start, even while grinder runs)
# 36 = brew done / cooldown
# (16 = grinding complete — reported but not acted on; brew_status uses the
#  40502/40507 grinder cmds for the grinding->brewing transition instead.)
ACTIVITY_HOME_STATES = (1, 65)   # Pro home, Auto/Easy home
ACTIVITY_BREWING    = 34
ACTIVITY_BREW_DONE  = 36


def _device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "xbloom_studio")},
        name="xBloom Studio",
        manufacturer="xBloom",
        model="Studio",
    )


# --------------------------------------------------------------------- #
# sensor.xbloom_studio_brew_status                                      #
# --------------------------------------------------------------------- #
class XBloomBrewStatusBleSensor(RestoreSensor, SensorEntity):
    """Live brew state — updates during the brew, returns to idle after.

    Same unique_id as the MQTT-mode sensor so blueprints/automations keyed
    on `sensor.xbloom_studio_brew_status` keep working.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "brew_status"
    _attr_unique_id = "xbloom_brew_status"  # matches MQTT-mode unique_id
    _attr_icon = "mdi:coffee"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(spec.BREW_STATES)
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = "idle"

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            value = last.native_value
            # A restored "grinding"/"brewing" is stale: on reload/restart there
            # is no brew in progress that HA is tracking, so resurrecting a
            # transient in-progress state wedges the UI (the dashboard hides
            # Start while brewing). Normalize any in-progress or out-of-options
            # value (e.g. MQTT-mode "offline") to "idle"; only a terminal "done"
            # carries meaning across a restart.
            if value not in self._attr_options or value in ("grinding", "brewing"):
                value = "idle"
            self._attr_native_value = value

        @callback
        def _on_event(decoded: dict) -> None:
            cmd = decoded.get("cmd")
            new_state: str | None = None
            if cmd == CMD_MACHINE_ACTIVITY:
                act = decoded.get("activity")
                # Activity codes reflect the machine's *overall* state, not
                # individual steps.  ACTIVITY_BREWING (34) fires the moment
                # the recipe starts — even while the grinder is still running
                # — so trusting it would immediately overwrite "grinding"
                # (activity 16 means "grinding complete", not "grinding").
                # We only use activity codes when the sensor is idle (to
                # catch the initial transition) or for brew-done.
                if act == ACTIVITY_BREW_DONE:
                    new_state = "done"
                elif act in ACTIVITY_HOME_STATES and self._attr_native_value in (
                    "grinding", "brewing"
                ):
                    # Reconciliation: the machine returned to a home/idle screen
                    # (Pro home 1 or Auto/Easy home 65), so any in-progress
                    # brew_status is stale — the brew was stopped on the
                    # machine/app, finished without HA seeing RD_ENJOY while the
                    # brew task lingers, or was left stale and this is the first
                    # heartbeat of a fresh connect (idle machines emit their home
                    # activity on connect). A home state can't fire mid-brew, so
                    # this clears the phantom "brewing"/"grinding" that greys out
                    # the Start button. "done" is left intact (cleared next brew).
                    new_state = "idle"
                elif act == ACTIVITY_BREWING and self._attr_native_value == "idle":
                    # Fallback: if we missed CMD_GRINDER_START, at least
                    # show something is happening.
                    new_state = "grinding"
            elif cmd == CMD_GRINDER_START:
                new_state = "grinding"
            elif cmd == CMD_GRINDER_STOP:
                # Grinder finished — transition to brewing (pours next)
                if self._attr_native_value == "grinding":
                    new_state = "brewing"
            elif cmd == CMD_BREWER_START:
                # 40506 fires ~3 s after grind start — it's the water heater
                # spinning up in parallel with the grind, NOT the pours
                # (verified 2026-06-11: brewer_started at +3 s, grinder ran
                # 41 s, first pour at +52 s). Ignore it mid-grind so the
                # "pouring" announcement doesn't fire while grinding; the
                # grinding → brewing transition comes from CMD_GRINDER_STOP.
                if self._attr_native_value != "grinding":
                    new_state = "brewing"
            elif cmd == CMD_BLOOM:
                new_state = "brewing"
            elif cmd == CMD_ENJOY:
                new_state = "done"

            if new_state is not None and new_state != self._attr_native_value:
                self._attr_native_value = new_state
                self.async_write_ha_state()

        @callback
        def _on_lifecycle(phase: str) -> None:
            if phase == "started" and self._attr_native_value != "idle":
                # Reset to idle at the start of a new brew so subscribers see
                # the transition — covers a prior "done" as well as a stale
                # in-progress value left behind by an aborted brew.
                self._attr_native_value = "idle"
                self.async_write_ha_state()
            elif phase == "ended" and self._attr_native_value in ("grinding", "brewing"):
                # The brew task ended (completed, cancelled or errored) without
                # a terminal event reaching us — clear the stuck in-progress
                # state so the dashboard's Start button comes back.
                self._attr_native_value = "idle"
                self.async_write_ha_state()

        eid = self._entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_event(eid), _on_event)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_brew_lifecycle(eid), _on_lifecycle)
        )


# --------------------------------------------------------------------- #
# sensor.xbloom_studio_machine_status                                   #
# --------------------------------------------------------------------- #
class XBloomMachineStatusBleSensor(RestoreSensor, SensorEntity):
    """Latest machine fault/condition — mirrors what the machine shows on its
    screen, so a VoiceOver user can query or be announced the machine state.

    Driven by the discrete fault notifications (RD_Error*) in spec.FAULTS. Stays
    at the reported fault until a new brew starts, which clears it back to "ok".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "machine_status"
    _attr_unique_id = "xbloom_machine_status"
    _attr_icon = "mdi:coffee-maker"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(spec.MACHINE_STATUSES)
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = "ok"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            value = last.native_value
            self._attr_native_value = (
                value if value in self._attr_options else "ok"
            )

        @callback
        def _on_event(decoded: dict) -> None:
            # MachineInfo (40521) heartbeat — continuous water status + extras.
            if "water_enough" in decoded:
                attrs = dict(self._attr_extra_state_attributes or {})
                if "system_status" in decoded:
                    attrs["system_status"] = decoded["system_status"]
                if "voltage" in decoded:
                    attrs["voltage"] = decoded["voltage"]
                self._attr_extra_state_attributes = attrs
                # Self-clearing water status: only toggles ok <-> no_water so it
                # never clobbers a distinct active fault (e.g. no_beans).
                if decoded["water_enough"] == 0 and self._attr_native_value == "ok":
                    self._attr_native_value = "no_water"
                elif decoded["water_enough"] == 1 and self._attr_native_value == "no_water":
                    self._attr_native_value = "ok"
                self.async_write_ha_state()
                return

            # Discrete fault notifications (RD_Error*).
            fault = spec.FAULTS.get(decoded.get("cmd"))
            if fault is None:
                return
            status = fault[0]
            if status != self._attr_native_value:
                self._attr_native_value = status
                self.async_write_ha_state()

        @callback
        def _on_lifecycle(phase: str) -> None:
            # A new brew clears any prior fault.
            if phase == "started" and self._attr_native_value != "ok":
                self._attr_native_value = "ok"
                self.async_write_ha_state()

        eid = self._entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_event(eid), _on_event)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_brew_lifecycle(eid), _on_lifecycle)
        )


# --------------------------------------------------------------------- #
# sensor.xbloom_studio_scale_weight                                     #
# --------------------------------------------------------------------- #
class XBloomScaleWeightBleSensor(RestoreSensor, SensorEntity):
    """Scale weight in grams — updates while connected, retains last value."""

    _attr_has_entity_name = True
    _attr_translation_key = "scale_weight"
    _attr_unique_id = "xbloom_scale_weight"  # matches MQTT-mode unique_id
    _attr_icon = "mdi:scale"
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_suggested_display_precision = 1
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value: float | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._attr_native_value = float(last.native_value) if last.native_value is not None else None
            except (TypeError, ValueError):
                self._attr_native_value = None

        @callback
        def _on_event(decoded: dict) -> None:
            if decoded.get("cmd") in (CMD_WEIGHT_2, CMD_WEIGHT_ALT) and "weight_g" in decoded:
                self._attr_native_value = decoded["weight_g"]
                self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry.entry_id), _on_event
            )
        )


# --------------------------------------------------------------------- #
# sensor.xbloom_studio_last_updated                                     #
# --------------------------------------------------------------------- #
class XBloomLastUpdatedSensor(RestoreSensor, SensorEntity):
    """Timestamp of the last status heartbeat — the freshness signal.

    Stamps ``now`` whenever any connection delivers an RD_MachineInfo heartbeat
    (a brew, a Connect session, a command's piggyback, or an explicit
    ``xbloom.refresh_status``). A dashboard/screen-reader shows it as
    "updated N minutes ago" so a reading's age is always visible — the honest
    alternative to a value that silently goes stale.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_updated"
    _attr_unique_id = "xbloom_last_updated"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = None

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value

        @callback
        def _on_event(decoded: dict) -> None:
            # "water_enough" appears only in the RD_MachineInfo heartbeat decode
            # — a reliable marker that we just synced machine status.
            if "water_enough" in decoded:
                self._attr_native_value = dt_util.utcnow()
                self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry.entry_id), _on_event,
            )
        )


# --------------------------------------------------------------------- #
# event.xbloom_studio_brew_event                                        #
# --------------------------------------------------------------------- #
class XBloomBrewEventBleEntity(EventEntity):
    """Brew lifecycle event entity.

    Fires the same `brew_started` and `brew_done` event types as the
    MQTT-mode entity (so the `brew_complete_with_recipe` blueprint keeps
    working), plus the granular per-stage events for richer automations.
    """

    _attr_has_entity_name = True
    _attr_name = "Brew Event"
    _attr_unique_id = "xbloom_brew_event"  # matches MQTT-mode unique_id
    _attr_icon = "mdi:coffee-maker"
    _attr_event_types = [
        # Same names as MQTT mode — for blueprint compatibility:
        "brew_started",
        "brew_done",
        # Granular extras only available in BLE mode:
        "grinder_started",
        "brewer_started",
        "grinder_stopped",
        "pour_started",
        "bypass_started",
        "brew_ended",
        # Fault notifications (machine → phone), derived from spec.FAULTS:
        *[event_type for (_status, event_type) in spec.FAULTS.values()],
    ]
    _attr_should_poll = False

    # cmd → granular event name
    _CMD_TO_GRANULAR = {
        CMD_GRINDER_START: "grinder_started",
        CMD_BREWER_START:  "brewer_started",
        CMD_GRINDER_STOP:  "grinder_stopped",
        CMD_BLOOM:         "pour_started",
        CMD_BYPASS:        "bypass_started",
        CMD_BREW_END:      "brew_ended",
        **{cmd: event_type for cmd, (_status, event_type) in spec.FAULTS.items()},
    }

    def __init__(self, entry) -> None:
        self._entry = entry
        self._brew_started_fired = False
        self._last_recipe_name: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._entry.entry_id)

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_event(decoded: dict) -> None:
            cmd = decoded.get("cmd")

            # Fire granular event if applicable
            granular = self._CMD_TO_GRANULAR.get(cmd)
            if granular:
                attrs: dict[str, Any] = {}
                if "pour_index" in decoded:
                    attrs["pour_index"] = decoded["pour_index"]
                self._trigger_event(granular, attrs)
                self.async_write_ha_state()

            # Aggregate `brew_started` — first pour after the brew started
            if cmd == CMD_BLOOM and not self._brew_started_fired:
                self._brew_started_fired = True
                self._trigger_event(
                    "brew_started",
                    {"recipe_name": self._last_recipe_name or ""},
                )
                self.async_write_ha_state()

            # Aggregate `brew_done` — RD_ENJOY
            if cmd == CMD_ENJOY:
                self._trigger_event(
                    "brew_done",
                    {"recipe_name": self._last_recipe_name or ""},
                )
                self._last_recipe_name = None
                self._brew_started_fired = False
                self.async_write_ha_state()

        @callback
        def _on_lifecycle(phase: str) -> None:
            # Reset the "started fired" latch at the start of each brew
            if phase == "started":
                self._brew_started_fired = False

        @callback
        def _on_brew_started_bus(event) -> None:
            # The xbloom.start_brew service fires this on the HA bus with the
            # selected recipe name, before any BLE traffic. Cache it so we
            # can attach it to brew_started / brew_done events.
            self._last_recipe_name = event.data.get("recipe_name", "")

        eid = self._entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_event(eid), _on_event)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_brew_lifecycle(eid), _on_lifecycle)
        )
        self.async_on_remove(
            self.hass.bus.async_listen("xbloom_brew_started", _on_brew_started_bus)
        )
