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

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# Signal names. Per-entry so multiple machines (rare) don't cross-talk.
def signal_event(entry_id: str) -> str:
    """Decoded BLE notification: payload dict {cmd, ...optional fields}."""
    return f"xbloom_ble_event_{entry_id}"


def signal_brew_lifecycle(entry_id: str) -> str:
    """Brew started/ended: payload str ('started'|'ended')."""
    return f"xbloom_ble_brewlife_{entry_id}"


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

# Machine fault notification codes (machine → phone). Each maps to a message the
# machine shows on its screen — see discovery/ipa/notes/machine-errors-catalog.md.
CMD_ERR_NO_WATER     = 40522  # RD_ErrorLackOfWater    — out of water
CMD_ERR_NO_BEANS     = 40517  # RD_ErrorIdling         — grinder ran with no beans
CMD_ERR_DOSE_WATER   = 8204   # RD_AbnormalDoseOrWater — dose/water ratio invalid
CMD_ERR_GEAR         = 8203   # RD_AbnormalGearPosition — grinder gear/position fault

# fault cmd → (machine_status enum value, brew_event type). Single source of
# truth shared by the machine-status sensor and the brew-event entity.
_FAULTS: dict[int, tuple[str, str]] = {
    CMD_ERR_NO_WATER:   ("no_water",            "error_no_water"),
    CMD_ERR_NO_BEANS:   ("no_beans",            "error_no_beans"),
    CMD_ERR_DOSE_WATER: ("dose_water_error",    "error_dose_water"),
    CMD_ERR_GEAR:       ("gear_position_error", "error_gear_position"),
}

# Machine activity values (cmd 8023 payload as LE uint32)
# These reflect the machine's overall state, NOT individual steps.
# 34 = brewing active (fires at recipe start, even while grinder runs)
# 36 = brew done / cooldown
# (16 = grinding complete — reported but not acted on; brew_status uses the
#  40502/40507 grinder cmds for the grinding->brewing transition instead.)
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
    _attr_options = ["idle", "grinding", "brewing", "done"]
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
            # BLE mode never emits "offline" (that's an MQTT-mode concept).
            # When migrating an existing entry from MQTT to BLE, the restored
            # value can still be "offline" — normalize to "idle" so we don't
            # publish a state outside our options list.
            self._attr_native_value = value if value in self._attr_options else "idle"

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
            if phase == "started" and self._attr_native_value == "done":
                # Reset to idle at the start of a new brew so subscribers
                # see the transition.
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

    Driven by the discrete fault notifications (RD_Error*) in `_FAULTS`. Stays
    at the reported fault until a new brew starts, which clears it back to "ok".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "machine_status"
    _attr_unique_id = "xbloom_machine_status"
    _attr_icon = "mdi:coffee-maker"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "ok",
        "no_water",
        "no_beans",
        "dose_water_error",
        "gear_position_error",
    ]
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
            fault = _FAULTS.get(decoded.get("cmd"))
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
        # Fault notifications (machine → phone), derived from _FAULTS:
        *[event_type for (_status, event_type) in _FAULTS.values()],
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
        **{cmd: event_type for cmd, (_status, event_type) in _FAULTS.items()},
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
