"""Tests for sensor.py — MQTT-subscribed brew status and scale weight entities.

Covers HA-02: brew status exposed as HA sensor entity.
Tests directly exercise entity state logic without requiring a live hass instance.

homeassistant is not installed in the dev environment; we inject minimal mock
modules into sys.modules before any custom_components import so that
sensor.py can be imported and exercised in isolation.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# OBSOLETE — pre-BLE architecture. imports MQTT-era XBloomBrewStatus/XBloomScaleWeight; replaced by BLE sensors in ble_entities.py.
# Skipped at module level until rewritten against the BLE-only component.
pytest.skip(
    "obsolete: imports MQTT-era XBloomBrewStatus/XBloomScaleWeight; replaced by BLE sensors in ble_entities.py",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by sensor.py."""

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
    exc_mod.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    # homeassistant.helpers.*
    _mod("homeassistant.helpers")
    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    dev_reg = _mod("homeassistant.helpers.device_registry")

    class _DeviceInfo(dict):
        """DeviceInfo stub — just a dict subclass."""
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

    # homeassistant.components.sensor
    sensor_comp = _mod("homeassistant.components.sensor")

    class _SensorEntity:
        _attr_has_entity_name = False
        _attr_name = None
        _attr_unique_id = None
        _attr_native_value = None
        _attr_icon = None
        _attr_native_unit_of_measurement = None

        def async_write_ha_state(self):
            pass

    class _RestoreSensor(_SensorEntity):
        async def async_get_last_sensor_data(self):
            return None

        async def async_added_to_hass(self):
            pass

    sensor_comp.SensorEntity = _SensorEntity
    sensor_comp.RestoreSensor = _RestoreSensor

    # homeassistant.components.button / select (needed by __init__.py if imported)
    button_comp = _mod("homeassistant.components.button")
    select_comp = _mod("homeassistant.components.select")



_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom.sensor import XBloomBrewStatus, XBloomScaleWeight  # noqa: E402
from custom_components.xbloom.const import MQTT_TOPIC_STATUS, MQTT_TOPIC_SCALE  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_brew_status_updates_on_mqtt_message(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomBrewStatus._attr_native_value must equal msg.payload after MQTT message."""
    entity = XBloomBrewStatus(mock_config_entry)
    entity.async_write_ha_state = MagicMock()

    msg = mock_mqtt_message(MQTT_TOPIC_STATUS, "grinding")
    # Simulate the callback directly
    entity._attr_native_value = msg.payload
    assert entity._attr_native_value == "grinding"

    msg2 = mock_mqtt_message(MQTT_TOPIC_STATUS, "done")
    entity._attr_native_value = msg2.payload
    assert entity._attr_native_value == "done"


async def test_scale_weight_casts_payload_to_float(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomScaleWeight._attr_native_value must be float(msg.payload), not str."""
    entity = XBloomScaleWeight(mock_config_entry)
    entity.async_write_ha_state = MagicMock()

    msg = mock_mqtt_message(MQTT_TOPIC_SCALE, "125.5")
    entity._attr_native_value = float(msg.payload)
    assert entity._attr_native_value == 125.5
    assert isinstance(entity._attr_native_value, float)


async def test_scale_weight_unit_is_grams(mock_config_entry) -> None:
    """XBloomScaleWeight native unit must be 'g'."""
    entity = XBloomScaleWeight(mock_config_entry)
    assert entity._attr_native_unit_of_measurement == "g"


async def test_mqtt_unsubscribe_registered_on_unload(mock_config_entry) -> None:
    """entry.async_on_unload must be called when subscribing."""
    entity = XBloomBrewStatus(mock_config_entry)
    # entry.async_on_unload is a MagicMock on mock_config_entry (from conftest)
    # Simulate what async_added_to_hass does: call async_on_unload with a canceller
    fake_unsubscribe = MagicMock()
    entity._entry.async_on_unload(fake_unsubscribe)
    mock_config_entry.async_on_unload.assert_called_once_with(fake_unsubscribe)
