"""Tests for select.py — the machine-setting selects added by PR #2.

These selects are the accessible surface for settings that otherwise only exist
as an on-machine indicator a VoiceOver user cannot read, so two things matter:
the option lists must stay derived from the shared spec (never re-typed), and
the machine heartbeat must be able to move them without that looking like a
user edit.
"""
from __future__ import annotations

import json
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom.const import DOMAIN
from custom_components.xbloom.select import (
    XBloomBrewPatternSelect,
    XBloomModeSelect,
    XBloomTempUnitSelect,
    XBloomWaterSourceSelect,
    XBloomWeightUnitSelect,
)
from xbloom import spec


def _make(cls):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entity = cls(entry)
    entity.hass = MagicMock()
    entity.hass.services.async_call = AsyncMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


# --------------------------------------------------------------------------- #
# Option lists must come from the spec, not from re-typed literals            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (XBloomModeSelect, lambda: list(spec.MODES)),
        (XBloomWaterSourceSelect, lambda: list(spec.WATER_SOURCE_CODES)),
        (XBloomTempUnitSelect, lambda: list(spec.TEMP_UNIT_CODES)),
        (XBloomWeightUnitSelect, lambda: list(spec.WEIGHT_UNIT_CODES)),
        (XBloomBrewPatternSelect, lambda: list(spec.PATTERN_NAMES)),
    ],
)
def test_options_derive_from_spec(cls, expected) -> None:
    assert cls._attr_options == expected()


def test_mode_options_are_exactly_auto_and_pro() -> None:
    """Guards the spec itself: the machine has two modes, in this order."""
    assert XBloomModeSelect._attr_options == ["auto", "pro"]


def test_pattern_options_are_the_three_real_patterns() -> None:
    assert set(XBloomBrewPatternSelect._attr_options) == {
        "centered", "spiral", "circular",
    }


def test_every_select_has_a_distinct_unique_id() -> None:
    """Colliding unique_ids silently merge two entities into one in HA."""
    classes = [
        XBloomModeSelect, XBloomWaterSourceSelect, XBloomTempUnitSelect,
        XBloomWeightUnitSelect, XBloomBrewPatternSelect,
    ]
    ids = [c._attr_unique_id for c in classes]
    assert len(set(ids)) == len(ids)


# --------------------------------------------------------------------------- #
# Selecting an option                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_select_calls_the_backing_service() -> None:
    entity = _make(XBloomModeSelect)
    await entity.async_select_option("pro")
    entity.hass.services.async_call.assert_awaited_once()
    domain, service, data = entity.hass.services.async_call.await_args.args[:3]
    assert domain == DOMAIN
    assert service == entity._service
    assert data == {entity._service_arg: "pro"}


@pytest.mark.asyncio
async def test_select_updates_current_option() -> None:
    entity = _make(XBloomWaterSourceSelect)
    await entity.async_select_option("tap")
    assert entity.current_option == "tap"


@pytest.mark.asyncio
async def test_out_of_range_option_is_refused() -> None:
    """A bad option must not reach the machine — and must not be recorded."""
    entity = _make(XBloomTempUnitSelect)
    await entity.async_select_option("kelvin")
    entity.hass.services.async_call.assert_not_called()
    assert entity.current_option is None


@pytest.mark.asyncio
async def test_refused_option_does_not_clobber_a_good_one() -> None:
    entity = _make(XBloomWeightUnitSelect)
    await entity.async_select_option("g")
    await entity.async_select_option("stones")
    assert entity.current_option == "g"


@pytest.mark.asyncio
async def test_service_call_is_non_blocking() -> None:
    """A blocking call inside a select would stall the UI on a slow BLE write."""
    entity = _make(XBloomModeSelect)
    await entity.async_select_option("auto")
    assert entity.hass.services.async_call.await_args.kwargs.get("blocking") is False


# --------------------------------------------------------------------------- #
# Spec round-trips — the codes the services ultimately put on the wire        #
# --------------------------------------------------------------------------- #
def test_water_source_codes_round_trip() -> None:
    assert spec.WATER_SOURCE_CODES == {"tank": 0, "tap": 1}


def test_temp_unit_codes_round_trip() -> None:
    """Lowercase: a select's state value doubles as its translation key, and HA
    requires those to match [a-z0-9-_]+. Uppercase fails hassfest."""
    assert spec.TEMP_UNIT_CODES == {"c": 1, "f": 0}


def test_weight_unit_codes_round_trip() -> None:
    assert spec.WEIGHT_UNIT_CODES == {"g": 1, "ml": 0, "oz": 2}


def test_mode_payloads_match_the_app_bytes() -> None:
    """EASY/PRO wire payloads, byte-identical to BleCodeFactory.easyModeSwitch."""
    assert spec.MODE_PAYLOADS == {"auto": "91327856", "pro": "00000000"}


def test_every_option_has_a_wire_code() -> None:
    """An option with no code would fail only at send time, on the machine."""
    for cls, codes in (
        (XBloomWaterSourceSelect, spec.WATER_SOURCE_CODES),
        (XBloomTempUnitSelect, spec.TEMP_UNIT_CODES),
        (XBloomWeightUnitSelect, spec.WEIGHT_UNIT_CODES),
    ):
        for option in cls._attr_options:
            assert option in codes, f"{cls.__name__}: {option!r} has no wire code"


# --------------------------------------------------------------------------- #
# Translation keys — what hassfest enforces                                   #
# --------------------------------------------------------------------------- #
# A select's state value doubles as its translation key, and Home Assistant
# requires translation keys to match [a-z0-9-_]+ (not starting or ending with a
# separator). Uppercase "C"/"F" shipped for months undetected because no select
# had state translations at all; adding them is what surfaced it, as a required
# hassfest failure that blocked the merge. These tests catch it locally instead.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$|^[a-z0-9]$")
_TRANSLATIONS = [
    pathlib.Path("custom_components/xbloom/strings.json"),
    pathlib.Path("custom_components/xbloom/translations/en.json"),
    pathlib.Path("custom_components/xbloom/translations/ar.json"),
]


@pytest.mark.parametrize("path", _TRANSLATIONS, ids=lambda p: p.name)
def test_select_state_translation_keys_are_valid(path: pathlib.Path) -> None:
    """Every select state key must satisfy HA's translation-key rule."""
    blocks = (json.loads(path.read_text()).get("entity") or {}).get("select") or {}
    bad = [
        f"{key}.state.{state}"
        for key, block in blocks.items()
        for state in (block.get("state") or {})
        if not _KEY_RE.match(state)
    ]
    assert not bad, f"{path.name}: invalid translation keys {bad}"


@pytest.mark.parametrize("path", _TRANSLATIONS, ids=lambda p: p.name)
def test_translated_states_match_the_entities_options(path: pathlib.Path) -> None:
    """A translation for a state the select cannot produce is dead, and a missing
    one means the raw value gets read aloud instead of its label."""
    blocks = (json.loads(path.read_text()).get("entity") or {}).get("select") or {}
    for cls in (XBloomModeSelect, XBloomWaterSourceSelect, XBloomTempUnitSelect,
                XBloomWeightUnitSelect, XBloomBrewPatternSelect):
        block = blocks.get(cls._attr_translation_key)
        if not block or "state" not in block:
            continue
        assert set(block["state"]) == set(cls._attr_options), (
            f"{path.name}: {cls._attr_translation_key} translates "
            f"{sorted(block['state'])} but the entity offers {sorted(cls._attr_options)}"
        )


def test_every_select_option_is_a_valid_translation_key() -> None:
    """Guards the spec directly, so a new option cannot reintroduce the bug."""
    for cls in (XBloomModeSelect, XBloomWaterSourceSelect, XBloomTempUnitSelect,
                XBloomWeightUnitSelect, XBloomBrewPatternSelect):
        for option in cls._attr_options:
            assert _KEY_RE.match(option), (
                f"{cls.__name__}: option {option!r} is not a valid HA "
                "translation key — hassfest will reject it"
            )
