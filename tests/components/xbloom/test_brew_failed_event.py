"""A brew that cannot run says so — `xbloom_brew_failed`.

Every way start_brew could fail used to end in a log line and nothing else:
no event, no state change a consumer could read. A caller waiting to hear how
its brew went heard nothing, and could not tell "failed" from "still going".

The event carries a `reason` code and no prose — wording is the consumer's
business, in its own language.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from xbloom import ble

from .test_brew_completion_contract import (
    _Entry,
    _FakeBle,
    _make_hass,
    _setup_and_get_handlers,
)


def _failed(hass):
    return [
        c.args[1]
        for c in hass.bus.async_fire.call_args_list
        if c.args and c.args[0] == "xbloom_brew_failed"
    ]


def _fired(hass):
    return [c.args[0] for c in hass.bus.async_fire.call_args_list if c.args]


async def test_a_machine_bluetooth_cannot_see_fails_the_brew():
    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device", AsyncMock(return_value=None)), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    failed = _failed(hass)
    assert len(failed) == 1
    assert failed[0]["reason"] == "machine_not_found"
    assert failed[0]["recipe_name"] == "Test Recipe One"
    assert failed[0]["run_id"]
    # And no start: nothing reached the machine, so nothing began. The event
    # announcements key on used to fire at dispatch, which had the house say
    # "started preparing X" for brews the machine then refused outright.
    assert "xbloom_brew_started" not in _fired(hass)


async def test_a_bluetooth_error_mid_brew_fails_the_brew_with_the_error():
    class _Broken(_FakeBle):
        async def brew(self, recipe):
            raise RuntimeError("GATT write failed")

    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Broken):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    failed = _failed(hass)
    assert len(failed) == 1
    assert failed[0]["reason"] == "bluetooth_error"
    assert "GATT write failed" in failed[0]["error"]
    assert "xbloom_brew_completed" not in _fired(hass)


async def _brew_with(fake):
    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", fake):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]
    return hass


async def test_a_step_the_machine_refuses_fails_the_brew_with_its_reason():
    # After a power cut the machine refuses the first command it is sent; the
    # brew must stop there, not execute on top of a recipe it never took.
    class _Refused(_FakeBle):
        async def brew(self, recipe):
            raise ble.CommandRefused("bypass+dose", "machine_busy")

    hass = await _brew_with(_Refused)
    failed = _failed(hass)
    assert len(failed) == 1
    assert failed[0]["reason"] == "machine_busy"
    assert failed[0]["step"] == "bypass+dose"
    assert "xbloom_brew_completed" not in _fired(hass)


async def test_a_step_the_machine_never_answers_fails_the_brew():
    class _Silent(_FakeBle):
        async def brew(self, recipe):
            raise ble.CommandUnanswered("recipe")

    failed = _failed(await _brew_with(_Silent))
    assert [(f["reason"], f["step"]) for f in failed] == [("no_reply", "recipe")]


async def test_a_recipe_that_cannot_be_found_fails_before_any_dispatch():
    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device", AsyncMock()), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={"recipe_name": "No such recipe"}))

    failed = _failed(hass)
    assert [f["reason"] for f in failed] == ["recipe_not_found"]
    assert "xbloom_brew_started" not in _fired(hass)
    assert entry.tasks == []


async def test_no_bluetooth_name_fails_before_any_dispatch():
    hass, entry = _make_hass(), _Entry()
    entry.data = {}
    with patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))

    assert [f["reason"] for f in _failed(hass)] == ["not_configured"]
    assert entry.tasks == []


async def test_a_healthy_brew_fires_no_failure():
    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    assert _failed(hass) == []


async def test_a_brew_the_machine_refuses_never_says_it_started():
    # 2026-09-20, after a power cut: the machine refused every command of three
    # brews, and each was announced as started while nothing was ground.
    class _Refusing(_FakeBle):
        async def brew(self, recipe):
            raise ble.CommandRefused("bypass+dose", "needs_calibration")

    hass, entry = _make_hass(), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Refusing):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    assert "xbloom_brew_started" not in _fired(hass)
    assert _failed(hass)[0]["reason"] == "needs_calibration"


async def test_an_accepted_brew_says_it_started_once_the_machine_has_taken_it():
    order = []

    class _Slow(_FakeBle):
        async def brew(self, recipe):
            order.append("frames accepted")
            await super().brew(recipe)

    hass, entry = _make_hass(), _Entry()
    hass.bus.async_fire.side_effect = lambda name, *a, **k: (
        order.append(name) if name == "xbloom_brew_started" else None
    )
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Slow):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]

    assert order[:2] == ["frames accepted", "xbloom_brew_started"]
    started = [c.args[1] for c in hass.bus.async_fire.call_args_list
               if c.args and c.args[0] == "xbloom_brew_started"]
    assert started[0]["recipe_name"] == "Test Recipe One"
