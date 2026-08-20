"""Shared fixtures for xBloom integration tests.

homeassistant and voluptuous are NOT installed in this dev environment.
This conftest injects stub modules into sys.modules before pytest imports
any test module, so the component tree can be imported and exercised in
isolation. Individual test files still carry their own legacy
``_inject_stubs()`` blocks — those are harmless no-ops/attribute overrides
on top of the modules created here (they use ``sys.modules.setdefault``).

Every stub module gets a PEP 562 ``__getattr__`` fallback returning a
MagicMock, so a new name imported by the component does not break test
collection. Names that must be real classes (entity bases, ConfigFlow,
Store, …) are defined explicitly because MagicMock cannot serve as a base
class in multiple-inheritance combinations.
"""
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Central homeassistant / voluptuous stub injection
# ---------------------------------------------------------------------------

def _stub_mod(name: str) -> types.ModuleType:
    """Create (or return) a registered stub module with MagicMock fallback."""
    if name in sys.modules:
        return sys.modules[name]
    m = types.ModuleType(name)
    # PEP 562 module-level __getattr__: unknown names resolve to MagicMock()
    # so `from <stub> import <new_name>` keeps working as the component grows.
    m.__getattr__ = lambda attr, _n=name: MagicMock(name=f"{_n}.{attr}")
    sys.modules[name] = m
    return m


def _base_class(name: str) -> type:
    """A permissive, distinct base class (entity bases must not share a
    class object — `class X(RestoreSensor, SensorEntity)` needs two bases)."""
    return type(name, (), {
        "__init__": lambda self, *a, **k: None,
        "__class_getitem__": classmethod(lambda cls, item: cls),
        "async_write_ha_state": lambda self: None,
        "async_on_remove": lambda self, fn: None,
    })


def _inject_global_stubs() -> None:
    ha = _stub_mod("homeassistant")

    # -- config_entries ----------------------------------------------------
    ce = _stub_mod("homeassistant.config_entries")

    class _ConfigEntry:
        def __init__(self):
            self.data = {}
            self.options = {}
            self.entry_id = "stub"
            self.runtime_data = None

        def async_on_unload(self, fn):
            return fn

        def async_create_background_task(self, hass, coro, name=None, **kw):
            import asyncio
            return asyncio.get_event_loop().create_task(coro)

    class _ConfigFlow:
        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__(**kw)
            cls._domain = domain

    class _OptionsFlow:
        pass

    ce.ConfigEntry = _ConfigEntry
    ce.ConfigFlow = _ConfigFlow
    ce.OptionsFlow = _OptionsFlow
    ce.SOURCE_REAUTH = "reauth"
    ce.FlowResult = dict
    ha.config_entries = ce

    # -- core / const / exceptions / data_entry_flow ------------------------
    core = _stub_mod("homeassistant.core")
    core.HomeAssistant = MagicMock
    core.ServiceCall = MagicMock
    core.SupportsResponse = MagicMock(name="SupportsResponse")
    core.Event = MagicMock(name="Event")  # supports Event[...] subscripting
    core.EventStateChangedData = MagicMock(name="EventStateChangedData")
    core.callback = lambda fn: fn

    const = _stub_mod("homeassistant.const")
    const.UnitOfMass = MagicMock(name="UnitOfMass")

    exc_mod = _stub_mod("homeassistant.exceptions")
    exc_mod.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
    exc_mod.HomeAssistantError = type("HomeAssistantError", (Exception,), {})

    def_mod = _stub_mod("homeassistant.data_entry_flow")
    def_mod.FlowResult = dict

    # -- helpers -------------------------------------------------------------
    helpers = _stub_mod("homeassistant.helpers")
    helpers.selector = _stub_mod("homeassistant.helpers.selector")

    aio_client = _stub_mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    dev_reg = _stub_mod("homeassistant.helpers.device_registry")
    dev_reg.DeviceInfo = type("DeviceInfo", (dict,), {
        "__init__": lambda self, **kw: dict.__init__(self, **kw),
    })

    dispatcher = _stub_mod("homeassistant.helpers.dispatcher")
    dispatcher.async_dispatcher_connect = MagicMock(return_value=MagicMock())
    dispatcher.async_dispatcher_send = MagicMock()

    hev = _stub_mod("homeassistant.helpers.event")
    hev.async_track_state_change_event = MagicMock(return_value=MagicMock())

    restore = _stub_mod("homeassistant.helpers.restore_state")
    restore.RestoreEntity = _base_class("RestoreEntity")

    storage = _stub_mod("homeassistant.helpers.storage")
    storage.Store = _base_class("Store")

    uc = _stub_mod("homeassistant.helpers.update_coordinator")
    uc.DataUpdateCoordinator = _base_class("DataUpdateCoordinator")
    uc.CoordinatorEntity = _base_class("CoordinatorEntity")
    uc.UpdateFailed = type("UpdateFailed", (Exception,), {})

    # -- components -----------------------------------------------------------
    components = _stub_mod("homeassistant.components")
    ha.components = components

    bt = _stub_mod("homeassistant.components.bluetooth")
    bt.BluetoothServiceInfoBleak = MagicMock
    bt.async_discovered_service_info = MagicMock(return_value=[])
    bt.async_ble_device_from_address = MagicMock(return_value=None)
    components.bluetooth = bt

    entity_bases = {
        "homeassistant.components.button": {"ButtonEntity": _base_class("ButtonEntity")},
        "homeassistant.components.event": {"EventEntity": _base_class("EventEntity")},
        "homeassistant.components.number": {
            "NumberEntity": _base_class("NumberEntity"),
            "NumberMode": MagicMock(name="NumberMode"),
        },
        "homeassistant.components.select": {"SelectEntity": _base_class("SelectEntity")},
        "homeassistant.components.sensor": {
            "SensorEntity": _base_class("SensorEntity"),
            "RestoreSensor": _base_class("RestoreSensor"),
            "SensorDeviceClass": MagicMock(name="SensorDeviceClass"),
            "SensorStateClass": MagicMock(name="SensorStateClass"),
        },
        "homeassistant.components.switch": {"SwitchEntity": _base_class("SwitchEntity")},
        "homeassistant.components.binary_sensor": {
            "BinarySensorEntity": _base_class("BinarySensorEntity"),
            "BinarySensorDeviceClass": MagicMock(name="BinarySensorDeviceClass"),
        },
        "homeassistant.components.text": {"TextEntity": _base_class("TextEntity")},
        "homeassistant.components.update": {
            "UpdateEntity": _base_class("UpdateEntity"),
            "UpdateEntityFeature": MagicMock(name="UpdateEntityFeature"),
        },
    }
    for mod_name, attrs in entity_bases.items():
        m = _stub_mod(mod_name)
        for attr, value in attrs.items():
            setattr(m, attr, value)
        setattr(components, mod_name.rsplit(".", 1)[1], m)

    # -- util ------------------------------------------------------------------
    # ble_entities does `from homeassistant.util import dt as dt_util` and calls
    # dt_util.utcnow() for event timestamps. A MagicMock would satisfy the
    # import but produce non-comparable timestamps, so hand back real UTC time.
    util = _stub_mod("homeassistant.util")
    dt_stub = _stub_mod("homeassistant.util.dt")
    dt_stub.utcnow = lambda: datetime.now(timezone.utc)
    dt_stub.now = lambda: datetime.now(timezone.utc)
    dt_stub.as_local = lambda value: value
    dt_stub.UTC = timezone.utc
    util.dt = dt_stub
    ha.util = util

    # -- voluptuous ------------------------------------------------------------
    vol = _stub_mod("voluptuous")
    vol.Schema = MagicMock(name="vol.Schema")
    vol.Required = MagicMock(name="vol.Required")
    vol.Optional = MagicMock(name="vol.Optional")
    vol.All = MagicMock(name="vol.All")
    vol.Coerce = MagicMock(name="vol.Coerce")
    vol.Range = MagicMock(name="vol.Range")
    vol.In = MagicMock(name="vol.In")
    vol.UNDEFINED = object()


_inject_global_stubs()

from homeassistant.config_entries import ConfigEntry as _ConfigEntry  # noqa: E402

_CONFIG_ENTRY_SPEC = _ConfigEntry

MOCK_CONFIG_ENTRY_DATA = {
    "access_token": "test_access_token_abc123",
    "refresh_token": "test_refresh_token_def456",
    "mqtt_host": "192.168.1.100",
    "mqtt_port": 1883,
    "device_id": "test_device_001",
    "product_id": "test_product_001",
}


@pytest.fixture
def mock_config_entry():
    """Return a mock ConfigEntry with Phase 4 token + MQTT + Phase 7 device data."""
    entry = MagicMock(spec=_CONFIG_ENTRY_SPEC) if _CONFIG_ENTRY_SPEC else MagicMock()
    entry.data = MOCK_CONFIG_ENTRY_DATA.copy()
    entry.entry_id = "test_entry_id_001"
    entry.async_on_unload = MagicMock()
    return entry


@pytest.fixture
def mock_xbloom_client():
    """Return a mock XBloomClient with async methods patched."""
    client = AsyncMock()
    client.get_recipes = AsyncMock(return_value=[
        {
            "id": "recipe_001",
            "name": "Test Espresso",
            "dose": 18.0,
            "grand_water": 36.0,
            "grinder_size": 3,
            "pour_count": 2,
            "pour_list": [],
            "cup_type": 1,
            "cup_type_name": "Espresso",
            "the_color": "#000000",
            "adapted_model": "Studio",
            "create_time_stamp": 1700000000,
            "is_default": True,
            "is_shortcuts": False,
            "sub_set_type": 0,
            "the_subset_id": "",
            "share_recipe_link": "",
            "is_enable_bypass_water": False,
        }
    ])
    return client


@pytest.fixture
def mock_mqtt_message():
    """Return a factory for mock MQTT ReceiveMessage objects."""
    def _make_message(topic: str, payload: str):
        msg = MagicMock()
        msg.topic = topic
        msg.payload = payload
        return msg
    return _make_message
