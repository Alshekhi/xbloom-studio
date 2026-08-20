"""Tests for reading_sensors.py — the machine-state sensors.

The design rule these sensors follow is *honesty over persistence*: a value the
integration can no longer verify must go blank rather than sit there looking
current. Two of them deliberately refuse RestoreSensor for exactly that reason
(a remembered module or pour number would be a lie after a restart), and the
module sensor clears itself the instant the Connect session ends.

So the tests here are mostly about clearing, not about setting.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom.reading_sensors import (
    EV_BREW_STARTED,
    EV_BREWER_SETTING,
    EV_GRINDER_KNOB,
    EV_MODULE_ENTERED,
    EV_RECIPE_CARD,
    READING_SENSORS,
    XBloomCurrentModuleSensor,
    XBloomCurrentPourSensor,
    XBloomGrindSizeSensor,
    XBloomLastRecipeCardSensor,
)
from custom_components.xbloom.vendor.xbloom import spec

CMD_BLOOM = 40510


def _make(cls):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entity = cls(entry)
    entity.hass = MagicMock()
    entity.hass.bus.async_listen = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


def _event(event_type: str, data: dict):
    ev = MagicMock()
    ev.event_type = event_type
    ev.data = data
    return ev


class _Wiring:
    """Handlers an entity registered during async_added_to_hass.

    `bus` is keyed by event type; `signals` is the ordered list of
    async_dispatcher_connect callbacks (BLE notifications, brew lifecycle).
    Scoped per entity — the module-level dispatcher mock accumulates across the
    whole session, so indexing it globally would hand back another test's
    handler.
    """

    def __init__(self, bus: dict, signals: list) -> None:
        self.bus = bus
        self.signals = signals

    def __getitem__(self, event_type: str):
        return self.bus[event_type]

    def __contains__(self, event_type: str) -> bool:
        return event_type in self.bus


async def _wire(entity) -> _Wiring:
    """Run async_added_to_hass with the dispatcher captured for this entity."""
    import custom_components.xbloom.reading_sensors as rs

    entity.async_get_last_sensor_data = _none
    signals: list = []

    def _connect(_hass, _signal, handler):
        signals.append(handler)
        return lambda: None

    with patch.object(rs, "async_dispatcher_connect", _connect):
        await entity.async_added_to_hass()

    bus = {c.args[0]: c.args[1] for c in entity.hass.bus.async_listen.call_args_list}
    return _Wiring(bus, signals)


async def _none():
    return None


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #
def test_every_reading_sensor_has_a_distinct_unique_id() -> None:
    ids = [c._attr_unique_id for c in READING_SENSORS]
    assert len(set(ids)) == len(ids)


def test_module_sensor_options_come_from_the_spec() -> None:
    assert XBloomCurrentModuleSensor._attr_options == list(spec.MODULES)


# --------------------------------------------------------------------------- #
# Grind size — event + heartbeat                                              #
# --------------------------------------------------------------------------- #
def test_grind_size_reads_a_grinder_knob_turn() -> None:
    entity = _make(XBloomGrindSizeSensor)
    assert entity._extract(EV_GRINDER_KNOB, {"parameter": "size", "value": 50}) == 50


def test_grind_size_ignores_a_speed_change() -> None:
    entity = _make(XBloomGrindSizeSensor)
    assert entity._extract(EV_GRINDER_KNOB, {"parameter": "speed", "value": 90}) is None


def test_grind_size_ignores_unrelated_brewer_settings() -> None:
    entity = _make(XBloomGrindSizeSensor)
    assert entity._extract(
        EV_BREWER_SETTING, {"setting": "temperature", "value": 93}
    ) is None


def test_grind_size_also_syncs_from_the_heartbeat() -> None:
    """So it is right on any connection, not only during a live knob turn."""
    assert XBloomGrindSizeSensor._signal_field == "grind_size_current"


@pytest.mark.asyncio
async def test_grind_size_updates_on_a_knob_event() -> None:
    entity = _make(XBloomGrindSizeSensor)
    handlers = await _wire(entity)
    handlers[EV_GRINDER_KNOB](_event(EV_GRINDER_KNOB, {"parameter": "size", "value": 42}))
    assert entity._attr_native_value == 42


@pytest.mark.asyncio
async def test_grind_size_ignores_a_repeat_of_the_same_value() -> None:
    entity = _make(XBloomGrindSizeSensor)
    handlers = await _wire(entity)
    ev = _event(EV_GRINDER_KNOB, {"parameter": "size", "value": 42})
    handlers[EV_GRINDER_KNOB](ev)
    entity.async_write_ha_state.reset_mock()
    handlers[EV_GRINDER_KNOB](ev)
    entity.async_write_ha_state.assert_not_called()


# --------------------------------------------------------------------------- #
# Current module — live only, never stale                                     #
# --------------------------------------------------------------------------- #
def test_module_sensor_starts_unknown() -> None:
    assert _make(XBloomCurrentModuleSensor)._attr_native_value is None


def test_module_sensor_does_not_restore_across_restarts() -> None:
    """A remembered module would claim knowledge the integration doesn't have."""
    from homeassistant.components.sensor import RestoreSensor

    assert not issubclass(XBloomCurrentModuleSensor, RestoreSensor)


@pytest.mark.asyncio
async def test_module_sensor_follows_module_entry() -> None:
    entity = _make(XBloomCurrentModuleSensor)
    handlers = await _wire(entity)
    handlers[EV_MODULE_ENTERED](_event(EV_MODULE_ENTERED, {"module": "grinder"}))
    assert entity._attr_native_value == "grinder"


@pytest.mark.asyncio
async def test_module_sensor_rejects_an_unknown_module() -> None:
    entity = _make(XBloomCurrentModuleSensor)
    handlers = await _wire(entity)
    handlers[EV_MODULE_ENTERED](_event(EV_MODULE_ENTERED, {"module": "teleporter"}))
    assert entity._attr_native_value is None


@pytest.mark.parametrize(
    "end_event",
    ["xbloom_connect_failed", "xbloom_connect_auto_stopped", "xbloom_connect_stopped"],
)
@pytest.mark.asyncio
async def test_module_sensor_clears_when_the_session_ends(end_event: str) -> None:
    """Idle timeout, failure, or manual disconnect — all mean 'we no longer know'."""
    entity = _make(XBloomCurrentModuleSensor)
    handlers = await _wire(entity)
    handlers[EV_MODULE_ENTERED](_event(EV_MODULE_ENTERED, {"module": "scale"}))
    handlers[end_event](_event(end_event, {}))
    assert entity._attr_native_value is None


@pytest.mark.asyncio
async def test_module_sensor_subscribes_to_every_session_end_event() -> None:
    entity = _make(XBloomCurrentModuleSensor)
    handlers = await _wire(entity)
    for ev in XBloomCurrentModuleSensor._SESSION_END_EVENTS:
        assert ev in handlers


@pytest.mark.asyncio
async def test_session_end_while_already_clear_does_not_rewrite_state() -> None:
    entity = _make(XBloomCurrentModuleSensor)
    handlers = await _wire(entity)
    entity.async_write_ha_state.reset_mock()
    handlers["xbloom_connect_stopped"](_event("xbloom_connect_stopped", {}))
    entity.async_write_ha_state.assert_not_called()


# --------------------------------------------------------------------------- #
# Current pour — live brew progress                                           #
# --------------------------------------------------------------------------- #
def test_pour_sensor_starts_at_zero() -> None:
    assert _make(XBloomCurrentPourSensor)._attr_native_value == 0


def test_pour_sensor_does_not_restore_across_restarts() -> None:
    """A leftover pour number would misreport a brew that isn't running."""
    from homeassistant.components.sensor import RestoreSensor

    assert not issubclass(XBloomCurrentPourSensor, RestoreSensor)


@pytest.mark.asyncio
async def test_pour_sensor_records_the_total_at_brew_start() -> None:
    entity = _make(XBloomCurrentPourSensor)
    handlers = await _wire(entity)
    handlers[EV_BREW_STARTED](_event(EV_BREW_STARTED, {"total_pours": 3}))
    assert entity.extra_state_attributes == {"total_pours": 3}
    assert entity._attr_native_value == 0


@pytest.mark.asyncio
async def test_pour_index_is_reported_one_based() -> None:
    """The wire index is 0-based; 'pour 0 of 3' would be nonsense to speak."""
    entity = _make(XBloomCurrentPourSensor)
    handlers = await _wire(entity)
    handlers.signals[0]({"cmd": CMD_BLOOM, "pour_index": 0})
    assert entity._attr_native_value == 1


@pytest.mark.asyncio
async def test_pour_sensor_ignores_other_notifications() -> None:
    entity = _make(XBloomCurrentPourSensor)
    handlers = await _wire(entity)
    handlers.signals[0]({"cmd": 12345, "pour_index": 2})
    assert entity._attr_native_value == 0


@pytest.mark.asyncio
async def test_pour_sensor_resets_when_the_brew_ends() -> None:
    entity = _make(XBloomCurrentPourSensor)
    handlers = await _wire(entity)
    handlers[EV_BREW_STARTED](_event(EV_BREW_STARTED, {"total_pours": 3}))
    handlers.signals[0]({"cmd": CMD_BLOOM, "pour_index": 1})
    assert entity._attr_native_value == 2
    handlers.signals[1]("ended")
    assert entity._attr_native_value == 0
    assert entity.extra_state_attributes == {"total_pours": None}


@pytest.mark.asyncio
async def test_pour_sensor_ignores_non_ended_lifecycle_phases() -> None:
    entity = _make(XBloomCurrentPourSensor)
    handlers = await _wire(entity)
    handlers[EV_BREW_STARTED](_event(EV_BREW_STARTED, {"total_pours": 3}))
    handlers.signals[0]({"cmd": CMD_BLOOM, "pour_index": 1})
    handlers.signals[1]("started")
    assert entity._attr_native_value == 2


# --------------------------------------------------------------------------- #
# Recipe card                                                                 #
# --------------------------------------------------------------------------- #
def test_recipe_card_sensor_listens_for_scans() -> None:
    assert EV_RECIPE_CARD in XBloomLastRecipeCardSensor._events


