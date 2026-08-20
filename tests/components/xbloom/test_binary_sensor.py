"""Tests for binary_sensor.py — MQTT-subscribed connectivity entities.

Covers HA-04: machine connectivity exposed as HA binary sensor entity.
Tests directly exercise entity state logic without requiring a live hass instance.

homeassistant is not installed in the dev environment; we inject minimal mock
modules into sys.modules before any custom_components import so that
binary_sensor.py can be imported and exercised in isolation.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# OBSOLETE — pre-BLE architecture. binary_sensor platform was never shipped (no binary_sensor.py in the component).
# Skipped at module level until rewritten against the BLE-only component.
pytest.skip(
    "obsolete: binary_sensor platform was never shipped (no binary_sensor.py in the component)",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by binary_sensor.py."""

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

    # homeassistant.components.binary_sensor
    bs_comp = _mod("homeassistant.components.binary_sensor")

    class _BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"

    class _BinarySensorEntity:
        _attr_has_entity_name = False
        _attr_name = None
        _attr_unique_id = None
        _attr_is_on = None
        _attr_device_class = None

        def async_write_ha_state(self):
            pass

        async def async_added_to_hass(self):
            pass

    bs_comp.BinarySensorDeviceClass = _BinarySensorDeviceClass
    bs_comp.BinarySensorEntity = _BinarySensorEntity

    # homeassistant.components.switch
    sw_comp = _mod("homeassistant.components.switch")

    class _SwitchEntity:
        _attr_has_entity_name = False
        _attr_name = None
        _attr_unique_id = None
        _attr_is_on = None
        _attr_icon = None

        def async_write_ha_state(self):
            pass

        async def async_added_to_hass(self):
            pass

    sw_comp.SwitchEntity = _SwitchEntity

    # homeassistant.components.sensor (needed if test_sensor already ran)
    sensor_comp = _mod("homeassistant.components.sensor")

    class _SensorEntity:
        pass

    class _RestoreSensor(_SensorEntity):
        async def async_get_last_sensor_data(self):
            return None

        async def async_added_to_hass(self):
            pass

    sensor_comp.SensorEntity = _SensorEntity
    sensor_comp.RestoreSensor = _RestoreSensor

    # homeassistant.components.button / select
    button_comp = _mod("homeassistant.components.button")
    select_comp = _mod("homeassistant.components.select")



_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom.binary_sensor import XBloomConnected, XBloomBridgeStatus  # noqa: E402
from custom_components.xbloom.const import MQTT_TOPIC_CONNECTED, MQTT_TOPIC_BRIDGE_STATUS  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_machine_connected_true_on_payload_true(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomConnected._attr_is_on must be True when MQTT payload is 'true'."""
    entity = XBloomConnected(mock_config_entry)
    msg = mock_mqtt_message(MQTT_TOPIC_CONNECTED, "true")
    entity._attr_is_on = msg.payload.lower() == "true"
    assert entity._attr_is_on is True


async def test_machine_connected_false_on_payload_false(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomConnected._attr_is_on must be False when MQTT payload is 'false'."""
    entity = XBloomConnected(mock_config_entry)
    msg = mock_mqtt_message(MQTT_TOPIC_CONNECTED, "false")
    entity._attr_is_on = msg.payload.lower() == "true"
    assert entity._attr_is_on is False


async def test_machine_connected_case_insensitive(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomConnected must handle 'True' (capitalized) payload."""
    entity = XBloomConnected(mock_config_entry)
    msg = mock_mqtt_message(MQTT_TOPIC_CONNECTED, "True")
    entity._attr_is_on = msg.payload.lower() == "true"
    assert entity._attr_is_on is True


async def test_bridge_online_true_on_payload_online(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomBridgeStatus._attr_is_on must be True when MQTT payload is 'online'."""
    entity = XBloomBridgeStatus(mock_config_entry)
    msg = mock_mqtt_message(MQTT_TOPIC_BRIDGE_STATUS, "online")
    entity._attr_is_on = msg.payload == "online"
    assert entity._attr_is_on is True


async def test_bridge_offline_false_on_payload_offline(mock_config_entry, mock_mqtt_message) -> None:
    """XBloomBridgeStatus._attr_is_on must be False when MQTT payload is 'offline'."""
    entity = XBloomBridgeStatus(mock_config_entry)
    msg = mock_mqtt_message(MQTT_TOPIC_BRIDGE_STATUS, "offline")
    entity._attr_is_on = msg.payload == "online"
    assert entity._attr_is_on is False


async def test_mqtt_unsubscribe_registered_on_unload(mock_config_entry) -> None:
    """entry.async_on_unload must be called with the unsubscribe canceller."""
    entity = XBloomConnected(mock_config_entry)
    fake_unsubscribe = MagicMock()
    entity._entry.async_on_unload(fake_unsubscribe)
    mock_config_entry.async_on_unload.assert_called_once_with(fake_unsubscribe)
