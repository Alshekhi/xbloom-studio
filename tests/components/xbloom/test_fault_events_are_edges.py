"""A fault is announced when it starts, not for as long as it lasts.

The machine reports a fault the way a low-fuel light works: it keeps saying
"there is no water" while that stays true, rather than saying it once. Relaying
every one of those frames as an event made the announcement blueprint speak the
same dry tank three times — 2026-09-13 12:44:19, 12:45:30 and 12:45:31, while
`sensor.xbloom_studio_machine_status` recorded a single `ok → no_water`.

So the event entity fires a fault on the edge into it, and stays quiet while it
holds. The sensor beside it already works this way; this makes the two agree.

Water re-arms itself from the MachineInfo heartbeat (`water_enough`), which is
the same self-clearing signal the sensor uses. The rest re-arm when a new brew
starts, which is also when the sensor drops back to `ok`.
"""
import contextlib
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    CMD_BLOOM,
    CMD_GRINDER_START,
    XBloomBrewEventBleEntity,
    signal_brew_lifecycle,
    signal_event,
)
from xbloom import spec

_CMD_BY_STATUS = {status: cmd for cmd, (status, _event) in spec.FAULTS.items()}
CMD_NO_WATER = _CMD_BY_STATUS["no_water"]
CMD_NO_BEANS = _CMD_BY_STATUS["no_beans"]
EVENT_NO_WATER = spec.FAULTS[CMD_NO_WATER][1]
EVENT_NO_BEANS = spec.FAULTS[CMD_NO_BEANS][1]


@contextlib.asynccontextmanager
async def _entity():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    ent = XBloomBrewEventBleEntity(entry)

    bus: dict[str, callable] = {}
    sig: dict[str, callable] = {}

    hass = MagicMock()
    hass.bus.async_listen = lambda event_type, handler: (
        bus.__setitem__(event_type, handler), lambda: None
    )[1]
    ent.hass = hass
    ent.async_write_ha_state = MagicMock()
    ent.async_on_remove = MagicMock()
    ent._trigger_event = MagicMock()

    def _connect(_hass, signal, handler):
        sig[signal] = handler
        return lambda: None

    with patch("custom_components.xbloom.ble_entities.async_dispatcher_connect", _connect):
        await ent.async_added_to_hass()

    yield ent, sig[signal_event(entry.entry_id)], sig[signal_brew_lifecycle(entry.entry_id)]


def fired(entity, event_type=None):
    names = [c.args[0] for c in entity._trigger_event.call_args_list]
    return [n for n in names if n == event_type] if event_type else names


@pytest.mark.asyncio
async def test_a_fault_that_keeps_being_reported_is_announced_once():
    """The 2026-09-13 brew: one dry tank, three frames, three announcements."""
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        on_event({"cmd": CMD_NO_WATER})
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_the_edge_into_a_fault_is_still_announced():
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_water_re_arms_when_the_machine_reports_water_again():
    """Refill, run dry again, and the second tank is real news."""
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        on_event({"water_enough": 1})
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER, EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_a_heartbeat_still_reporting_no_water_does_not_re_arm():
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        on_event({"water_enough": 0})
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_a_new_brew_re_arms_every_fault():
    """The sensor drops to `ok` when a brew starts; the events follow it."""
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_BEANS})
        on_event({"cmd": CMD_GRINDER_START})
        on_event({"cmd": CMD_NO_BEANS})
        assert fired(ent, EVENT_NO_BEANS) == [EVENT_NO_BEANS, EVENT_NO_BEANS]


@pytest.mark.asyncio
async def test_one_fault_holding_does_not_silence_a_different_one():
    """Two conditions are two pieces of news, however long either lasts."""
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        on_event({"cmd": CMD_NO_BEANS})
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER]
        assert fired(ent, EVENT_NO_BEANS) == [EVENT_NO_BEANS]


@pytest.mark.asyncio
async def test_repeats_are_only_suppressed_for_faults():
    """Every pour is a real pour; only a held condition repeats itself."""
    async with _entity() as (ent, on_event, _lifecycle):
        on_event({"cmd": CMD_BLOOM, "pour_index": 0})
        on_event({"cmd": CMD_BLOOM, "pour_index": 1})
        assert fired(ent, "pour_started") == ["pour_started", "pour_started"]


@pytest.mark.asyncio
async def test_water_is_news_again_once_the_brew_that_reported_it_has_ended():
    """The sensor releases its water reading when the link goes; this follows it.

    Otherwise the pair disagrees in the worst direction: the sensor shows `ok`
    while the event entity still holds water latched, so a tank that is empty
    on the next connection is neither displayed nor announced.
    """
    async with _entity() as (ent, on_event, lifecycle):
        on_event({"cmd": CMD_NO_WATER})
        lifecycle("ended")
        on_event({"cmd": CMD_NO_WATER})
        assert fired(ent, EVENT_NO_WATER) == [EVENT_NO_WATER, EVENT_NO_WATER]


@pytest.mark.asyncio
async def test_a_bean_fault_stays_latched_across_the_end_of_a_brew():
    """Nothing re-reports it, so repeating it is repetition, not news."""
    async with _entity() as (ent, on_event, lifecycle):
        on_event({"cmd": CMD_NO_BEANS})
        lifecycle("ended")
        on_event({"cmd": CMD_NO_BEANS})
        assert fired(ent, EVENT_NO_BEANS) == [EVENT_NO_BEANS]
