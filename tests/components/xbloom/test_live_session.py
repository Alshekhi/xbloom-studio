"""Tests for live_session.py — the held BLE session behind switch.xbloom_studio_connect.

This is the accessibility core: every event fired here becomes speech via the
announce blueprint, so the failure modes are *noise* (announcing a weight while
the user is grinding, repeating the same knob value three times) and *silence*
(dropping a Fahrenheit machine's temperature because it fell outside the
Celsius range).

`session_event_filter` is a pure function, which makes the wire-decode half of
this directly testable; the dispatch half is driven through a fake hass bus.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.xbloom import live_session as ls
from custom_components.xbloom.live_session import (
    LiveSessionListener,
    _ScaleDebouncer,
    _ble_size_to_ui,
    session_event_filter,
)
from custom_components.xbloom.vendor.xbloom import spec

NOTIFY_WEIGHT_2 = 20501
NOTIFY_GRIND_SIZE = 8105
NOTIFY_GRIND_SPEED = 8106
NOTIFY_BREW_PATTERN = 8107
NOTIFY_BREW_TEMP = 8108
NOTIFY_BREW_RATIO = 8109
NOTIFY_PODS = 40501
NOTIFY_TARE = 9007
CMD_ACTIVITY = 8023


# --------------------------------------------------------------------------- #
# Grind size wire → UI                                                        #
# --------------------------------------------------------------------------- #
def test_ble_grind_size_offset() -> None:
    """Per brAzzi64's PROTOCOL.md: UI = max(1, BLE − 30)."""
    assert _ble_size_to_ui(31) == 1
    assert _ble_size_to_ui(80) == 50
    assert _ble_size_to_ui(110) == 80


def test_ble_grind_size_never_goes_below_one() -> None:
    assert _ble_size_to_ui(0) == 1


# --------------------------------------------------------------------------- #
# session_event_filter — decode                                               #
# --------------------------------------------------------------------------- #
def test_weight_is_decoded() -> None:
    got = session_event_filter({"cmd": NOTIFY_WEIGHT_2, "weight_g": 18.4})
    assert got == {"kind": "weight", "weight_g": 18.4}


def test_grind_size_is_converted_to_ui_units() -> None:
    got = session_event_filter({"cmd": NOTIFY_GRIND_SIZE, "grind_size": 80})
    assert got == {"kind": "grinder", "parameter": "size", "value": 50}


@pytest.mark.parametrize("raw", [30, 111, 0, 255])
def test_out_of_range_grind_size_is_dropped(raw: int) -> None:
    """A garbled frame must stay silent rather than announce a bogus size."""
    assert session_event_filter({"cmd": NOTIFY_GRIND_SIZE, "grind_size": raw}) is None


def test_grind_speed_is_decoded() -> None:
    got = session_event_filter({"cmd": NOTIFY_GRIND_SPEED, "grind_speed": 90})
    assert got == {"kind": "grinder", "parameter": "speed", "value": 90}


@pytest.mark.parametrize("rpm", [59, 121])
def test_out_of_range_grind_speed_is_dropped(rpm: int) -> None:
    assert session_event_filter({"cmd": NOTIFY_GRIND_SPEED, "grind_speed": rpm}) is None


def test_pattern_carries_a_spoken_name() -> None:
    got = session_event_filter({"cmd": NOTIFY_BREW_PATTERN, "pattern": 2})
    assert got["setting"] == "pattern"
    assert got["value_name"] == "spiral"


def test_unknown_pattern_byte_is_dropped() -> None:
    assert session_event_filter({"cmd": NOTIFY_BREW_PATTERN, "pattern": 9}) is None


def test_ratio_is_decoded() -> None:
    got = session_event_filter({"cmd": NOTIFY_BREW_RATIO, "brew_ratio": 16.0})
    assert got == {"kind": "brewer", "setting": "ratio", "value": 16.0}


@pytest.mark.parametrize("ratio", [0.5, 30.5])
def test_out_of_range_ratio_is_dropped(ratio: float) -> None:
    assert session_event_filter({"cmd": NOTIFY_BREW_RATIO, "brew_ratio": ratio}) is None


def test_recipe_card_scan_is_decoded() -> None:
    got = session_event_filter({"cmd": NOTIFY_PODS, "pod_id": "ABC123"})
    assert got == {"kind": "recipe_card", "pod_id": "ABC123"}


def test_recipe_card_without_an_id_is_dropped() -> None:
    assert session_event_filter({"cmd": NOTIFY_PODS, "pod_id": ""}) is None


def test_tare_is_decoded() -> None:
    assert session_event_filter({"cmd": NOTIFY_TARE}) == {"kind": "tare"}


def test_unknown_command_is_dropped() -> None:
    assert session_event_filter({"cmd": 1234, "whatever": 1}) is None


# --------------------------------------------------------------------------- #
# Temperature — the knob's two unit domains                                   #
# --------------------------------------------------------------------------- #
def test_celsius_knob_value_passes_through() -> None:
    got = session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 93})
    assert got == {"kind": "brewer", "setting": "temperature", "value": 93}


def test_fahrenheit_knob_value_is_normalised_not_dropped() -> None:
    """A machine set to °F reports 103-204; dropping it would silence the knob."""
    got = session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 200})
    assert got["value"] == 93


def test_temperature_ends_are_named_for_speech() -> None:
    low = session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 39})
    high = session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 96})
    assert low["value_name"] == "RT"
    assert high["value_name"] == "BP"


def test_mid_range_temperature_has_no_sentinel_name() -> None:
    got = session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 93})
    assert "value_name" not in got


def test_temperature_outside_both_domains_is_dropped() -> None:
    assert session_event_filter({"cmd": NOTIFY_BREW_TEMP, "temperature_c": 5}) is None


def test_temperature_domain_comes_from_the_shared_spec() -> None:
    assert (ls.TEMP_C_MIN, ls.TEMP_C_MAX) == (
        spec.BREW_TEMP_DISPLAY_MIN, spec.BREW_TEMP_DISPLAY_MAX,
    )


# --------------------------------------------------------------------------- #
# Module detection                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("activity", "module"),
    [(1, "home"), (2, "grinder"), (3, "brewer"), (4, "scale"), (5, "scale"), (65, "auto")],
)
def test_activity_codes_map_to_modules(activity: int, module: str) -> None:
    got = session_event_filter({"cmd": CMD_ACTIVITY, "activity": activity})
    assert got == {"kind": "module", "module": module}


def test_unknown_activity_code_is_dropped() -> None:
    assert session_event_filter({"cmd": CMD_ACTIVITY, "activity": 99}) is None


def test_physical_knob_entry_codes_are_decoded() -> None:
    """9000/9002 fire only on a physical press; 8023 covers commanded entry."""
    assert session_event_filter({"cmd": 9000})["module"] == "grinder"
    assert session_event_filter({"cmd": 9002})["module"] == "scale"


def test_8022_echo_is_not_treated_as_home() -> None:
    """8022 is state-gated and rejected from a module screen — decoding its echo
    announced a 'home' that never happened. Regression guard for that fix."""
    assert session_event_filter({"cmd": 8022}) is None


def test_every_decoded_module_is_a_known_spec_module() -> None:
    for activity in (1, 2, 3, 4, 5, 65):
        got = session_event_filter({"cmd": CMD_ACTIVITY, "activity": activity})
        assert got["module"] in spec.MODULES


# --------------------------------------------------------------------------- #
# Scale debouncer                                                             #
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(ls.time, "monotonic", c)
    return c


@pytest.mark.asyncio
async def test_unsettled_weight_does_not_fire(clock) -> None:
    fired: list[float] = []
    d = _ScaleDebouncer(lambda w: _append(fired, w))
    await d.feed(10.0)
    clock.advance(0.5)
    await d.feed(20.0)   # jumped — restarts the settle window
    clock.advance(0.5)
    assert fired == []


@pytest.mark.asyncio
async def test_settled_weight_fires_once(clock) -> None:
    fired: list[float] = []
    d = _ScaleDebouncer(lambda w: _append(fired, w))
    await d.feed(18.0)
    clock.advance(3.0)
    await d.feed(18.0)
    assert fired == [18.0]


@pytest.mark.asyncio
async def test_same_settled_weight_is_not_re_reported(clock) -> None:
    """The load cell streams continuously — one announcement per settle."""
    fired: list[float] = []
    d = _ScaleDebouncer(lambda w: _append(fired, w))
    await d.feed(18.0)
    clock.advance(3.0)
    await d.feed(18.0)
    clock.advance(3.0)
    await d.feed(18.0)
    assert fired == [18.0]


@pytest.mark.asyncio
async def test_reset_allows_the_same_weight_to_fire_again(clock) -> None:
    """Re-entering the scale should re-announce, not stay silent."""
    fired: list[float] = []
    d = _ScaleDebouncer(lambda w: _append(fired, w))
    await d.feed(18.0)
    clock.advance(3.0)
    await d.feed(18.0)
    d.reset()
    await d.feed(18.0)
    clock.advance(3.0)
    await d.feed(18.0)
    assert fired == [18.0, 18.0]


async def _append(sink: list, value: float) -> None:
    sink.append(value)


# --------------------------------------------------------------------------- #
# Dispatch — what actually reaches the HA bus                                 #
# --------------------------------------------------------------------------- #
def _listener(clock=None) -> LiveSessionListener:
    hass = MagicMock()
    hass.bus.async_fire = MagicMock()
    return LiveSessionListener(hass, ble_device_resolver=MagicMock(), entry_id="e1")


def _fired(listener) -> list[tuple[str, dict]]:
    return [(c.args[0], c.args[1] if len(c.args) > 1 else {})
            for c in listener.hass.bus.async_fire.call_args_list]


@pytest.mark.asyncio
async def test_weight_is_suppressed_outside_the_scale_module(clock) -> None:
    """The load cell streams on every screen; announcing it while grinding is noise."""
    listener = _listener()
    await listener._dispatch({"kind": "module", "module": "grinder"})
    for _ in range(3):
        clock.advance(3.0)
        await listener._dispatch({"kind": "weight", "weight_g": 18.0})
    assert not any(ev == "xbloom_scale_weight_stable" for ev, _ in _fired(listener))


@pytest.mark.asyncio
async def test_weight_is_announced_on_the_scale_module(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "module", "module": "scale"})
    await listener._dispatch({"kind": "weight", "weight_g": 18.0})
    clock.advance(3.0)
    await listener._dispatch({"kind": "weight", "weight_g": 18.0})
    assert ("xbloom_scale_weight_stable", {"weight_g": 18.0, "unit": "g"}) in _fired(listener)


@pytest.mark.asyncio
async def test_repeated_module_entry_fires_once(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "module", "module": "grinder"})
    await listener._dispatch({"kind": "module", "module": "grinder"})
    entered = [ev for ev, _ in _fired(listener) if ev == "xbloom_module_entered"]
    assert len(entered) == 1


@pytest.mark.asyncio
async def test_grinder_knob_repeat_is_suppressed(clock) -> None:
    """The machine echoes some knob changes; announcing twice is jarring."""
    listener = _listener()
    await listener._dispatch({"kind": "grinder", "parameter": "size", "value": 50})
    await listener._dispatch({"kind": "grinder", "parameter": "size", "value": 50})
    changed = [ev for ev, _ in _fired(listener) if ev == "xbloom_grinder_knob_changed"]
    assert len(changed) == 1


@pytest.mark.asyncio
async def test_grinder_knob_repeat_fires_again_after_the_window(clock) -> None:
    """Deliberately returning to the same value later IS a real change."""
    listener = _listener()
    await listener._dispatch({"kind": "grinder", "parameter": "size", "value": 50})
    clock.advance(1.0)
    await listener._dispatch({"kind": "grinder", "parameter": "size", "value": 50})
    changed = [ev for ev, _ in _fired(listener) if ev == "xbloom_grinder_knob_changed"]
    assert len(changed) == 2


@pytest.mark.asyncio
async def test_grinder_size_and_speed_dedup_independently(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "grinder", "parameter": "size", "value": 50})
    await listener._dispatch({"kind": "grinder", "parameter": "speed", "value": 50})
    changed = [ev for ev, _ in _fired(listener) if ev == "xbloom_grinder_knob_changed"]
    assert len(changed) == 2


@pytest.mark.asyncio
async def test_brewer_event_keeps_the_spoken_name(clock) -> None:
    listener = _listener()
    await listener._dispatch(
        {"kind": "brewer", "setting": "pattern", "value": 2, "value_name": "spiral"}
    )
    payload = dict(_fired(listener))["xbloom_brewer_setting_changed"]
    assert payload["value_name"] == "spiral"


@pytest.mark.asyncio
async def test_brewer_ratio_stays_a_float(clock) -> None:
    """Ratio is 1:15.5 — rounding it to an int would misstate the recipe."""
    listener = _listener()
    await listener._dispatch({"kind": "brewer", "setting": "ratio", "value": 15.5})
    payload = dict(_fired(listener))["xbloom_brewer_setting_changed"]
    assert payload["value"] == 15.5


@pytest.mark.asyncio
async def test_duplicate_tare_frame_is_collapsed(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "tare"})
    await listener._dispatch({"kind": "tare"})
    tares = [ev for ev, _ in _fired(listener) if ev == "xbloom_scale_tared"]
    assert len(tares) == 1


@pytest.mark.asyncio
async def test_second_real_tare_press_fires(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "tare"})
    clock.advance(2.0)
    await listener._dispatch({"kind": "tare"})
    tares = [ev for ev, _ in _fired(listener) if ev == "xbloom_scale_tared"]
    assert len(tares) == 2


@pytest.mark.asyncio
async def test_recipe_card_scan_reaches_the_bus(clock) -> None:
    listener = _listener()
    await listener._dispatch({"kind": "recipe_card", "pod_id": "ABC123"})
    assert ("xbloom_recipe_card_scanned", {"pod_id": "ABC123"}) in _fired(listener)


# --------------------------------------------------------------------------- #
# Lifecycle bridging                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "phase", ["connecting", "ready", "failed", "auto_stopped"],
)
def test_lifecycle_phases_map_to_connect_event_names(phase: str) -> None:
    """The blueprint and switch.py listen for these exact names."""
    listener = _listener()
    listener._fire_lifecycle(phase, {"reason": "x"})
    assert _fired(listener) == [(f"xbloom_connect_{phase}", {"reason": "x"})]


def test_listener_identifies_itself_as_connect() -> None:
    assert _listener().mode_name == "connect"


def test_background_task_uses_ha_helper_when_available() -> None:
    """HA's background-task spawn is the only one that delivers bleak notifies."""
    listener = _listener()
    coro = MagicMock()
    listener._make_background_task(coro, "n")
    listener.hass.async_create_background_task.assert_called_once_with(coro, name="n")
