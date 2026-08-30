"""Tests for the `xbloom.build_recipe` service.

The builder itself is covered by `tests/test_recipe_build.py`; what matters
here is the service wrapper — that it is registered, that it translates the
service-call fields into the builder's, that it reports adjustments and
errors rather than raising, and that `save` reaches the coordinator by the
right path.
"""
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The stub injection in test_init.py must run before custom_components is
# imported; importing it here reuses that setup rather than repeating it.
from . import test_init as _ti  # noqa: F401

from custom_components.xbloom import async_setup_entry  # noqa: E402


async def _handlers(entry) -> dict:
    """Set up the entry and return {service_name: handler}."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.states = MagicMock()
    entry.async_on_unload = MagicMock()
    with patch("custom_components.xbloom.XBloomCoordinator") as mc, \
         patch("custom_components.xbloom.XBloomClient") as mk:
        mk.return_value = AsyncMock()
        coord = MagicMock()
        coord.async_config_entry_first_refresh = AsyncMock()
        coord.async_add_recipe = AsyncMock()
        coord.async_replace_recipe = AsyncMock()
        coord.data = []
        mc.return_value = coord
        await async_setup_entry(hass, entry)
    handlers = {
        call[0][1]: call[0][2]
        for call in hass.services.async_register.call_args_list
        if len(call[0]) >= 3
    }
    return handlers, entry.runtime_data.coordinator


def _call(**data):
    """A service call carrying `data`, with the schema defaults applied."""
    call = MagicMock()
    call.data = {"save": False, "apply_brew_defaults": True, **data}
    return call


@pytest.fixture
async def build_recipe(mock_config_entry):
    handlers, coordinator = await _handlers(mock_config_entry)
    return handlers["build_recipe"], coordinator


async def test_build_recipe_is_registered(mock_config_entry) -> None:
    handlers, _ = await _handlers(mock_config_entry)
    assert "build_recipe" in handlers


async def test_returns_a_valid_recipe_from_the_minimal_fields(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16"))
    assert res["ok"] is True
    assert res["errors"] == {}
    assert res["recipe"]["name"] == "Morning"
    assert res["recipe"]["dose_g"] == 18.0


async def test_maps_the_dose_field_onto_the_recipes_dose_g(build_recipe) -> None:
    """The service surface says `dose`; the recipe dict says `dose_g`."""
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=15.0, ratio="1:16"))
    assert res["recipe"]["dose_g"] == 15.0


async def test_reports_adjustments_in_plain_language(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16", grind_size=95))
    assert res["ok"] is True
    assert any("grind" in line for line in res["adjustments"])


async def test_parses_pours_from_json(build_recipe) -> None:
    handler, _ = build_recipe
    pours = [{"volume_ml": 144, "temperature_c": 94}, {"volume_ml": 144}]
    res = await handler(_call(
        name="Morning", dose=18.0, ratio="1:16", pours_json=json.dumps(pours),
    ))
    assert res["ok"] is True
    assert res["recipe"]["pour_count"] == 2
    assert res["recipe"]["pours"][0]["temperature_c"] == 94.0


async def test_rejects_malformed_pours_json_without_raising(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16",
                              pours_json="{not json"))
    assert res["ok"] is False
    assert "pours_json" in res["error"]


async def test_rejects_pours_json_that_is_not_a_list(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16",
                              pours_json='{"volume_ml": 100}'))
    assert res["ok"] is False
    assert "array" in res["error"]


async def test_reports_a_missing_name_as_a_structured_error(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(dose=18.0, ratio="1:16"))
    assert res["ok"] is False
    assert res["errors"]["name"] == "name_required"
    assert "name" in res["error"]


async def test_does_not_save_by_default(build_recipe) -> None:
    handler, coordinator = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16"))
    assert res["saved"] is False
    coordinator.async_add_recipe.assert_not_called()


async def test_save_adds_a_new_recipe(build_recipe) -> None:
    handler, coordinator = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16", save=True))
    assert res["saved"] is True
    coordinator.async_add_recipe.assert_awaited_once()
    saved = coordinator.async_add_recipe.await_args[0][0]
    assert saved["name"] == "Morning"


async def test_save_with_an_id_replaces_instead_of_adding(build_recipe) -> None:
    """An edit must overwrite the recipe it came from, not duplicate it."""
    handler, coordinator = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16",
                              id="local-abc", save=True))
    assert res["saved"] is True
    coordinator.async_replace_recipe.assert_awaited_once()
    coordinator.async_add_recipe.assert_not_called()
    assert coordinator.async_replace_recipe.await_args[0][0]["id"] == "local-abc"


async def test_an_invalid_recipe_is_never_saved(build_recipe) -> None:
    handler, coordinator = build_recipe
    res = await handler(_call(dose=18.0, ratio="1:16", save=True))
    assert res["ok"] is False
    coordinator.async_add_recipe.assert_not_called()


async def test_a_failed_save_is_reported_not_raised(build_recipe) -> None:
    handler, coordinator = build_recipe
    coordinator.async_add_recipe.side_effect = RuntimeError("cloud unreachable")
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16", save=True))
    assert res["ok"] is False
    assert "cloud unreachable" in res["error"]


async def test_brew_defaults_can_be_turned_off(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16",
                              pour_count=2, apply_brew_defaults=False))
    assert [p["pause_s"] for p in res["recipe"]["pours"]] == [0, 0]


async def test_brew_defaults_are_applied_by_default(build_recipe) -> None:
    handler, _ = build_recipe
    res = await handler(_call(name="Morning", dose=18.0, ratio="1:16", pour_count=2))
    assert all(p["pause_s"] >= 10 for p in res["recipe"]["pours"])
