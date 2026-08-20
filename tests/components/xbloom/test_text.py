"""Tests for text.py — the 'Save as new recipe' name box.

Small entity, but it is the only free-text input in the integration and it
re-seeds itself from the recipe picker, so the interesting cases are the states
where the picker has no usable value.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.xbloom.text import XBloomNewRecipeName, _RECIPE_SELECT


def _make(picker_state: str | None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entity = XBloomNewRecipeName(entry)
    entity.hass = MagicMock()
    if picker_state is None:
        entity.hass.states.get = MagicMock(return_value=None)
    else:
        state = MagicMock()
        state.state = picker_state
        entity.hass.states.get = MagicMock(return_value=state)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


def test_starts_empty() -> None:
    entity = _make("Ethiopia Natural")
    assert entity._attr_native_value == ""


def test_suggestion_appends_custom_suffix() -> None:
    entity = _make("Ethiopia Natural")
    assert entity._suggested() == "Ethiopia Natural (custom)"


@pytest.mark.parametrize("bad_state", ["unknown", "unavailable", ""])
def test_no_suggestion_when_picker_has_no_real_value(bad_state: str) -> None:
    """'unknown (custom)' would be a terrible thing to read aloud."""
    entity = _make(bad_state)
    assert entity._suggested() == ""


def test_no_suggestion_when_picker_entity_is_missing() -> None:
    """The picker may not exist yet during startup ordering."""
    entity = _make(None)
    assert entity._suggested() == ""


def test_suggestion_reads_the_recipe_picker_entity() -> None:
    entity = _make("Kenya AA")
    entity._suggested()
    entity.hass.states.get.assert_called_with(_RECIPE_SELECT)


@pytest.mark.asyncio
async def test_set_value_stores_and_writes_state() -> None:
    entity = _make("Kenya AA")
    await entity.async_set_value("My Blend")
    assert entity._attr_native_value == "My Blend"
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_set_value_accepts_empty_string() -> None:
    """native_min is 0 — clearing the box is a legitimate action."""
    entity = _make("Kenya AA")
    await entity.async_set_value("")
    assert entity._attr_native_value == ""


def test_max_length_leaves_room_for_the_custom_suffix() -> None:
    """A 60-char cap must not be shorter than a realistic name + ' (custom)'."""
    assert XBloomNewRecipeName._attr_native_max >= len("Ethiopia Natural (custom)")
    assert XBloomNewRecipeName._attr_native_min == 0
