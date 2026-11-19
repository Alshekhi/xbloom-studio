"""Entities that only matter during a step on the dashboard start hidden.

A verdict picker, a version to keep, a finished bag's question: each has
nothing to show between its moments, which Home Assistant renders as
"unknown" on the integration's page. They stay working for the dashboard,
automations and the AI tools, only folded away on the device page. New
installs register them hidden; an existing install hides them once.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.xbloom.button import (
    XBloomArchiveRecipeButton,
    XBloomDeleteSelectedRecipeButton,
    XBloomRestoreArchivedRecipeButton,
)
from custom_components.xbloom.coffee_lab.entities import (
    BagQuestionSensor,
    BuyAgainSelect,
    CupIssueSelect,
    RateBrewSelect,
    RatingQuestionSensor,
)
from custom_components.xbloom.select import XBloomArchivedRecipeSelect, XBloomLibraryRecipeSelect
from custom_components.xbloom.versions import (
    KeepVersionButton,
    LeaveRecipeButton,
    NextChangeSensor,
    UseNextChangeButton,
    VersionToKeepSensor,
)
from custom_components.xbloom.workflow_entities import WORKFLOW_ENTITIES, hide_workflow_entities

HIDDEN_CLASSES = (
    XBloomArchiveRecipeButton, XBloomDeleteSelectedRecipeButton, XBloomRestoreArchivedRecipeButton,
    BagQuestionSensor, BuyAgainSelect, CupIssueSelect, RateBrewSelect, RatingQuestionSensor,
    XBloomArchivedRecipeSelect, XBloomLibraryRecipeSelect,
    KeepVersionButton, LeaveRecipeButton, NextChangeSensor, UseNextChangeButton, VersionToKeepSensor,
)


def test_workflow_entities_register_hidden() -> None:
    for cls in HIDDEN_CLASSES:
        assert cls._attr_entity_registry_visible_default is False, cls.__name__


def test_the_list_names_each_hidden_entity() -> None:
    assert set(WORKFLOW_ENTITIES) == {
        "xbloom_coffee_lab_rating_question", "xbloom_coffee_lab_rate_brew",
        "xbloom_coffee_lab_cup_issue", "xbloom_coffee_lab_bag_question",
        "xbloom_coffee_lab_buy_again",
        "xbloom_next_change", "xbloom_version_to_keep", "xbloom_use_next_change",
        "xbloom_make_version_the_recipe", "xbloom_save_version_as_new",
        "xbloom_leave_recipe_unchanged",
        "xbloom_library_recipe_select", "xbloom_archived_recipe_select",
        "xbloom_delete_selected_recipe_button", "xbloom_archive_recipe_button",
        "xbloom_archive_recipe_remove_from_cloud_button",
        "xbloom_restore_archived_recipe_button",
    }


def _entry(unique_id, hidden_by=None):
    return SimpleNamespace(entity_id=f"x.{unique_id}", unique_id=unique_id, hidden_by=hidden_by)


def test_an_existing_install_hides_them_once_and_nothing_else() -> None:
    registry = MagicMock()
    entries = [
        _entry("xbloom_coffee_lab_rate_brew"),
        _entry("xbloom_next_change", hidden_by="user"),   # already hidden by the person
        _entry("xbloom_brew_status_sensor"),              # a reading, stays visible
    ]
    hide_workflow_entities(registry, entries, hider="integration")
    registry.async_update_entity.assert_called_once_with(
        "x.xbloom_coffee_lab_rate_brew", hidden_by="integration")


async def test_the_migration_hides_them_once_and_moves_the_entry_on() -> None:
    from unittest.mock import patch

    from custom_components.xbloom import async_migrate_entry

    hass = MagicMock()
    entry = SimpleNamespace(version=3, minor_version=1, entry_id="e1", data={})

    def _update(_entry, **changes):
        for key, value in changes.items():
            setattr(_entry, key, value)

    hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
    from homeassistant.helpers import entity_registry as er
    registry = MagicMock()
    with patch.object(er, "async_get", return_value=registry, create=True), \
            patch.object(er, "async_entries_for_config_entry",
                         return_value=[_entry("xbloom_coffee_lab_buy_again"),
                                       _entry("xbloom_run_recipe_action_button")], create=True), \
            patch.object(er, "RegistryEntryHider", SimpleNamespace(INTEGRATION="integration"),
                         create=True):
        assert await async_migrate_entry(hass, entry) is True
        assert entry.minor_version == 2
        registry.async_update_entity.assert_called_once_with(
            "x.xbloom_coffee_lab_buy_again", hidden_by="integration")
        registry.async_remove.assert_called_once_with("x.xbloom_run_recipe_action_button")
        registry.async_update_entity.reset_mock()
        await async_migrate_entry(hass, entry)          # already done: nothing again
        registry.async_update_entity.assert_not_called()
