"""Coffee Lab's entities: present only when it is on, and fully translated.

Read through `_attr_*`: the stubbed entity bases do not turn those into
properties the way Home Assistant does.
"""
import json
from pathlib import Path

import pytest

from custom_components.xbloom.coffee_lab.entities import (
    COUNT_RESULTS, ActiveBagSelect, LastCountSensor, ManualBrewerSelect, RemainingSensor,
    StatsPeriodSelect,
    bag_labels, entities_for,
)
from custom_components.xbloom.coffee_lab import actions
from custom_components.xbloom.coffee_lab.models import Bean
from custom_components.xbloom.coffee_lab.stats import PERIODS

from .test_coffee_lab_lab import _bag, _lab

COMPONENT = Path(__file__).parents[3] / "custom_components" / "xbloom"
PLATFORMS = ("select", "sensor", "number", "button", "binary_sensor")


def test_with_coffee_lab_off_there_are_no_entities():
    assert all(entities_for(None, platform) == [] for platform in PLATFORMS)


def test_a_shared_name_is_told_apart_by_roast_date():
    beans = [Bean(id=i, name=n, status="open", roast_date=d)
             for i, n, d in (("a", "Kenya", "2026-09-01"), ("b", "Kenya", "2026-11-01"), ("c", "Brazil", ""))]
    assert bag_labels(beans) == {"a": "Kenya (2026-09-01)", "b": "Kenya (2026-11-01)", "c": "Brazil"}


@pytest.mark.parametrize("dates", [("", ""), ("2026-09-01", ""), ("2026-09-01", "2026-09-01")])
def test_a_shared_name_without_distinct_roast_dates_is_numbered(dates):
    beans = [Bean(id=i, name="Kenya", status="open", roast_date=d) for i, d in zip("ab", dates)]
    assert bag_labels(beans) == {"a": "Kenya", "b": "Kenya 2"}


async def test_picking_a_label_selects_that_bag_by_id():
    lab = await _lab()
    await _bag(lab)
    second = await _bag(lab, status="open")
    select = ActiveBagSelect(lab)
    await select.async_read()
    assert select._attr_options == ["Kenya", "Kenya 2"]
    await select.async_select_option("Kenya 2")
    assert lab.active_bean_id == second.id
    await select.async_read()
    assert select._attr_current_option == "Kenya 2"


async def test_an_untracked_bag_has_no_amount_left_not_zero():
    lab = await _lab()
    bag = await _bag(lab, tracked=False, remaining_g=None, status="open")
    await lab.async_select(bag.id)
    sensor = RemainingSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value is None


async def test_the_last_count_shows_a_flag_with_its_reason():
    lab = await _lab()
    await lab.async_consume(bean_id=None, grams=18, run_id="r1")
    sensor = LastCountSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value == "flagged"
    assert sensor._attr_extra_state_attributes["reason"] == "no_bag"


async def test_the_period_select_offers_the_stats_periods():
    lab = await _lab()
    select = StatsPeriodSelect(lab)
    await select.async_read()
    assert select._attr_options == list(PERIODS) and select._attr_current_option == "last_7_days"


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json", "translations/ar.json"])
async def test_every_entity_and_state_is_translated(path):
    lab = await _lab()
    table = json.loads((COMPONENT / path).read_text())["entity"]
    for platform in PLATFORMS:
        for entity in entities_for(lab, platform):
            entry = table[platform][entity._attr_translation_key]
            assert entry["name"]
    assert set(table["select"]["coffee_lab_stats_period"]["state"]) == set(PERIODS)
    assert set(table["sensor"]["coffee_lab_last_count"]["state"]) == set(COUNT_RESULTS)
    assert set(table["select"]["coffee_lab_manual_brewer"]["state"]) == {"other"}
    from custom_components.xbloom.coffee_lab.stock import MEASURES
    for kind, measures in MEASURES.items():
        assert set(table["select"][f"coffee_lab_{kind}_stock_measure"]["state"]) == set(measures)


async def test_the_brewer_picker_offers_the_configured_brewers_and_other():
    lab = await _lab()
    lab.brewers = ("V60", "Hario Switch")
    select = ManualBrewerSelect(lab)
    assert select._attr_options == ["V60", "Hario Switch", "other"]
    await select.async_select_option("Hario Switch")
    await select.async_read()
    assert select._attr_current_option == "Hario Switch"


async def test_a_brew_made_with_other_is_counted_as_other():
    lab = await _lab()
    bag = await _bag(lab)
    await lab.async_select(bag.id)
    await lab.async_set_manual_dose(15.0)
    await lab.async_set_manual_brewer("other")
    await actions.record_manual_brew(lab, {})
    [brew] = await lab.store.async_list_brews()
    assert brew.brewer is None
    report = await lab.async_stats("today")
    assert dict(report.now.by_brewer) == {"other": 1}


def test_every_entity_name_is_in_both_languages():
    en = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    ar = json.loads((COMPONENT / "translations/ar.json").read_text())["entity"]
    for platform, entities in en.items():
        for key, entry in entities.items():
            if "name" in entry:
                assert ar[platform][key]["name"], (platform, key)


def test_no_entity_hardcodes_its_name():
    import re

    for path in COMPONENT.rglob("*.py"):
        assert not re.search(r"^\s*_attr_name = ", path.read_text(), re.M), path.name



async def test_a_store_that_cannot_be_reached_keeps_the_last_values():
    from unittest.mock import AsyncMock, MagicMock
    from homeassistant.exceptions import HomeAssistantError

    lab = await _lab()
    bag = await _bag(lab, status="open")
    await lab.async_select(bag.id)
    sensor = RemainingSensor(lab)
    await sensor.async_read()
    shown = sensor._attr_native_value
    sensor.entity_id = "sensor.xbloom_studio_coffee_left"
    sensor.async_write_ha_state = MagicMock()
    sensor.async_read = AsyncMock(side_effect=HomeAssistantError("Notion timed out"))

    await sensor._async_read_and_write()

    assert sensor._attr_native_value == shown
    sensor.async_write_ha_state.assert_not_called()



# ── Stock ────────────────────────────────────────────────────────────────────

from custom_components.xbloom.coffee_lab.entities import (  # noqa: E402
    StockLevelNumber, StockLowBinarySensor, StockMeasureSelect, StockSensor,
)
from custom_components.xbloom.coffee_lab.stock import Stock  # noqa: E402


def _stock(lab, kind="coffee", **values):
    lab.stock = {kind: Stock(kind=kind, kept=True, amount=values.get("amount", 300.0),
                             bags=values.get("bags", 2), cups=values.get("cups", 17.0),
                             days=values.get("days", 12.4), unknown=values.get("unknown", ()))}


async def test_the_stock_sensor_shows_the_chosen_measure_and_every_figure():
    lab = await _lab()
    _stock(lab)
    sensor = StockSensor(lab, "coffee")
    await sensor.async_read()
    assert sensor._attr_native_value == 12 and sensor._attr_available
    attrs = sensor._attr_extra_state_attributes
    assert (attrs["measure"], attrs["level"], attrs["low"]) == ("days", 7, False)
    assert (attrs["grams"], attrs["bags"], attrs["cups"], attrs["days"]) == (300, 2, 17, 12)
    await lab.async_set_stock_measure("coffee", "bags")
    await sensor.async_read()
    assert sensor._attr_native_value == 2


async def test_an_unknown_figure_shows_at_least_and_no_low():
    lab = await _lab()
    _stock(lab, amount=40.0, unknown=("u",))
    await lab.async_set_stock_low_state("coffee", True)
    sensor, low = StockSensor(lab, "coffee"), StockLowBinarySensor(lab, "coffee")
    await sensor.async_read()
    await low.async_read()
    assert sensor._attr_native_value is None
    assert sensor._attr_extra_state_attributes["at_least"] == 12
    assert sensor._attr_extra_state_attributes["unknown"] == 1
    assert low._attr_is_on is False


async def test_the_low_signal_follows_the_stored_state_while_the_figure_is_known():
    lab = await _lab()
    _stock(lab, days=3.0)
    low = StockLowBinarySensor(lab, "coffee")
    await lab.async_set_stock_low_state("coffee", True)
    await low.async_read()
    assert low._attr_is_on is True
    await lab.async_set_stock_level("coffee", 0)
    await low.async_read()
    assert low._attr_is_on is False


async def test_the_level_number_follows_the_measure():
    lab = await _lab()
    _stock(lab)
    number = StockLevelNumber(lab, "coffee")
    await number.async_read()
    assert (number._attr_native_value, number._attr_native_max_value, number._attr_native_step) == (7, 60, 1)
    await lab.async_set_stock_measure("coffee", "grams")
    await number.async_read()
    assert (number._attr_native_value, number._attr_native_max_value, number._attr_native_step) == (250, 2000, 10)
    await number.async_set_native_value(100)
    assert lab.stock_level("coffee") == 100


async def test_the_measure_select_offers_the_kind_s_measures():
    lab = await _lab()
    _stock(lab, kind="xpod")
    select = StockMeasureSelect(lab, "xpod")
    await select.async_read()
    assert select._attr_options == ["days", "pods", "boxes"] and select._attr_current_option == "pods"
    await select.async_select_option("boxes")
    assert lab.stock_measure("xpod") == "boxes"


async def test_a_kind_never_kept_has_no_stock_entities_available():
    lab = await _lab()
    lab.stock = {"tea": Stock(kind="tea", kept=False, amount=None, bags=0, cups=None, days=None)}
    for make in (StockSensor, StockLowBinarySensor, StockMeasureSelect, StockLevelNumber):
        entity = make(lab, "tea")
        await entity.async_read()
        assert entity._attr_available is False, make


async def test_recent_brews_show_the_newest_brew_and_each_in_full():
    from custom_components.xbloom.coffee_lab.entities import RecentBrewsSensor

    from datetime import datetime, timedelta, timezone
    lab = await _lab()
    bag = await _bag(lab)
    newest = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="r1", recipe="Daily",
                            brewed_at=(newest - timedelta(days=1)).isoformat())
    await lab.async_consume(bean_id=bag.id, grams=20, run_id="r2", recipe="Iced",
                            brewed_at=newest.isoformat())
    sensor = RecentBrewsSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value.replace(second=0) == newest.replace(second=0)
    brews = sensor._attr_extra_state_attributes["brews"]
    assert [b["recipe"] for b in brews] == ["Iced", "Daily"]
    assert brews[0]["bag"] == bag.name and brews[0]["dose_g"] == 20
    assert "brews" in RecentBrewsSensor._unrecorded_attributes


async def test_recent_brews_with_nothing_brewed():
    from custom_components.xbloom.coffee_lab.entities import RecentBrewsSensor

    sensor = RecentBrewsSensor(await _lab())
    await sensor.async_read()
    assert sensor._attr_native_value is None
    assert sensor._attr_extra_state_attributes == {"brews": []}


async def test_the_brews_listed_follow_the_stats_period():
    from datetime import datetime, timedelta, timezone
    from custom_components.xbloom.coffee_lab.entities import RecentBrewsSensor

    lab = await _lab()
    bag = await _bag(lab)
    now = datetime.now(timezone.utc)
    for n, days in enumerate((1, 3, 20, 40)):
        await lab.async_consume(bean_id=bag.id, grams=17, run_id=f"p{n}", recipe=f"R{n}",
                                brewed_at=(now - timedelta(days=days)).isoformat())
    sensor = RecentBrewsSensor(lab)
    await lab.async_set_stats_period("last_7_days")
    await sensor.async_read()
    assert [b["recipe"] for b in sensor._attr_extra_state_attributes["brews"]] == ["R0", "R1"]
    await lab.async_set_stats_period("last_30_days")
    await sensor.async_read()
    assert [b["recipe"] for b in sensor._attr_extra_state_attributes["brews"]] == ["R0", "R1", "R2"]


async def test_last_months_brews_are_not_crowded_out_by_this_months():
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from custom_components.xbloom.coffee_lab import entities
    from custom_components.xbloom.coffee_lab.stats import window

    lab = await _lab()
    bag = await _bag(lab, remaining_g=5000.0)
    w = window("last_month", dt_util.now())
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="old", recipe="Old",
                            brewed_at=(w.start + timedelta(days=2)).isoformat())
    for n in range(3):
        await lab.async_consume(bean_id=bag.id, grams=17, run_id=f"new{n}", recipe="New",
                                brewed_at=(w.end + timedelta(hours=n + 1)).isoformat())
    await lab.async_set_stats_period("last_month")
    old_limit, entities.RECENT_BREWS = entities.RECENT_BREWS, 2
    try:
        sensor = entities.RecentBrewsSensor(lab)
        await sensor.async_read()
    finally:
        entities.RECENT_BREWS = old_limit
    assert [b["recipe"] for b in sensor._attr_extra_state_attributes["brews"]] == ["Old"]


# ── Finish this bag? ─────────────────────────────────────────────────────────

from custom_components.xbloom.coffee_lab.entities import (  # noqa: E402
    BagToFinishSensor, FinishAskedButton, KeepAskedButton,
)


async def _asked():
    lab = await _lab()
    bag = await _bag(lab, status="open", remaining_g=25.5)
    await lab.async_consume(bean_id=bag.id, grams=17, run_id="r1")
    return lab, bag


async def test_the_bag_to_finish_names_the_bag_and_what_is_left():
    lab, bag = await _asked()
    sensor = BagToFinishSensor(lab)
    await sensor.async_read()
    assert sensor._attr_native_value == "Kenya"
    assert sensor._attr_extra_state_attributes == {"bean_id": bag.id, "remaining_g": 8.5}
    assert sensor.entity_id == "sensor.xbloom_studio_bag_to_finish"


async def test_with_nothing_asked_the_sensor_is_empty_and_the_buttons_unavailable():
    lab = await _lab()
    sensor, finish, keep = BagToFinishSensor(lab), FinishAskedButton(lab), KeepAskedButton(lab)
    for entity in (sensor, finish, keep):
        await entity.async_read()
    assert sensor._attr_native_value is None
    assert finish.available is False and keep.available is False


async def test_the_buttons_finish_or_keep_the_bag_asked_about():
    lab, bag = await _asked()
    finish, keep = FinishAskedButton(lab), KeepAskedButton(lab)
    assert (finish.entity_id, keep.entity_id) == ("button.xbloom_studio_finish_bag", "button.xbloom_studio_keep_bag")
    await finish.async_read()
    assert finish.available is True
    await finish.async_press()
    assert (await lab.store.async_get_bean(bag.id)).status == "finished"


async def test_the_ai_tools_see_the_question():
    lab, bag = await _asked()
    facts = await actions.active_bean(lab, {})
    assert facts["finish_question"] == {"bean_id": bag.id, "bag": "Kenya", "remaining_g": 8.5}


# ── Use the rest of the bag ──────────────────────────────────────────────────

from custom_components.xbloom.coffee_lab.entities import UseRestOfBagButton  # noqa: E402


async def test_the_rest_button_follows_what_todays_cup_says_and_presses_through():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    lab = await _lab()
    bag = await _bag(lab, status="open", remaining_g=25.5)
    await lab.async_select(bag.id)
    lab.todays_cup = SimpleNamespace(rest_of_bag_dose=lambda b: 25.0 if b and b.id == bag.id else None,
                                     async_use_rest=AsyncMock())
    button = UseRestOfBagButton(lab)
    assert button.entity_id == "button.xbloom_studio_use_rest_of_bag"
    await button.async_read()
    assert button.available is True
    await button.async_press()
    lab.todays_cup.async_use_rest.assert_awaited_once()
    lab.todays_cup.rest_of_bag_dose = lambda b: None
    await button.async_read()
    assert button.available is False


async def test_without_todays_cup_the_rest_button_is_unavailable():
    lab = await _lab()
    button = UseRestOfBagButton(lab)
    await button.async_read()
    assert button.available is False
