"""Keeping the picked recipe prepared, and what happens around it.

The dashboard's picks are the app's first tap: a recipe picked (and, with
Coffee Lab on, a bag) is sent to the machine ahead, so Start Brew sends execute
alone. Every way in and out of that is here — the picks settling, the bag rule,
a start arriving mid-preparation, the brew ending with or without coffee used,
a change of mind, Connect turned off by hand, the link lost.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import custom_components.xbloom.prepare as prep
from custom_components.xbloom.prepare import BrewPreparer, PrepareRefused


class _State(SimpleNamespace):
    pass


class _Hass:
    """States to read, services to record, tasks to run."""

    def __init__(self):
        self.states_by_id: dict[str, str] = {
            prep.RECIPE: "Test Recipe", prep.BAG: "Test Bag", prep.DOSE: "15.0",
            prep.RATIO: "16.0", prep.GRIND: "50.0", prep.IN_RANGE: "on",
            prep.BREW_STATUS: "idle", prep.CONNECT: "off",
        }
        self.calls: list[tuple[str, str, dict]] = []
        self.states = SimpleNamespace(get=self._get)

        async def _call(domain, service, data, blocking=False):
            self.calls.append((domain, service, data))
            if (domain, service) == ("switch", "turn_on"):
                self.states_by_id[prep.CONNECT] = "on"
            if (domain, service) == ("switch", "turn_off"):
                self.states_by_id[prep.CONNECT] = "off"

        self.services = SimpleNamespace(async_call=_call)
        self.fired: list[tuple[str, dict]] = []
        self.bus = SimpleNamespace(async_fire=lambda event, data: self.fired.append((event, data)))

    def _get(self, entity_id):
        if entity_id not in self.states_by_id:
            return None
        return _State(state=self.states_by_id[entity_id])

    def async_create_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)


class _Lab:
    def __init__(self, bean="bag-1"):
        self.active_bean_id = bean

    async def async_select(self, bean_id):
        self.active_bean_id = bean_id


class _NotSent(Exception):
    """A preparation the machine did not take, as the integration raises it."""

    def __init__(self, reason: str = "no_reply"):
        super().__init__(reason)
        self.not_prepared = {"reason": reason, "recipe_name": "Test Recipe"}


class _Rig:
    """A preparer with everything it reaches recorded."""

    def __init__(self, lab: _Lab | None = None, fail: Exception | None = None):
        self.hass = _Hass()
        self.prepared: list[dict] = []
        self.quits = 0
        self.running = False
        self.signals: list[tuple] = []
        self.timers: list = []
        self.fail = fail
        entry = SimpleNamespace(entry_id="e1", runtime_data=SimpleNamespace(coffee_lab=lab))

        async def _prepare(data):
            if self.fail is not None:
                raise self.fail
            if self.prepared and self.prepared[-1] == data:
                return None  # the machine already holds it: nothing sent
            self.prepared.append(data)
            return {"recipe_name": "Test Recipe", "changes": {"dose": {"saved": 20, "now": data.get("dose")}}}

        async def _quit():
            self.quits += 1

        self.preparer = BrewPreparer(self.hass, entry, _prepare, lambda: self.running, _quit)

    def change(self, entity_id: str, new: str, old: str | None = "before"):
        self.hass.states_by_id[entity_id] = new
        event = SimpleNamespace(data={
            "entity_id": entity_id,
            "old_state": None if old is None else _State(state=old),
            "new_state": _State(state=new),
        })
        self.preparer._on_change(event)

    def status(self, old: str, new: str):
        self.hass.states_by_id[prep.BREW_STATUS] = new
        self.preparer._on_status(SimpleNamespace(data={
            "old_state": _State(state=old), "new_state": _State(state=new),
        }))

    async def settle(self):
        """Let the settle timer fire and the preparation finish."""
        while self.timers:
            self.timers.pop()(None)
        for _ in range(10):
            await asyncio.sleep(0)

    def ready(self):
        return self.preparer.ready


@pytest.fixture
def rig_factory():
    patches = []

    def make(**kw) -> _Rig:
        rig = _Rig(**kw)

        def _later(_hass, _delay, action):
            rig.timers.append(action)
            return lambda: rig.timers.remove(action) if action in rig.timers else None

        def _send(_hass, signal, *args):
            rig.signals.append((signal, *args))

        for target, value in (("async_call_later", _later), ("async_dispatcher_send", _send)):
            p = patch.object(prep, target, value)
            p.start()
            patches.append(p)
        return rig

    yield make
    for p in patches:
        p.stop()


async def test_a_burst_of_changes_is_prepared_once(rig_factory):
    # Picking a recipe resets three sliders; dragging one changes it many times.
    rig = rig_factory()
    for value in ("15.5", "16.0", "16.5"):
        rig.change(prep.DOSE, value, old="15.0")
    await rig.settle()
    assert len(rig.prepared) == 1
    assert rig.prepared[0]["dose"] == 16.5
    assert rig.ready()


async def test_entities_appearing_at_startup_prepare_nothing(rig_factory):
    rig = rig_factory()
    rig.change(prep.RECIPE, "Test Recipe", old=None)
    rig.change(prep.DOSE, "15.0", old="unavailable")
    await rig.settle()
    assert rig.prepared == []


async def test_with_coffee_lab_on_nothing_is_prepared_without_a_bag(rig_factory):
    rig = rig_factory(lab=_Lab(bean=None))
    rig.hass.states_by_id[prep.BAG] = "unknown"
    rig.change(prep.RECIPE, "Test Recipe")
    await rig.settle()
    assert rig.prepared == []
    assert rig.preparer.reason == "no_bag"
    # Picking the bag is what lets it go ahead.
    rig.change(prep.BAG, "Test Bag", old="unknown")
    await rig.settle()
    assert len(rig.prepared) == 1


async def test_coffee_from_no_bag_is_prepared_when_said_so(rig_factory):
    rig = rig_factory(lab=_Lab(bean=None))
    rig.hass.states_by_id[prep.BAG] = "unknown"
    rig.preparer.unattributed = True
    await rig.preparer.async_prepare_now()
    assert len(rig.prepared) == 1


async def test_nothing_is_prepared_while_a_brew_runs(rig_factory):
    rig = rig_factory()
    rig.running = True
    rig.change(prep.RATIO, "17.0", old="16.0")
    await rig.settle()
    assert rig.prepared == []
    with pytest.raises(PrepareRefused) as err:
        await rig.preparer.async_prepare_now()
    assert err.value.reason == "brewing"


async def test_nothing_is_prepared_out_of_range(rig_factory):
    rig = rig_factory()
    rig.hass.states_by_id[prep.IN_RANGE] = "off"
    rig.change(prep.RECIPE, "Test Recipe")
    await rig.settle()
    assert rig.prepared == [] and rig.preparer.reason == "machine_not_found"


async def test_a_start_mid_adjustment_prepares_the_latest_picks_first(rig_factory):
    # Start Brew pressed within the settle window: execute must not go out
    # for the recipe as it was before the slider moved.
    rig = rig_factory()
    rig.change(prep.GRIND, "52.0", old="50.0")
    assert not rig.ready()
    await rig.preparer.async_settled()
    assert rig.prepared[-1]["grind_size"] == 52
    assert rig.ready()


async def test_a_refusal_leaves_it_not_ready_and_says_why(rig_factory):
    err = Exception("refused")
    err.translation_key = "refused_not_on_home_screen"
    rig = rig_factory(fail=err)
    rig.change(prep.RECIPE, "Test Recipe")
    await rig.settle()
    assert not rig.ready()
    assert rig.preparer.reason == "refused_not_on_home_screen"


async def test_coffee_made_clears_the_picks_and_turns_connect_off_if_this_turned_it_on(rig_factory):
    lab = _Lab()
    rig = rig_factory(lab=lab)
    await rig.preparer.async_hold_link()
    await rig.preparer.async_prepare_now()
    await rig.preparer.async_brew_ended(used_coffee=True)
    assert (prep.signal_clear_recipe("e1"),) in rig.signals
    assert lab.active_bean_id is None
    assert ("switch", "turn_off", {"entity_id": prep.CONNECT}) in rig.hass.calls


async def test_connect_turned_on_by_hand_stays_on_after_the_brew(rig_factory):
    rig = rig_factory()
    rig.hass.states_by_id[prep.CONNECT] = "on"
    await rig.preparer.async_hold_link()
    await rig.preparer.async_brew_ended(used_coffee=True)
    assert all(call[1] != "turn_off" for call in rig.hass.calls)


async def test_a_brew_that_made_no_coffee_unpicks_the_recipe_and_keeps_the_bag(rig_factory):
    # No beans: refill, pick again. The bag is still the right one, and
    # Connect stays on so the next preparation does not reconnect first.
    lab = _Lab()
    rig = rig_factory(lab=lab)
    await rig.preparer.async_hold_link()
    await rig.preparer.async_prepare_now()
    await rig.preparer.async_brew_ended(used_coffee=False)
    assert (prep.signal_clear_recipe("e1"),) in rig.signals
    assert lab.active_bean_id == "bag-1"
    assert all(call[1] != "turn_off" for call in rig.hass.calls)
    assert not rig.ready()


async def test_connect_is_let_go_when_nothing_is_picked_after_a_while(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_hold_link()
    await rig.preparer.async_brew_ended(used_coffee=False)
    rig.hass.states_by_id[prep.RECIPE] = "unknown"
    assert len(rig.timers) == 1
    rig.timers.pop()(None)
    for _ in range(5):
        await asyncio.sleep(0)
    assert ("switch", "turn_off", {"entity_id": prep.CONNECT}) in rig.hass.calls


async def test_picking_again_keeps_connect_on(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_hold_link()
    await rig.preparer.async_brew_ended(used_coffee=False)
    rig.change(prep.RECIPE, "Test Recipe", old="unknown")
    # Only the settle timer for the new pick is left; the release is gone.
    assert len(rig.timers) == 1
    await rig.settle()
    assert all(call[1] != "turn_off" for call in rig.hass.calls)
    assert rig.ready()


async def test_a_session_turned_on_by_hand_is_never_let_go_by_the_timer(rig_factory):
    rig = rig_factory()
    rig.hass.states_by_id[prep.CONNECT] = "on"
    await rig.preparer.async_hold_link()
    await rig.preparer.async_brew_ended(used_coffee=False)
    assert rig.timers == []


async def test_a_change_of_mind_takes_back_the_recipe_and_keeps_the_bag(rig_factory):
    lab = _Lab()
    rig = rig_factory(lab=lab)
    await rig.preparer.async_hold_link()
    await rig.preparer.async_prepare_now()
    await rig.preparer.async_cancel()
    assert rig.quits == 1
    assert (prep.signal_clear_recipe("e1"),) in rig.signals
    assert lab.active_bean_id == "bag-1"
    assert ("switch", "turn_off", {"entity_id": prep.CONNECT}) in rig.hass.calls
    assert not rig.ready()


async def test_a_cancel_with_nothing_sent_sends_no_quit(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_cancel()
    assert rig.quits == 0


async def test_connect_turned_off_by_hand_is_an_undo(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_prepare_now()
    await rig.preparer.async_undo()
    assert rig.quits == 1
    assert (prep.signal_clear_recipe("e1"),) in rig.signals
    # The switch is already turning itself off.
    assert all(call[1] != "turn_off" for call in rig.hass.calls)


async def test_a_lost_link_is_not_ready(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_prepare_now()
    rig.preparer.async_link_lost()
    assert not rig.ready()
    await rig.preparer.async_cancel()
    assert rig.quits == 0, "nothing held by a session that is gone"


async def test_a_brew_started_at_the_machine_ends_like_any_other(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_prepare_now()
    rig.status("brewing", "done")
    for _ in range(10):
        await asyncio.sleep(0)
    assert (prep.signal_clear_recipe("e1"),) in rig.signals


async def test_a_home_assistant_brew_reports_its_own_end(rig_factory):
    rig = rig_factory()
    rig.running = True
    rig.status("brewing", "done")
    for _ in range(10):
        await asyncio.sleep(0)
    assert (prep.signal_clear_recipe("e1"),) not in rig.signals


async def test_clearing_its_own_picks_is_not_a_new_request(rig_factory):
    rig = rig_factory()
    await rig.preparer.async_prepare_now()
    rig.preparer._quiet = True
    rig.change(prep.RECIPE, "unknown", old="Test Recipe")
    rig.preparer._quiet = False
    # Nothing new to prepare; the announcement of what was sent may still wait.
    assert [t for t in rig.timers if t != rig.preparer._announce] == []


async def test_closing_a_session_that_prepared_nothing_leaves_the_picks(rig_factory):
    # Connect used for the knobs alone, with a recipe restored after a restart.
    rig = rig_factory()
    await rig.preparer.async_undo()
    assert rig.quits == 0
    assert (prep.signal_clear_recipe("e1"),) not in rig.signals


async def test_preparing_shows_while_a_preparation_waits_or_runs(rig_factory):
    rig = rig_factory()
    rig.change(prep.DOSE, "16.0", old="15.0")
    assert rig.preparer.preparing and not rig.ready()
    await rig.settle()
    assert rig.ready() and not rig.preparer.preparing


async def test_preparing_soon_answers_before_the_machine_does(rig_factory):
    rig = rig_factory()
    rig.preparer.async_prepare_soon()
    assert rig.preparer.preparing and rig.prepared == []
    for _ in range(10):
        await asyncio.sleep(0)
    assert rig.ready() and len(rig.prepared) == 1


async def test_preparing_soon_refuses_at_once_without_a_bag(rig_factory):
    rig = rig_factory(lab=_Lab(bean=None))
    rig.hass.states_by_id[prep.BAG] = "unknown"
    with pytest.raises(PrepareRefused) as err:
        rig.preparer.async_prepare_soon()
    assert err.value.reason == "no_bag" and not rig.preparer.preparing


async def test_pre_ground_for_one_brew_is_put_back_after_it(rig_factory):
    rig = rig_factory()
    rig.preparer.grinder_before = "on"
    await rig.preparer.async_brew_ended(used_coffee=True)
    assert ("switch", "turn_on", {"entity_id": prep.USE_GRINDER}) in rig.hass.calls
    assert rig.preparer.grinder_before is None


async def test_a_change_of_mind_puts_the_grinder_back_too(rig_factory):
    rig = rig_factory()
    rig.preparer.grinder_before = "on"
    await rig.preparer.async_cancel()
    assert ("switch", "turn_on", {"entity_id": prep.USE_GRINDER}) in rig.hass.calls


# ── Announcing what reached the machine ─────────────────────────────────────

def _announced(rig):
    return [data for event, data in rig.hass.fired if event == prep.EV_PREPARED]


async def test_what_reached_the_machine_is_announced_once_the_picks_settle(rig_factory):
    rig = rig_factory()
    rig.change(prep.DOSE, "18.0")
    await rig.settle()          # prepared; the announcement now waits
    assert _announced(rig) == []
    await rig.settle()          # left alone: announced
    assert _announced(rig) == [
        {"recipe_name": "Test Recipe", "changes": {"dose": {"saved": 20, "now": 18.0}}},
    ]


async def test_adjusting_again_while_it_waits_announces_only_the_last(rig_factory):
    rig = rig_factory()
    rig.change(prep.DOSE, "18.0")
    await rig.settle()
    rig.change(prep.DOSE, "17.0")   # before the announcement: it starts over
    await rig.settle()
    await rig.settle()
    assert [a["changes"]["dose"]["now"] for a in _announced(rig)] == [17.0]


async def test_a_brew_started_before_it_settles_is_not_announced_as_arrived(rig_factory):
    rig = rig_factory()
    rig.change(prep.DOSE, "18.0")
    await rig.settle()
    rig.hass.states_by_id[prep.BREW_STATUS] = "grinding"
    await rig.settle()
    assert _announced(rig) == []


async def test_a_change_that_sends_nothing_still_announces_what_the_machine_holds(rig_factory):
    # Picking the bag again prepares nothing new; what was sent is still there.
    rig = rig_factory()
    rig.change(prep.DOSE, "18.0")
    await rig.settle()
    rig.change(prep.BAG, "Other Bag")
    await rig.settle()
    await rig.settle()
    assert [a["changes"]["dose"]["now"] for a in _announced(rig)] == [18.0]


def test_the_water_is_given_whenever_the_dose_or_ratio_changes():
    saved = {"dose_g": 20, "water_ratio": 16, "grinder_size": 50}
    assert prep.changes_from_recipe(saved, 15, 16, 50, True) == {
        "dose": {"saved": 20, "now": 15}, "water": {"saved": 320, "now": 240},
    }
    assert prep.changes_from_recipe(saved, 20, 16, 50, True) == {}


def test_pre_ground_coffee_is_a_change():
    saved = {"dose_g": 20, "water_ratio": 16, "grinder_size": 50, "grinder_size_enabled": 1}
    assert prep.changes_from_recipe(saved, 20, 16, 50, False) == {
        "use_grinder": {"saved": True, "now": False},
    }


def _failures(rig):
    return [data for event, data in rig.hass.fired if event == prep.EV_NOT_PREPARED]


async def test_a_failure_is_announced_only_if_it_stays_failed(rig_factory):
    rig = rig_factory(fail=_NotSent("no_reply"))
    rig.change(prep.DOSE, "18.0")
    await rig.settle()           # the attempt failed; nothing said yet
    assert _failures(rig) == []
    await rig.settle()           # left alone, still failed: said
    assert [f["reason"] for f in _failures(rig)] == ["no_reply"]


async def test_a_failure_the_next_attempt_replaces_is_not_announced(rig_factory):
    # Adjusting while the link answers late: one attempt fails, the next works.
    rig = rig_factory(fail=_NotSent("no_reply"))
    rig.change(prep.DOSE, "18.0")
    await rig.settle()
    rig.fail = None
    rig.change(prep.DOSE, "17.0")
    await rig.settle()
    await rig.settle()
    assert _failures(rig) == []
    assert [a["changes"]["dose"]["now"] for a in _announced(rig)] == [17.0]
