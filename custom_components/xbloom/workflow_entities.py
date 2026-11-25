"""Entities that only matter during a step on the dashboard, hidden by default.

Each has nothing to show between its moments — no brew waiting for a verdict,
no version to keep, no recipe picked to manage — which Home Assistant renders
as "unknown" on the integration's page. They keep working for the dashboard,
automations and the AI tools; they are only folded away on the device page.
New installs register them hidden (`_attr_entity_registry_visible_default`);
an install from before is hidden once, by the config entry migration.
"""
from __future__ import annotations

from typing import Any, Iterable

WORKFLOW_ENTITIES = (
    # Coffee Lab: the rating and the finished bag's question.
    "xbloom_coffee_lab_rating_question",
    "xbloom_coffee_lab_rate_brew",
    "xbloom_coffee_lab_cup_issue",
    "xbloom_coffee_lab_bag_question",
    "xbloom_coffee_lab_buy_again",
    # Coffee Lab: a bag a brew left short of another cup.
    "xbloom_coffee_lab_finish_question",
    "xbloom_coffee_lab_finish_asked",
    "xbloom_coffee_lab_keep_asked",
    # A recipe's next change and the version to keep.
    "xbloom_next_change",
    "xbloom_version_to_keep",
    "xbloom_use_next_change",
    "xbloom_make_version_the_recipe",
    "xbloom_save_version_as_new",
    "xbloom_leave_recipe_unchanged",
    # Managing the library.
    "xbloom_library_recipe_select",
    "xbloom_archived_recipe_select",
    "xbloom_delete_selected_recipe_button",
    "xbloom_archive_recipe_button",
    "xbloom_archive_recipe_remove_from_cloud_button",
    "xbloom_restore_archived_recipe_button",
)


# Entities an earlier version provided and this one does not: their registry
# entries stay behind as "unavailable" until removed.
RETIRED_ENTITIES = (
    "xbloom_recipe_action_select",
    "xbloom_run_recipe_action_button",
)


def remove_retired_entities(registry: Any, entries: Iterable[Any]) -> None:
    """Remove the registry entries of entities no longer provided."""
    for entry in entries:
        if entry.unique_id in RETIRED_ENTITIES:
            registry.async_remove(entry.entity_id)


def hide_workflow_entities(registry: Any, entries: Iterable[Any], hider: Any) -> None:
    """Hide the workflow entities an earlier install registered visible.

    One already hidden, by the person or otherwise, is left as it is.
    """
    for entry in entries:
        if entry.unique_id in WORKFLOW_ENTITIES and entry.hidden_by is None:
            registry.async_update_entity(entry.entity_id, hidden_by=hider)
