"""A coffee's country, process, variety and roast, in the community hub's words.

A bag's country and process are typed by a person or an assistant, so the
same coffee can arrive as "Ethiopia", "ethiopia" or in Arabic, a process as
"Anaerobic" where the hub says "Anaerobic Fermentation", a roast as "light"
where it says "Light Roast". Suggestions match bags on these words, against
each other and against the hub, so a bag's are rewritten to the hub's own
English name when one is meant. A bag's tasting notes stay as typed; the hub's
flavor names are found in them (`async_flavors_in`).

A name the hub does not list — a country it has no recipes from, a process it
does not name — is kept as typed, never refused: the bag exists either way.

`name_key` is the comparison: case, hyphens and the words that only say "this
is a process" or "a roast" ("process", "fermentation", "roast", …) are
ignored, and a hub name with alternatives ("Geisha/Gesha") answers to each.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import aiohttp
from xbloom.community import XBloomCommunityClient
from xbloom.exceptions import XBloomAPIError

# The hub's lists, and which of a bag's fields each names. "flavor" is no
# field of its own: its names are found in a bag's tasting notes.
LISTS = {
    "country": "originList", "process": "processingList",
    "varietal": "varietalList", "roast": "roastList", "flavor": "flavorList",
}
# The languages a name is accepted in: the hub's English names are the ones
# kept, and the others it is spoken to in map onto them.
LANGUAGES = ("en", "ar", "zh")
# Adding a bag waits for this, so a hub that does not answer must not hold it.
LOOKUP_TIMEOUT = 5
# A language that did not answer is asked for again after this, in seconds.
RETRY_AFTER = 600
_NOISE = {"process", "processing", "processed", "fermentation", "fermented", "method", "roast"}


def name_key(text: Any) -> str:
    """What two names are compared by: "Semi-washed process" == "semi washed".

    Punctuation separates words too, so a name is found in "jasmine, honey".
    """
    words = re.split(r"[\s\-_/,;:.()&+\u060c\u061b]+", str(text or "").casefold())
    return " ".join(w for w in words if w and w not in _NOISE)


class HubNames:
    """The hub's origin and process names, read once, in every language."""

    def __init__(self, session: Any) -> None:
        self._session = session
        # list name → name_key → the hub's English name
        self._names: dict[str, dict[str, str]] | None = None
        # Set while another language's names are missing: when to ask again.
        # Until then the names that did load are used, so one language not
        # answering is not waited on at every lookup.
        self._retry_at: float | None = None

    async def _async_load(self) -> dict[str, dict[str, str]]:
        if self._names is not None and (self._retry_at is None or time.monotonic() < self._retry_at):
            return self._names
        names: dict[str, dict[str, str]] = {lst: {} for lst in LISTS.values()}
        english: dict[str, dict[str, str]] = {}  # list → value → English name
        complete = True
        for language in LANGUAGES:
            try:
                async with asyncio.timeout(LOOKUP_TIMEOUT):
                    criteria = await XBloomCommunityClient(self._session, language=language).criteria()
            except (XBloomAPIError, aiohttp.ClientError, TimeoutError):
                # Without English nothing can be named; another language only
                # adds what a name may arrive as, so its names are used without
                # it until RETRY_AFTER has passed.
                if language == "en":
                    if self._names is not None:
                        return self._names
                    raise
                complete = False
                continue
            for lst in LISTS.values():
                options = criteria.get(lst, [])
                if language == "en":
                    english[lst] = {o["value"]: o["name"] for o in options}
                # Every option's whole name first, then the alternatives in a
                # name like "Green/Vegetative": an alternative never takes the
                # place of an option that is named that on its own.
                whole = [(o["name"], o["value"]) for o in options]
                parts = [(a, o["value"]) for o in options if "/" in str(o["name"]) for a in str(o["name"]).split("/")]
                for alias, value in whole + parts:
                    canonical = english.get(lst, {}).get(value)
                    if canonical and (key := name_key(alias)):
                        names[lst].setdefault(key, canonical)
        self._names = names
        self._retry_at = None if complete else time.monotonic() + RETRY_AFTER
        return names

    async def async_canonical(self, field: str, text: str) -> str | None:
        """The hub's English name for a bag's country or process; None if it has none.

        Raises what the hub client raises when the hub cannot be read, and a
        TimeoutError after LOOKUP_TIMEOUT seconds a language.
        """
        key = name_key(text)
        if not key:
            return None
        names = await self._async_load()
        return names[LISTS[field]].get(key)

    async def async_keys(self, field: str, values: Any) -> set[str]:
        """What `values` are compared by: the hub's name's key, or their own.

        So "light", "Light Roast" and the Arabic for it are one roast, and a
        name the hub does not list still matches itself. Raises as
        `async_canonical` does.
        """
        names = (await self._async_load())[LISTS[field]]
        keys = set()
        for value in values or ():
            if key := name_key(value):
                keys.add(name_key(names.get(key) or value))
        return keys

    async def async_flavors_in(self, text: str) -> set[str]:
        """The keys of the hub's flavor names said in `text`, whole words only.

        Raises as `async_canonical` does.
        """
        words = f" {name_key(text)} "
        if not words.strip():
            return set()
        names = (await self._async_load())[LISTS["flavor"]]
        found = set()
        # Longest first, each taking its words: "dark chocolate" is not also
        # "chocolate".
        for key in sorted(names, key=len, reverse=True):
            if f" {key} " in words:
                found.add(name_key(names[key]))
                words = words.replace(f" {key} ", " | ")
        return found
