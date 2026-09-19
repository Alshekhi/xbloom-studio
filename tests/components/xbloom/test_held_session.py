"""Standalone actions while a Connect session holds the link.

The machine takes one connection at a time. A pour or grind that opened its own
link while Connect held one tore the session down, and the dashboard stayed on
the brewer screen long after the machine had gone home. So while a session is
held, those actions travel over it — still confirmed, so a refusal reaches the
caller — and a recipe brew, which needs its own link, ends the session first.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from xbloom import ble

from .test_brew_completion_contract import (
    _Entry, _FakeBle, _make_hass, _setup_and_get_handlers,
)
from .test_brew_standalone import _BREWER, _with_brewer_states


class _Session:
    """A held Connect session: records what it carries, can refuse."""

    def __init__(self, refuse: dict[str, str] | None = None):
        self.is_running = True
        self.sent: list[str] = []
        self.refuse = refuse or {}
        self.stopped = False

    async def send_confirmed(self, name, frame):
        self.sent.append(name)
        if name in self.refuse:
            raise ble.CommandRefused(name, self.refuse[name])
        return True

    async def stop(self):
        self.stopped = True
        self.is_running = False


class _NoSecondLink:
    """Records every attempt to open a link: the handlers catch and log errors,
    so raising alone would not fail a test."""

    opened: list = []

    def __init__(self, *_a, **_kw):
        _NoSecondLink.opened.append(True)
        raise AssertionError("opened a second Bluetooth link while Connect held one")


def _machine_in_range():
    """The machine found, and any second link recorded, for the whole call."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("custom_components.xbloom._resolve_ble_device",
                              AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))))
    stack.enter_context(patch("xbloom.ble.XBloomBleClient", _NoSecondLink))
    return stack


async def _handlers_with(session, hass=None, client=_NoSecondLink):
    _NoSecondLink.opened = []
    hass = hass or _with_brewer_states(_make_hass(), _BREWER)
    entry = _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", client):
        handlers = await _setup_and_get_handlers(hass, entry)
    entry.runtime_data.live_session_listener = session
    return hass, entry, handlers


async def test_a_standalone_pour_goes_over_the_held_session():
    session = _Session()
    _, _, handlers = await _handlers_with(session)
    with patch("xbloom.ble.XBloomBleClient", _NoSecondLink):
        await handlers["brew_standalone"](MagicMock(data={}))
    assert session.sent == ["brew_standalone"]
    assert _NoSecondLink.opened == []


async def test_a_pour_the_machine_refuses_is_an_error():
    session = _Session(refuse={"brew_standalone": "no_water"})
    _, _, handlers = await _handlers_with(session)
    with patch("xbloom.ble.XBloomBleClient", _NoSecondLink):
        with pytest.raises(HomeAssistantError) as err:
            await handlers["brew_standalone"](MagicMock(data={}))
    assert (err.value.translation_domain, err.value.translation_key) == ("xbloom", "refused_no_water")


async def test_a_pour_refused_without_a_session_is_an_error_too():
    class _Refusing:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def send_command(self, name, frame, **_kw):
            raise ble.CommandRefused(name, "machine_busy")

    _, _, handlers = await _handlers_with(None)
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Refusing):
        with pytest.raises(HomeAssistantError) as err:
            await handlers["brew_standalone"](MagicMock(data={}))
    assert err.value.translation_key == "refused_machine_busy"


async def test_a_grind_goes_over_the_held_session():
    session = _Session()
    _, _, handlers = await _handlers_with(session)
    with patch("xbloom.ble.XBloomBleClient", _NoSecondLink):
        await handlers["grind"](MagicMock(data={"size": 50, "speed": 80, "seconds": 0}))
    assert session.sent == ["grind_enter", "grind_start", "grind_stop"]
    assert _NoSecondLink.opened == []


async def test_a_grind_the_machine_refuses_is_an_error():
    session = _Session(refuse={"grind_start": "machine_busy"})
    _, _, handlers = await _handlers_with(session)
    with patch("xbloom.ble.XBloomBleClient", _NoSecondLink):
        with pytest.raises(HomeAssistantError) as err:
            await handlers["grind"](MagicMock(data={"size": 50, "speed": 80, "seconds": 0}))
    assert err.value.translation_key == "refused_machine_busy"
    assert "grind_stop" not in session.sent


async def test_a_recipe_brew_ends_the_held_session_before_it_connects():
    session = _Session()
    hass, entry, handlers = await _handlers_with(session, hass=_make_hass())
    order: list[str] = []

    class _Brew(_FakeBle):
        async def brew(self, recipe):
            order.append("brew")

    real_stop = session.stop

    async def _stop():
        order.append("session_stopped")
        await real_stop()
    session.stop = _stop

    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Brew):
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    assert order[:2] == ["session_stopped", "brew"]
    stopped = [c.args[1] for c in hass.bus.async_fire.call_args_list
               if c.args and c.args[0] == "xbloom_connect_stopped"]
    assert stopped == [{"reason": "brew"}]


def test_every_refusal_has_a_message_in_each_language():
    import json
    import pathlib

    from xbloom import spec

    root = pathlib.Path(__file__).parents[3] / "custom_components" / "xbloom"
    for name in ("strings.json", "translations/en.json", "translations/ar.json"):
        messages = json.loads((root / name).read_text())["exceptions"]
        for reason in set(spec.REPLY_REFUSALS.values()):
            assert messages[f"refused_{reason}"]["message"], (name, reason)


async def test_cancel_brew_goes_over_the_held_session():
    # Cancel Brew pressed with Connect on opened its own link, and the session
    # it tore down ended itself as a lost connection.
    session = _Session()
    _, _, handlers = await _handlers_with(session)
    with _machine_in_range():
        await handlers["stop_brew"](MagicMock(data={}))
    assert session.sent == ["stop_brew"]
    assert _NoSecondLink.opened == []


async def test_writing_a_slot_goes_over_the_held_session():
    session = _Session()
    hass, _, handlers = await _handlers_with(session, hass=_make_hass())
    with _machine_in_range():
        await handlers["write_slot"](MagicMock(data={"slot": "A", "recipe_name": "Test Recipe One"}))
    assert session.sent == ["write_slot"]
    assert _NoSecondLink.opened == []


async def test_a_status_refresh_leaves_a_held_session_alone():
    # The readings already stream over the session; a second link would only
    # tear it down.
    session = _Session()
    _, _, handlers = await _handlers_with(session)
    with _machine_in_range():
        await handlers["refresh_status"](MagicMock(data={}))
    assert _NoSecondLink.opened == []


async def test_the_link_probe_leaves_a_held_session_alone():
    session = _Session()
    _, _, handlers = await _handlers_with(session)
    with _machine_in_range():
        await handlers["ble_connect"](MagicMock(data={}))
    assert _NoSecondLink.opened == []
