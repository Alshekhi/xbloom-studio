"""The brew completion contract — `xbloom_brew_completed`.

Root cause these lock in: RD_ENJOY is not guaranteed. An observed brew ground,
poured three times, emitted `brew_ended` and never emitted `brew_done`. It made
coffee, moved
`brew_status` to idle via the home-activity reconciliation, and told nobody —
the announcement blueprint requires `event_type == 'brew_done'`, and the
watcher read `idle` as "cancelled".

So a brew that ends without ENJOY is complete but *unconfirmed*: it must still
fire a completion, tagged `presumed` rather than `confirmed`, so consumers can
announce it and deduct inventory while knowing which signal they got.

homeassistant/voluptuous are stubbed by conftest.py; we drive the actual
handlers registered by async_setup_entry.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom import async_setup_entry
from custom_components.xbloom.const import CONF_BLE_NAME, CONF_PRODUCT_ID
from xbloom import spec as _spec

CMD_BREW_END = 40511

_RECIPE = {
    "id": "1419717",
    "name": "Test Recipe One",
    "pours": [{"volume_ml": 60, "temperature_c": 93}],
    "dose_g": 20,
    "grinder_size": 55,
    "grinder_size_enabled": 1,
    "cup_type": 3,
    "rpm": 100,
}


class _FakeBle:
    """Stand-in for XBloomBleClient.

    `enjoy` decides whether RD_ENJOY ever arrives: True returns immediately
    (the healthy brew), False blocks forever (the 09-08 brew, where the task
    sat until its 600 s safety net).
    """

    instances: list["_FakeBle"] = []
    enjoy = True

    def __init__(self, device_or_name, *, on_event=None, **_kw):
        self.on_event = on_event
        self._client = MagicMock()
        self._client.write_gatt_char = AsyncMock()
        _FakeBle.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def brew(self, recipe):
        return None

    async def wait_for_completion(self, timeout=600.0):
        if _FakeBle.enjoy:
            return True
        await asyncio.Event().wait()
        return True


class _Entry:
    def __init__(self):
        self.data = {CONF_BLE_NAME: "XBLOOM TEST", CONF_PRODUCT_ID: "TEST01"}
        self.entry_id = "test_entry"
        self.runtime_data = None
        self.tasks: list[asyncio.Task] = []

    def async_on_unload(self, fn):
        return fn

    def async_create_background_task(self, hass, coro, name=None, **_kw):
        task = asyncio.get_event_loop().create_task(coro)
        self.tasks.append(task)
        return task


def _make_hass():
    hass = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.bus.async_fire = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.loop.time = lambda: 1000.0

    def _get_state(entity_id):
        state = MagicMock()
        if entity_id == "select.xbloom_studio_recipe":
            state.state = "Test Recipe One"
        elif entity_id == "switch.xbloom_studio_use_grinder":
            state.state = "on"
        else:
            state.state = "unknown"
        return state

    hass.states.get = _get_state
    return hass


async def _setup_and_get_handlers(hass, entry):
    coord = MagicMock()
    coord.data = [_RECIPE]
    coord.async_config_entry_first_refresh = AsyncMock()
    with patch("custom_components.xbloom.XBloomCoordinator", return_value=coord), \
         patch("custom_components.xbloom.XBloomClient", return_value=AsyncMock()):
        await async_setup_entry(hass, entry)
    handlers = {}
    for call in hass.services.async_register.call_args_list:
        if len(call.args) >= 3:
            handlers[call.args[1]] = call.args[2]
    return handlers


def _completed_events(hass):
    """Every `xbloom_brew_completed` payload fired on the bus."""
    return [
        c.args[1]
        for c in hass.bus.async_fire.call_args_list
        if c.args and c.args[0] == "xbloom_brew_completed"
    ]


@pytest.fixture(autouse=True)
def _reset_fake_ble():
    _FakeBle.instances = []
    _FakeBle.enjoy = True
    yield
    _FakeBle.instances = []
    _FakeBle.enjoy = True


async def test_enjoy_fires_confirmed_completion():
    """RD_ENJOY arrives — the healthy path — so the outcome is confirmed."""
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    events = _completed_events(hass)
    assert len(events) == 1, "one completion per brew"
    assert events[0]["outcome"] == "confirmed"
    assert events[0]["recipe_name"] == "Test Recipe One"
    assert events[0]["recipe_id"] == "1419717"
    assert events[0]["dose_g"] == 20
    assert events[0]["cup_type"] == 3
    assert events[0]["run_id"]


async def test_brew_end_without_enjoy_fires_presumed_completion():
    """The observed case: BREW_END arrives, ENJOY never does.

    This must still complete — the coffee was made — but tagged `presumed`.
    """
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 0.05):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)

        # The machine stops brewing. No ENJOY will follow.
        await _FakeBle.instances[0].on_event({"cmd": CMD_BREW_END})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    events = _completed_events(hass)
    assert len(events) == 1, "a brew that ends without ENJOY must still complete"
    assert events[0]["outcome"] == "presumed"
    assert events[0]["recipe_name"] == "Test Recipe One"
    assert events[0]["dose_g"] == 20


async def test_enjoy_after_brew_end_still_counts_as_confirmed():
    """BREW_END then ENJOY inside the grace window is the *normal* sequence.

    Recorder shows ENJOY landing 37-70 s after BREW_END on every healthy brew,
    so arriving second must not downgrade the outcome to presumed.
    """
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 5.0):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        await _FakeBle.instances[0].on_event({"cmd": CMD_BREW_END})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    events = _completed_events(hass)
    assert len(events) == 1
    assert events[0]["outcome"] == "confirmed"


async def test_cancelled_brew_fires_no_completion():
    """A cancelled brew consumed nothing, so nothing may be told it finished."""
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        entry.tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await entry.tasks[0]

    assert _completed_events(hass) == []


def _fired(hass, name):
    """Every payload fired on the bus under `name`."""
    return [
        c.args[1]
        for c in hass.bus.async_fire.call_args_list
        if c.args and c.args[0] == name
    ]


async def test_a_presumed_completion_is_not_also_called_a_timeout():
    """`xbloom_brew_timeout` means the ending was never heard. BREW_END is one.

    A consumer waiting on the brew takes a timeout as final — it is one — so
    firing it alongside a presumed completion tells the caller the brew timed
    out and then never reaches them with the completion that follows. That is
    precisely the brew this contract exists for: the coffee was made and
    RD_ENJOY was lost.
    """
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 0.05):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        await _FakeBle.instances[0].on_event({"cmd": CMD_BREW_END})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    assert _completed_events(hass)[0]["outcome"] == "presumed"
    assert _fired(hass, "xbloom_brew_timeout") == []


async def test_an_ending_nobody_heard_is_still_a_timeout():
    """No BREW_END and no ENJOY: the 600 s safety net, and genuinely unknown."""
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch.object(_FakeBle, "wait_for_completion", AsyncMock(return_value=False)):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    assert _completed_events(hass) == []
    assert len(_fired(hass, "xbloom_brew_timeout")) == 1


# --- the window ends on evidence, not only on the clock ---------------------

CMD_MACHINE_ACTIVITY = 8023
ACTIVITY_HOME = 1
ACTIVITY_BREWING = 34


async def test_going_home_after_brew_end_completes_without_waiting_out_the_window():
    """When ENJOY is lost the machine returns to its home screen.

    That is positive evidence no ENJOY is coming, so the brew can be called
    complete then — rather than leaving the caller in silence for two minutes
    waiting for a frame that has already been overtaken.
    """
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 30.0):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)

        ble = _FakeBle.instances[0]
        await ble.on_event({"cmd": CMD_BREW_END})
        await ble.on_event({"cmd": CMD_MACHINE_ACTIVITY, "activity": ACTIVITY_HOME})

        # Finishes on the frame, not on the 30 s window.
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    events = _completed_events(hass)
    assert len(events) == 1
    assert events[0]["outcome"] == "presumed"
    assert _fired(hass, "xbloom_brew_timeout") == []


async def test_a_home_frame_before_the_brew_ends_decides_nothing():
    """Idle machines emit their home activity on connect, mid-brew they do not.

    Taking that as an ending would complete a brew that has not started pouring.
    """
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 0.05):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)

        ble = _FakeBle.instances[0]
        await ble.on_event({"cmd": CMD_MACHINE_ACTIVITY, "activity": ACTIVITY_HOME})
        await ble.on_event({"cmd": CMD_MACHINE_ACTIVITY, "activity": ACTIVITY_BREWING})
        await asyncio.sleep(0)
        assert not entry.tasks[0].done(), "a home frame before BREW_END ended the wait"

        await ble.on_event({"cmd": CMD_BREW_END})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    assert _completed_events(hass)[0]["outcome"] == "presumed"


# --- a fault that stops the machine stops the brew ---------------------------

_CMD_BY_STATUS = {status: cmd for cmd, (status, _event) in _spec.FAULTS.items()}
CMD_NO_BEANS = _CMD_BY_STATUS["no_beans"]
CMD_NO_WATER = _CMD_BY_STATUS["no_water"]


async def test_no_beans_ends_the_brew_rather_than_waiting_for_an_ending():
    """The machine gave up, and the brew task waited regardless."""
    _FakeBle.enjoy = False
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 30.0):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)

        await _FakeBle.instances[0].on_event({"cmd": CMD_NO_BEANS})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    failed = _fired(hass, "xbloom_brew_failed")
    assert len(failed) == 1
    assert failed[0]["reason"] == "no_beans"
    assert failed[0]["recipe_name"] == "Test Recipe One"
    assert _completed_events(hass) == [], "a brew that never ran did not complete"


async def test_a_water_fault_does_not_end_the_brew():
    """It reports low water mid-pour and carries on; two brews prove it."""
    hass = _make_hass()
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle), \
         patch("custom_components.xbloom.BREW_END_GRACE_S", 30.0):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        await _FakeBle.instances[0].on_event({"cmd": CMD_NO_WATER})
        await asyncio.wait_for(entry.tasks[0], timeout=2.0)

    assert _fired(hass, "xbloom_brew_failed") == []
    assert _completed_events(hass)[0]["outcome"] == "confirmed"
