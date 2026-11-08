"""Coffee, xPod boxes and tea: each brew draws from the kind its cup takes.

A coffee brew takes grams from a bag of coffee, an xPod brew one pod from an
xPod box, a tea brew grams from a tea. An xPod or tea brew with none of its
kind in use is recorded against nothing, never charged to a bag of coffee.
"""
from unittest.mock import MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.coffee_lab import actions
from custom_components.xbloom.coffee_lab.inventory import kind_of_cup

from .test_coffee_lab_rating import _lab

XPOD, OMNI, TEA = 1, 2, 4


async def _items():
    lab, store, coffee = await _lab()
    box = await store.async_add_bean(name="Test Box", status="unopened", kind="xpod",
                                     tracked=True, pods_left=2)
    tea = await store.async_add_bean(name="Test Tea", status="open", kind="tea",
                                     tracked=True, remaining_g=50.0)
    await lab.async_select(coffee.id)
    await lab.async_select(box.id)
    await lab.async_select(tea.id)
    return lab, store, coffee, box, tea


async def _brew(lab, cup, run, grams=15):
    return await lab.async_consume(
        bean_id=lab.active_bean_id, xpod_id=lab.active_id("xpod"), tea_id=lab.active_id("tea"),
        grams=grams, run_id=run, cup_type=cup, recipe="Test Recipe",
    )


def test_a_cup_type_names_the_kind_it_draws_from():
    assert [kind_of_cup(c) for c in (XPOD, OMNI, 3, TEA, None, "x")] == [
        "xpod", "coffee", "coffee", "tea", "coffee", "coffee",
    ]


async def test_each_kind_is_in_use_side_by_side():
    lab, store, coffee, box, tea = await _items()
    assert (lab.active_bean_id, lab.active_id("xpod"), lab.active_id("tea")) == (coffee.id, box.id, tea.id)


async def test_an_xpod_brew_takes_one_pod_and_the_last_finishes_the_box():
    lab, store, coffee, box, tea = await _items()
    first = await _brew(lab, XPOD, "r1")
    assert first.result == "counted" and first.bean_id == box.id
    assert (await store.async_get_bean(box.id)).pods_left == 1
    assert (await store.async_get_bean(box.id)).status == "open"
    await _brew(lab, XPOD, "r2")
    emptied = await store.async_get_bean(box.id)
    assert (emptied.pods_left, emptied.status) == (0, "finished")
    assert (await store.async_get_bean(coffee.id)).remaining_g == 200.0, "no coffee taken"
    assert lab.bag_question["name"] == "Test Box"


async def test_a_tea_brew_takes_grams_from_the_tea_never_the_coffee():
    lab, store, coffee, box, tea = await _items()
    await _brew(lab, TEA, "t1", grams=5)
    assert (await store.async_get_bean(tea.id)).remaining_g == 45.0
    assert (await store.async_get_bean(coffee.id)).remaining_g == 200.0


async def test_without_an_item_of_its_kind_an_xpod_or_tea_brew_is_recorded_against_nothing():
    lab, store, coffee = await _lab()
    await lab.async_select(coffee.id)
    for cup, run in ((XPOD, "x1"), (TEA, "t1")):
        result = await _brew(lab, cup, run)
        assert result.result == "recorded" and result.bean_id is None
    assert (await store.async_get_bean(coffee.id)).remaining_g == 200.0


async def test_a_coffee_brew_is_unchanged():
    lab, store, coffee, box, tea = await _items()
    await _brew(lab, OMNI, "c1")
    assert (await store.async_get_bean(coffee.id)).remaining_g == 185.0
    assert (await store.async_get_bean(box.id)).pods_left == 2


async def test_a_box_with_pods_left_cannot_be_finished_by_hand():
    lab, store, coffee, box, tea = await _items()
    await _brew(lab, XPOD, "r1")  # opens it, one pod left
    with pytest.raises(HomeAssistantError) as raised:
        await actions.finish_bag(lab, {"bean_id": box.id})
    assert raised.value.translation_key == "box_not_empty"


async def test_a_box_is_added_and_counted_in_pods():
    lab, store, coffee = await _lab()
    added = (await actions.add_bean(lab, {"name": "Test Pods", "kind": "xpod", "pods": 8}))["added"]
    assert (added["kind"], added["pods_left"], added["remaining_g"]) == ("xpod", 8, None)
    again = await actions.start_tracking(lab, {"bean_id": added["id"], "pods": 6})
    assert again["bag"]["pods_left"] == 6
    with pytest.raises(HomeAssistantError):
        await actions.start_tracking(lab, {"bean_id": added["id"], "grams": 100})


async def test_a_card_read_teaches_the_box_in_use_then_finds_it():
    lab, store, coffee, box, tea = await _items()
    learnt = await lab.async_card_read("TEST01")
    assert learnt.id == box.id and (await store.async_get_bean(box.id)).pod_id == "TEST01"
    other = await store.async_add_bean(name="Other Box", status="open", kind="xpod",
                                       tracked=True, pods_left=8)
    await lab.async_select(other.id)
    found = await lab.async_card_read("TEST01")
    assert found.id == box.id and lab.active_id("xpod") == box.id, "the card found its own box"


async def test_finishing_an_item_clears_it_from_its_own_kind():
    lab, store, coffee, box, tea = await _items()
    await store.async_update_bean(tea.id, remaining_g=3.0)
    await lab.async_finish(tea.id)
    assert lab.active_id("tea") is None and lab.active_bean_id == coffee.id
