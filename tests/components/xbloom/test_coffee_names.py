"""A new bag's country and process, in the hub's words (coffee_names.py).

The hub is faked: its lists in English and in another language. What is
tested is that a name the hub knows is kept as the hub's English name, that
one it does not know is kept as typed and reported, and that matching bags
and choosing a bag use the same names.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from . import test_init as _ti  # noqa: F401

from custom_components.xbloom import coffee_names, community as cm, suggestions
from custom_components.xbloom.coffee_lab import actions
from custom_components.xbloom.coffee_lab.models import Bean, Brew
from custom_components.xbloom.coffee_names import HubNames, name_key

from .test_coffee_lab_lab import _lab

CRITERIA = {
    "en": {"originList": [{"name": "Ethiopia", "value": "7"}, {"name": "Colombia", "value": "4"}],
           "processingList": [{"name": "Natural", "value": "1"},
                              {"name": "Anaerobic Fermentation", "value": "6"},
                              {"name": "Semi-Washed Process", "value": "4"}]},
    "zh": {"originList": [{"name": "埃塞俄比亚", "value": "7"}], "processingList": []},
    "ar": {"originList": [], "processingList": []},
}


class FakeHubClient:
    def __init__(self, session, language=None):
        self.language = language

    async def criteria(self):
        return CRITERIA[self.language]


@pytest.fixture
def hub():
    with patch.object(coffee_names, "XBloomCommunityClient", FakeHubClient):
        yield HubNames(MagicMock())


def test_names_compare_without_case_hyphens_or_process_words():
    assert name_key("Semi-washed process") == name_key("semi washed") == "semi washed"
    assert name_key("Anaerobic") == name_key("Anaerobic Fermentation")
    assert name_key("Natural Anaerobic") != name_key("Natural")


async def test_a_known_name_in_any_form_or_language_becomes_the_hubs(hub):
    assert await hub.async_canonical("country", "ethiopia") == "Ethiopia"
    assert await hub.async_canonical("country", "埃塞俄比亚") == "Ethiopia"
    assert await hub.async_canonical("process", "anaerobic") == "Anaerobic Fermentation"
    assert await hub.async_canonical("process", "semi washed") == "Semi-Washed Process"
    assert await hub.async_canonical("country", "Bolivia") is None


async def test_a_new_bag_is_kept_in_the_hubs_words_and_the_rest_reported(hub):
    lab = await _lab()
    lab.hub_names = hub
    facts = await actions.add_bean(lab, {"name": "Test Bag", "country": "ethiopia ",
                                         "process": "Natural Anaerobic"})
    assert facts["added"]["country"] == "Ethiopia"
    assert facts["added"]["process"] == "Natural Anaerobic", "kept as typed, never refused"
    assert facts["not_on_hub"] == {"process": "Natural Anaerobic"}


async def test_correcting_a_bag_checks_its_names_too(hub):
    lab = await _lab()
    lab.hub_names = hub
    await actions.add_bean(lab, {"name": "Test Bag"})
    facts = await actions.update_bean(lab, {"bean": "Test Bag", "process": "anaerobic"})
    assert facts["updated"]["process"] == "Anaerobic Fermentation"
    assert "not_on_hub" not in facts


async def test_a_bag_is_added_as_typed_when_the_hub_cannot_be_read():
    lab = await _lab()
    lab.hub_names = MagicMock(async_canonical=AsyncMock(side_effect=aiohttp.ClientError()))
    facts = await actions.add_bean(lab, {"name": "Test Bag", "country": "ethiopia"})
    assert facts["added"]["country"] == "ethiopia"
    assert facts["unchecked"] == ["country"]


def test_an_older_bags_process_still_matches_the_hubs_name():
    bag = Bean(id="new", name="New Bag", status="open", country="Ethiopia", process="Anaerobic Fermentation")
    old = Bean(id="old", name="Old Bag", status="finished", country="ethiopia", process="Anaerobic")
    brews = [Brew(id="b", brewed_at="2026-10-01", recorded_at="2026-10-01", dose_g=15.0,
                  brewer="xBloom Studio", bean_id="old", recipe="Alpha")]
    [found] = suggestions.rank(bag, [bag, old], brews, [{"name": "Alpha"}])
    assert (found.name, found.matched) == ("Alpha", "origin_process")


async def test_the_hub_is_searched_by_its_own_name(hub):
    client = MagicMock()
    client.search = AsyncMock(return_value={"recipes": [{"id": 1, "name": "Test Recipe", "dose_g": 15}]})
    await cm.suggest(client, [], "ethiopia", "anaerobic", names=hub)
    kwargs = client.search.await_args.kwargs
    assert (kwargs["origins"], kwargs["processes"]) == (["Ethiopia"], ["Anaerobic Fermentation"])


# ── Choosing another bag ─────────────────────────────────────────────────────


async def test_the_lab_says_when_the_bag_in_use_changes_and_only_then():
    lab = await _lab()
    first = await actions.add_bean(lab, {"name": "First Bag"})
    second = await actions.add_bean(lab, {"name": "Second Bag"})
    chosen = []
    lab.on_bag_chosen = chosen.append
    await lab.async_select(first["added"]["id"])
    await lab.async_select(first["added"]["id"])
    await lab.async_select(second["added"]["id"])
    await lab.async_select(None)
    assert chosen == [first["added"]["id"], second["added"]["id"], None]


def _browser():
    hass = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    with patch.object(cm, "async_dispatcher_send"):
        browser = cm.CommunityBrowser(hass, "entry", MagicMock(), MagicMock(), MagicMock())
    browser.own = [suggestions.OwnSuggestion("Mine", 2, "this_bag", "")]
    browser.suggestions = [{"id": 1, "name": "Theirs"}]
    browser.choice = "own:Mine"
    return browser, hass


async def test_choosing_another_bag_drops_the_last_bags_suggestions_and_asks_again():
    browser, hass = _browser()
    lab = SimpleNamespace(active_bean_id="second")
    with patch.object(cm, "async_dispatcher_send"), \
            patch.object(browser, "async_suggest_for_bag", AsyncMock()) as asked:
        browser.bag_chosen(lab, "second")
        assert (browser.own, browser.suggestions, browser.choice) == (None, [], None)
        [task] = [c.args[0] for c in hass.async_create_task.call_args_list]
        await task
    asked.assert_awaited_once_with(lab)


async def test_a_bag_already_changed_again_is_not_suggested_for():
    browser, hass = _browser()
    lab = SimpleNamespace(active_bean_id="third")
    with patch.object(cm, "async_dispatcher_send"), \
            patch.object(browser, "async_suggest_for_bag", AsyncMock()) as asked:
        browser.bag_chosen(lab, "second")
        await hass.async_create_task.call_args.args[0]
    asked.assert_not_awaited()


async def test_no_bag_in_use_clears_and_asks_nothing():
    browser, hass = _browser()
    with patch.object(cm, "async_dispatcher_send"):
        browser.bag_chosen(SimpleNamespace(active_bean_id=None), None)
    assert browser.own is None and not hass.async_create_task.called


async def test_english_names_still_work_when_another_language_fails():
    class ChineseDown(FakeHubClient):
        async def criteria(self):
            if self.language == "zh":
                raise aiohttp.ClientError()
            return await super().criteria()

    with patch.object(coffee_names, "XBloomCommunityClient", ChineseDown):
        names = HubNames(MagicMock())
        assert await names.async_canonical("country", "ethiopia") == "Ethiopia"
        assert names._names is None, "asked for again next time"


async def test_a_name_made_only_of_process_words_matches_nothing(hub):
    assert await hub.async_canonical("process", "Process") is None
