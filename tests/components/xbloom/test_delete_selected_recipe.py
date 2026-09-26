"""Delete Selected Recipe: by the picked recipe's id, never by guess."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import button as button_module
from custom_components.xbloom.button import XBloomDeleteSelectedRecipeButton


def _button(state):
    coordinator = MagicMock()
    coordinator.async_delete_recipe = AsyncMock(return_value=True)
    entity = XBloomDeleteSelectedRecipeButton.__new__(XBloomDeleteSelectedRecipeButton)
    entity.coordinator = coordinator
    entity.hass = MagicMock()
    entity.hass.states.get = lambda entity_id: state
    registry = MagicMock()
    registry.async_get_entity_id = lambda *a: "select.xbloom_studio_recipe"
    return entity, coordinator, registry


async def test_the_picked_recipe_is_deleted_by_its_id():
    entity, coordinator, registry = _button(SimpleNamespace(attributes={"id": "r-2", "name": "Kenya"}))
    with patch.object(button_module.er, "async_get", return_value=registry):
        await entity.async_press()
    coordinator.async_delete_recipe.assert_awaited_once_with("r-2")


async def test_nothing_picked_deletes_nothing():
    entity, coordinator, registry = _button(SimpleNamespace(attributes={}))
    with patch.object(button_module.er, "async_get", return_value=registry):
        with pytest.raises(HomeAssistantError) as caught:
            await entity.async_press()
    assert caught.value.translation_key == "no_recipe_selected"
    coordinator.async_delete_recipe.assert_not_called()
