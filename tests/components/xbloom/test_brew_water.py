"""A brew Home Assistant started follows its tank.

The brew task feeds the water tracker every frame and publishes what it
decides on `signal_water`; the finished and refused brews carry what they
know about the tank. Frames follow one measured 500 ml brew whose switch
tripped 112 ml in.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import signal_water
from xbloom import ble

from .test_brew_completion_contract import (
    _RECIPE,
    _Entry,
    _FakeBle,
    _make_hass,
    _setup_and_get_handlers,
)

LOW = {"cmd": 40522, "water_enough": 0}
POURS_500 = [{"volume_ml": 125, "temperature_c": 93}] * 4
# Home Assistant's loop clock during a test brew: frames move it on.
NOW = [1000.0]


def _frames(*frames):
    """A fake client that sends these (clock, frame) pairs while brewing."""

    class _Brewing(_FakeBle):
        async def brew(self, recipe):
            for clock, frame in frames:
                NOW[0] = clock
                await self.on_event(frame)

    return _Brewing


async def _brew(fake, *, water_source="tank"):
    hass, entry = _make_hass(), _Entry()
    NOW[0] = 1000.0
    hass.loop.time = lambda: NOW[0]
    plain_get = hass.states.get

    def _get_state(entity_id):
        if entity_id == "select.xbloom_studio_water_source":
            return MagicMock(state=water_source)
        return plain_get(entity_id)

    hass.states.get = _get_state
    fake.hass = hass
    sent = []

    def _send(_hass, signal, *payload):
        if signal == signal_water("test_entry"):
            sent.append(payload[0] if len(payload) == 1 else payload)

    with patch.dict(_RECIPE, {"pours": POURS_500}), \
         patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("homeassistant.helpers.dispatcher.async_dispatcher_send", _send), \
         patch("xbloom.ble.XBloomBleClient", fake), \
         patch("custom_components.xbloom.ble_entities.water_source_entity",
               lambda _hass: "select.xbloom_studio_water_source"):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]
    return hass, sent


def _bus(hass, name):
    return [c.args[1] for c in hass.bus.async_fire.call_args_list
            if c.args and c.args[0] == name]


@pytest.fixture(autouse=True)
def _reset():
    _FakeBle.enjoy = True
    yield
    _FakeBle.enjoy = True


async def test_a_trip_that_will_not_finish_is_signalled():
    _, sent = await _brew(_frames(
        (1000, {"cmd": 40510, "pour_index": 0}),
        (1001, {"cmd": 40523, "water_ml": 112.4}),
        (1002, LOW),
    ))
    lows = [p for p in sent if p[0] == "water_low"]
    assert len(lows) == 1
    assert lows[0][1]["water_short_ml"] == 118
    assert lows[0][1]["enough_to_finish"] is False


async def test_completion_carries_the_tank():
    hass, _ = await _brew(_frames(
        (1000, {"cmd": 40510, "pour_index": 0}),
        (1001, {"cmd": 40523, "water_ml": 300}),
        (1002, LOW),
        (1003, {"cmd": 40523, "water_ml": 500}),
    ))
    done = _bus(hass, "xbloom_brew_completed")
    assert done[0]["tank_low"] is True
    assert done[0]["water_left_ml"] == 70


async def test_a_full_tank_adds_nothing_to_the_completion():
    hass, _ = await _brew(_frames((1000, {"cmd": 40510, "pour_index": 0})))
    done = _bus(hass, "xbloom_brew_completed")[0]
    assert "tank_low" not in done and "water_left_ml" not in done


async def test_a_refused_start_names_the_water_needed():
    class _Refused(_FakeBle):
        async def brew(self, recipe):
            raise ble.CommandRefused("execute", "no_water")

    hass, _ = await _brew(_Refused)
    failed = _bus(hass, "xbloom_brew_failed")
    assert failed[0]["reason"] == "no_water"
    assert failed[0]["water_needed_ml"] == 500


async def test_tap_mode_follows_no_water():
    _, sent = await _brew(_frames(
        (1000, {"cmd": 40510, "pour_index": 0}),
        (1001, {"cmd": 40523, "water_ml": 112.4}),
        (1002, LOW),
    ), water_source="tap")
    assert sent == []


async def test_a_water_pause_does_not_time_out_the_brew():
    class _LongPause(_FakeBle):
        calls = 0

        async def brew(self, recipe):
            for frame in ({"cmd": 40510, "pour_index": 0},
                          {"cmd": 40523, "water_ml": 112.4}, LOW,
                          {"cmd": 40523, "water_ml": 394.9},
                          {"cmd": 8023, "activity": 12}):
                await self.on_event(frame)

        async def wait_for_completion(self, timeout=600.0):
            _LongPause.calls += 1
            if _LongPause.calls == 1:
                # The 600 s budget ran out, all of it waiting for water.
                NOW[0] = 1600.0
                return False
            await self.on_event({"cmd": 9011})
            return True

    hass, _ = await _brew(_LongPause)
    assert _LongPause.calls == 2
    assert _bus(hass, "xbloom_brew_completed")[0]["outcome"] == "confirmed"
    assert _bus(hass, "xbloom_brew_timeout") == []


async def test_the_brew_ending_clears_the_water_state():
    _, sent = await _brew(_frames(
        (1000, {"cmd": 40510, "pour_index": 0}),
        (1001, {"cmd": 40523, "water_ml": 300}),
        (1002, LOW),
    ))
    assert sent[-1] == (None, {}, None)


async def test_a_client_that_stops_listening_mid_pause_ends_the_wait():
    """The link drops while the brew waits for water: no spinning."""
    from custom_components.xbloom import _wait_for_enjoy

    class _Gone:
        calls = 0

        async def wait_for_completion(self, timeout=600.0):
            _Gone.calls += 1
            if _Gone.calls > 5:
                raise RuntimeError("the wait kept being extended")
            return False          # returned at once: the session is gone

    waited = iter(range(1, 100))
    assert await _wait_for_enjoy(_Gone(), lambda: float(next(waited))) is False
    assert _Gone.calls == 1


async def test_a_tracker_failure_does_not_cost_the_brew_its_pours():
    class _Swallowing(_FakeBle):
        async def brew(self, recipe):
            for frame in ({"cmd": 40510, "pour_index": 0},):
                try:          # the real client drops a callback's exception
                    await self.on_event(frame)
                except Exception:  # noqa: BLE001
                    pass

    with patch("custom_components.xbloom.water.WaterTracker.feed",
               side_effect=RuntimeError("tracker")):
        hass, _ = await _brew(_Swallowing)
    assert _bus(hass, "xbloom_brew_completed")[0]["first_pour_at"] is not None


async def test_a_wait_for_water_is_not_endless():
    """A brew left on the water screen gives up after WATER_WAIT_MAX_S."""
    from custom_components.xbloom import WATER_WAIT_MAX_S, _wait_for_enjoy

    clock = [0.0]

    class _Waiting:
        calls = 0

        async def wait_for_completion(self, timeout=600.0):
            _Waiting.calls += 1
            if _Waiting.calls > 50:
                raise RuntimeError("never gave up")
            clock[0] += timeout   # the whole budget, all of it paused
            return False

    paused = lambda: clock[0]   # noqa: E731 — paused from the start
    assert await _wait_for_enjoy(_Waiting(), paused, lambda: clock[0]) is False
    assert clock[0] == 600.0 + WATER_WAIT_MAX_S
