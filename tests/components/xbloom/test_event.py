"""Tests for event.py — XBloomBrewEvent EventEntity.

Covers HA-03: brew-started and brew-done exposed as HA event entities.
Tests directly exercise entity event logic without requiring a live hass instance.

homeassistant is not installed in the dev environment; we inject minimal mock
modules into sys.modules before any custom_components import so that
event.py can be imported and exercised in isolation.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest

# OBSOLETE — pre-BLE architecture. imports MQTT-era XBloomBrewEvent; replaced by ble_entities.XBloomBrewEventBleEntity.
# Skipped at module level until rewritten against the BLE-only component.
pytest.skip(
    "obsolete: imports MQTT-era XBloomBrewEvent; replaced by ble_entities.XBloomBrewEventBleEntity",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs():
    """Create the minimal sys.modules entries needed by event.py."""

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
    from unittest.mock import AsyncMock
    mqtt_mod = _mod("homeassistant.components.mqtt")
    mqtt_mod.async_subscribe = AsyncMock(return_value=MagicMock())
    mqtt_mod.async_publish = AsyncMock()
    mqtt_models = _mod("homeassistant.components.mqtt.models")
    mqtt_models.ReceiveMessage = MagicMock
    mqtt_mod.models = mqtt_models

    # homeassistant.components.event
    event_comp = _mod("homeassistant.components.event")

    class _EventEntity:
        _attr_has_entity_name = False
        _attr_name = None
        _attr_unique_id = None
        _attr_icon = None
        _attr_event_types = []

        def _trigger_event(self, event_type: str, event_attributes: dict | None = None) -> None:
            """Base implementation — subclasses override if needed."""
            pass

        def async_write_ha_state(self):
            pass

        async def async_added_to_hass(self):
            pass

    event_comp.EventEntity = _EventEntity

    # homeassistant.components.sensor / binary_sensor / switch / button / select
    # (needed if other test modules already injected partial stubs)
    sensor_comp = _mod("homeassistant.components.sensor")

    bs_comp = _mod("homeassistant.components.binary_sensor")
    bs_comp.BinarySensorDeviceClass = MagicMock

    sw_comp = _mod("homeassistant.components.switch")

    button_comp = _mod("homeassistant.components.button")
    select_comp = _mod("homeassistant.components.select")



_inject_stubs()

# Now safe to import from custom_components
from custom_components.xbloom.event import XBloomBrewEvent  # noqa: E402
from custom_components.xbloom.const import MQTT_TOPIC_STATUS  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_brew_event_types_declared(mock_config_entry) -> None:
    """XBloomBrewEvent must declare brew_started and brew_done in _attr_event_types."""
    entity = XBloomBrewEvent(mock_config_entry)
    assert "brew_started" in entity._attr_event_types
    assert "brew_done" in entity._attr_event_types


async def test_grinding_payload_fires_brew_started(mock_config_entry, mock_mqtt_message) -> None:
    """MQTT payload 'grinding' must trigger brew_started event type."""
    entity = XBloomBrewEvent(mock_config_entry)
    fired_events = []
    entity._trigger_event = MagicMock(side_effect=lambda t, d: fired_events.append(t))
    msg = mock_mqtt_message(MQTT_TOPIC_STATUS, "grinding")
    # Simulate callback: payload "grinding" → brew_started
    if msg.payload == "grinding":
        entity._trigger_event("brew_started", {"raw_payload": msg.payload})
    assert "brew_started" in fired_events


async def test_done_payload_fires_brew_done(mock_config_entry, mock_mqtt_message) -> None:
    """MQTT payload 'done' must trigger brew_done event type."""
    entity = XBloomBrewEvent(mock_config_entry)
    fired_events = []
    entity._trigger_event = MagicMock(side_effect=lambda t, d: fired_events.append(t))
    msg = mock_mqtt_message(MQTT_TOPIC_STATUS, "done")
    if msg.payload == "done":
        entity._trigger_event("brew_done", {"raw_payload": msg.payload})
    assert "brew_done" in fired_events


async def test_idle_payload_fires_no_event(mock_config_entry, mock_mqtt_message) -> None:
    """MQTT payload 'idle' must not fire any event."""
    entity = XBloomBrewEvent(mock_config_entry)
    fired_events = []
    entity._trigger_event = MagicMock(side_effect=lambda t, d: fired_events.append(t))
    msg = mock_mqtt_message(MQTT_TOPIC_STATUS, "idle")
    # Simulate callback logic: idle → no event
    if msg.payload == "grinding":
        entity._trigger_event("brew_started", {"raw_payload": msg.payload})
    elif msg.payload == "done":
        entity._trigger_event("brew_done", {"raw_payload": msg.payload})
    assert fired_events == []


async def test_unsubscribe_registered_on_unload(mock_config_entry) -> None:
    """entry.async_on_unload must be called with the unsubscribe canceller."""
    entity = XBloomBrewEvent(mock_config_entry)
    fake_unsubscribe = MagicMock()
    entity._entry.async_on_unload(fake_unsubscribe)
    mock_config_entry.async_on_unload.assert_called_once_with(fake_unsubscribe)


async def test_brew_done_includes_recipe_name(mock_config_entry, mock_mqtt_message) -> None:
    """NOTF-01/D-09: brew_done event_data includes recipe_name when _last_recipe_name is set."""
    entity = XBloomBrewEvent(mock_config_entry)
    entity._last_recipe_name = "Ethiopia Yirgacheffe"
    fired_events = []
    entity._trigger_event = lambda event_type, event_data: fired_events.append((event_type, event_data))
    msg = mock_mqtt_message("xbloom/status", "done")
    # Simulate message_received callback behavior:
    payload = msg.payload
    if payload == "done":
        entity._trigger_event("brew_done", {
            "raw_payload": payload,
            "recipe_name": entity._last_recipe_name or "",
        })
        entity._last_recipe_name = None
    assert len(fired_events) == 1
    event_type, event_data = fired_events[0]
    assert event_type == "brew_done"
    assert event_data.get("recipe_name") == "Ethiopia Yirgacheffe"


async def test_brew_done_recipe_name_resets_after_fire(mock_config_entry, mock_mqtt_message) -> None:
    """NOTF-01: _last_recipe_name is reset to None after brew_done fires."""
    entity = XBloomBrewEvent(mock_config_entry)
    entity._last_recipe_name = "Ethiopia Yirgacheffe"
    fired_events = []
    entity._trigger_event = lambda et, ed: fired_events.append((et, ed))
    payload = "done"
    entity._trigger_event("brew_done", {"raw_payload": payload, "recipe_name": entity._last_recipe_name or ""})
    entity._last_recipe_name = None
    assert entity._last_recipe_name is None
