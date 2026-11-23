"""Choosing the AI task that writes brew stories, in Configure."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.xbloom.config_flow import XBloomOptionsFlow


def _flow(data=None):
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = dict(data or {})
    entry.runtime_data = SimpleNamespace(coffee_lab=None, coordinator=SimpleNamespace(cloud_logged_in=False))
    flow = XBloomOptionsFlow(entry)
    flow.config_entry = entry
    flow.hass = MagicMock()
    return flow, entry


async def test_brew_stories_is_on_the_menu():
    flow, _ = _flow()
    assert "brew_stories" in (await flow.async_step_init())["menu_options"]


async def test_the_brew_stories_step_shows_a_form_first():
    flow, _ = _flow()
    assert (await flow.async_step_brew_stories())["step_id"] == "brew_stories"


async def test_the_brew_stories_step_saves_and_clears_the_agent():
    flow, entry = _flow({"ble_name": "XBLOOM X"})
    result = await flow.async_step_brew_stories({"story_agent": "ai_task.claude"})
    assert result["type"] == "create_entry"
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved == {"ble_name": "XBLOOM X", "story_agent": "ai_task.claude"}
    flow.hass.config_entries.async_reload.assert_called_once_with("e1")

    flow, entry = _flow({"ble_name": "XBLOOM X", "story_agent": "ai_task.claude"})
    await flow.async_step_brew_stories({})
    assert flow.hass.config_entries.async_update_entry.call_args.kwargs["data"] == {"ble_name": "XBLOOM X"}
