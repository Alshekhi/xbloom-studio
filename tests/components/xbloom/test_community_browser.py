"""The dashboard's community search (community.py, community_entities.py).

The hub client is xbloom-py's and is faked here; what is tested is what the
browser asks of it, what the entities show, and that a recipe reaches the
library only through its share link and only for the Studio.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from . import test_init as _ti  # noqa: F401

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import community as cm
from custom_components.xbloom import community_entities as ce

LINK = "https://share-h5.xbloom.com/?id=abc%3D%3D"
LISTED = {"id": 4021, "name": "Test Kenya Hot", "machine": "Studio", "share_url": LINK}
DETAIL = {
    **LISTED, "author": "Test\nAuthor", "official": False, "origin": ["Kenya"],
    "process": ["Washed"], "roast": "Light Roast", "flavor": ["Plum", "\u0007"],
    "description": "Bright.\n\nClean.", "dose_g": 16.0, "water_ratio": 15.0,
    "grinder_size": 52.0, "rpm": 90, "likes": 3,
    "pours": [{"name": "Bloom", "volume_ml": 40.0, "temperature_c": 92.0, "pattern": 2, "pause_s": 30}],
}


def _browser(detail=DETAIL, recipes=(LISTED,)):
    client = MagicMock()
    client.search = AsyncMock(return_value={"page": 1, "total_pages": 1, "total": len(recipes), "recipes": list(recipes)})
    client.detail = AsyncMock(return_value=detail)
    client.criteria = AsyncMock(return_value={"originList": [{"name": "Kenya", "value": "9"}]})
    share = MagicMock()
    share.share_id_from_url = MagicMock(return_value="abc==")
    share.get_recipe_by_share_id = AsyncMock(return_value={"id": "77001", "name": "Another Name", "pours": []})
    coordinator = MagicMock()
    coordinator.async_add_recipe = AsyncMock()
    with patch.object(cm, "async_dispatcher_send"):
        browser = cm.CommunityBrowser(MagicMock(), "entry", client, share, coordinator)
    return browser, client, share, coordinator


@pytest.fixture(autouse=True)
def _quiet_signal():
    with patch.object(cm, "async_dispatcher_send"):
        yield


async def test_search_asks_for_studio_recipes_with_the_chosen_filters():
    browser, client, *_ = _browser()
    browser.set_keyword("kenya")
    browser.set_origin("Kenya")
    browser.set_sort("likes")
    await browser.async_search()
    client.search.assert_awaited_once_with(
        "kenya", machine="Studio", origins=["Kenya"], sort="likes", page_size=cm.RESULTS_SHOWN,
    )
    assert browser.matches == 1 and browser.results == [LISTED]


async def test_any_origin_sends_no_origin_filter():
    browser, client, *_ = _browser()
    await browser.async_search()
    assert client.search.await_args.kwargs["origins"] == []
    assert client.search.await_args.args == (None,)


async def test_a_failed_search_is_translated_and_marked():
    browser, client, *_ = _browser()
    client.search.side_effect = ValueError("not on the hub: Atlantis")
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_search()
    assert caught.value.translation_key == "community_failed"
    assert browser.failed is True


async def test_picking_reads_the_recipe_and_cleans_its_text():
    browser, *_ = _browser()
    await browser.async_search()
    await browser.async_pick("Test Kenya Hot")
    facts = browser.picked_facts()
    assert facts["author"] == "Test Author"
    assert facts["flavor"] == ["Plum"]
    assert facts["description"] == "Bright. Clean."
    assert facts["pours"] == [{"volume_ml": 40.0, "temperature_c": 92.0, "pattern": "spiral", "pause_s": 30}]


async def test_a_recipe_for_another_machine_cannot_be_picked():
    browser, *_ = _browser(detail={**DETAIL, "machine": "Original"})
    await browser.async_search()
    with pytest.raises(HomeAssistantError):
        await browser.async_pick("Test Kenya Hot")
    assert browser.detail is None


async def test_add_copies_the_recipe_through_its_link_under_the_picked_name():
    browser, _, share, coordinator = _browser()
    await browser.async_search()
    await browser.async_pick("Test Kenya Hot")
    assert await browser.async_add_picked() == "Test Kenya Hot"
    share.share_id_from_url.assert_called_once_with(LINK)
    added = coordinator.async_add_recipe.await_args.args[0]
    assert added["name"] == "Test Kenya Hot" and added["id"] == "77001"
    assert browser.added == "Test Kenya Hot"


async def test_add_without_a_pick_is_refused():
    browser, *_ = _browser()
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_add_picked()
    assert caught.value.translation_key == "community_none_picked"


async def test_a_link_that_is_not_xbloom_is_never_followed():
    browser, _, share, coordinator = _browser(detail={**DETAIL, "share_url": "https://evil.invalid/?id=a"})
    await browser.async_search()
    await browser.async_pick("Test Kenya Hot")
    with pytest.raises(HomeAssistantError):
        await browser.async_add_picked()
    share.get_recipe_by_share_id.assert_not_awaited()
    coordinator.async_add_recipe.assert_not_awaited()


async def test_two_results_with_one_name_are_both_reachable():
    browser, *_ = _browser(recipes=(LISTED, {**LISTED, "id": 4022}))
    await browser.async_search()
    assert [label for label, _ in browser.labelled()] == ["Test Kenya Hot", "Test Kenya Hot (2)"]


async def test_the_origin_picker_offers_any_then_the_hubs_origins():
    browser, *_ = _browser()
    await browser.async_load_origins()
    select = ce.CommunityOriginSelect(browser)
    assert select.options == ["any", "Kenya"]
    assert select.current_option == "any"


async def test_the_recipe_picker_says_how_the_search_went():
    browser, *_ = _browser()
    select = ce.CommunityRecipeSelect(browser)
    assert select.extra_state_attributes["matches"] is None, "not searched yet"
    await browser.async_search()
    attrs = select.extra_state_attributes
    assert (attrs["matches"], attrs["shown"], attrs["picked"]) == (1, 1, None)
    assert select.options == ["Test Kenya Hot"]


def test_every_platform_gets_its_entities_and_nothing_without_a_browser():
    entry = MagicMock()
    entry.runtime_data.community = _browser()[0]
    assert [type(e).__name__ for e in ce.entities_for(entry, "button")] == [
        "CommunitySearchButton", "CommunitySuggestButton", "CommunityAddButton",
        "SuggestRecipeButton", "UseSuggestedRecipeButton", "AddAndUseCommunityRecipeButton",
    ]
    entry.runtime_data.community = None
    assert ce.entities_for(entry, "select") == []



# ── Suggesting a recipe for the bag in use ───────────────────────────────────


def _bag(country="Ethiopia", process="Natural", name="Test Bag"):
    lab = MagicMock()
    lab.async_active_bean = AsyncMock(return_value=SimpleNamespace(country=country, process=process, name=name))
    return lab


async def test_suggestion_matches_the_bag_and_sorts_by_downloads():
    browser, client, *_ = _browser()
    await browser.async_suggest(_bag())
    kw = client.search.await_args.kwargs
    assert (kw["machine"], kw["origins"], kw["processes"], kw["sort"]) == ("Studio", ["Ethiopia"], ["Natural"], "downloads")
    assert browser.suggested_for == "Test Bag"
    assert browser.basis == {"origin": "Ethiopia", "process": "Natural"}
    assert browser.picked_id == 4021, "one suggestion is picked and read in full"


async def test_suggestion_widens_when_the_hub_does_not_know_the_process():
    browser, client, *_ = _browser()
    client.search.side_effect = [ValueError("not on the hub: Other"), client.search.return_value]
    await browser.async_suggest(_bag(process="Other"))
    assert client.search.await_args.kwargs["processes"] == []
    assert browser.basis == {"origin": "Ethiopia", "process": None}


async def test_recipes_already_in_the_library_are_not_suggested():
    browser, client, _, coordinator = _browser()
    coordinator.data = [{"name": "test kenya hot"}]
    empty = {"page": 1, "total_pages": 0, "total": 0, "recipes": []}
    client.search.side_effect = [client.search.return_value, empty, empty]
    await browser.async_suggest(_bag())
    assert browser.results == [] and browser.matches == 0
    assert client.search.await_count == 3, "bag, then origin alone, then any recipe"


async def test_without_coffee_lab_the_suggestion_is_any_studio_recipe():
    browser, client, *_ = _browser()
    await browser.async_suggest(None)
    kw = client.search.await_args.kwargs
    assert (kw["origins"], kw["processes"]) == ([], [])
    assert browser.suggested_for is None


async def test_a_new_search_is_no_longer_a_suggestion():
    browser, *_ = _browser()
    await browser.async_suggest(_bag())
    await browser.async_search()
    assert browser.suggested is False and browser.suggested_for is None



# ── Fitting a community suggestion to the bag and the drippers ───────────────


async def test_a_recipe_needing_more_coffee_than_is_left_is_not_suggested():
    browser, client, *_ = _browser()
    big = {**LISTED, "id": 1, "name": "Big", "dose_g": 20.0}
    small = {**LISTED, "id": 2, "name": "Small", "dose_g": 15.0}
    client.search.return_value = {"page": 1, "total_pages": 1, "total": 2, "recipes": [big, small]}
    found = await cm.suggest(client, [], "Ethiopia", None, remaining_g=16.0)
    assert [r["name"] for r in found["recipes"]] == ["Small"]


async def test_recipes_for_the_librarys_drippers_come_first():
    browser, client, *_ = _browser()
    pod = {**LISTED, "id": 1, "name": "Pod", "cup_type": 1}
    omni = {**LISTED, "id": 2, "name": "Omni", "cup_type": 2}
    client.search.return_value = {"page": 1, "total_pages": 1, "total": 2, "recipes": [pod, omni]}
    found = await cm.suggest(client, [{"name": "Mine", "cup_type": 2}], None, None)
    assert [r["name"] for r in found["recipes"]] == ["Omni", "Pod"]


def test_an_uncounted_bag_has_no_remaining_limit():
    assert cm.bag_remaining_g(SimpleNamespace(tracked=False, remaining_g=10.0)) is None
    assert cm.bag_remaining_g(SimpleNamespace(tracked=True, remaining_g=10.0)) == 10.0


# ── The Brew tab: your own recipes, and using one ────────────────────────────


async def test_suggest_for_bag_offers_your_own_and_a_community_one():
    browser, client, *_ = _browser()
    own = [cm.OwnSuggestion("Mine", 3, "this_bag", "2026-11-01")]
    with patch.object(cm, "async_own_suggestions", AsyncMock(return_value=own)):
        await browser.async_suggest_for_bag(_bag())
    assert browser.own_facts() == [{"name": "Mine", "brews": 3, "matched": "this_bag", "last_brewed": "2026-11-01"}]
    assert browser.picked_id == 4021


async def test_your_own_are_kept_when_the_hub_cannot_be_reached():
    browser, client, *_ = _browser()
    client.search.side_effect = cm.XBloomAPIError("down")
    own = [cm.OwnSuggestion("Mine", 1, "origin", "")]
    with patch.object(cm, "async_own_suggestions", AsyncMock(return_value=own)):
        await browser.async_suggest_for_bag(_bag())
    assert browser.own == own


async def test_use_and_add_and_use_pick_the_recipe_in_the_picker():
    browser, *_ = _browser()
    browser._hass.services.async_call = AsyncMock()
    registry = MagicMock()
    registry.async_get_entity_id = MagicMock(return_value="select.xbloom_studio_recipe")
    browser.own = [cm.OwnSuggestion("Mine", 1, "origin", "")]
    with patch.object(cm.er, "async_get", return_value=registry):
        await browser.async_use_own()
        await browser.async_search()
        await browser.async_pick("Test Kenya Hot")
        await browser.async_add_and_use()
    picked = [c.args[2]["option"] for c in browser._hass.services.async_call.await_args_list]
    assert picked == ["Mine", "Test Kenya Hot"]


async def test_use_without_a_suggestion_is_refused():
    browser, *_ = _browser()
    browser.own = []
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_use_own()
    assert caught.value.translation_key == "suggestion_none"
