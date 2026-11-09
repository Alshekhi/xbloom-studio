"""Managing recipes: a picker of its own, a button per action, Restore for the archive."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import button as button_module
from custom_components.xbloom.button import (
    XBloomArchiveRecipeButton,
    XBloomDeleteSelectedRecipeButton,
    XBloomRestoreArchivedRecipeButton,
)
from custom_components.xbloom.select import (
    XBloomArchivedRecipeSelect,
    XBloomLibraryRecipeSelect,
)

SELECTS = {
    "xbloom_recipe_select": "select.xbloom_studio_recipe",
    "xbloom_library_recipe_select": "select.xbloom_studio_recipe_to_manage",
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


@pytest.mark.parametrize("remove", [False, True])
async def test_archive_acts_on_the_recipe_to_manage(remove):
    entity, coordinator, registry = _press(XBloomArchiveRecipeButton, {
        "select.xbloom_studio_recipe": _state("Ethiopia", id="r-1"),
        "select.xbloom_studio_recipe_to_manage": _state("Kenya", id="r-2"),
    })
    entity._remove = remove
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_archive_recipe.assert_awaited_once_with("r-2", remove_from_cloud=remove)


async def test_delete_acts_on_the_recipe_to_manage():
    entity, coordinator, registry = _press(XBloomDeleteSelectedRecipeButton, {
        "select.xbloom_studio_recipe": _state("Ethiopia", id="r-1"),
        "select.xbloom_studio_recipe_to_manage": _state("Kenya", id="r-2"),
    })
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_delete_recipe.assert_awaited_once_with("r-2")


@pytest.mark.parametrize("cls", [XBloomArchiveRecipeButton, XBloomDeleteSelectedRecipeButton])
async def test_nothing_is_done_until_a_recipe_to_manage_is_picked(cls):
    entity, coordinator, registry = _press(cls, {
        "select.xbloom_studio_recipe": _state("Ethiopia", id="r-1"),
        "select.xbloom_studio_recipe_to_manage": _state("unknown"),
    })
    entity._remove = False
    with patch.object(button_module.er, "async_get", return_value=registry):
        with pytest.raises(HomeAssistantError) as caught:
            await entity.async_press()
    assert caught.value.translation_key == "no_recipe_selected"
    coordinator.async_delete_recipe.assert_not_called()
    coordinator.async_archive_recipe.assert_not_called()


@pytest.mark.parametrize("remove, signed_in, available", [
    (False, False, True), (False, True, True), (True, False, False), (True, True, True),
])
def test_removing_from_the_cloud_is_offered_only_signed_in(remove, signed_in, available):
    entity = XBloomArchiveRecipeButton.__new__(XBloomArchiveRecipeButton)
    entity.coordinator = MagicMock(last_update_success=True, cloud_logged_in=signed_in)
    entity._remove = remove
    assert entity.available is available


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


async def test_the_recipe_to_manage_starts_empty_and_is_picked_by_id():
    entity = _select(XBloomLibraryRecipeSelect)
    entity.coordinator.data = [{"id": "a", "name": "Kenya"}, {"id": "b", "name": "Kenya"}]
    assert entity.current_option is None
    assert entity.extra_state_attributes is None
    await entity.async_select_option("Kenya (2)")
    assert entity.current_option == "Kenya (2)"
    assert entity.extra_state_attributes == {"id": "b"}


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
