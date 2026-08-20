"""Tests for button.py — XBloomStartBrewButton and XBloomCancelBrewButton.

Covers CTL-01 (start brew) and CTL-02 (cancel brew) behaviors.
Tests are in RED state — XBloomStartBrewButton and XBloomCancelBrewButton do
not yet exist in button.py.

homeassistant is not installed in this dev environment; we inject minimal mock
modules into sys.modules before any custom_components import.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by button.py."""

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

    class _callback:
        """Minimal @callback decorator — just passes the function through."""
        def __new__(cls, fn):
            return fn

    core.callback = _callback

    # homeassistant.exceptions
    exc_mod = _mod("homeassistant.exceptions")
    # ConfigEntryAuthFailed / ConfigEntryNotReady are defined once in
    # conftest.py. Re-creating them here would rebind the shared stub to a
    # NEW class object, so a module that imported the old one would no
    # longer match it in `except` / `pytest.raises`.

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

    class _CoordinatorEntity:
        """Minimal CoordinatorEntity stub."""
        def __init__(self, coordinator, *args, **kwargs):
            self.coordinator = coordinator

    uc.CoordinatorEntity = _CoordinatorEntity

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

    class _ButtonEntity:
        """Minimal ButtonEntity stub."""
        _attr_has_entity_name = False
        _attr_name = None
        _attr_unique_id = None
        _attr_icon = None

        async def async_press(self) -> None:
            pass

    button_comp.ButtonEntity = _ButtonEntity

    select_comp = _mod("homeassistant.components.select")



_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom.button import XBloomStartBrewButton, XBloomCancelBrewButton  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_start_brew_button_press(mock_config_entry) -> None:
    """CTL-01: async_press delegates to xbloom.start_brew (BLE-only path).

    The button sends an empty payload — grinder use is governed by
    ``switch.xbloom_studio_use_grinder``, which ``start_brew`` reads itself.
    """
    coordinator = MagicMock()
    coordinator.config_entry = mock_config_entry
    entry = mock_config_entry
    button = XBloomStartBrewButton(coordinator, entry)
    button.hass = MagicMock()
    button.hass.services.async_call = AsyncMock()
    # Selected recipe present.
    select_state = MagicMock()
    select_state.state = "Ethiopia Yirgacheffe"
    button.hass.states.get = MagicMock(
        side_effect=lambda eid: {
            "select.xbloom_studio_recipe": select_state,
        }.get(eid)
    )
    await button.async_press()
    button.hass.services.async_call.assert_awaited_once_with(
        "xbloom", "start_brew", {}, blocking=False
    )


@pytest.mark.asyncio
async def test_cancel_brew_sends_stop_command(mock_config_entry) -> None:
    """CTL-02: Cancel button delegates to xbloom.stop_brew."""
    entry = mock_config_entry
    button = XBloomCancelBrewButton(entry)
    button.hass = MagicMock()
    button.hass.services.async_call = AsyncMock()
    await button.async_press()
    button.hass.services.async_call.assert_awaited_once_with(
        "xbloom", "stop_brew", {}, blocking=False
    )


async def test_start_brew_unavailable_without_recipe(mock_config_entry) -> None:
    """CTL-01/D-02: Start Brew button is unavailable when no recipe selected."""
    coordinator = MagicMock()
    entry = mock_config_entry
    button = XBloomStartBrewButton(coordinator, entry)
    button.hass = MagicMock()
    button.hass.states.get = MagicMock(return_value=None)
    assert button.available is False
    # Also test unknown state
    state_unknown = MagicMock()
    state_unknown.state = "unknown"
    button.hass.states.get = MagicMock(return_value=state_unknown)
    assert button.available is False


async def test_start_brew_available_with_recipe(mock_config_entry) -> None:
    """CTL-01/D-02: Start Brew button is available when a recipe is selected."""
    coordinator = MagicMock()
    entry = mock_config_entry
    button = XBloomStartBrewButton(coordinator, entry)
    button.hass = MagicMock()
    state = MagicMock()
    state.state = "Ethiopia Yirgacheffe"
    button.hass.states.get = MagicMock(return_value=state)
    assert button.available is True
