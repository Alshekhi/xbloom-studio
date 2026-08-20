"""Tests for the platform registration shims (sensor.py, event.py, text.py, …).

These modules are thin — they just hand entity classes to async_add_entities.
But an entity dropped from one of those lists doesn't fail anywhere; it simply
never appears in Home Assistant, which for a VoiceOver user reads as a feature
that silently vanished. So the lists themselves are worth pinning.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom import (
    button as button_platform,
    event as event_platform,
    number as number_platform,
    select as select_platform,
    sensor as sensor_platform,
    text as text_platform,
    update as update_platform,
)
from custom_components.xbloom.reading_sensors import READING_SENSORS

PLATFORMS = {
    "sensor": sensor_platform,
    "event": event_platform,
    "number": number_platform,
    "select": select_platform,
    "text": text_platform,
    "update": update_platform,
    "button": button_platform,
}


async def _added(module):
    """Run a platform's async_setup_entry and return the entities it added."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {}
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    add = MagicMock()
    await module.async_setup_entry(hass, entry, add)
    entities = []
    for call in add.call_args_list:
        entities.extend(call.args[0])
    return entities


def _ids(entities) -> set[str]:
    return {getattr(e, "_attr_unique_id", None) for e in entities}


@pytest.mark.parametrize("name", sorted(PLATFORMS))
@pytest.mark.asyncio
async def test_platform_adds_at_least_one_entity(name: str) -> None:
    assert await _added(PLATFORMS[name]), f"{name} platform added nothing"


@pytest.mark.parametrize("name", sorted(PLATFORMS))
@pytest.mark.asyncio
async def test_platform_entities_have_unique_ids(name: str) -> None:
    """A missing or duplicated unique_id makes HA merge or drop the entity."""
    entities = await _added(PLATFORMS[name])
    ids = [getattr(e, "_attr_unique_id", None) for e in entities]
    assert None not in ids, f"{name}: an entity has no unique_id"
    assert len(set(ids)) == len(ids), f"{name}: duplicate unique_id"


@pytest.mark.asyncio
async def test_grind_size_is_deliberately_shared_across_two_domains() -> None:
    """`xbloom_grind_size` is used by BOTH the sensor and the number entity.

    That is legal and intentional, not a collision: HA's entity registry keys on
    (entity domain, integration, unique_id), so `sensor.xbloom_grind_size` and
    `number.xbloom_grind_size` are separate rows. Grind size is genuinely two
    things — what the machine currently reports (sensor) and what you want it to
    be (slider). Pinned here so the duplication reads as a decision rather than
    a mistake to anyone who greps for the id.
    """
    assert "xbloom_grind_size" in _ids(await _added(sensor_platform))
    assert "xbloom_grind_size" in _ids(await _added(number_platform))


@pytest.mark.asyncio
async def test_no_unique_id_is_reused_within_a_single_domain() -> None:
    """Within one domain a reused id makes HA drop the second entity outright."""
    from collections import defaultdict

    by_domain: dict[str, list[str]] = defaultdict(list)
    for name, module in PLATFORMS.items():
        for entity in await _added(module):
            by_domain[name].append(getattr(entity, "_attr_unique_id", None))
    for domain, ids in by_domain.items():
        assert len(set(ids)) == len(ids), f"{domain}: duplicate unique_id"


@pytest.mark.asyncio
async def test_sensor_platform_registers_every_reading_sensor() -> None:
    """READING_SENSORS is the list; the platform must actually add all of it."""
    entities = await _added(sensor_platform)
    added = {type(e) for e in entities}
    missing = [c.__name__ for c in READING_SENSORS if c not in added]
    assert not missing, f"reading sensors never registered: {missing}"


@pytest.mark.asyncio
async def test_sensor_platform_registers_the_ble_sensors() -> None:
    ids = _ids(await _added(sensor_platform))
    assert {"xbloom_brew_status", "xbloom_machine_status"} <= ids


@pytest.mark.asyncio
async def test_update_platform_registers_the_firmware_entity() -> None:
    assert _ids(await _added(update_platform)) == {"xbloom_firmware"}


@pytest.mark.asyncio
async def test_text_platform_registers_the_recipe_name_box() -> None:
    assert _ids(await _added(text_platform)) == {"xbloom_new_recipe_name"}


@pytest.mark.asyncio
async def test_number_platform_registers_all_eight_sliders() -> None:
    ids = _ids(await _added(number_platform))
    assert {
        "xbloom_grind_size", "xbloom_grind_speed", "xbloom_brew_volume",
        "xbloom_brew_temperature", "xbloom_brew_flow_rate",
        "xbloom_brew_grind", "xbloom_brew_ratio", "xbloom_brew_dose",
    } <= ids


@pytest.mark.asyncio
async def test_select_platform_registers_the_machine_setting_selects() -> None:
    ids = _ids(await _added(select_platform))
    assert {
        "xbloom_mode_select", "xbloom_water_source_select",
        "xbloom_temp_unit_select", "xbloom_weight_unit_select",
        "xbloom_brew_pattern_select",
    } <= ids


@pytest.mark.asyncio
async def test_event_platform_registers_the_brew_event_entity() -> None:
    from custom_components.xbloom.ble_entities import XBloomBrewEventBleEntity

    entities = await _added(event_platform)
    assert any(isinstance(e, XBloomBrewEventBleEntity) for e in entities)
