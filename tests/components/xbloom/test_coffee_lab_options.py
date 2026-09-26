"""Adding and editing bags in Configure."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.xbloom.config_flow import XBloomOptionsFlow

from .test_coffee_lab_lab import _bag, _lab


def _flow(lab):
    entry = MagicMock()
    entry.runtime_data = SimpleNamespace(
        coffee_lab=lab, coordinator=SimpleNamespace(cloud_logged_in=False)
    )
    flow = XBloomOptionsFlow(entry)
    flow.config_entry = entry
    flow.hass = MagicMock()
    return flow


async def test_bags_are_offered_only_while_coffee_lab_is_on():
    off = await _flow(None).async_step_init()
    assert "add_bag" not in off["menu_options"]
    on = await _flow(await _lab()).async_step_init()
    assert {"add_bag", "edit_bag"} <= set(on["menu_options"])


async def test_adding_a_bag_with_an_amount_counts_it_down():
    lab = await _lab()
    result = await _flow(lab).async_step_add_bag(
        {"name": "Kenya", "remaining_g": 250.0, "status": "unopened", "roaster": ""}
    )
    assert result["type"] == "create_entry"
    [bean] = await lab.store.async_list_beans()
    assert (bean.name, bean.tracked, bean.remaining_g, bean.roaster) == ("Kenya", True, 250.0, "")


async def test_a_bag_needs_a_name():
    lab = await _lab()
    result = await _flow(lab).async_step_add_bag({"name": "  ", "status": "unopened"})
    assert result["errors"] == {"name": "required"}
    assert await lab.store.async_list_beans() == []


async def test_editing_with_no_bags_says_so():
    result = await _flow(await _lab()).async_step_edit_bag()
    assert result == {"type": "abort", "reason": "no_bags"}


async def test_editing_a_bag_keeps_its_id_and_a_new_amount_starts_counting():
    lab = await _lab()
    bag = await _bag(lab, tracked=False, remaining_g=None, status="open")
    flow = _flow(lab)
    form = await flow.async_step_edit_bag({"bag": bag.id})
    assert form["step_id"] == "edit_bag_details"
    result = await flow.async_step_edit_bag_details(
        {"name": "Kenya AA", "status": "open", "remaining_g": 120.0, "country": "Kenya"}
    )
    assert result["type"] == "create_entry"
    after = await lab.store.async_get_bean(bag.id)
    assert (after.name, after.country, after.tracked, after.remaining_g) == (
        "Kenya AA", "Kenya", True, 120.0
    )


async def test_a_field_emptied_in_the_form_is_cleared():
    lab = await _lab()
    bag = await _bag(lab, status="open", roaster="Somewhere", bag_size_g=250.0)
    flow = _flow(lab)
    await flow.async_step_edit_bag({"bag": bag.id})
    # The form sends no key at all for a field someone emptied.
    await flow.async_step_edit_bag_details({"name": "Kenya", "status": "open"})
    after = await lab.store.async_get_bean(bag.id)
    assert (after.roaster, after.bag_size_g) == ("", None)
