"""Reminding to buy: the list item, the phone, and when each is sent."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.coffee_lab.stock_watch import StockWatch

from .test_coffee_lab_lab import _bag, _lab

TEXTS = {
    "item_coffee": "Coffee beans", "item_tea": "Tea", "item_xpod": "xPods",
    "kind_coffee": "Coffee", "kind_tea": "Tea", "kind_xpod": "xPods",
    "running_low": "{kind}: running low.", "left_bags": "Bags left: {n}.",
    "left_days": "Days left: about {n}.", "left_grams": "Grams left: {n}.",
    "left_cups": "Cups left: about {n}.", "left_pods": "Pods left: {n}.",
    "left_boxes": "Boxes left: {n}.", "added": "Added to {list}.",
    "buy_again": "Time to buy {name} again.",
}


class _Home:
    """The services a reminder uses: a todo list and a notify service."""

    def __init__(self, items=None, fail=None):
        self.items = list(items or [])
        self.added, self.completed, self.notified, self.fired = [], [], [], []
        self.fail = fail or set()
        self.hass = MagicMock()
        self.hass.services.async_call = self.call
        self.hass.bus.async_fire = lambda event, data=None: self.fired.append((event, data))
        self.hass.states.get = lambda eid: SimpleNamespace(attributes={"friendly_name": "Shopping list"})

    async def call(self, domain, service, data=None, blocking=False, return_response=False, **kw):
        if f"{domain}.{service}" in self.fail:
            raise HomeAssistantError("unavailable")
        if (domain, service) == ("todo", "get_items"):
            return {data["entity_id"]: {"items": [i for i in self.items if i["status"] == "needs_action"]}}
        if (domain, service) == ("todo", "add_item"):
            uid = f"uid-{len(self.items) + 1}"
            self.items.append({"summary": data["item"], "uid": uid, "status": "needs_action"})
            self.added.append((data["entity_id"], data["item"]))
        elif (domain, service) == ("todo", "update_item"):
            for item in self.items:
                if item["uid"] == data["item"]:
                    item["status"] = data["status"]
            self.completed.append((data["entity_id"], data["item"]))
        elif domain == "notify":
            self.notified.append((service, data["message"]))
        return None


async def _watch(home, lab, **kw):
    watch = StockWatch(home.hass, lab, todo_list=kw.get("todo_list", "todo.test_list"),
                       notify=kw.get("notify", "notify.mobile_app_test"), texts=TEXTS)
    return watch


async def _low_coffee(home=None, **kw):
    """Coffee measured in bags, level 2, one bag on hand: low."""
    home = home or _Home()
    lab = await _lab()
    await _bag(lab, status="open")
    await lab.async_set_stock_measure("coffee", "bags")
    await lab.async_set_stock_level("coffee", 2)
    await lab.async_set_stock_low_state("coffee", False)
    watch = await _watch(home, lab, **kw)
    return home, lab, watch


def _events(home):
    return [e for e, _ in home.fired]


async def test_going_low_adds_one_item_and_sends_one_notification():
    home, lab, watch = await _low_coffee()
    await watch.async_refresh()
    assert home.added == [("todo.test_list", "Coffee beans")]
    assert home.notified == [("mobile_app_test", "Coffee: running low. Bags left: 1. Added to Shopping list.")]
    assert _events(home) == ["xbloom_stock_low"]
    assert lab.stock_item("coffee") == "uid-1"
    await watch.async_refresh()
    assert len(home.added) == 1 and len(home.notified) == 1 and _events(home) == ["xbloom_stock_low"]


async def test_an_item_already_on_the_list_in_any_case_is_not_added_and_never_ticked_off():
    own = {"summary": "coffee BEANS", "uid": "own", "status": "needs_action"}
    home, lab, watch = await _low_coffee(_Home(items=[own]))
    await watch.async_refresh()
    assert home.added == [] and lab.stock_item("coffee") is None
    assert home.notified == [("mobile_app_test", "Coffee: running low. Bags left: 1.")]
    await _bag(lab, status="unopened")
    await watch.async_refresh()
    assert _events(home) == ["xbloom_stock_low", "xbloom_stock_restored"] and home.completed == []


async def test_restored_ticks_off_only_the_item_coffee_lab_added():
    home, lab, watch = await _low_coffee()
    await watch.async_refresh()
    await _bag(lab, status="unopened")
    await watch.async_refresh()
    assert home.completed == [("todo.test_list", "uid-1")] and lab.stock_item("coffee") is None
    assert len(home.notified) == 1


async def test_an_item_already_ticked_off_is_not_ticked_again_on_restore():
    home, lab, watch = await _low_coffee()
    await watch.async_refresh()
    home.items[0]["status"] = "completed"
    await _bag(lab, status="unopened")
    await watch.async_refresh()
    assert home.completed == [] and lab.stock_item("coffee") is None


async def test_a_restart_while_low_reminds_nothing():
    home, lab, watch = await _low_coffee()
    await lab.async_set_stock_low_state("coffee", True)
    await watch.async_refresh()
    assert home.added == home.notified == home.fired == []


async def test_the_first_run_seeds_silently():
    home, lab, watch = await _low_coffee()
    await lab.async_set_stock_low_state("coffee", None)
    await watch.async_refresh()
    assert lab.stock_low_state("coffee") is True
    assert home.added == home.notified == home.fired == []


async def test_raising_the_level_above_the_stock_is_a_low_crossing():
    home, lab, watch = await _low_coffee()
    await lab.async_set_stock_level("coffee", 1)
    await watch.async_refresh()
    assert home.fired == []
    await lab.async_set_stock_level("coffee", 5)
    await watch.async_refresh()
    assert _events(home) == ["xbloom_stock_low"]


async def test_delivery_that_fails_is_logged_and_not_retried():
    home, lab, watch = await _low_coffee(_Home(fail={"todo.add_item", "notify.mobile_app_test"}))
    await watch.async_refresh()
    assert lab.stock_low_state("coffee") is True and _events(home) == ["xbloom_stock_low"]
    home.fail.clear()
    await watch.async_refresh()
    assert home.added == [] and home.notified == []


async def test_a_kind_never_kept_reminds_nothing():
    home, lab, watch = await _low_coffee()
    await lab.async_set_stock_low_state("tea", False)
    await watch.async_refresh()
    assert [d["kind"] for _, d in home.fired] == ["coffee"]


async def test_the_events_carry_every_figure():
    home, lab, watch = await _low_coffee()
    await watch.async_refresh()
    [(_, data)] = home.fired
    assert data["kind"] == "coffee" and data["measure"] == "bags" and data["level"] == 2
    assert (data["value"], data["bags"], data["amount"], data["unknown"]) == (1, 1, 250.0, [])
    assert {"cups", "days"} <= set(data)


async def test_without_a_list_or_phone_the_events_still_fire():
    home, lab, watch = await _low_coffee(todo_list=None, notify=None)
    await watch.async_refresh()
    assert _events(home) == ["xbloom_stock_low"] and home.added == home.notified == []


async def test_buy_again_adds_the_coffee_unless_another_bag_of_it_is_on_hand():
    home = _Home()
    lab = await _lab()
    finished = await _bag(lab, status="finished", roaster="Test Roaster")
    watch = await _watch(home, lab)
    await watch.async_buy_again(finished)
    assert home.added == [("todo.test_list", "Kenya, Test Roaster")]
    assert home.notified == [("mobile_app_test", "Time to buy Kenya, Test Roaster again. Added to Shopping list.")]
    assert _events(home) == ["xbloom_buy_again"]

    home = _Home()
    await _bag(lab, status="unopened", roaster="Test Roaster")
    watch = await _watch(home, lab)
    await watch.async_buy_again(finished)
    assert home.added == home.notified == home.fired == []
