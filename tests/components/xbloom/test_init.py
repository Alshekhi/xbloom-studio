"""Tests for __init__.py — xBloom integration setup and service registration.

Covers CTL-03: xbloom.start_brew service registration and deregistration.
Tests are in RED state — async_setup_entry does not yet register start_brew service.

homeassistant is not installed in this dev environment; we inject minimal mock
modules into sys.modules before any custom_components import.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by __init__.py."""

    def _mod(name):
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    # homeassistant root
    _mod("homeassistant")
    _mod("homeassistant.components")

    # homeassistant.config_entries
    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = MagicMock

    # homeassistant.core
    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock
    core.ServiceCall = MagicMock

    class _callback:
        """Minimal @callback decorator — just passes the function through."""
        def __new__(cls, fn):
            return fn

    core.callback = _callback

    # homeassistant.exceptions
    exc_mod = _mod("homeassistant.exceptions")
    exc_mod.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    # homeassistant.helpers.*
    _mod("homeassistant.helpers")
    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    dev_reg = _mod("homeassistant.helpers.device_registry")

    class _DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    dev_reg.DeviceInfo = _DeviceInfo

    uc = _mod("homeassistant.helpers.update_coordinator")
    uc.UpdateFailed = Exception

    # homeassistant.components.mqtt
    mqtt_mod = _mod("homeassistant.components.mqtt")
    mqtt_mod.async_subscribe = AsyncMock(return_value=MagicMock())
    mqtt_mod.async_publish = AsyncMock()
    mqtt_models = _mod("homeassistant.components.mqtt.models")
    mqtt_models.ReceiveMessage = MagicMock
    mqtt_mod.models = mqtt_models

    # homeassistant.components.event
    event_comp = _mod("homeassistant.components.event")

    # homeassistant.components.sensor / binary_sensor / switch / button / select
    sensor_comp = _mod("homeassistant.components.sensor")

    bs_comp = _mod("homeassistant.components.binary_sensor")
    bs_comp.BinarySensorDeviceClass = MagicMock

    sw_comp = _mod("homeassistant.components.switch")

    button_comp = _mod("homeassistant.components.button")

    select_comp = _mod("homeassistant.components.select")


    # voluptuous (used in some Phase 7 service schemas)
    vol_mod = _mod("voluptuous")
    vol_mod.Schema = MagicMock()
    vol_mod.Optional = MagicMock()
    vol_mod.Required = MagicMock()


_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom import async_setup_entry, async_unload_entry  # noqa: E402
from custom_components.xbloom.const import DOMAIN  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_service_registration(mock_config_entry) -> None:
    """CTL-03: after async_setup_entry, hass.services.async_register is called with start_brew."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.states = MagicMock()
    entry = mock_config_entry
    entry.async_on_unload = MagicMock()
    with patch("custom_components.xbloom.XBloomCoordinator") as mc, \
         patch("custom_components.xbloom.XBloomClient") as mk:
        mk.return_value = AsyncMock()
        coord = MagicMock()
        coord.async_config_entry_first_refresh = AsyncMock()
        mc.return_value = coord
        await async_setup_entry(hass, entry)
    hass.services.async_register.assert_called()
    names = [a[0][1] for a in hass.services.async_register.call_args_list if len(a[0]) >= 2]
    assert "start_brew" in names


async def test_service_deregistration_on_unload(mock_config_entry) -> None:
    """CTL-03: the unload callback registered via entry.async_on_unload calls hass.services.async_remove."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.states = MagicMock()
    callbacks = []
    entry = mock_config_entry
    entry.async_on_unload = MagicMock(side_effect=lambda cb: callbacks.append(cb))
    with patch("custom_components.xbloom.XBloomCoordinator") as mc, \
         patch("custom_components.xbloom.XBloomClient") as mk:
        mk.return_value = AsyncMock()
        coord = MagicMock()
        coord.async_config_entry_first_refresh = AsyncMock()
        mc.return_value = coord
        await async_setup_entry(hass, entry)
    for cb in callbacks:
        cb()
    hass.services.async_remove.assert_called()
    remove_pairs = [(a[0][0], a[0][1]) for a in hass.services.async_remove.call_args_list if len(a[0]) >= 2]
    assert (DOMAIN, "start_brew") in remove_pairs
