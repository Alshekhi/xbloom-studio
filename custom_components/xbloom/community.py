"""The community hub: Studio recipes other people shared.

What every part of the integration that shows hub recipes has in common —
the services, the AI tool and the dashboard entities:

  * Only Studio recipes are offered. A recipe for another machine is refused
    even by id, because nothing here has checked that one brews correctly on
    the Studio.
  * Hub text was typed by strangers. `hub_text` reduces it to one capped line
    of printable text before it is shown or handed to an agent, and
    `hub_share_url` passes on a share link only when it is one.

`CommunityBrowser` holds the dashboard's search: the words, origin and order
asked for, the results, the recipe picked and its detail. Its entities read it
and are told of every change over one dispatcher signal.
"""
from __future__ import annotations

import logging
import random
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from xbloom import spec
from xbloom.client import XBloomClient
from xbloom.community import XBloomCommunityClient
from xbloom.exceptions import XBloomAPIError

from .const import COMMUNITY_MACHINE, DOMAIN
from .tool_common import fail

_LOGGER = logging.getLogger(__name__)

HUB_SHORT = 80     # a name, an author, a note
HUB_LONG = 600     # a description
SHARE_PREFIX = "https://share-h5.xbloom.com/?"
# How many matches the dashboard's picker offers; a longer list is a longer
# swipe through it, and the search words narrow it better than scrolling.
RESULTS_SHOWN = 20
# The origin option that means "no origin filter".
ANY_ORIGIN = "any"


def hub_text(value: Any, limit: int = HUB_SHORT) -> str | None:
    """Stranger-typed text as one line of printable text, at most `limit`."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value or ""))
    text = " ".join(text.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def hub_texts(values: Any) -> list[str]:
    return [t for t in (hub_text(v) for v in values or []) if t]


def hub_share_url(recipe: dict[str, Any]) -> str | None:
    """The recipe's share link, only when it is an xBloom share link."""
    link = str(recipe.get("share_url") or "")
    if link.startswith(SHARE_PREFIX) and link.isprintable() and " " not in link:
        return link
    return None


class NotForThisMachine(Exception):
    """A hub recipe for a machine other than the Studio."""


async def studio_recipe(client: XBloomCommunityClient, recipe_id: int) -> dict[str, Any]:
    """One hub recipe in full, refused unless it is for the Studio."""
    recipe = await client.detail(recipe_id)
    if recipe.get("machine") != COMMUNITY_MACHINE:
        raise NotForThisMachine(
            f"recipe {recipe.get('id')} is for the "
            f"{recipe.get('machine') or 'another machine'}, not the {COMMUNITY_MACHINE}"
        )
    return recipe


# A suggestion is drawn from the most downloaded Studio recipes for the bag:
# the first SUGGEST_POOL of them, less any already in the library, of which
# SUGGESTIONS are offered.
SUGGEST_POOL = 20
SUGGESTIONS = 5


async def suggest(
    client: XBloomCommunityClient,
    library: list[dict[str, Any]],
    country: str | None,
    process: str | None,
) -> dict[str, Any]:
    """Community recipes worth trying for a coffee of this origin and process.

    The hub recommends nothing itself, so this asks for its most downloaded
    Studio recipes matching the coffee, and widens the search when nothing
    new is left: origin and process, then origin alone, then any. A name the
    hub does not list (a bag's process of "Other") counts as nothing found.
    `origin` and `process` in the answer say what was matched.
    """
    have = {str(r.get("name") or "").casefold() for r in library}
    country = (country or "").strip() or None
    process = (process or "").strip() or None
    tried: list[tuple[str | None, str | None]] = []
    for attempt in ((country, process), (country, None), (None, None)):
        if attempt in tried:
            continue
        tried.append(attempt)
        origin, proc = attempt
        try:
            page = await client.search(
                machine=COMMUNITY_MACHINE,
                origins=[origin] if origin else [],
                processes=[proc] if proc else [],
                sort="downloads",
                page_size=SUGGEST_POOL,
            )
        except ValueError:
            continue
        fresh = [
            r for r in page["recipes"]
            if (hub_text(r.get("name")) or "").casefold() not in have
        ]
        if fresh:
            return {"origin": origin, "process": proc, "recipes": fresh[:SUGGESTIONS]}
    return {"origin": None, "process": None, "recipes": []}


async def active_bag(lab: Any) -> Any:
    """The bag in use, when Coffee Lab is on and one is chosen."""
    if lab is None:
        return None
    return await lab.async_active_bean()


def signal_community(entry_id: str) -> str:
    return f"{DOMAIN}_community_{entry_id}"


class CommunityBrowser:
    """The dashboard's community search, shared by its entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: XBloomCommunityClient,
        share_client: XBloomClient,
        coordinator: Any,
    ) -> None:
        self._hass = hass
        self._signal = signal_community(entry_id)
        self._client = client
        self._share_client = share_client
        self._coordinator = coordinator
        self.keyword = ""
        self.origin = ANY_ORIGIN
        self.sort = "date"
        self.origins: list[str] = []
        # None until a search has run, so "no matches" and "not searched yet"
        # stay apart.
        self.matches: int | None = None
        self.results: list[dict[str, Any]] = []
        self.failed = False
        self.picked_id: int | None = None
        self.detail: dict[str, Any] | None = None
        self.added: str | None = None
        # Set while the results are a suggestion rather than a search: the bag
        # it was made for (None without one) and what of it was matched.
        self.suggested = False
        self.suggested_for: str | None = None
        self.basis: dict[str, str | None] = {}

    @callback
    def _changed(self) -> None:
        async_dispatcher_send(self._hass, self._signal)

    @property
    def signal(self) -> str:
        return self._signal

    async def async_load_origins(self) -> None:
        """The hub's origin names, in the Home Assistant language."""
        try:
            criteria = await self._client.criteria()
        except (XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.warning("xbloom community: could not read the hub's origins: %s", err)
            return
        self.origins = [o["name"] for o in criteria.get("originList", []) if o.get("name")]
        self._changed()

    @callback
    def set_keyword(self, value: str) -> None:
        self.keyword = value
        self._changed()

    @callback
    def set_origin(self, value: str) -> None:
        self.origin = value
        self._changed()

    @callback
    def set_sort(self, value: str) -> None:
        self.sort = value
        self._changed()

    async def async_search(self) -> None:
        self.added = None
        try:
            page = await self._client.search(
                self.keyword or None,
                machine=COMMUNITY_MACHINE,
                origins=[] if self.origin == ANY_ORIGIN else [self.origin],
                sort=self.sort,
                page_size=RESULTS_SHOWN,
            )
        except (ValueError, XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.warning("xbloom community search: %s", err)
            self.failed = True
            self._changed()
            raise fail("community_failed", reason=str(err)) from err
        self.failed = False
        self.suggested = False
        self.suggested_for = None
        self.basis = {}
        self.matches = page["total"]
        self.results = page["recipes"]
        self.picked_id = None
        self.detail = None
        self._changed()

    async def async_suggest(self, lab: Any) -> None:
        """Fill the picker with suggestions for the bag in use, and pick one.

        The pick is drawn at random from the suggestions, so asking again
        offers something else rather than the same recipe every time.
        """
        self.added = None
        bag = await active_bag(lab)
        try:
            found = await suggest(
                self._client, self._coordinator.data or [],
                getattr(bag, "country", None), getattr(bag, "process", None),
            )
        except (XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.warning("xbloom community suggestion: %s", err)
            self.failed = True
            self._changed()
            raise fail("community_failed", reason=str(err)) from err
        self.failed = False
        self.suggested = True
        self.suggested_for = getattr(bag, "name", None)
        self.basis = {"origin": found["origin"], "process": found["process"]}
        self.results = found["recipes"]
        self.matches = len(self.results)
        self.picked_id = None
        self.detail = None
        self._changed()
        if self.results:
            label, _ = random.choice(self.labelled())
            await self.async_pick(label)

    def labelled(self) -> list[tuple[str, dict[str, Any]]]:
        """Each result with the label its picker offers it under."""
        seen: dict[str, int] = {}
        out: list[tuple[str, dict[str, Any]]] = []
        for recipe in self.results:
            name = hub_text(recipe.get("name")) or str(recipe.get("id"))
            seen[name] = seen.get(name, 0) + 1
            out.append((name if seen[name] == 1 else f"{name} ({seen[name]})", recipe))
        return out

    async def async_pick(self, label: str) -> None:
        recipe = next((r for lbl, r in self.labelled() if lbl == label), None)
        if recipe is None:
            return
        self.added = None
        self.picked_id = int(recipe["id"])
        self.detail = None
        self._changed()
        try:
            self.detail = await studio_recipe(self._client, self.picked_id)
        except (NotForThisMachine, XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.warning("xbloom community recipe %s: %s", self.picked_id, err)
            raise fail("community_failed", reason=str(err)) from err
        finally:
            self._changed()

    async def async_add_picked(self) -> str:
        """Copy the picked recipe into the library, through its share link.

        Kept under the name it was picked by: the share link can carry a
        different one, and the recipe is looked for in the library by the name
        it was seen under.
        """
        link = hub_share_url(self.detail or {})
        if self.detail is None or link is None:
            raise fail("community_none_picked")
        try:
            recipe = await self._share_client.get_recipe_by_share_id(
                self._share_client.share_id_from_url(link)
            )
        except (ValueError, XBloomAPIError, aiohttp.ClientError) as err:
            raise fail("community_failed", reason=str(err)) from err
        name = hub_text(self.detail.get("name"), 60) or recipe.get("name")
        await self._coordinator.async_add_recipe({**recipe, "name": name})
        self.added = name
        self._changed()
        return name

    def picked_facts(self) -> dict[str, Any]:
        """The picked recipe as the dashboard shows it, every text cleaned."""
        d = self.detail
        if not d:
            return {}
        return {
            "id": d.get("id"),
            "official": bool(d.get("official")),
            "author": hub_text(d.get("author")),
            "origin": hub_texts(d.get("origin")),
            "process": hub_texts(d.get("process")),
            "roast": hub_text(d.get("roast")),
            "flavor": hub_texts(d.get("flavor")),
            "description": hub_text(d.get("description"), HUB_LONG),
            "dose_g": d.get("dose_g"),
            # A hub recipe's water_ratio is the ratio's denominator (xbloom-py's
            # CommunityRecipe), never total water.
            "ratio": d.get("water_ratio"),
            "grind_size": d.get("grinder_size"),
            "rpm": d.get("rpm"),
            "likes": d.get("likes"),
            "pours": [
                {
                    "volume_ml": p.get("volume_ml"),
                    "temperature_c": p.get("temperature_c"),
                    "pattern": spec.PATTERN_API_TO_NAME.get(p.get("pattern")),
                    "pause_s": p.get("pause_s"),
                }
                for p in d.get("pours") or []
            ],
        }
