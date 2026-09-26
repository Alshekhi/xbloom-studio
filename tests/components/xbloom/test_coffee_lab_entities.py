"""Coffee Lab's entities: present only when it is on, and fully translated.

Read through `_attr_*`: the stubbed entity bases do not turn those into
properties the way Home Assistant does.
"""
import json
from pathlib import Path

import pytest

from custom_components.xbloom.coffee_lab.entities import (
    COUNT_RESULTS, ActiveBagSelect, LastCountSensor, RemainingSensor, StatsPeriodSelect,
    bag_labels, entities_for,
)
from custom_components.xbloom.coffee_lab.models import Bean
from custom_components.xbloom.coffee_lab.stats import PERIODS

from .test_coffee_lab_lab import _bag, _lab

COMPONENT = Path(__file__).parents[3] / "custom_components" / "xbloom"
PLATFORMS = ("select", "sensor", "number", "button")


def test_with_coffee_lab_off_there_are_no_entities():
    assert all(entities_for(None, platform) == [] for platform in PLATFORMS)


def test_a_shared_name_is_numbered_so_every_label_is_unique():
    beans = [Bean(id=i, name=n, status="open") for i, n in (("a", "Kenya"), ("b", "Kenya"), ("c", "Brazil"))]
    assert bag_labels(beans) == {"a": "Kenya", "b": "Kenya 2", "c": "Brazil"}


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
