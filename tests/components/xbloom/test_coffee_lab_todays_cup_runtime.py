"""Today's cup at runtime: one read per refresh, and using it on the Brew tab."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.coffee_lab.todays_cup_runtime import TodaysCup

from .test_coffee_lab_lab import _lab

TODAY = date.today().isoformat()
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
LIBRARY = [{"name": "Daily", "water_ratio": 15, "dose_g": 18, "cup_type": 2}]


class _Home:
    def __init__(self, status="idle"):
        self.status = status
        self.calls = []
        self.hass = MagicMock()
        self.hass.services.async_call = self.call
        self.hass.states.get = self.get

    def get(self, entity_id):
        if entity_id == "sensor.xbloom_studio_brew_status":
            return SimpleNamespace(state=self.status, attributes={})
        if entity_id == "select.xbloom_studio_recipe":
            picked = [c for c in self.calls if c[0] == "recipe"]
            return SimpleNamespace(state=picked[-1][1] if picked else "unknown", attributes={})
        return None

    async def call(self, domain, service, data=None, blocking=False, **kw):
        self.calls.append((f"{domain}.{service}", data))


def _browser(home, hub=None):
    async def use(name):
        home.calls.append(("recipe", name))

    async def add_and_use(recipe):
        home.calls.append(("recipe", recipe["name"]))
        home.calls.append(("added", recipe["id"]))

    return SimpleNamespace(drink="any", async_use=use, async_add_and_use_recipe=add_and_use,
                           async_community_for=AsyncMock(return_value=hub))


async def _cup(home, hub=None, library=LIBRARY):
    lab = await _lab()
    bag = await lab.store.async_add_bean(name="Hill Farm", status="open", tracked=True,
                                         remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="r1", recipe="Daily",
                            brewed_at=YESTERDAY)
    browser = _browser(home, hub)
    return TodaysCup(home.hass, lab, browser, lambda: library), lab, bag, browser


async def test_a_refresh_builds_the_pick_from_one_read():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    lab.store.async_list_beans = AsyncMock(wraps=lab.store.async_list_beans)
    lab.store.async_list_brews = AsyncMock(wraps=lab.store.async_list_brews)
    await cup.async_refresh()
    assert (cup.pick.bag_id, cup.pick.recipe, cup.pick.drink) == (bag.id, "Daily", "hot")
    assert lab.store.async_list_beans.await_count == 1
    assert lab.store.async_list_brews.await_count == 1


async def test_use_picks_bag_then_recipe_then_dose():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    await cup.async_refresh()
    await cup.async_use()
    assert lab.active_bean_id == bag.id
    assert home.calls[0] == ("recipe", "Daily")
    assert home.calls[-1] == ("number.set_value",
                              {"entity_id": "number.xbloom_studio_brew_dose", "value": cup.pick.dose_g})


async def test_use_adds_a_community_recipe_first():
    home = _Home()
    cup, *_ = await _cup(home, hub={"id": 42, "name": "Shared"}, library=[])
    await cup.async_refresh()
    assert (cup.pick.recipe_source, cup.pick.hub_id) == ("community", 42)
    await cup.async_use()
    assert ("added", 42) in home.calls


async def test_use_is_refused_while_brewing():
    home = _Home()
    cup, *_ = await _cup(home)
    await cup.async_refresh()
    home.status = "brewing"
    with pytest.raises(HomeAssistantError):
        await cup.async_use()


async def test_another_walks_the_candidates_and_counts_a_skip():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                   remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await cup.async_refresh()
    first = cup.pick
    await cup.async_another()
    assert cup.pick != first
    await cup.async_another()
    assert cup.pick == first
    assert sum((lab._state.get("todays_cup_skips") or {}).values()) == 2


async def test_the_pick_holds_still_during_a_brew():
    home = _Home()
    cup, lab, *_ = await _cup(home)
    await cup.async_refresh()
    first = cup.pick
    home.status = "grinding"
    await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                   remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await cup.async_refresh()
    assert cup.pick == first and cup.waiting


async def test_a_failed_read_keeps_the_last_pick():
    home = _Home()
    cup, lab, *_ = await _cup(home)
    await cup.async_refresh()
    first = cup.pick
    lab.store.async_list_beans = AsyncMock(side_effect=HomeAssistantError("down"))
    await cup.async_refresh()
    assert cup.pick == first


async def test_the_sensor_and_buttons_follow_the_pick():
    from custom_components.xbloom.coffee_lab.entities import (
        AnotherCupButton, TodaysCupSensor, UseTodaysCupButton,
    )
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    lab.todays_cup = cup
    sensor = TodaysCupSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value is None
    await cup.async_refresh()
    await sensor.async_read()
    assert sensor._attr_native_value == "Hill Farm"
    attrs = sensor._attr_extra_state_attributes
    assert (attrs["bag_id"], attrs["recipe"], attrs["source"], attrs["drink"]) == (bag.id, "Daily", "own", "hot")
    assert attrs["reasons"] and isinstance(attrs["reasons"], list)
    await UseTodaysCupButton(lab).async_press()
    assert ("recipe", "Daily") in home.calls
    cup.async_another = AsyncMock()
    await AnotherCupButton(lab).async_press()
    cup.async_another.assert_awaited_once()


async def test_the_entities_have_ids_the_dashboard_can_name():
    from custom_components.xbloom.coffee_lab.entities import (
        AnotherCupButton, TodaysCupSensor, UseTodaysCupButton,
    )
    home = _Home()
    cup, lab, *_ = await _cup(home)
    assert TodaysCupSensor(lab).entity_id == "sensor.xbloom_studio_todays_cup"
    assert UseTodaysCupButton(lab).entity_id == "button.xbloom_studio_use_todays_cup"
    assert AnotherCupButton(lab).entity_id == "button.xbloom_studio_another_cup"


async def test_a_cup_chosen_with_another_stays_through_a_refresh():
    home = _Home()
    cup, lab, *_ = await _cup(home)
    await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                   remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await cup.async_refresh()
    await cup.async_another()
    chosen = cup.pick
    await cup.async_refresh()
    assert (cup.pick.bag_id, cup.pick.recipe) == (chosen.bag_id, chosen.recipe)


def test_routine_refreshes_wait_their_turn_and_real_events_do_not():
    from custom_components.xbloom.coffee_lab import todays_cup_runtime as rt
    wait = rt.refresh_delay
    assert wait(None, 1000.0, force=False) == rt.SETTLE_S
    assert wait(1000.0, 1060.0, force=False) == rt.MIN_INTERVAL_S - 60
    assert wait(1000.0, 1000.0 + rt.MIN_INTERVAL_S + 1, force=False) == rt.SETTLE_S
    assert wait(1000.0, 1060.0, force=True) == rt.SETTLE_S


async def test_a_skip_is_counted_through_the_lab():
    lab = await _lab()
    await lab.async_count_skip("b1", "Daily")
    await lab.async_count_skip("b1", "Daily")
    assert lab.todays_cup_skips == {"b1|Daily": 2}


async def test_the_pick_moves_on_after_a_brew():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    other = await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                           remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await cup.async_refresh()
    first = cup.pick
    brewed = first.bag_id
    await lab.async_consume(bean_id=brewed, grams=17, run_id="r2", recipe="Daily",
                            brewed_at=datetime.now(timezone.utc).isoformat())
    await cup.async_refresh(reset=True)
    assert cup.pick.bag_id != brewed


async def test_a_cup_shown_first_is_not_held_by_a_routine_refresh():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                   remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    await cup.async_refresh()
    brewed = cup.pick.bag_id
    await lab.async_consume(bean_id=brewed, grams=17, run_id="r2", recipe="Daily",
                            brewed_at=datetime.now(timezone.utc).isoformat())
    await cup.async_refresh()
    assert cup.pick.bag_id != brewed


def test_a_routine_request_does_not_push_back_a_sooner_refresh(monkeypatch):
    from custom_components.xbloom.coffee_lab import todays_cup_runtime as rt
    home = _Home()
    cup = rt.TodaysCup(home.hass, MagicMock(), MagicMock(), lambda: [])
    scheduled = []
    monkeypatch.setattr(rt, "async_call_later",
                        lambda hass, delay, action: (scheduled.append(delay), lambda: scheduled.append("cancelled"))[1])
    cup._last_refresh = rt.time.monotonic()
    cup.schedule_now()
    cup.schedule()
    assert scheduled == [rt.SETTLE_S]


def test_the_schedulers_run_on_the_event_loop():
    # Dispatcher and time-change targets that are not marked as callbacks are
    # run in a worker thread, where timers are not safe to start or cancel.
    # (The test stubs replace the decorator, so its use is read from the source.)
    import inspect
    from custom_components.xbloom.coffee_lab import todays_cup_runtime as rt
    source = inspect.getsource(rt.TodaysCup)
    for name in ("schedule", "schedule_now", "_schedule", "stop"):
        assert f"@callback\n    def {name}(" in source, name


async def test_use_keeps_the_dose_within_what_the_slider_takes():
    home = _Home()
    cup, *_ = await _cup(home, hub={"id": 42, "name": "Shared"}, library=[])
    await cup.async_refresh()
    import dataclasses
    cup.picks[0] = dataclasses.replace(cup.picks[0], dose_g=30.0)
    real_get = home.get
    home.hass.states.get = lambda eid: (SimpleNamespace(state="18", attributes={"min": 5, "max": 18})
                                        if eid == "number.xbloom_studio_brew_dose" else real_get(eid))
    await cup.async_use()
    assert home.calls[-1][1]["value"] == 18


async def test_the_daily_grams_are_the_coffee_pace_alone():
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    tea = await lab.store.async_add_bean(name="Green Leaf", status="open", kind="tea",
                                         tracked=True, remaining_g=100.0)
    for n in range(6):
        when = (datetime.now(timezone.utc) - timedelta(days=n, hours=2)).isoformat()
        await lab.async_consume(bean_id=bag.id, grams=17, run_id=f"c{n}", recipe="Daily", brewed_at=when)
        await lab.async_consume(bean_id=tea.id, grams=4, run_id=f"t{n}", brewed_at=when)
    await cup.async_refresh()
    from custom_components.xbloom.coffee_lab.stock import pace
    beans = await lab.store.async_list_beans(selectable_only=False)
    brews = await lab.store.async_list_brews()
    assert cup.daily_g == pytest.approx(pace("coffee", beans, brews, datetime.now(timezone.utc))[1], rel=0.05)


async def test_a_brew_started_during_the_read_keeps_the_pick():
    home = _Home()
    cup, lab, *_ = await _cup(home)
    await cup.async_refresh()
    first = cup.pick
    await lab.store.async_add_bean(name="Valley Lot", status="open", tracked=True,
                                   remaining_g=200.0, bag_size_g=250.0, opened_on=TODAY)
    real = lab.store.async_list_brews

    async def brew_starts(*a, **kw):
        home.status = "grinding"
        return await real(*a, **kw)

    lab.store.async_list_brews = brew_starts
    await cup.async_refresh(reset=True)
    assert cup.pick == first and cup.waiting


async def test_the_card_goes_once_the_days_coffee_is_brewed():
    from custom_components.xbloom.coffee_lab.entities import TodaysCupSensor
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    lab.todays_cup = cup
    await cup.async_refresh()
    sensor = TodaysCupSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value == "Hill Farm"
    assert sensor._attr_extra_state_attributes["due"] is True
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="r9", recipe="Daily",
                            brewed_at=datetime.now(timezone.utc).isoformat())
    await cup.async_refresh(reset=True)
    await sensor.async_read()
    # Not offered again today; the pick is still there for an agent to ask.
    assert sensor._attr_native_value is None
    attrs = sensor._attr_extra_state_attributes
    assert attrs["due"] is False and attrs["bag"] == "Hill Farm"


async def test_a_brew_recorded_hides_the_card_before_any_refresh():
    from custom_components.xbloom.coffee_lab.models import Brew
    home = _Home()
    cup, lab, bag, _ = await _cup(home)
    await cup.async_refresh()
    assert cup.due()
    cup.brew_recorded(Brew(id="x", brewed_at=datetime.now(timezone.utc).isoformat(),
                           recorded_at="", dose_g=17.0, bean_id=bag.id))
    assert not cup.due()


# ── The last cup within what the cup takes ───────────────────────────────────


def _last(dose):
    from custom_components.xbloom.coffee_lab.todays_cup import Pick
    return Pick("b", "Bag", "R", "own", None, "hot", dose, ("last_cup",))


async def test_a_last_cup_is_fitted_to_what_the_cup_takes():
    # The Omni dripper takes 18 g at most: the pick's own 25.5 g is clamped,
    # not replaced by the usual dose.
    cup, *_ = await _cup(_Home(), library=[{"name": "R", "dose_g": 17, "cup_type": 2}])
    assert cup._fit_dose(_last(25.5), 17.0).dose_g == 18.0


async def test_a_last_cup_within_the_cup_keeps_its_dose():
    cup, *_ = await _cup(_Home(), library=[{"name": "R", "dose_g": 17, "cup_type": 3}])
    assert cup._fit_dose(_last(25.0), 17.0).dose_g == 25.0
