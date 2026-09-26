"""Archiving a recipe: it leaves the library whole, and can come back.

Signed in, the library is the cloud. An archived recipe kept there is only
hidden; one removed from it is created again on restore. Signed out, the
library is local and the cloud is never touched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.storage import (
    CLOUD_KEPT, CLOUD_NONE, CLOUD_REMOVED, XBloomRecipeArchive,
)

from .test_coordinator import CLOUD_RECIPE, CREDS, LOCAL_RECIPE, _make


class _Store:
    def __init__(self):
        self.saved = None

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data


def _archive():
    archive = XBloomRecipeArchive.__new__(XBloomRecipeArchive)
    archive._store = _Store()
    archive._cache = None
    return archive


def _signed_in(cloud_list):
    coord = _make(creds=CREDS)
    coord.archive = _archive()
    session = MagicMock()
    session.list_recipes = AsyncMock(return_value=list(cloud_list))
    session.delete_recipe = AsyncMock()
    session.create_recipe = AsyncMock()
    coord._session = lambda: session
    coord.data = list(cloud_list)
    return coord, session


def _signed_out(local_list):
    coord = _make(stored=local_list)
    coord.archive = _archive()
    coord.data = list(local_list)
    return coord


async def test_kept_in_the_cloud_is_only_hidden_here():
    coord, session = _signed_in([CLOUD_RECIPE])
    entry = await coord.async_archive_recipe("9001", remove_from_cloud=False)
    assert entry["cloud"] == CLOUD_KEPT
    session.delete_recipe.assert_not_called()
    # The next refresh still gets it from the cloud, and hides it.
    coord._async_library = AsyncMock(return_value=[CLOUD_RECIPE])
    assert await coord._async_update_data() == []


async def test_removed_from_the_cloud_lives_only_in_the_archive():
    coord, session = _signed_in([CLOUD_RECIPE])
    entry = await coord.async_archive_recipe("9001", remove_from_cloud=True)
    assert entry["cloud"] == CLOUD_REMOVED
    session.delete_recipe.assert_awaited_once_with("9001")
    assert coord.archive.get("9001")["recipe"] == CLOUD_RECIPE


async def test_a_failed_cloud_delete_leaves_it_in_the_library():
    coord, session = _signed_in([CLOUD_RECIPE])
    session.delete_recipe.side_effect = HomeAssistantError("cloud down")
    with pytest.raises(HomeAssistantError):
        await coord.async_archive_recipe("9001", remove_from_cloud=True)
    assert coord.archive.get("9001") is None


async def test_signed_out_it_leaves_the_local_library():
    coord = _signed_out([LOCAL_RECIPE])
    entry = await coord.async_archive_recipe("local-1", remove_from_cloud=False)
    assert entry["cloud"] == CLOUD_NONE
    coord.store.async_delete.assert_awaited_once_with("local-1")


async def test_signed_out_the_cloud_cannot_be_asked_for():
    coord = _signed_out([LOCAL_RECIPE])
    with pytest.raises(HomeAssistantError) as caught:
        await coord.async_archive_recipe("local-1", remove_from_cloud=True)
    assert caught.value.translation_key == "cloud_sign_in_required"
    assert coord.archive.get("local-1") is None


async def test_an_unknown_recipe_is_refused():
    coord = _signed_out([LOCAL_RECIPE])
    with pytest.raises(HomeAssistantError) as caught:
        await coord.async_archive_recipe("nope", remove_from_cloud=False)
    assert caught.value.translation_key == "recipe_not_found"


async def test_restoring_one_still_in_the_cloud_shows_it_again():
    coord, session = _signed_in([CLOUD_RECIPE])
    await coord.async_archive_recipe("9001", remove_from_cloud=False)
    assert await coord.async_restore_recipe("9001") == "shown"
    session.create_recipe.assert_not_called()
    assert coord.archive.get("9001") is None


async def test_restoring_one_gone_from_the_cloud_creates_it_again():
    coord, session = _signed_in([CLOUD_RECIPE])
    await coord.async_archive_recipe("9001", remove_from_cloud=True)
    session.list_recipes.return_value = []
    assert await coord.async_restore_recipe("9001") == "added"
    session.create_recipe.assert_awaited_once_with(CLOUD_RECIPE)


async def test_restoring_signed_out_returns_it_to_the_local_library():
    coord = _signed_out([LOCAL_RECIPE])
    await coord.async_archive_recipe("local-1", remove_from_cloud=False)
    assert await coord.async_restore_recipe("local-1") == "local"
    coord.store.async_replace.assert_awaited_once_with(LOCAL_RECIPE)


async def test_a_failed_restore_keeps_it_archived():
    coord, session = _signed_in([CLOUD_RECIPE])
    await coord.async_archive_recipe("9001", remove_from_cloud=True)
    session.list_recipes.return_value = []
    session.create_recipe.side_effect = HomeAssistantError("cloud down")
    with pytest.raises(HomeAssistantError):
        await coord.async_restore_recipe("9001")
    assert coord.archive.get("9001") is not None


async def test_restoring_what_is_not_archived_is_refused():
    coord = _signed_out([])
    await coord.archive.async_load()
    with pytest.raises(HomeAssistantError) as caught:
        await coord.async_restore_recipe("9001")
    assert caught.value.translation_key == "archived_recipe_not_found"


async def test_the_archive_survives_a_restart():
    archive = _archive()
    await archive.async_add(CLOUD_RECIPE, "2026-09-26T00:00:00+00:00", CLOUD_KEPT)
    again = _archive()
    again._store = archive._store
    await again.async_load()
    assert again.ids() == {"9001"}
