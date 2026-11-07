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
from homeassistant.components.text import TextEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from xbloom.community import SORTS

from .community import ANY_ORIGIN, CommunityBrowser
from .const import DOMAIN


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
        ],
        "button": [
            CommunitySearchButton(browser),
            CommunitySuggestButton(browser, entry),
            CommunityAddButton(browser),
        ],
        "sensor": [CommunityMatchesSensor(browser)],
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
