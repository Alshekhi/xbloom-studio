"""Machine Control: a switch that refuses whatever would set the machine going.

Off, a command that starts, prepares or changes something on the machine is
refused before any link opens, whoever sends it. What only stops it, or only
reads and edits recipes, still runs: turning the switch off must never leave
a brew that cannot be stopped.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.ble_entities import send_live_frame
from custom_components.xbloom.switch import XBloomConnectSwitch, XBloomMachineControlSwitch

from .test_brew_completion_contract import (
    _Entry, _FakeBle, _make_hass, _setup_and_get_handlers,
)


@pytest.fixture(autouse=True)
def _reset():
    _FakeBle.instances = []
    _FakeBle.enjoy = True
    yield
    _FakeBle.enjoy = True


def _machine_found():
    return patch("custom_components.xbloom._resolve_ble_device",
                 AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF")))


async def _handlers_with_control(on: bool):
    hass, entry = _make_hass(), _Entry()
    handlers = await _setup_and_get_handlers(hass, entry)
    entry.runtime_data.machine_control = on
    return handlers, entry


def _refused(error: Exception) -> bool:
    return getattr(error, "translation_key", None) == "machine_control_off"


@pytest.mark.parametrize("service", [
    "start_brew", "prepare_brew", "ble_connect", "tare", "back_to_home",
    "brew_resume", "grind", "brew_standalone", "set_mode", "set_water_source",
    "set_temp_unit", "set_weight_unit", "write_slot",
])
async def test_off_refuses_every_command_that_sets_the_machine_going(service):
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers, _ = await _handlers_with_control(False)
        with pytest.raises(HomeAssistantError) as raised:
            await handlers[service](MagicMock(data={}))

    assert _refused(raised.value)
    assert _FakeBle.instances == [], "refused before any link opened"


@pytest.mark.parametrize("service", [
    "stop_brew", "brew_pause", "cancel_preparation", "ble_disconnect", "refresh_status",
    "list_recipes",
])
async def test_off_still_lets_the_machine_be_stopped_and_recipes_be_read(service):
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers, _ = await _handlers_with_control(False)
        try:
            await handlers[service](MagicMock(data={}))
        except Exception as error:  # these may fail for want of a machine, not of control
            assert not _refused(error)


async def test_on_lets_a_command_through():
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers, _ = await _handlers_with_control(True)
        await handlers["tare"](MagicMock(data={}))

    assert len(_FakeBle.instances) == 1


def _switch(on_before: str | None):
    entry = MagicMock()
    entry.runtime_data.machine_control = True
    entity = XBloomMachineControlSwitch(entry)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    last = None if on_before is None else MagicMock(state=on_before)
    entity.async_get_last_state = AsyncMock(return_value=last)
    return entity, entry


async def test_switch_starts_on_and_keeps_its_state_across_restarts():
    entity, entry = _switch(None)
    with patch("homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass", AsyncMock()):
        await entity.async_added_to_hass()
    assert entity._attr_is_on is True

    entity, entry = _switch("off")
    with patch("homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass", AsyncMock()):
        await entity.async_added_to_hass()
    assert entity._attr_is_on is False
    assert entry.runtime_data.machine_control is False


async def test_switch_sets_what_the_commands_read():
    entity, entry = _switch(None)
    await entity.async_turn_off()
    assert entry.runtime_data.machine_control is False
    await entity.async_turn_on()
    assert entry.runtime_data.machine_control is True


async def test_off_refuses_a_new_connect_session():
    entry = MagicMock()
    entry.runtime_data.machine_control = False
    listener = AsyncMock()
    entity = XBloomConnectSwitch(listener, entry)
    entity.async_write_ha_state = MagicMock()

    with pytest.raises(HomeAssistantError) as raised:
        await entity.async_turn_on()

    assert _refused(raised.value)
    listener.start.assert_not_awaited()


async def test_off_refuses_a_command_over_a_held_session():
    entry = MagicMock()
    entry.runtime_data.machine_control = False
    entry.runtime_data.live_session_listener.is_running = True
    entry.runtime_data.live_session_listener.send_live = AsyncMock(return_value=True)

    with pytest.raises(HomeAssistantError) as raised:
        await send_live_frame(entry, b"\x00")

    assert _refused(raised.value)
    entry.runtime_data.live_session_listener.send_live.assert_not_awaited()


async def test_off_still_pauses_a_brew_over_a_held_connect_session():
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _FakeBle):
        handlers, entry = await _handlers_with_control(False)
        session = MagicMock(is_running=True, send_live=AsyncMock(return_value=True))
        entry.runtime_data.live_session_listener = session
        await handlers["brew_pause"](MagicMock(data={}))
        with pytest.raises(HomeAssistantError) as raised:
            await handlers["tare"](MagicMock(data={}))
    session.send_live.assert_awaited_once()
    assert _refused(raised.value), "a command that sets the machine going is still refused"
