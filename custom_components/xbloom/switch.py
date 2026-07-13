"""Voice Mode switch for the xBloom Studio integration.

Single switch that, when ON, holds a long-lived BLE connection and
announces every interesting machine event:
    - Stable scale weight (debounced)
    - Grinder knob changes (size + speed)
    - Brewer knob changes (pattern + temperature, when emitted)

Replaces the previous three separate mode switches (Scale / Grinder /
Brewer) which conflicted with each other (only one BLE connection per
device). Now one toggle covers all live announcements.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .vendor.xbloom.mode_listener import XBloomModeListener
from .voice_mode import VoiceModeListener

_LOGGER = logging.getLogger(__name__)


def _device_info() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "xbloom_studio")},
        name="xBloom Studio",
        manufacturer="xBloom",
        model="Studio",
    )


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    runtime = entry.runtime_data
    resolver = runtime.ble_device_resolver

    voice_listener = VoiceModeListener(hass, resolver)
    runtime.voice_listener = voice_listener
    # Backward-compat — keep the old slot names empty so async_unload_entry's
    # cleanup loop doesn't crash if it iterates them.
    runtime.scale_listener = None
    runtime.grinder_listener = None
    runtime.brewer_listener = None

    async_add_entities([
        XBloomVoiceModeSwitch(voice_listener),
        XBloomUseGrinderSwitch(),
    ])


class XBloomUseGrinderSwitch(SwitchEntity, RestoreEntity):
    """Whether a recipe brew should run the grinder (ON) or skip it (OFF).

    OFF means the beans are already ground (pre-ground / external grinder), so
    the machine goes straight to pouring. This is a stored preference, not a BLE
    command; the ``xbloom.start_brew`` service reads it (as ``use_preground =
    not on``) unless the caller passes ``use_preground`` explicitly.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "use_grinder"
    _attr_unique_id = "xbloom_use_grinder"
    _attr_icon = "mdi:coffee-maker"

    def __init__(self) -> None:
        self._attr_is_on = True  # default: use the grinder

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def async_turn_on(self, **_kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class XBloomVoiceModeSwitch(SwitchEntity):
    """When ON: HA holds BLE and speaks every interesting event in Arabic."""

    _attr_has_entity_name = True
    _attr_name = "Live Control"
    _attr_unique_id = "xbloom_live_control_switch"
    _attr_icon = "mdi:remote"

    def __init__(self, listener: XBloomModeListener) -> None:
        self._listener = listener
        self._attr_is_on = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    async def async_added_to_hass(self) -> None:
        """Flip OFF on connect failure or idle timeout."""
        await super().async_added_to_hass()

        @callback
        def _on_failed(_event) -> None:
            if self._attr_is_on:
                _LOGGER.info("[voice] failed — flipping switch OFF")
                self._attr_is_on = False
                self.async_write_ha_state()

        @callback
        def _on_auto_stopped(_event) -> None:
            if self._attr_is_on:
                _LOGGER.info("[voice] idle auto-stopped — flipping switch OFF")
                self._attr_is_on = False
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen("xbloom_live_control_failed", _on_failed)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                "xbloom_live_control_auto_stopped", _on_auto_stopped,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        await self._listener.stop()

    async def async_turn_on(self, **_kwargs) -> None:
        await self._listener.start()
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs) -> None:
        await self._listener.stop()
        self._attr_is_on = False
        self.async_write_ha_state()
