"""Local recipe library backed by HA's `Store` helper.

One file per config entry, persisted under
``<config>/.storage/xbloom.recipes.<entry_id>``. The schema is just the list
of Recipe dicts that ``vendor.xbloom.client._parse_recipe`` produces; we
don't transform on the way in or out.

API:
    store = XBloomRecipeStore(hass, entry_id)
    await store.async_load()                 # -> list[dict]
    await store.async_add(recipe)            # name-keyed insert/replace
    await store.async_remove(name)           # name-keyed delete
    await store.async_replace(recipe)        # id-keyed upsert (Phase 9 edit)
    await store.async_delete(table_id)       # id-keyed delete (Phase 9)
    await store.async_replace_all(recipes)   # bulk overwrite
    await store.async_clear()                # wipe (entry uninstall)
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
_STORE_KEY_FMT = "xbloom.recipes.{entry_id}"


class XBloomRecipeStore:
    """Per-entry recipe library."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, _STORE_KEY_FMT.format(entry_id=entry_id)
        )
        self._cache: list[dict] | None = None

    async def async_load(self) -> list[dict]:
        """Load recipes from disk (cached after the first read)."""
        if self._cache is not None:
            return self._cache
        data = await self._store.async_load()
        if data is None:
            self._cache = []
        else:
            self._cache = list(data.get("recipes", []))
        _LOGGER.debug("xbloom store loaded %d recipes for entry %s",
                      len(self._cache), self._entry_id)
        return self._cache

    async def async_replace_all(self, recipes: list[dict]) -> None:
        """Overwrite the whole library with `recipes`. Used by the migration
        bootstrap (Commit 2 imports the old captured-body snapshot once)."""
        self._cache = list(recipes)
        await self._store.async_save({"recipes": self._cache})

    async def async_add(self, recipe: dict) -> None:
        """Add a recipe. Replaces an existing one with the same name (case-
        sensitive). Saves to disk. Raises ValueError if the recipe is missing
        a non-empty `name`."""
        name = (recipe.get("name") or "").strip()
        if not name:
            raise ValueError("Recipe is missing a non-empty 'name' field")

        recipes = await self.async_load()
        # Replace if name already present, else append. Preserve insertion order
        # so the select dropdown is predictable.
        existing_idx = next(
            (i for i, r in enumerate(recipes) if r.get("name") == name), None
        )
        if existing_idx is not None:
            recipes[existing_idx] = recipe
            _LOGGER.info("xbloom store: replaced existing recipe %r", name)
        else:
            recipes.append(recipe)
            _LOGGER.info("xbloom store: added recipe %r (now %d total)",
                         name, len(recipes))
        self._cache = recipes
        await self._store.async_save({"recipes": recipes})

    async def async_remove(self, name: str) -> bool:
        """Remove the recipe with this name. Returns True if it existed."""
        recipes = await self.async_load()
        before = len(recipes)
        recipes = [r for r in recipes if r.get("name") != name]
        removed = len(recipes) < before
        if removed:
            self._cache = recipes
            await self._store.async_save({"recipes": recipes})
            _LOGGER.info("xbloom store: removed recipe %r", name)
        return removed

    async def async_replace(self, recipe: dict) -> None:
        """Insert or overwrite a recipe by its 'id' (tableId).

        Used by the Phase 9 edit flow where the user re-saves a recipe
        under the same tableId. Preserves all keys including the `meta`
        sub-object (D-60) — this is a full-dict overwrite with no key
        filtering, matching `async_replace_all` semantics on a single slot.
        """
        table_id = (recipe.get("id") or "").strip()
        if not table_id:
            raise ValueError("Recipe is missing 'id'")
        recipes = await self.async_load()
        idx = next(
            (i for i, r in enumerate(recipes) if r.get("id") == table_id),
            None,
        )
        if idx is None:
            recipes.append(recipe)
            _LOGGER.info("xbloom store: added recipe id=%s", table_id)
        else:
            recipes[idx] = recipe
            _LOGGER.info("xbloom store: replaced recipe id=%s", table_id)
        self._cache = recipes
        await self._store.async_save({"recipes": recipes})

    async def async_delete(self, table_id: str) -> bool:
        """Delete a recipe by its 'id' (tableId). Returns True if removed."""
        recipes = await self.async_load()
        before = len(recipes)
        recipes = [r for r in recipes if r.get("id") != table_id]
        removed = len(recipes) < before
        if removed:
            self._cache = recipes
            await self._store.async_save({"recipes": recipes})
            _LOGGER.info("xbloom store: deleted recipe id=%s", table_id)
        return removed

    async def async_clear(self) -> None:
        """Wipe the library. (Used on entry uninstall.)"""
        await self._store.async_remove()
        self._cache = []
