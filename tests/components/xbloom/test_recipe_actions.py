"""The recipe menu: an action, a Run button, and Restore for the archive."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import button as button_module
from custom_components.xbloom.button import (
    XBloomRestoreArchivedRecipeButton,
    XBloomRunRecipeActionButton,
)
from custom_components.xbloom.select import (
    XBloomArchivedRecipeSelect,
    XBloomRecipeActionSelect,
)

SELECTS = {
    "xbloom_recipe_select": "select.xbloom_studio_recipe",
    "xbloom_recipe_action_select": "select.xbloom_studio_recipe_action",
    "xbloom_archived_recipe_select": "select.xbloom_studio_archived_recipe",
}


def _press(cls, states):
    coordinator = MagicMock()
    coordinator.async_delete_recipe = AsyncMock(return_value=True)
    coordinator.async_archive_recipe = AsyncMock()
    coordinator.async_restore_recipe = AsyncMock(return_value="shown")
    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity.hass = MagicMock()
    entity.hass.states.get = lambda entity_id: states.get(entity_id)
    registry = MagicMock()
    registry.async_get_entity_id = lambda platform, domain, unique_id: SELECTS[unique_id]
    return entity, coordinator, registry


def _state(value, **attributes):
    return SimpleNamespace(state=value, attributes=attributes)


@pytest.mark.parametrize("action, remove", [("archive", False), ("archive_remove_from_cloud", True)])
async def test_run_archives_the_picked_recipe(action, remove):
    entity, coordinator, registry = _press(XBloomRunRecipeActionButton, {
        "select.xbloom_studio_recipe": _state("Kenya", id="r-2"),
        "select.xbloom_studio_recipe_action": _state(action),
    })
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_archive_recipe.assert_awaited_once_with("r-2", remove_from_cloud=remove)


async def test_run_deletes_by_id():
    entity, coordinator, registry = _press(XBloomRunRecipeActionButton, {
        "select.xbloom_studio_recipe": _state("Kenya", id="r-2"),
        "select.xbloom_studio_recipe_action": _state("delete"),
    })
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_delete_recipe.assert_awaited_once_with("r-2")


@pytest.mark.parametrize("states, key", [
    ({"select.xbloom_studio_recipe_action": _state("delete")}, "no_recipe_selected"),
    ({"select.xbloom_studio_recipe": _state("Kenya", id="r-2"),
      "select.xbloom_studio_recipe_action": _state("unknown")}, "no_recipe_action_selected"),
])
async def test_run_does_nothing_without_both_picks(states, key):
    entity, coordinator, registry = _press(XBloomRunRecipeActionButton, states)
    with patch.object(button_module.er, "async_get", return_value=registry):
        with pytest.raises(HomeAssistantError) as caught:
            await entity.async_press()
    assert caught.value.translation_key == key
    coordinator.async_delete_recipe.assert_not_called()
    coordinator.async_archive_recipe.assert_not_called()


async def test_restore_brings_back_the_picked_archived_recipe():
    entity, coordinator, registry = _press(XBloomRestoreArchivedRecipeButton, {
        "select.xbloom_studio_archived_recipe": _state("Kenya", id="r-2"),
    })
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_restore_recipe.assert_awaited_once_with("r-2")


async def test_restore_with_nothing_picked_is_refused():
    entity, coordinator, registry = _press(XBloomRestoreArchivedRecipeButton, {})
    with patch.object(button_module.er, "async_get", return_value=registry):
        with pytest.raises(HomeAssistantError) as caught:
            await entity.async_press()
    assert caught.value.translation_key == "no_archived_recipe_selected"


def _select(cls, *, signed_in=False, archived=()):
    coordinator = MagicMock()
    coordinator.cloud_logged_in = signed_in
    coordinator.archive.entries = [
        {"recipe": r, "archived_at": "2026-09-26T00:00:00+00:00", "cloud": "kept"} for r in archived
    ]
    coordinator.archive.get = lambda rid: next(
        (e for e in coordinator.archive.entries if e["recipe"]["id"] == rid), None)
    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity.async_write_ha_state = MagicMock()
    entity._action = None
    entity._current_id = None
    return entity


def test_removing_from_the_cloud_is_offered_only_signed_in():
    assert _select(XBloomRecipeActionSelect).options == ["archive", "delete"]
    assert _select(XBloomRecipeActionSelect, signed_in=True).options == [
        "archive", "archive_remove_from_cloud", "delete"]


async def test_an_archived_recipe_is_picked_by_id_even_under_a_shared_name():
    entity = _select(XBloomArchivedRecipeSelect, archived=[
        {"id": "a", "name": "Kenya"}, {"id": "b", "name": "Kenya"}])
    assert entity.options == ["Kenya", "Kenya (2)"]
    await entity.async_select_option("Kenya (2)")
    assert entity.current_option == "Kenya (2)"
    assert entity.extra_state_attributes["id"] == "b"
    assert entity.extra_state_attributes["cloud"] == "kept"


def test_the_archive_select_is_empty_only_when_the_archive_is():
    assert _select(XBloomArchivedRecipeSelect).current_option is None
    entity = _select(XBloomArchivedRecipeSelect, archived=[{"id": "a", "name": "Kenya"}])
    assert entity.current_option == "Kenya"
    assert entity.extra_state_attributes["id"] == "a"
