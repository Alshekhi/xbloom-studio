"""Connect switch for the xBloom Studio integration.

Single switch that, when ON, opens a live session: it holds a long-lived
BLE connection (Method 2) and streams every interesting machine event onto
the HA bus. Those events are voice-agnostic — they drive sensors and the
dashboard, and optionally feed spoken announcements via a blueprint. The
switch itself has no opinion about speech; speaking is an automation's job.

The session is transient by design (starts OFF, auto-expires on idle) so
the machine returns to the iOS app when you walk away.

Replaces the previous three separate mode switches (Scale / Grinder /
Brewer) which conflicted with each other (only one BLE connection per
device). Now one toggle covers the whole live session.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_IDLE_TIMEOUT, DOMAIN
from .live_session import LiveSessionListener
from xbloom.mode_listener import IDLE_TIMEOUT_SEC

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

    # Idle auto-disconnect window: vendor default unless the user overrode it
    # in the integration's options (CONF_IDLE_TIMEOUT).
    idle_timeout = float(entry.data.get(CONF_IDLE_TIMEOUT, IDLE_TIMEOUT_SEC))
    live_listener = LiveSessionListener(
        hass, resolver, idle_timeout_s=idle_timeout, entry_id=entry.entry_id,
    )
    runtime.live_session_listener = live_listener

    async_add_entities([
        XBloomConnectSwitch(live_listener),
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


class XBloomConnectSwitch(SwitchEntity):
    """When ON: HA opens a live session — holds BLE and streams machine
    events onto the bus (for sensors, dashboard, and optional announcements).
    Transient by design; auto-expires on idle so the iOS app can reclaim BLE."""

    _attr_has_entity_name = True
    _attr_name = "Connect"
    _attr_unique_id = "xbloom_connect_switch"
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, listener: LiveSessionListener) -> None:
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
                _LOGGER.info("[connect] failed — flipping switch OFF")
                self._attr_is_on = False
                self.async_write_ha_state()

        @callback
        def _on_auto_stopped(_event) -> None:
            if self._attr_is_on:
                _LOGGER.info("[connect] idle auto-stopped — flipping switch OFF")
                self._attr_is_on = False
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen("xbloom_connect_failed", _on_failed)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                "xbloom_connect_auto_stopped", _on_auto_stopped,
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
        # Signal session end so live-only consumers (e.g. current_module) clear.
        # Idle-timeout and failure paths already emit their own lifecycle events
        # from the listener; this covers an explicit/user disconnect.
        self.hass.bus.async_fire("xbloom_connect_stopped", {"reason": "user"})
