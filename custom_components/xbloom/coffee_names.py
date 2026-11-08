"""A coffee's country and process, in the community hub's words.

A bag's country and process are typed by a person or an assistant, so the
same coffee can arrive as "Ethiopia", "ethiopia" or in Arabic, and a process
as "Anaerobic" where the hub says "Anaerobic Fermentation". Suggestions match
bags on these words, against each other and against the hub, so a bag's are
rewritten to the hub's own English name when one is meant.

A name the hub does not list — a country it has no recipes from, a process it
does not name — is kept as typed, never refused: the bag exists either way.

`name_key` is the comparison: case, hyphens and the words that only say "this
is a process" ("process", "fermentation", …) are ignored.
"""
from __future__ import annotations

import re
from typing import Any

from xbloom.community import XBloomCommunityClient

# The hub's lists, and which of a bag's fields each names.
LISTS = {"country": "originList", "process": "processingList"}
# The languages a name is accepted in: the hub's English names are the ones
# kept, and the others it is spoken to in map onto them.
LANGUAGES = ("en", "ar", "zh")
_NOISE = {"process", "processing", "processed", "fermentation", "fermented", "method"}


def name_key(text: Any) -> str:
    """What two names are compared by: "Semi-washed process" == "semi washed"."""
    words = re.split(r"[\s\-_/]+", str(text or "").casefold())
    return " ".join(w for w in words if w and w not in _NOISE)


class HubNames:
    """The hub's origin and process names, read once, in every language."""

    def __init__(self, session: Any) -> None:
        self._session = session
        # list name → name_key → the hub's English name
        self._names: dict[str, dict[str, str]] | None = None

    async def _async_load(self) -> dict[str, dict[str, str]]:
        if self._names is not None:
            return self._names
        english: dict[str, dict[str, str]] = {}  # list → value → English name
        names: dict[str, dict[str, str]] = {lst: {} for lst in LISTS.values()}
        for language in LANGUAGES:
            criteria = await XBloomCommunityClient(self._session, language=language).criteria()
            for lst in LISTS.values():
                for option in criteria.get(lst, []):
                    if language == "en":
                        english.setdefault(lst, {})[option["value"]] = option["name"]
                    canonical = english.get(lst, {}).get(option["value"])
                    if canonical and option["name"]:
                        names[lst].setdefault(name_key(option["name"]), canonical)
        self._names = names
        return names

    async def async_canonical(self, field: str, text: str) -> str | None:
        """The hub's English name for a bag's country or process; None if it has none.

        Raises what the hub client raises when the hub cannot be read.
        """
        names = await self._async_load()
        return names[LISTS[field]].get(name_key(text))
