"""The dashboard's community hub search, as entities.

Search words, an origin and an order go in; Search fills the Community Recipe
picker with the first matches, or Suggest with recipes for the bag in use; picking one reads it in full into that
picker's attributes; Add Community Recipe copies it into the library, where it
is brewed like any other recipe. All of them read one CommunityBrowser and
redraw on its signal.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.translation import async_get_translations

from xbloom.community import SORTS

from .community import ANY_ORIGIN, CommunityBrowser, account_facts, hub_text, is_xpod
from .const import DOMAIN, DRINKS


def entities_for(entry, platform: str) -> list:
    browser: CommunityBrowser | None = getattr(entry.runtime_data, "community", None)
    if browser is None:
        return []
    return {
        "text": [CommunitySearchText(browser)],
        "select": [
            CommunityOriginSelect(browser),
            CommunitySortSelect(browser),
            CommunityRecipeSelect(browser),
            SuggestedRecipeSelect(browser),
            DrinkSelect(browser, entry),
            CommunityListSelect(browser),
            AccountRecipeSelect(browser, "trending"),
            AccountRecipeSelect(browser, "tea"),
        ],
        "button": [
            CommunitySearchButton(browser),
            CommunitySuggestButton(browser, entry),
            CommunityAddButton(browser),
            SuggestRecipeButton(browser, entry),
            UseSuggestedRecipeButton(browser),
            AnotherForYouButton(browser),
            AddAccountRecipeButton(browser, "trending"),
            AddAccountRecipeButton(browser, "tea"),
            AddAccountRecipeButton(browser, "for_you"),
        ],
        "switch": [ShowXpodRecipesSwitch(browser)],
        "sensor": [CommunityMatchesSensor(browser), RecipeSuggestionsSensor(browser), ForYouSensor(browser)],
    }.get(platform, [])


class _CommunityEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, browser: CommunityBrowser) -> None:
        self._browser = browser

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, "xbloom_studio")})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()  # type: ignore[misc]
        self.async_on_remove(  # type: ignore[attr-defined]
            async_dispatcher_connect(self.hass, self._browser.signal, self._redraw)  # type: ignore[attr-defined]
        )

    @callback
    def _redraw(self) -> None:
        self.async_write_ha_state()  # type: ignore[attr-defined]


class CommunitySearchText(_CommunityEntity, TextEntity):
    """Words to look for in community recipe names."""

    _attr_translation_key = "community_search"
    _attr_unique_id = "xbloom_community_search"
    _attr_icon = "mdi:magnify"
    _attr_native_min = 0
    _attr_native_max = 60
    _attr_mode = "text"

    @property
    def native_value(self) -> str:
        return self._browser.keyword

    async def async_set_value(self, value: str) -> None:
        self._browser.set_keyword(value.strip())


class CommunityOriginSelect(_CommunityEntity, SelectEntity):
    """Any origin, or one of the hub's own."""

    _attr_translation_key = "community_origin"
    _attr_unique_id = "xbloom_community_origin"
    _attr_icon = "mdi:earth"

    @property
    def options(self) -> list[str]:
        return [ANY_ORIGIN, *self._browser.origins]

    @property
    def current_option(self) -> str | None:
        return self._browser.origin if self._browser.origin in self.options else ANY_ORIGIN

    async def async_select_option(self, option: str) -> None:
        self._browser.set_origin(option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # In the background: the hub's origin list is not worth delaying
        # startup for, and "any origin" is offered until it arrives.
        self.hass.async_create_background_task(
            self._browser.async_load_origins(), "xbloom community origins",
        )


class CommunitySortSelect(_CommunityEntity, SelectEntity):
    """Newest or most liked first."""

    _attr_translation_key = "community_sort"
    _attr_unique_id = "xbloom_community_sort"
    _attr_icon = "mdi:sort"
    _attr_options = list(SORTS)

    @property
    def current_option(self) -> str | None:
        return self._browser.sort

    async def async_select_option(self, option: str) -> None:
        self._browser.set_sort(option)


class CommunityRecipeSelect(_CommunityEntity, SelectEntity):
    """The matches of the last search; the pick is read in full.

    Its attributes say how the search went — `matches` is None before any
    search — and carry the picked recipe with every stranger-typed text
    already reduced to one capped line.
    """

    _attr_translation_key = "community_recipe"
    _attr_unique_id = "xbloom_community_recipe"
    _attr_icon = "mdi:account-group"

    @property
    def options(self) -> list[str]:
        return [label for label, _ in self._browser.labelled()]

    @property
    def current_option(self) -> str | None:
        for label, recipe in self._browser.labelled():
            if recipe.get("id") == self._browser.picked_id:
                return label
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "matches": self._browser.matches,
            "shown": len(self._browser.results),
            "failed": self._browser.failed,
            "added": self._browser.added,
            "suggested": self._browser.suggested,
            "suggested_for": self._browser.suggested_for,
            "matched_origin": self._browser.basis.get("origin"),
            "matched_process": self._browser.basis.get("process"),
            "picked": self._browser.picked_facts() or None,
        }

    async def async_select_option(self, option: str) -> None:
        await self._browser.async_pick(option)


class CommunitySearchButton(_CommunityEntity, ButtonEntity):
    _attr_translation_key = "search_community"
    _attr_unique_id = "xbloom_search_community"
    _attr_icon = "mdi:magnify"

    async def async_press(self) -> None:
        await self._browser.async_search()


class CommunitySuggestButton(_CommunityEntity, ButtonEntity):
    """Suggest community recipes for the bag in use, and pick one of them."""

    _attr_translation_key = "suggest_community_recipe"
    _attr_unique_id = "xbloom_suggest_community_recipe"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, browser: CommunityBrowser, entry) -> None:
        super().__init__(browser)
        self._entry = entry

    async def async_press(self) -> None:
        await self._browser.async_suggest(getattr(self._entry.runtime_data, "coffee_lab", None))


class CommunityAddButton(_CommunityEntity, ButtonEntity):
    """Copy the picked community recipe into the library."""

    _attr_translation_key = "add_community_recipe"
    _attr_unique_id = "xbloom_add_community_recipe"
    _attr_icon = "mdi:playlist-plus"

    async def async_press(self) -> None:
        await self._browser.async_add_picked()


class CommunityMatchesSensor(_CommunityEntity, SensorEntity):
    """How many Studio recipes the last search matched; unknown before one.

    A number a dashboard can show or hide a section by, which the picker's
    attributes cannot be.
    """

    _attr_translation_key = "community_matches"
    _attr_unique_id = "xbloom_community_matches"
    _attr_icon = "mdi:counter"

    @property
    def native_value(self) -> int | None:
        return None if self._browser.failed else self._browser.matches



# ── The Brew tab: a recipe for the bag in use ────────────────────────────────


class SuggestRecipeButton(_CommunityEntity, ButtonEntity):
    """Your own recipes for the bag in use, and a community one beside them."""

    _attr_translation_key = "suggest_recipe"
    _attr_unique_id = "xbloom_suggest_recipe"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, browser: CommunityBrowser, entry) -> None:
        super().__init__(browser)
        self._entry = entry

    async def async_press(self) -> None:
        await self._browser.async_suggest_for_bag(getattr(self._entry.runtime_data, "coffee_lab", None))


class DrinkSelect(_CommunityEntity, SelectEntity, RestoreEntity):
    """Hot or iced: suggestions for the bag only for that drink, or for any."""

    _attr_translation_key = "drink"
    _attr_unique_id = "xbloom_drink"
    _attr_icon = "mdi:coffee-to-go"
    _attr_options = list(DRINKS)

    def __init__(self, browser: CommunityBrowser, entry) -> None:
        super().__init__(browser)
        self._entry = entry

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in DRINKS:
            self._browser.drink = last.state

    @property
    def current_option(self) -> str:
        return self._browser.drink

    async def async_select_option(self, option: str) -> None:
        self._browser.set_drink(getattr(self._entry.runtime_data, "coffee_lab", None), option)


class SuggestedRecipeSelect(_CommunityEntity, SelectEntity):
    """Every suggestion for the bag in use, your own first, the best chosen.

    A community recipe is offered under its name with a marker saying so, in
    Home Assistant's language, so it is never mistaken for one of your own.
    Its attributes say why the chosen one was suggested.
    """

    _attr_translation_key = "suggested_recipe"
    _attr_unique_id = "xbloom_suggested_recipe"
    _attr_icon = "mdi:lightbulb-on-outline"
    _community_marker = "community"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        strings = await async_get_translations(
            self.hass, self.hass.config.language, "selector", {DOMAIN},
        )
        self._community_marker = strings.get(
            f"component.{DOMAIN}.selector.suggestion_source.options.community",
            self._community_marker,
        )

    def _labels(self) -> list[tuple[str, str]]:
        """(label, key) for each choice; a repeated label is told apart by a number."""
        seen: dict[str, int] = {}
        out = []
        for key in self._browser.choice_keys():
            recipe = self._browser.suggestion(key)
            if recipe is None:
                label = key[4:]
            else:
                name = hub_text(recipe.get("name")) or str(recipe.get("id"))
                label = f"{name} ({self._community_marker})"
            seen[label] = seen.get(label, 0) + 1
            out.append((label if seen[label] == 1 else f"{label} {seen[label]}", key))
        return out

    @property
    def options(self) -> list[str]:
        return [label for label, _ in self._labels()]

    @property
    def current_option(self) -> str | None:
        return next((label for label, key in self._labels() if key == self._browser.choice), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        key = self._browser.choice
        if key is None:
            return {}
        if key.startswith("own:"):
            own = next((o for o in self._browser.own or [] if f"own:{o.name}" == key), None)
            return {"source": "own", "brews": own.brews, "matched": own.matched} if own else {}
        picked = self._browser.picked_facts()
        return {"source": "community", "author": picked.get("author"),
                "official": picked.get("official"), "likes": picked.get("likes")}

    async def async_select_option(self, option: str) -> None:
        key = next((key for label, key in self._labels() if label == option), None)
        if key is not None:
            await self._browser.async_choose(key)


class UseSuggestedRecipeButton(_CommunityEntity, ButtonEntity):
    """Pick the chosen suggestion for brewing, adding a community one first."""

    _attr_translation_key = "use_suggested_recipe"
    _attr_unique_id = "xbloom_use_suggested_recipe"
    _attr_icon = "mdi:check"

    async def async_press(self) -> None:
        await self._browser.async_use_choice()


class RecipeSuggestionsSensor(_CommunityEntity, SensorEntity):
    """How many of your own recipes suit the bag in use; unknown until asked.

    `own` lists them best first, with how many brews counted and the closest
    match among them: this_bag, origin_process or origin.
    """

    _attr_translation_key = "recipe_suggestions"
    _attr_unique_id = "xbloom_recipe_suggestions"
    _attr_icon = "mdi:lightbulb-on-outline"

    @property
    def native_value(self) -> int | None:
        return None if self._browser.own is None else len(self._browser.own)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"own": self._browser.own_facts(), "bag": self._browser.suggested_for}


# ── The app's Recipes tab, for a signed-in account ──────────────────────────


# What the Community tab shows, one list at a time. The account's lists need
# a sign-in; searching the hub does not.
COMMUNITY_LISTS = ("for_you", "trending", "tea", "search")


class CommunityListSelect(_CommunityEntity, SelectEntity, RestoreEntity):
    """Which list the Community tab shows: For You, Trending, Tea or a search.

    Signed out only the search is offered, and it is what is shown.
    """

    _attr_translation_key = "community_list"
    _attr_unique_id = "xbloom_community_list"
    _attr_icon = "mdi:view-list"

    def __init__(self, browser: CommunityBrowser) -> None:
        super().__init__(browser)
        self._choice = COMMUNITY_LISTS[0]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in COMMUNITY_LISTS:
            self._choice = last.state

    @property
    def options(self) -> list[str]:
        return list(COMMUNITY_LISTS) if self._browser.signed_in else ["search"]

    @property
    def current_option(self) -> str:
        return self._choice if self._choice in self.options else self.options[0]

    async def async_select_option(self, option: str) -> None:
        self._choice = option
        self.async_write_ha_state()


class _AccountEntity(_CommunityEntity):
    """Present only while signed in to the xBloom account."""

    @property
    def available(self) -> bool:
        return self._browser.signed_in


class AccountRecipeSelect(_AccountEntity, SelectEntity):
    """Trending or Tea, as the app lists them; the pick's details as attributes.

    An xPod recipe is marked as such, in Home Assistant's language.
    """

    _attr_icon = "mdi:fire"
    _xpod_marker = "xPod"

    def __init__(self, browser: CommunityBrowser, kind: str) -> None:
        super().__init__(browser)
        self._kind = kind
        self._attr_translation_key = f"{kind}_recipe"
        self._attr_unique_id = f"xbloom_{kind}_recipe"
        if kind == "tea":
            self._attr_icon = "mdi:tea"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        strings = await async_get_translations(
            self.hass, self.hass.config.language, "selector", {DOMAIN},
        )
        self._xpod_marker = strings.get(
            f"component.{DOMAIN}.selector.suggestion_source.options.xpod", self._xpod_marker,
        )

    def _labels(self) -> list[tuple[str, str]]:
        seen: dict[str, int] = {}
        out = []
        for recipe in self._browser.account_recipes(self._kind):
            label = hub_text(recipe.get("name")) or str(recipe.get("id"))
            if is_xpod(recipe):
                label = f"{label} ({self._xpod_marker})"
            seen[label] = seen.get(label, 0) + 1
            out.append((label if seen[label] == 1 else f"{label} {seen[label]}", str(recipe.get("id"))))
        return out

    @property
    def options(self) -> list[str]:
        return [label for label, _ in self._labels()]

    @property
    def current_option(self) -> str | None:
        wanted = self._browser.account_pick.get(self._kind)
        return next((label for label, rid in self._labels() if rid == wanted), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return account_facts(self._browser.account_pick_recipe(self._kind))

    async def async_select_option(self, option: str) -> None:
        rid = next((rid for label, rid in self._labels() if label == option), None)
        if rid is not None:
            self._browser.set_account_pick(self._kind, rid)


class ForYouSensor(_AccountEntity, SensorEntity):
    """The recipe the account's For You suggests; its details as attributes."""

    _attr_translation_key = "for_you_recipe"
    _attr_unique_id = "xbloom_for_you_recipe"
    _attr_icon = "mdi:star-shooting-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The account's lists are read here, in the background: a slow
        # account must not hold up setup.
        self.hass.async_create_background_task(
            self._browser.async_load_account(), "xbloom account recipes",
        )

    @property
    def native_value(self) -> str | None:
        recipe = self._browser.for_you
        return hub_text(recipe.get("name")) if recipe else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return account_facts(self._browser.for_you)


class AnotherForYouButton(_AccountEntity, ButtonEntity):
    """Ask For You for another recipe, as the app's Switch does."""

    _attr_translation_key = "another_for_you"
    _attr_unique_id = "xbloom_another_for_you"
    _attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        await self._browser.async_another_for_you()


class AddAccountRecipeButton(_AccountEntity, ButtonEntity):
    """Add the chosen Trending or Tea recipe, or the For You one, to the library."""

    _attr_icon = "mdi:playlist-plus"

    def __init__(self, browser: CommunityBrowser, kind: str) -> None:
        super().__init__(browser)
        self._kind = kind
        self._attr_translation_key = f"add_{kind}_recipe"
        self._attr_unique_id = f"xbloom_add_{kind}_recipe"

    async def async_press(self) -> None:
        await self._browser.async_add_account(self._kind)


class ShowXpodRecipesSwitch(_CommunityEntity, SwitchEntity, RestoreEntity):
    """Whether Trending, Tea and For You offer xPod recipes; on unless turned off."""

    _attr_translation_key = "show_xpod_recipes"
    _attr_unique_id = "xbloom_show_xpod_recipes"
    _attr_icon = "mdi:coffee-maker-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._browser.set_show_xpods(last is None or last.state != "off")

    @property
    def is_on(self) -> bool:
        return self._browser.show_xpods

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._browser.set_show_xpods(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._browser.set_show_xpods(False)
