"""`brew_done` must also fire when the completion contract says so.

The event entity already synthesises aggregate events — `brew_started` on the
first pour, `brew_done` on RD_ENJOY — on top of the granular per-frame ones. It
is an aggregation layer, not a raw frame mirror, so "the brew finished" belongs
in it even when the machine never said ENJOY.

Doing it here rather than in the blueprint keeps announcements working for a
brew started **at the machine**, which runs no HA brew task and so fires no
`xbloom_brew_completed` at all.

The latch matters: a confirmed completion follows an ENJOY that already fired
`brew_done`, and announcing the same coffee twice is worse than not at all.
"""
import contextlib
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom.ble_entities import (
    XBloomBrewEventBleEntity,
    signal_brew_lifecycle,
    signal_event,
)

CMD_ENJOY = 40512


@contextlib.asynccontextmanager
async def _entity():
    """Build the entity and hand back the handlers it registered.

    The dispatcher and bus handlers are closures inside `async_added_to_hass`,
    so we capture them at registration rather than adding test-only hooks to
    production code.
    """
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

    eid = entry.entry_id
    yield ent, bus, sig[signal_event(eid)], sig[signal_brew_lifecycle(eid)]


def _fired(entity):
    return [c.args[0] for c in entity._trigger_event.call_args_list]


@pytest.mark.asyncio
async def test_presumed_completion_fires_brew_done():
    async with _entity() as (ent, bus, _on_event, _on_lifecycle):
        bus["xbloom_brew_completed"](
            MagicMock(data={"outcome": "presumed", "recipe_name": "Misty Valley"})
        )
        assert "brew_done" in _fired(ent)


@pytest.mark.asyncio
async def test_brew_done_carries_the_recipe_name():
    async with _entity() as (ent, bus, _on_event, _on_lifecycle):
        bus["xbloom_brew_completed"](
            MagicMock(data={"outcome": "presumed", "recipe_name": "Misty Valley"})
        )
        payload = ent._trigger_event.call_args_list[-1].args[1]
        assert payload["recipe_name"] == "Misty Valley"


@pytest.mark.asyncio
async def test_enjoy_then_confirmed_completion_fires_brew_done_once():
    """ENJOY already announced it. The confirmed completion must stay quiet."""
    async with _entity() as (ent, bus, on_event, _on_lifecycle):
        on_event({"cmd": CMD_ENJOY})
        bus["xbloom_brew_completed"](
            MagicMock(data={"outcome": "confirmed", "recipe_name": "Misty Valley"})
        )
        assert _fired(ent).count("brew_done") == 1


@pytest.mark.asyncio
async def test_latch_resets_so_the_next_brew_announces():
    async with _entity() as (ent, bus, _on_event, on_lifecycle):
        bus["xbloom_brew_completed"](MagicMock(data={"outcome": "presumed"}))
        on_lifecycle("started")          # the next brew begins
        bus["xbloom_brew_completed"](MagicMock(data={"outcome": "presumed"}))
        assert _fired(ent).count("brew_done") == 2


@pytest.mark.asyncio
async def test_latch_resets_from_machine_frames_not_only_the_ha_task():
    """A brew started at the machine runs no HA brew task.

    Its lifecycle signal never fires, so a latch that only reset there would
    let the first machine-started brew announce and silence every one after it.
    The machine's own grinder frame must reset it.
    """
    CMD_GRINDER_START = 40502
    async with _entity() as (ent, bus, on_event, _on_lifecycle):
        bus["xbloom_brew_completed"](MagicMock(data={"outcome": "presumed"}))
        on_event({"cmd": CMD_GRINDER_START})     # next brew, started at the machine
        bus["xbloom_brew_completed"](MagicMock(data={"outcome": "presumed"}))

        assert _fired(ent).count("brew_done") == 2
