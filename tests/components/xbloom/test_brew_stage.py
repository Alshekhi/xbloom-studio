"""Brew Stage: what a brew is doing between Brew Status's coarse phases.

Brew Status says `brewing` from the first pour to the end. Brew Stage splits
that into pouring, waiting after a pour, and draining after the last one, and
counts down to the next pour when the recipe is known. The water figures below
follow a measured 4-pour brew: the water reading stopped at each pour's running
total (43, 128, 204, 272 ml against 42.5, 127.5, 204, 272), and the waits ran
the recipe's pause, plus the agitation step after the one pour that had it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.xbloom import brew_stage
from custom_components.xbloom.brew_stage import (
    AGITATE_S,
    XBloomBrewStageSensor,
    pour_plan,
)

CMD_BLOOM = 40510
CMD_BREW_END = 40511
NOTIFY_WATER_VOLUME = 40523

RECIPE = {
    "pours": [
        {"volume_ml": 42.5, "pause_s": 35, "agitate_after": 1},
        {"volume_ml": 85.0, "pause_s": 20, "agitate_after": 2},
        {"volume_ml": 76.5, "pause_s": 20, "agitate_after": 2},
        {"volume_ml": 68.0, "pause_s": 10, "agitate_after": 2},
    ]
}
NOW = datetime(2026, 11, 22, 3, 43, 4, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# The plan a recipe gives                                                     #
# --------------------------------------------------------------------------- #

def test_plan_gives_each_pours_running_water_total() -> None:
    assert [p["water_ml"] for p in pour_plan(RECIPE)] == [42.5, 127.5, 204.0, 272.0]


def test_plan_wait_is_the_pause_plus_agitation_when_it_follows_the_pour() -> None:
    assert [p["wait_s"] for p in pour_plan(RECIPE)] == [35 + AGITATE_S, 20, 20, 10]


def test_plan_wait_includes_the_agitation_before_the_next_pour() -> None:
    # Measured: the wait before a pour that agitates first ran its pause plus
    # the agitation, with no frame for it.
    recipe = {"pours": [
        {"volume_ml": 45, "pause_s": 15, "agitate_before": 1},
        {"volume_ml": 55, "pause_s": 15, "agitate_after": 1},
        {"volume_ml": 55, "pause_s": 10},
        {"volume_ml": 100, "pause_s": 10, "agitate_before": 1},
    ]}
    # Pour 1's own agitation comes before it, ahead of any wait.
    assert [p["wait_s"] for p in pour_plan(recipe)] == [
        15, 15 + AGITATE_S, 10 + AGITATE_S, 10]


def test_plan_of_a_recipe_without_pours_is_empty() -> None:
    assert pour_plan({}) == []
    assert pour_plan({"pours": None}) == []


def test_plan_treats_a_missing_pause_as_no_wait() -> None:
    assert pour_plan({"pours": [{"volume_ml": 100}]}) == [{"water_ml": 100.0, "wait_s": 0}]


# --------------------------------------------------------------------------- #
# The sensor                                                                  #
# --------------------------------------------------------------------------- #

class _Stage:
    """A Brew Stage sensor with its handlers captured, driven by hand."""

    def __init__(self) -> None:
        entry = MagicMock()
        entry.entry_id = "test_entry"
        self.entity = XBloomBrewStageSensor(entry)
        self.entity.hass = MagicMock()
        self.entity.async_write_ha_state = MagicMock()
        self.entity.async_on_remove = MagicMock()
        self.now = NOW

    async def wire(self) -> "_Stage":
        signals: list = []

        def _connect(_hass, _signal, handler):
            signals.append(handler)
            return lambda: None

        with patch.object(brew_stage, "async_dispatcher_connect", _connect), \
             patch.object(brew_stage, "_entity_id", self._lookup):
            await self.entity.async_added_to_hass()
        self.signal = signals[0]
        calls = self.entity.hass.bus.async_listen.call_args_list
        self.bus = {c.args[0]: c.args[1] for c in calls if c.args[0] != "state_changed"}
        self.followers = [(c.kwargs["event_filter"], c.args[1])
                          for c in calls if c.args[0] == "state_changed"]
        return self

    # Entities are found when their changes arrive, not when Brew Stage is
    # added: on a new install the binary sensors are not registered yet then.
    registered = {"xbloom_brew_status": "sensor.brew_status",
                  "xbloom_brew_paused": "binary_sensor.paused"}

    def _lookup(self, _hass, _domain, unique_id):
        return self.registered.get(unique_id)

    def brew_started(self, recipe=RECIPE) -> None:
        ev = MagicMock()
        ev.data = {"recipe_name": "R", "total_pours": len(recipe["pours"]),
                   "pours": pour_plan(recipe)}
        self.bus["xbloom_brew_started"](ev)

    def status(self, value: str) -> None:
        self._state("sensor.brew_status", value)

    def paused(self, on: bool) -> None:
        self._state("binary_sensor.paused", "on" if on else "off")

    def _state(self, entity_id: str, value: str) -> None:
        ev = MagicMock()
        ev.data = {"entity_id": entity_id, "new_state": MagicMock(state=value)}
        with patch.object(brew_stage, "_entity_id", self._lookup):
            for accepts, handler in self.followers:
                if accepts(ev.data):
                    handler(ev)

    def frame(self, cmd: int, **data) -> None:
        with patch.object(brew_stage.dt_util, "utcnow", lambda: self.now):
            self.signal({"cmd": cmd, **data})

    def pour(self, index: int) -> None:
        self.frame(CMD_BLOOM, pour_index=index)

    def water(self, ml: float) -> None:
        self.frame(NOTIFY_WATER_VOLUME, water_ml=ml)

    @property
    def state(self):
        return self.entity._attr_native_value

    @property
    def attrs(self) -> dict:
        return self.entity.extra_state_attributes


@pytest.fixture
async def stage() -> _Stage:
    return await _Stage().wire()


def test_stage_starts_idle() -> None:
    assert _Stage().entity._attr_native_value == "idle"


def test_stage_offers_the_states_it_can_take() -> None:
    assert XBloomBrewStageSensor._attr_options == [
        "idle", "grinding", "pouring", "waiting", "draining", "done"]


async def test_an_entity_registered_after_brew_stage_is_still_followed() -> None:
    stage = _Stage()
    stage.registered = {}
    await stage.wire()
    stage.registered = {"xbloom_brew_status": "sensor.brew_status"}
    stage.status("grinding")
    assert stage.state == "grinding"


async def test_changes_of_other_entities_are_ignored(stage) -> None:
    stage._state("sensor.something_else", "grinding")
    assert stage.state == "idle"


async def test_grinding_and_done_follow_brew_status(stage) -> None:
    stage.status("grinding")
    assert stage.state == "grinding"
    stage.status("done")
    assert stage.state == "done"
    stage.status("idle")
    assert stage.state == "idle"


async def test_a_pour_is_pouring_with_its_number(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    assert stage.state == "pouring"
    assert stage.attrs["pour"] == 1
    assert stage.attrs["pours"] == 4


async def test_the_pour_reaching_its_water_is_waiting_with_the_next_pours_time(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.water(20)
    assert stage.state == "pouring"
    stage.water(43)
    assert stage.state == "waiting"
    assert stage.attrs["pour"] == 1
    assert stage.attrs["next_pour_at"] == (NOW + timedelta(seconds=35 + AGITATE_S)).isoformat()


async def test_a_reading_just_short_of_the_total_ends_the_pour(stage) -> None:
    # The reading is whole millilitres of a fractional target.
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.water(42)
    assert stage.state == "waiting"


async def test_the_next_pour_ends_the_wait(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.water(43)
    stage.pour(1)
    assert stage.state == "pouring"
    assert stage.attrs["pour"] == 2
    assert stage.attrs.get("next_pour_at") is None
    stage.water(100)
    assert stage.state == "pouring"
    stage.water(128)
    assert stage.state == "waiting"


async def test_the_wait_after_the_last_pour_has_no_next_pour(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    for index, ml in enumerate((43, 128, 204, 272)):
        stage.pour(index)
        stage.water(ml)
    assert stage.state == "waiting"
    assert stage.attrs["pour"] == 4
    assert stage.attrs.get("next_pour_at") is None


async def test_brew_end_is_draining(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(3)
    stage.water(272)
    stage.frame(CMD_BREW_END)
    assert stage.state == "draining"
    assert stage.attrs.get("next_pour_at") is None


async def test_without_a_recipe_a_pour_stays_pouring_until_brew_end(stage) -> None:
    # A brew started at the machine from its own slots: no plan, so no wait
    # can be told from a pour.
    stage.status("brewing")
    stage.pour(0)
    stage.water(500)
    assert stage.state == "pouring"
    assert stage.attrs.get("pours") is None
    stage.frame(CMD_BREW_END)
    assert stage.state == "draining"


async def test_frames_outside_a_brew_change_nothing(stage) -> None:
    # A standalone pour on the brewer screen leaves Brew Status idle.
    stage.pour(0)
    stage.frame(CMD_BREW_END)
    assert stage.state == "idle"


async def test_brewing_begins_as_pouring(stage) -> None:
    # Brew Status turns brewing on the first pour, which may land first.
    stage.brew_started()
    stage.status("brewing")
    assert stage.state == "pouring"


async def test_the_first_pour_heard_before_brewing_still_counts(stage) -> None:
    # Brew Status turns brewing on that same first-pour frame; its state
    # change reaches Brew Stage after the frame did.
    stage.brew_started()
    stage.status("grinding")
    stage.pour(0)
    stage.status("brewing")
    assert stage.state == "pouring"
    assert stage.attrs["pour"] == 1
    stage.water(43)
    assert stage.state == "waiting"


async def test_a_brew_over_forgets_its_plan(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.status("done")
    stage.status("idle")
    # The next brew is one started at the machine: nothing of the old plan.
    stage.status("brewing")
    stage.pour(0)
    stage.water(43)
    assert stage.state == "pouring"
    assert stage.attrs.get("pours") is None


async def test_a_pause_drops_the_countdown(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.water(43)
    stage.paused(True)
    assert stage.state == "waiting"
    assert stage.attrs.get("next_pour_at") is None


async def test_a_repeat_reading_writes_nothing(stage) -> None:
    stage.brew_started()
    stage.status("brewing")
    stage.pour(0)
    stage.water(43)
    writes = stage.entity.async_write_ha_state.call_count
    stage.water(43)
    assert stage.entity.async_write_ha_state.call_count == writes


# --------------------------------------------------------------------------- #
# Next Pour: the countdown as a timestamp the dashboard renders as it ticks   #
# --------------------------------------------------------------------------- #

async def _next_pour():
    from custom_components.xbloom.brew_stage import XBloomNextPourSensor
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entity = XBloomNextPourSensor(entry)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    lookup = lambda _hass, domain, uid: "sensor.brew_stage"
    with patch.object(brew_stage, "_entity_id", lookup):
        await entity.async_added_to_hass()
    call = entity.hass.bus.async_listen.call_args

    def stage(value: str, next_pour_at: str | None) -> None:
        ev = MagicMock()
        ev.data = {"entity_id": "sensor.brew_stage",
                   "new_state": MagicMock(state=value, attributes={"next_pour_at": next_pour_at})}
        with patch.object(brew_stage, "_entity_id", lookup):
            assert call.kwargs["event_filter"](ev.data)
        call.args[1](ev)

    return entity, stage


def test_next_pour_is_a_timestamp_and_starts_empty() -> None:
    from custom_components.xbloom.brew_stage import XBloomNextPourSensor
    entity = XBloomNextPourSensor(MagicMock())
    assert entity._attr_native_value is None
    assert XBloomNextPourSensor._attr_device_class == brew_stage.SensorDeviceClass.TIMESTAMP


async def test_next_pour_follows_the_stages_countdown() -> None:
    entity, stage = await _next_pour()
    at = (NOW + timedelta(seconds=15)).isoformat()
    stage("waiting", at)
    assert entity._attr_native_value == NOW + timedelta(seconds=15)
    stage("pouring", None)
    assert entity._attr_native_value is None
