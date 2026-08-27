"""Number entities for the xBloom Studio integration.

Brew/grind parameters as sliders (grind size, grind speed, brew volume,
brew temperature, brew flow rate), stored with RestoreEntity so values
survive HA restarts.

These sliders are two-way where the machine has a matching physical knob:

  * REFLECT — while a Connect session is streaming, the slider mirrors the
    machine: a knob twist (RD_GRINDER_SIZE/SPEED, RD_BREWER_TEMPERATURE)
    updates the slider, and grind size also syncs from the heartbeat. So the
    slider shows the machine's live value, not just a stale setpoint.
  * DRIVE — (added separately) moving the slider sends the value to the
    machine over the held session.

Volume and flow rate have no machine knob (they are app-only standalone-brew
params), so they stay pure setpoints. The REFLECT path updates
``_current_value`` directly (never via ``async_set_native_value``) so it can
never be mistaken for a user edit / re-driven to the machine.
"""
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_call_later, async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity

from .ble_entities import send_brewer_temp_live, signal_event
from .const import DOMAIN
from xbloom import spec
from xbloom.ble import packet_grinder_set

_LOGGER = logging.getLogger(__name__)

# Coalesce rapid slider changes into a single machine write. Each grinder write
# (8006) homes the gear, so we don't want one per drag tick.
_DRIVE_DEBOUNCE_S = 0.4

# Live-session bus events (emitted by live_session.py) a slider reflects.
EV_GRINDER_KNOB = "xbloom_grinder_knob_changed"
EV_BREWER_SETTING = "xbloom_brewer_setting_changed"


def _range(field_name: str) -> tuple[float, float, float]:
    """(min, max, step) for a NumberEntity slider, from the shared spec field.

    Only the *range* is shared with the spec; each entity keeps its own
    `_default_value` because the standalone-brew defaults differ from the
    recipe-wizard defaults.
    """
    r = spec.field(field_name)
    return float(r.min), float(r.max), float(r.step)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([
        XBloomGrindSizeNumber(entry),
        XBloomGrindSpeedNumber(entry),
        XBloomBrewVolumeNumber(entry),
        XBloomBrewTemperatureNumber(entry),
        XBloomBrewFlowRateNumber(entry),
        # Brew customizer — one-off overrides that reset to the picked recipe.
        XBloomBrewGrindNumber(entry),
        XBloomBrewRatioNumber(entry),
        XBloomBrewDoseNumber(entry),
    ])


# Entity the customizer sliders follow (the recipe picker). Its
# extra_state_attributes carries the full recipe dict (dose_g, water_ratio,
# grinder_size, cup_type, pours, …) — see select.XBloomRecipeSelect.
_RECIPE_SELECT = "select.xbloom_studio_recipe"


class _XBloomNumberBase(NumberEntity, RestoreEntity):
    """Shared base for xBloom number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _default_value: float = 0.0

    # REFLECT hooks — subclasses set these to mirror a machine knob.
    _reflect_events: tuple[str, ...] = ()
    _reflect_signal_field: str | None = None   # heartbeat field, if any

    def __init__(self, entry) -> None:
        self._entry = entry
        self._current_value: float = self._default_value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def native_value(self) -> float | None:
        return self._current_value

    async def async_set_native_value(self, value: float) -> None:
        # User edit (or a service call). DRIVE is layered on top of this later;
        # REFLECT deliberately does NOT go through here.
        self._current_value = value
        self.async_write_ha_state()

    # ---- REFLECT ------------------------------------------------------- #
    def _reflect_from_event(self, event_type: str, data: dict) -> float | None:
        """Return the machine value carried by a knob event, or None to ignore."""
        return None

    def _apply_reflected(self, value: float) -> None:
        if value != self._current_value:
            self._current_value = value
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                self._current_value = float(last.state)
            except ValueError:
                pass

        @callback
        def _on_event(event) -> None:
            v = self._reflect_from_event(event.event_type, event.data)
            if v is not None:
                self._apply_reflected(v)

        for ev in self._reflect_events:
            self.async_on_remove(self.hass.bus.async_listen(ev, _on_event))

        if self._reflect_signal_field is not None:
            @callback
            def _on_signal(decoded: dict) -> None:
                raw = decoded.get(self._reflect_signal_field)
                if raw is None:
                    return
                try:
                    self._apply_reflected(float(raw))
                except (TypeError, ValueError):
                    return

            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, signal_event(self._entry.entry_id), _on_signal,
                )
            )


class _XBloomGrinderNumber(_XBloomNumberBase):
    """A grinder slider (size or speed) that also DRIVES the machine.

    Moving it while a Connect session is live sends 8006 (APP_GRINDER_IN) with
    [size, speed] — exactly what the app fires on every knob change to
    pre-position the gear. The two grinder sliders always send *both* current
    values together (8006 carries the pair), debounced so a drag homes the gear
    once, not per tick. When no session is live it's a plain setpoint.
    """

    _grinder_field = ""        # "size" | "speed" — which one this entity is
    _sibling_entity_id = ""    # the other grinder slider's entity_id
    _sibling_default = 0.0

    def __init__(self, entry) -> None:
        super().__init__(entry)
        self._drive_unsub = None

    async def async_set_native_value(self, value: float) -> None:
        await super().async_set_native_value(value)   # store + write state
        self._schedule_drive()

    def _live_listener(self):
        listener = getattr(
            self._entry.runtime_data, "live_session_listener", None,
        )
        return listener if (listener is not None and listener.is_running) else None

    def _schedule_drive(self) -> None:
        if self._live_listener() is None:
            return   # not connected → plain setpoint, no machine write
        if self._drive_unsub is not None:
            self._drive_unsub()
        self._drive_unsub = async_call_later(
            self.hass, _DRIVE_DEBOUNCE_S, self._do_drive,
        )

    async def _do_drive(self, _now) -> None:
        self._drive_unsub = None
        listener = self._live_listener()
        if listener is None:
            return
        # Own value is authoritative (just set); read the sibling from its state.
        own = self._current_value
        sibling = self._read_state(self._sibling_entity_id, self._sibling_default)
        size, speed = (
            (own, sibling) if self._grinder_field == "size" else (sibling, own)
        )
        ok = await listener.send_live(packet_grinder_set(int(size), int(speed)))
        if ok:
            # The grind value is a digital screen number (the knobs are infinite
            # encoders, no motor move) and a *commanded* set makes the machine
            # echo 8006 but emit NO knob event — so a screen-reader user would
            # get zero feedback. Synthesize the same event a physical twist
            # fires, so the announcement blueprint speaks "Grind size N" and the
            # user knows the machine received it.
            self.hass.bus.async_fire(
                EV_GRINDER_KNOB,
                {"parameter": self._grinder_field, "value": int(own)},
            )

    def _read_state(self, entity_id: str, default: float) -> float:
        st = self.hass.states.get(entity_id)
        if st is None or st.state in ("unknown", "unavailable"):
            return default
        try:
            return float(st.state)
        except ValueError:
            return default

    async def async_will_remove_from_hass(self) -> None:
        if self._drive_unsub is not None:
            self._drive_unsub()
            self._drive_unsub = None
        await super().async_will_remove_from_hass()


class XBloomGrindSizeNumber(_XBloomGrinderNumber):
    _attr_name = "Grind Size"
    _attr_unique_id = "xbloom_grind_size"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("grind_size")
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:grain"
    _default_value = 65.0
    # Grinder size knob (RD_GRINDER_SIZE) + heartbeat (correct on any connection).
    _reflect_events = (EV_GRINDER_KNOB,)
    _reflect_signal_field = "grind_size_current"
    _grinder_field = "size"
    _sibling_entity_id = "number.xbloom_studio_grind_speed"
    _sibling_default = 60.0

    def _reflect_from_event(self, event_type: str, data: dict) -> float | None:
        if event_type == EV_GRINDER_KNOB and data.get("parameter") == "size":
            return float(data["value"])
        return None


class XBloomGrindSpeedNumber(_XBloomGrinderNumber):
    _attr_name = "Grind Speed"
    _attr_unique_id = "xbloom_grind_speed"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("grinder_speed_rpm")
    _attr_native_unit_of_measurement = "RPM"
    _attr_icon = "mdi:rotate-right"
    _default_value = 60.0
    # Grinder speed knob (RD_GRINDER_SPEED). Not in the heartbeat (on-change).
    _reflect_events = (EV_GRINDER_KNOB,)
    _grinder_field = "speed"
    _sibling_entity_id = "number.xbloom_studio_grind_size"
    _sibling_default = 65.0

    def _reflect_from_event(self, event_type: str, data: dict) -> float | None:
        if event_type == EV_GRINDER_KNOB and data.get("parameter") == "speed":
            return float(data["value"])
        return None


class XBloomBrewVolumeNumber(_XBloomNumberBase):
    _attr_name = "Brew Volume"
    _attr_unique_id = "xbloom_brew_volume"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("pour_volume_ml")
    _attr_native_unit_of_measurement = "ml"
    _attr_icon = "mdi:cup-water"
    _default_value = 120.0
    # No machine knob — pure standalone-brew setpoint.


class XBloomBrewTemperatureNumber(_XBloomNumberBase):
    """Brew temperature — two-way, like the grinder sliders.

    REFLECT: mirrors the brewer temperature knob (RD_BREWER_TEMPERATURE).
    DRIVE: while Connected, moving it sends 4510 (APP_BREWER_SET_TEMPERATURE,
    temp-only, int ×10) — the app's live temp-slider command, independent of
    pattern. The slider is the DISPLAY domain (39-96); we convert to WIRE °C
    before sending. Then speaks the change (parity with a knob turn; a commanded
    set gets no machine knob-event otherwise).
    """

    _attr_name = "Brew Temperature"
    _attr_unique_id = "xbloom_brew_temperature"
    # DISPLAY domain 39..96 — the unified model (spec.brew_temp_*): this is what
    # the machine's brewer knob (cmd 8108) reports and what the app's brewer
    # screen shows, so the slider mirrors it 1:1 (39 = RT, 96 = BP, 40..95 °C).
    # The wire translation (39→20 / 96→98) happens on DRIVE, in the library.
    _attr_native_min_value = spec.BREW_TEMP_DISPLAY_MIN
    _attr_native_max_value = spec.BREW_TEMP_DISPLAY_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"
    _default_value = 93.0
    # Brewer temperature knob (RD_BREWER_TEMPERATURE). Not in the heartbeat.
    _reflect_events = (EV_BREWER_SETTING,)

    def __init__(self, entry) -> None:
        super().__init__(entry)
        self._drive_unsub = None

    def _reflect_from_event(self, event_type: str, data: dict) -> float | None:
        if event_type == EV_BREWER_SETTING and data.get("setting") == "temperature":
            return float(data["value"])
        return None

    async def async_set_native_value(self, value: float) -> None:
        await super().async_set_native_value(value)   # store + write state
        self._schedule_drive()

    def _live_listener(self):
        listener = getattr(
            self._entry.runtime_data, "live_session_listener", None,
        )
        return listener if (listener is not None and listener.is_running) else None

    def _schedule_drive(self) -> None:
        if self._live_listener() is None:
            return
        if self._drive_unsub is not None:
            self._drive_unsub()
        self._drive_unsub = async_call_later(
            self.hass, _DRIVE_DEBOUNCE_S, self._do_drive,
        )

    async def _do_drive(self, _now) -> None:
        self._drive_unsub = None
        if self._live_listener() is None:
            return
        # Temperature-only live set (cmd 4510), independent of pattern — the app's
        # brewer-screen temp-slider command. The slider is the DISPLAY domain
        # (39-96); convert to the WIRE °C the machine expects (39→20 RT, 96→98 BP,
        # else literal) before sending. Fires only when the user moves the HA
        # slider while Connected.
        wire_temp = spec.brew_temp_display_to_wire(self._current_value)
        ok = await send_brewer_temp_live(self._entry, wire_temp)
        if ok:
            # Speak it (parity with a knob turn; a commanded set emits no
            # machine knob-event, so a screen-reader user gets no feedback).
            self.hass.bus.async_fire(
                EV_BREWER_SETTING,
                {"setting": "temperature", "value": int(self._current_value)},
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._drive_unsub is not None:
            self._drive_unsub()
            self._drive_unsub = None
        await super().async_will_remove_from_hass()


class XBloomBrewFlowRateNumber(_XBloomNumberBase):
    _attr_name = "Brew Flow Rate"
    _attr_unique_id = "xbloom_brew_flow_rate"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("pour_flow_rate")
    _attr_native_unit_of_measurement = "ml/s"
    _attr_icon = "mdi:water-pump"
    _default_value = 3.0
    # No machine knob — pure standalone-brew setpoint.


# --------------------------------------------------------------------------- #
# Brew customizer — one-off override sliders for the SELECTED recipe.
#
# Each resets to the picked recipe's value whenever the recipe picker changes,
# and is a pure input (no machine drive). The brew-customizer Start/Save actions
# read these three + the recipe to scale the pours (xbloom.brew_scale). Dose is
# clamped to the recipe's cup-type dose window and hidden (unavailable) for the
# fixed-dose xPod cup.
# --------------------------------------------------------------------------- #
class _XBloomRecipeOverrideNumber(_XBloomNumberBase):
    """Slider that follows the recipe picker; resets to the recipe's value on
    every recipe change. Not restored across restarts (the recipe seeds it)."""

    _recipe_attr: str = ""     # attribute on _RECIPE_SELECT carrying the value

    def _recipe_value(self, name: str):
        st = self.hass.states.get(_RECIPE_SELECT)
        return st.attributes.get(name) if st is not None else None

    def _seed_from_recipe(self) -> None:
        raw = self._recipe_value(self._recipe_attr)
        if raw is None:
            return
        try:
            self._current_value = float(raw)
        except (TypeError, ValueError):
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        # Skip the BLE-reflect wiring in the base (no _reflect_events set); we
        # follow the recipe picker instead.
        await NumberEntity.async_added_to_hass(self)
        self._seed_from_recipe()

        @callback
        def _on_recipe_change(_event) -> None:
            self._seed_from_recipe()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [_RECIPE_SELECT], _on_recipe_change,
            )
        )


class XBloomBrewGrindNumber(_XBloomRecipeOverrideNumber):
    _attr_name = "Brew Grind Size"
    _attr_unique_id = "xbloom_brew_grind"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("grind_size")
    _attr_icon = "mdi:grain"
    _default_value = 50.0
    _recipe_attr = "grinder_size"


class XBloomBrewRatioNumber(_XBloomRecipeOverrideNumber):
    _attr_name = "Brew Ratio"
    _attr_unique_id = "xbloom_brew_ratio"
    _attr_native_min_value = spec.RATIO_DENOM.min
    _attr_native_max_value = spec.RATIO_DENOM.max
    _attr_native_step = spec.RATIO_DENOM.step
    _attr_icon = "mdi:scale-balance"
    _default_value = 16.0
    _recipe_attr = "water_ratio"


class XBloomBrewDoseNumber(_XBloomRecipeOverrideNumber):
    """Dose (g) — clamped to the recipe's cup dose window; hidden for xPod."""

    _attr_name = "Brew Dose"
    _attr_unique_id = "xbloom_brew_dose"
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "g"
    _attr_icon = "mdi:coffee"
    _default_value = 18.0
    _recipe_attr = "dose_g"

    _XPOD_CUP = 1  # fixed 15 g — no point showing a slider

    def _cup_range(self):
        ct = self._recipe_value("cup_type")
        try:
            return spec.CUP_DOSE.get(int(ct)) if ct is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def native_min_value(self) -> float:
        r = self._cup_range()
        return float(r.min) if r else 5.0

    @property
    def native_max_value(self) -> float:
        r = self._cup_range()
        return float(r.max) if r else 25.0

    @property
    def available(self) -> bool:
        ct = self._recipe_value("cup_type")
        if ct is None:
            return True
        try:
            return int(ct) != self._XPOD_CUP
        except (TypeError, ValueError):
            return True
