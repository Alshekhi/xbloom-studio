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

from . import _resolve_ble_name, remember_address
from .const import CONF_BLE_ADDRESS, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([XBloomInRangeSensor(entry)])


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
