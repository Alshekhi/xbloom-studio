"""Regression tests for the start_brew / stop_brew session guard.

Root cause these lock in (see __init__.py handle_start_brew): a brew that never
reaches RD_ENJOY left the background task blocked in wait_for_completion for the
full 600s timeout, holding both the duplicate-guard and the BLE link. Every new
Start Brew was then dropped as "already running", so the user could not restart
after low water, a machine fault, or a brew stopped from the app.

The guard is now time-boxed:
  * a repeat within BREW_DUP_WINDOW_S is swallowed (voice-agent retry),
  * a later press preempts the stale/wedged session and starts fresh,
  * stop_brew cancels the in-flight task (Cancel Brew as a hard reset).

homeassistant/voluptuous are stubbed by conftest.py; we drive the actual
handlers registered by async_setup_entry.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom import BREW_DUP_WINDOW_S, async_setup_entry
from custom_components.xbloom.const import CONF_BLE_NAME, CONF_PRODUCT_ID

_RECIPE = {
    "name": "Test Recipe",
    "pours": [{"volume_ml": 60, "temperature_c": 93}],
    "dose_g": 18,
    "grinder_size": 65,
    "grinder_size_enabled": 1,
    "cup_type": 2,
    "rpm": 60,
}


class _FakeBle:
    """Stand-in for XBloomBleClient. brew() is instant; wait_for_completion
    blocks until cancelled — simulating a brew that never reaches RD_ENJOY."""

    instances: list["_FakeBle"] = []

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
        # Block forever (until the task is cancelled). This is the "stuck
        # brew" the guard must let the user escape from.
        await asyncio.Event().wait()
        return True


class _Entry:
    """Minimal config entry with a real background-task factory that records
    every task it spawns, so the test can assert how many brews were started."""

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


def _make_hass(clock: dict):
    hass = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.bus.async_fire = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.loop.time = lambda: clock["t"]

    def _get_state(entity_id):
        state = MagicMock()
        if entity_id == "select.xbloom_studio_recipe":
            state.state = "Test Recipe"
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


@pytest.fixture(autouse=True)
def _reset_fake_ble():
    _FakeBle.instances = []
    yield
    _FakeBle.instances = []


async def test_duplicate_within_window_is_ignored():
    """A second start_brew within the retry window must not spawn a 2nd task."""
    clock = {"t": 1000.0}
    hass = _make_hass(clock)
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        start = handlers["start_brew"]

        await start(MagicMock(data={}))
        await asyncio.sleep(0)  # let the task reach wait_for_completion
        assert len(entry.tasks) == 1
        assert not entry.tasks[0].done()

        # Still within the window — duplicate is swallowed.
        clock["t"] += BREW_DUP_WINDOW_S / 2
        await start(MagicMock(data={}))
        await asyncio.sleep(0)
        assert len(entry.tasks) == 1

        entry.tasks[0].cancel()


async def test_later_press_preempts_stuck_session():
    """After the window, a new start_brew cancels the stuck task and starts fresh."""
    clock = {"t": 1000.0}
    hass = _make_hass(clock)
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        start = handlers["start_brew"]

        await start(MagicMock(data={}))
        await asyncio.sleep(0)
        first = entry.tasks[0]
        assert not first.done()

        # Past the window: this press must preempt the wedged session.
        clock["t"] += BREW_DUP_WINDOW_S + 5
        await start(MagicMock(data={}))
        await asyncio.sleep(0)

        assert len(entry.tasks) == 2
        assert first.cancelled()          # old brew was cancelled
        assert not entry.tasks[1].done()  # new brew is running

        entry.tasks[1].cancel()


async def test_stop_brew_cancels_active_task():
    """stop_brew must cancel the in-flight brew task (Cancel Brew = hard reset)."""
    clock = {"t": 1000.0}
    hass = _make_hass(clock)
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)

        await handlers["start_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        brew_task = entry.tasks[0]
        assert not brew_task.done()

        await handlers["stop_brew"](MagicMock(data={}))
        await asyncio.sleep(0)
        assert brew_task.cancelled()
