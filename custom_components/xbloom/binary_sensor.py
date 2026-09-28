"""Whether the machine is in range of Home Assistant's Bluetooth.

Nothing else here can tell. The status sensors keep the last thing the machine
reported, so a machine that is switched off still reads "ok", and finding out
by connecting would take the machine's one connection from the app. Home
Assistant's Bluetooth already follows the machine's advertisements, and keeps
a device it is connected to in its list, so this reads that instead: on while
the machine is seen, off once Home Assistant drops it.
"""
from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from xbloom.ble import NOTIFY_BREW_PAUSED, NOTIFY_BREW_RESUMED, NOTIFY_ENJOY

from . import _resolve_ble_name, remember_address
from .ble_entities import _device_info, signal_brew_lifecycle, signal_event
from .const import CONF_BLE_ADDRESS, DOMAIN
from .prepare import signal_prepared


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([
        XBloomInRangeSensor(entry), XBloomBrewPausedSensor(entry), XBloomRecipeReadySensor(entry),
    ])


class XBloomInRangeSensor(BinarySensorEntity):
    """On while Home Assistant's Bluetooth can see the machine."""

    _attr_has_entity_name = True
    _attr_translation_key = "in_range"
    _attr_unique_id = "xbloom_in_range"
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_is_on = False
        self._stop_by_name = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def icon(self) -> str:
        return "mdi:bluetooth" if self.is_on else "mdi:bluetooth-off"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        address = self._entry.data.get(CONF_BLE_ADDRESS)
        if address:
            self._follow(address)
            return
        # Until the address is known the machine is recognised by name, and
        # the first advertisement carrying the name gives the address.
        self._stop_by_name = bluetooth.async_register_callback(
            self.hass, self._on_named,
            {"local_name": _resolve_ble_name(self._entry), "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self.async_on_remove(self._stop_listening_by_name)

    def _follow(self, address: str) -> None:
        self._attr_is_on = bluetooth.async_address_present(
            self.hass, address, connectable=True,
        )
        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, self._on_seen,
            {"address": address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        ))
        self.async_on_remove(bluetooth.async_track_unavailable(
            self.hass, self._on_gone, address, connectable=True,
        ))
        self.async_write_ha_state()

    @callback
    def _stop_listening_by_name(self) -> None:
        if self._stop_by_name is not None:
            self._stop_by_name()
            self._stop_by_name = None

    @callback
    def _on_named(self, service_info, _change) -> None:
        if self._stop_by_name is None:
            return
        self._stop_listening_by_name()
        remember_address(self.hass, self._entry, service_info.address)
        self._follow(service_info.address)

    @callback
    def _on_seen(self, _service_info, _change) -> None:
        if not self._attr_is_on:
            self._attr_is_on = True
            self.async_write_ha_state()

    @callback
    def _on_gone(self, _service_info) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class XBloomBrewPausedSensor(BinarySensorEntity):
    """On while a recipe brew is paused.

    The machine reports both sides itself: a paused brew sends 40515 and a
    resumed one 40516. Anything that ends the brew, or starts the next, also
    ends the pause, so it never outlives the brew it belongs to.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "brew_paused"
    _attr_unique_id = "xbloom_brew_paused"
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_is_on = False

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def icon(self) -> str:
        return "mdi:pause-circle" if self.is_on else "mdi:play-circle"

    @callback
    def _set(self, paused: bool) -> None:
        if self._attr_is_on != paused:
            self._attr_is_on = paused
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_signal(decoded: dict) -> None:
            cmd = decoded.get("cmd")
            if cmd == NOTIFY_BREW_PAUSED:
                self._set(True)
            elif cmd in (NOTIFY_BREW_RESUMED, NOTIFY_ENJOY):
                self._set(False)

        @callback
        def _on_lifecycle(_phase: str) -> None:
            # Started or ended, a pause does not carry over.
            self._set(False)

        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_event(self._entry.entry_id), _on_signal)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_brew_lifecycle(self._entry.entry_id), _on_lifecycle
            )
        )


class XBloomRecipeReadySensor(BinarySensorEntity):
    """On while the machine holds the picked recipe, ready to start at once.

    `reason` says why it is not, when something stopped it: no bag picked,
    the machine refused, a brew running.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "recipe_ready"
    _attr_unique_id = "xbloom_recipe_ready"
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_is_on = False
        self._attr_extra_state_attributes = {"reason": None}

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def icon(self) -> str:
        return "mdi:coffee-to-go" if self.is_on else "mdi:coffee-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_prepared(ready: bool, reason: str | None) -> None:
            self._attr_is_on = ready
            self._attr_extra_state_attributes = {"reason": reason}
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_prepared(self._entry.entry_id), _on_prepared)
        )
