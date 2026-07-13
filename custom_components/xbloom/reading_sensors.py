"""xBloom Studio "reading" sensors — the machine's live values as entities.

These surface every value the integration observes as a normal HA sensor, so a
user with no Alexa speakers (or who never installs the announcement blueprints)
can still see the whole operation on a dashboard. They subscribe **directly** to
what the integration itself emits — the ``xbloom.start_brew`` service and the
Live Control listener — never to anything a blueprint produces, so they populate
with zero blueprints installed. Display and audio are independent choices.

Two groups:
  * Recipe-brew progress (``current_recipe``, ``current_pour``) — updated during
    an ``xbloom.start_brew`` brew.
  * Live manual readings (grind size/speed, pour pattern, temperature, ratio,
    current module, last recipe card) — updated while the Live Control switch is
    on.

BLE is connect-on-demand, so these update while the integration holds the
connection (a brew, or Live Control on) and retain their last value otherwise.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .ble_entities import (
    CMD_BLOOM,
    _device_info,
    signal_event,
)

_LOGGER = logging.getLogger(__name__)

# Bus events fired by the integration's listeners (voice_mode / start_brew).
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

    def _extract(self, event_type: str, data: dict) -> Any:
        raise NotImplementedError


class XBloomGrindSizeSensor(_XBloomReadingSensor):
    _attr_translation_key = "grind_size"
    _attr_unique_id = "xbloom_grind_size"
    _attr_icon = "mdi:dots-grid"
    _events = (EV_GRINDER_KNOB, EV_BREWER_SETTING)

    def _extract(self, event_type: str, data: dict) -> Any:
        if event_type == EV_GRINDER_KNOB and data.get("parameter") == "size":
            return int(data["value"])
        if event_type == EV_BREWER_SETTING and data.get("setting") == "size":
            return int(data["value"])
        return None


class XBloomGrindSpeedSensor(_XBloomReadingSensor):
    _attr_translation_key = "grind_speed"
    _attr_unique_id = "xbloom_grind_speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = "RPM"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _events = (EV_GRINDER_KNOB, EV_BREWER_SETTING)

    def _extract(self, event_type: str, data: dict) -> Any:
        if event_type == EV_GRINDER_KNOB and data.get("parameter") == "speed":
            return int(data["value"])
        if event_type == EV_BREWER_SETTING and data.get("setting") == "speed":
            return int(data["value"])
        return None


class XBloomPourPatternSensor(_XBloomReadingSensor):
    _attr_translation_key = "pour_pattern"
    _attr_unique_id = "xbloom_pour_pattern"
    _attr_icon = "mdi:vector-circle"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["centered", "circular", "spiral"]
    _events = (EV_BREWER_SETTING,)

    def _extract(self, event_type: str, data: dict) -> Any:
        if data.get("setting") != "pattern":
            return None
        name = data.get("value_name")
        return name if name in self._attr_options else None


class XBloomBrewTemperatureSensor(_XBloomReadingSensor):
    _attr_translation_key = "brew_temperature"
    _attr_unique_id = "xbloom_brew_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _events = (EV_BREWER_SETTING,)

    def _extract(self, event_type: str, data: dict) -> Any:
        if data.get("setting") != "temperature":
            return None
        return int(data["value"])


class XBloomBrewRatioSensor(_XBloomReadingSensor):
    _attr_translation_key = "brew_ratio"
    _attr_unique_id = "xbloom_brew_ratio"
    _attr_icon = "mdi:scale-balance"
    _events = (EV_BREWER_SETTING,)

    def _extract(self, event_type: str, data: dict) -> Any:
        if data.get("setting") != "ratio":
            return None
        return float(data["value"])


class XBloomCurrentModuleSensor(_XBloomReadingSensor):
    _attr_translation_key = "current_module"
    _attr_unique_id = "xbloom_current_module"
    _attr_icon = "mdi:gesture-tap-button"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["home", "grinder", "scale", "brewer", "auto"]
    _events = (EV_MODULE_ENTERED,)

    def _extract(self, event_type: str, data: dict) -> Any:
        module = data.get("module")
        return module if module in self._attr_options else None


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


class XBloomCurrentPourSensor(RestoreSensor, SensorEntity):
    """Current pour number within the in-progress brew (1-based; 0 when idle).

    Reset to 0 on ``xbloom_brew_started`` and advanced by each RD_BLOOM
    (``CMD_BLOOM``) notification dispatched during the brew.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "current_pour"
    _attr_unique_id = "xbloom_current_pour"
    _attr_icon = "mdi:cup-water"

    def __init__(self, entry) -> None:
        self._entry = entry
        self._total_pours: int | None = None

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {"total_pours": self._total_pours}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value

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

        self.async_on_remove(
            self.hass.bus.async_listen(EV_BREW_STARTED, _on_started)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry.entry_id), _on_signal
            )
        )


READING_SENSORS = [
    XBloomCurrentRecipeSensor,
    XBloomCurrentPourSensor,
    XBloomGrindSizeSensor,
    XBloomGrindSpeedSensor,
    XBloomPourPatternSensor,
    XBloomBrewTemperatureSensor,
    XBloomBrewRatioSensor,
    XBloomCurrentModuleSensor,
    XBloomLastRecipeCardSensor,
]
