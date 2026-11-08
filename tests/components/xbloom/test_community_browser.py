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
        "SuggestRecipeButton", "UseSuggestedRecipeButton", "AnotherForYouButton",
        "AddAccountRecipeButton", "AddAccountRecipeButton", "AddAccountRecipeButton",
    ]
    assert [type(e).__name__ for e in ce.entities_for(entry, "select")][-4:] == [
        "SuggestedRecipeSelect", "DrinkSelect", "AccountRecipeSelect", "AccountRecipeSelect",
    ]
    assert [type(e).__name__ for e in ce.entities_for(entry, "switch")] == ["ShowXpodRecipesSwitch"]
    entry.runtime_data.community = None
    assert ce.entities_for(entry, "select") == []



# ── Suggesting a recipe for the bag in use ───────────────────────────────────


def _bag(country="Ethiopia", process="Natural", name="Test Bag"):
    lab = MagicMock()
    lab.active_bean_id = "bag"
    lab.async_active_bean = AsyncMock(return_value=SimpleNamespace(
        id="bag", country=country, process=process, name=name))
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
    assert browser.own_facts() == [{"name": "Mine", "brews": 3, "matched": "this_bag",
                                    "last_brewed": "2026-11-01", "versions": []}]
    assert browser.picked_id == 4021


async def test_your_own_are_kept_when_the_hub_cannot_be_reached():
    browser, client, *_ = _browser()
    client.search.side_effect = cm.XBloomAPIError("down")
    own = [cm.OwnSuggestion("Mine", 1, "origin", "")]
    with patch.object(cm, "async_own_suggestions", AsyncMock(return_value=own)):
        await browser.async_suggest_for_bag(_bag())
    assert browser.own == own


SECOND = {"id": 4022, "name": "Test Peru Iced", "machine": "Studio", "share_url": LINK}


def _registry(browser):
    browser._hass.services.async_call = AsyncMock()
    registry = MagicMock()
    registry.async_get_entity_id = MagicMock(return_value="select.xbloom_studio_recipe")
    return patch.object(cm.er, "async_get", return_value=registry)


def _picked(browser):
    return [c.args[2]["option"] for c in browser._hass.services.async_call.await_args_list]


async def _suggested(own, recipes=(LISTED, SECOND)):
    browser, client, share, coordinator = _browser(recipes=recipes)
    with patch.object(cm, "async_own_suggestions", AsyncMock(return_value=own)):
        await browser.async_suggest_for_bag(_bag())
    return browser, client, coordinator


async def test_the_picker_lists_your_own_then_the_community_most_downloaded_first():
    own = [cm.OwnSuggestion("Mine", 3, "this_bag", ""), cm.OwnSuggestion("Other", 1, "origin", "")]
    browser, *_ = await _suggested(own)
    assert browser.choice_keys() == ["own:Mine", "own:Other", "hub:4021", "hub:4022"]
    assert browser.choice == "own:Mine", "your best one is chosen"
    assert browser.picked_id == 4021, "the most downloaded, not a random one"


async def test_using_your_own_choice_picks_it_by_name():
    own = [cm.OwnSuggestion("Mine", 3, "this_bag", ""), cm.OwnSuggestion("Other", 1, "origin", "")]
    browser, _, coordinator = await _suggested(own)
    with _registry(browser):
        await browser.async_choose("own:Other")
        await browser.async_use_choice()
    assert _picked(browser) == ["Other"]
    coordinator.async_add_recipe.assert_not_awaited()


async def test_using_a_community_choice_adds_it_then_picks_it():
    browser, client, coordinator = await _suggested([])
    assert browser.choice == "hub:4021", "with none of your own, the community's first"
    with _registry(browser):
        await browser.async_choose("hub:4022")
        await browser.async_use_choice()
    assert client.detail.await_args_list[-1].args[0] == 4022
    coordinator.async_add_recipe.assert_awaited_once()
    assert _picked(browser) == [browser.added]


async def test_a_community_search_meanwhile_does_not_change_what_is_used():
    browser, client, coordinator = await _suggested([])
    await browser.async_choose("hub:4022")
    await browser.async_search()  # the Community tab picks nothing, the results change
    await browser.async_pick("Test Kenya Hot")
    with _registry(browser):
        await browser.async_use_choice()
    assert client.detail.await_args_list[-1].args[0] == 4022


async def test_use_without_a_suggestion_is_refused():
    browser, *_ = _browser()
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_use_choice()
    assert caught.value.translation_key == "suggestion_none"


async def test_a_community_choice_is_marked_in_the_picker():
    browser, *_ = await _suggested([cm.OwnSuggestion("Mine", 3, "this_bag", "")])
    select = ce.SuggestedRecipeSelect(browser)
    select._community_marker = "community"
    assert select.options == ["Mine", "Test Kenya Hot (community)", "Test Peru Iced (community)"]
    assert select.current_option == "Mine"
    assert select.extra_state_attributes == {"source": "own", "brews": 3, "matched": "this_bag"}
    await select.async_select_option("Test Peru Iced (community)")
    assert browser.choice == "hub:4022"
    assert select.extra_state_attributes["source"] == "community"



async def test_a_suggestion_for_a_bag_no_longer_in_use_is_dropped():
    browser, client, *_ = _browser()
    lab = _bag()

    async def own_then_bag_changes(*args):
        lab.active_bean_id = "other"  # the bag changed while the record was read
        return [cm.OwnSuggestion("Mine", 3, "this_bag", "")]

    with patch.object(cm, "async_own_suggestions", own_then_bag_changes):
        await browser.async_suggest_for_bag(lab)
    assert browser.own is None and browser.choice_keys() == []


async def test_a_hub_timeout_still_offers_your_own_with_the_best_chosen():
    browser, client, *_ = _browser()
    client.search.side_effect = TimeoutError()
    own = [cm.OwnSuggestion("Mine", 1, "origin", "")]
    with patch.object(cm, "async_own_suggestions", AsyncMock(return_value=own)):
        await browser.async_suggest_for_bag(_bag())
    assert browser.choice == "own:Mine" and browser.failed


async def test_a_hub_recipe_never_replaces_one_of_yours_with_the_same_name():
    browser, client, share, coordinator = _browser()
    coordinator.data = [{"name": "Test Kenya Hot"}, {"name": "Test Kenya Hot 2"}]
    await browser.async_search()
    await browser.async_pick("Test Kenya Hot")
    name = await browser.async_add_picked()
    assert name == "Test Kenya Hot 3"
    assert coordinator.async_add_recipe.await_args.args[0]["name"] == "Test Kenya Hot 3"



# ── The app's Recipes tab, signed in ─────────────────────────────────────────


def _pod(rid, name, xpod=False):
    recipe = {"id": str(rid), "name": name, "cup_type_name": "XPOD" if xpod else "OMNI",
              "pod": {"theName": "Tea Leaf"} if name.startswith("Tea") else None,
              "dose_g": 15.0, "water_ratio": 16.0, "grinder_size": 50.0, "pours": [{}, {}]}
    if xpod:
        recipe["pod"] = {"theName": "Test Pod", "origin": "Test Origin\nline", "process": "Natural"}
    return recipe


def _signed_in(browser, coordinator, lists, for_you=None):
    coordinator.cloud_logged_in = True
    coordinator.data = [{"name": "Test Trend"}]

    async def account(kind):
        return for_you if kind == "for_you" else lists.get(kind, [])

    coordinator.async_account_recipes = account


async def test_signed_out_shows_nothing_of_the_account():
    browser, *_ , coordinator = _browser()
    coordinator.cloud_logged_in = False
    await browser.async_load_account()
    assert browser.account_recipes("trending") == [] and browser.for_you is None
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_another_for_you()
    assert caught.value.translation_key == "account_signed_out"


async def test_the_accounts_lists_are_offered_with_xpods_marked_and_hideable():
    browser, *_, coordinator = _browser()
    _signed_in(browser, coordinator, {"trending": [_pod(1, "Test Pod Recipe", xpod=True), _pod(2, "Test Omni")]})
    await browser.async_load_account()
    select = ce.AccountRecipeSelect(browser, "trending")
    assert select.options == ["Test Pod Recipe (xPod)", "Test Omni"]
    facts = select.extra_state_attributes
    assert facts["xpod"] is True and facts["coffee"]["origin"] == "Test Origin line"
    browser.set_show_xpods(False)
    assert select.options == ["Test Omni"] and select.current_option == "Test Omni"


async def test_adding_an_account_recipe_never_replaces_one_of_yours():
    browser, *_, coordinator = _browser()
    _signed_in(browser, coordinator, {"tea": [_pod(9, "Test Trend")]})
    await browser.async_load_account()
    name = await browser.async_add_account("tea")
    assert name == "Test Trend 2"
    added = coordinator.async_add_recipe.await_args.args[0]
    assert added["name"] == "Test Trend 2" and "id" not in added


async def test_for_you_asks_past_a_hidden_xpod():
    browser, *_, coordinator = _browser()
    picks = iter([_pod(1, "Pod One", xpod=True), _pod(2, "Test Filter")])
    coordinator.cloud_logged_in = True

    async def account(kind):
        return next(picks)

    coordinator.async_account_recipes = account
    browser.show_xpods = False
    await browser.async_another_for_you()
    assert browser.for_you["name"] == "Test Filter"


def test_a_tea_recipe_with_a_pod_is_not_an_xpod():
    assert cm.is_xpod(_pod(1, "Tea Test")) is False
    assert cm.is_xpod(_pod(2, "Pod Test", xpod=True)) is True


async def test_picks_for_an_assistant_follow_the_switch_and_carry_the_link():
    browser, *_, coordinator = _browser()
    trend = [{**_pod(1, "Test Pod Recipe", xpod=True), "share_url": LINK}, _pod(2, "Test Omni")]
    _signed_in(browser, coordinator, {"trending": trend})
    picks = await browser.async_picks("trending")
    assert [(p["name"], p["xpod"], p["share_url"]) for p in picks] == [
        ("Test Pod Recipe", True, LINK), ("Test Omni", False, None),
    ]
    browser.set_show_xpods(False)
    assert [p["name"] for p in await browser.async_picks("trending")] == ["Test Omni"]


async def test_picks_are_refused_signed_out():
    browser, *_, coordinator = _browser()
    coordinator.cloud_logged_in = False
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_picks("tea")
    assert caught.value.translation_key == "account_signed_out"


async def test_saving_a_shared_link_reads_only_xbloom_links_and_numbers_a_clash():
    browser, _, share, coordinator = _browser()
    coordinator.data = [{"name": "Another Name"}]
    with pytest.raises(HomeAssistantError) as caught:
        await browser.async_save_link("https://example.invalid/?id=abc")
    assert caught.value.translation_key == "share_link_invalid"
    share.get_recipe_by_share_id.assert_not_awaited()
    assert await browser.async_save_link(LINK) == "Another Name 2"
    assert "id" not in coordinator.async_add_recipe.await_args.args[0]


# ── Hot or iced ──────────────────────────────────────────────────────────────


def test_a_recipe_is_iced_by_how_little_water_it_pours():
    assert [cm.drink_of({"water_ratio": r}) for r in (8.5, 12, 12.5, 16, None, "x")] == [
        "iced", "iced", "hot", "hot", None, None,
    ]


async def test_an_iced_suggestion_reads_more_recipes_and_keeps_only_iced_ones():
    browser, client, *_ = _browser()
    hot = {**LISTED, "id": 1, "name": "Hot", "water_ratio": 16}
    iced = {**LISTED, "id": 2, "name": "Iced", "water_ratio": 9}
    client.search.return_value = {"page": 1, "total_pages": 1, "total": 2, "recipes": [hot, iced]}
    found = await cm.suggest(client, [], "Ethiopia", None, drink="iced")
    assert [r["name"] for r in found["recipes"]] == ["Iced"]
    assert client.search.await_args.kwargs["page_size"] == cm.ICED_POOL


async def test_choosing_a_drink_suggests_again_for_the_bag_in_use_from_its_own_recipes():
    browser, client, _, coordinator = _browser()
    coordinator.data = [{"name": "Mine Hot", "water_ratio": 16}, {"name": "Mine Iced", "water_ratio": 9}]
    lab = _bag()
    seen = []

    async def own(lab_, bag, library):
        seen.append([r["name"] for r in library])
        return []

    tasks = []
    browser._hass.async_create_task = tasks.append
    with patch.object(cm, "async_own_suggestions", own):
        browser.set_drink(lab, "iced")
        assert browser.drink == "iced" and len(tasks) == 1, "the bag in use is suggested for again"
        await tasks[0]
    assert seen == [["Mine Iced"]]
    assert client.search.await_args.kwargs["page_size"] == cm.ICED_POOL
