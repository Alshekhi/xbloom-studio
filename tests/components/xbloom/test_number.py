"""Tests for number.py — the two-way sliders added by PR #2.

Two things carry real risk here:

1. **Slider bounds must come from the shared spec.** Re-typed bounds are exactly
   how the pattern/temperature/volume bugs in PR #1 happened.
2. **The brewer-temperature DISPLAY↔WIRE split.** The slider and the machine's
   knob speak 39..96, where the ends are sentinels for "room temperature" and
   "boiling point"; anything SET or SAVED must be converted to 20/98 first.
   Send 39 raw and the machine gets a nonsensical 39 °C.

REFLECT (machine → slider) must never route through `async_set_native_value`,
or a knob twist would be re-driven back at the machine as if the user had moved
the slider.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.xbloom.number import (
    EV_BREWER_SETTING,
    EV_GRINDER_KNOB,
    XBloomBrewDoseNumber,
    XBloomBrewFlowRateNumber,
    XBloomBrewGrindNumber,
    XBloomBrewRatioNumber,
    XBloomBrewTemperatureNumber,
    XBloomBrewVolumeNumber,
    XBloomGrindSizeNumber,
    XBloomGrindSpeedNumber,
)
from xbloom import spec

ALL_NUMBERS = [
    XBloomGrindSizeNumber, XBloomGrindSpeedNumber, XBloomBrewVolumeNumber,
    XBloomBrewTemperatureNumber, XBloomBrewFlowRateNumber,
    XBloomBrewGrindNumber, XBloomBrewRatioNumber, XBloomBrewDoseNumber,
]


def _make(cls, *, recipe_attrs: dict | None = None):
    """Build an entity with no recipe picked unless `recipe_attrs` is given.

    `hass.states.get` must return a real None rather than a MagicMock: the
    override sliders do `int(cup_type)` on whatever comes back, and MagicMock
    implements `__int__` (returning 1), which would silently masquerade as a
    picked xPod recipe.
    """
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entity = cls(entry)
    entity.hass = MagicMock()
    if recipe_attrs is None:
        entity.hass.states.get = MagicMock(return_value=None)
    else:
        state = MagicMock()
        state.attributes = dict(recipe_attrs)
        entity.hass.states.get = MagicMock(return_value=state)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


# --------------------------------------------------------------------------- #
# Bounds derive from the spec                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("cls", "field_name"),
    [
        (XBloomGrindSizeNumber, "grind_size"),
        (XBloomGrindSpeedNumber, "grinder_speed_rpm"),
        (XBloomBrewVolumeNumber, "pour_volume_ml"),
        (XBloomBrewFlowRateNumber, "pour_flow_rate"),
        (XBloomBrewGrindNumber, "grind_size"),
    ],
)
def test_slider_bounds_match_the_spec_field(cls, field_name: str) -> None:
    r = spec.field(field_name)
    assert cls._attr_native_min_value == float(r.min)
    assert cls._attr_native_max_value == float(r.max)
    assert cls._attr_native_step == float(r.step)


def test_ratio_slider_matches_the_ratio_grid() -> None:
    assert XBloomBrewRatioNumber._attr_native_min_value == spec.RATIO_DENOM.min
    assert XBloomBrewRatioNumber._attr_native_max_value == spec.RATIO_DENOM.max
    assert XBloomBrewRatioNumber._attr_native_step == spec.RATIO_DENOM.step


def test_every_number_has_a_distinct_unique_id() -> None:
    ids = [c._attr_unique_id for c in ALL_NUMBERS]
    assert len(set(ids)) == len(ids)


def _bounds(entity) -> tuple[float, float]:
    """(min, max) for an entity, whether fixed or computed.

    Most sliders declare `_attr_native_min_value`; the dose slider overrides
    `native_min_value`/`native_max_value` because its window depends on the
    recipe's cup type.
    """
    cls = type(entity)
    if isinstance(getattr(cls, "native_min_value", None), property):
        return float(entity.native_min_value), float(entity.native_max_value)
    return float(cls._attr_native_min_value), float(cls._attr_native_max_value)


@pytest.mark.parametrize("cls", ALL_NUMBERS)
def test_default_value_is_inside_the_slider_range(cls) -> None:
    """A default outside its own bounds shows as an out-of-range slider in HA."""
    entity = _make(cls)
    low, high = _bounds(entity)
    assert low <= entity.native_value <= high


def test_dose_range_falls_back_when_no_cup_is_known() -> None:
    """Before a recipe is picked there is no cup type, so a safe window is used."""
    entity = _make(XBloomBrewDoseNumber)
    assert (entity.native_min_value, entity.native_max_value) == (5.0, 25.0)


@pytest.mark.parametrize("cup_api", sorted(spec.CUP_DOSE))
def test_dose_range_follows_the_recipe_cup_type(cup_api: int) -> None:
    """Each cup has its own dose window in the spec; the slider must track it."""
    dose = spec.CUP_DOSE[cup_api]
    entity = _make(XBloomBrewDoseNumber, recipe_attrs={"cup_type": cup_api})
    assert entity.native_min_value == float(dose.min)
    assert entity.native_max_value == float(dose.max)


def test_dose_range_survives_a_junk_cup_type() -> None:
    """A malformed stored recipe must not raise inside a property HA reads."""
    entity = _make(XBloomBrewDoseNumber, recipe_attrs={"cup_type": "not-a-cup"})
    assert (entity.native_min_value, entity.native_max_value) == (5.0, 25.0)


def test_dose_slider_is_hidden_for_xpod() -> None:
    """xPod is a fixed 15 g capsule — a dose slider there is a lie."""
    entity = _make(XBloomBrewDoseNumber, recipe_attrs={"cup_type": 1})
    assert entity.available is False


def test_dose_slider_is_shown_for_adjustable_cups() -> None:
    entity = _make(XBloomBrewDoseNumber, recipe_attrs={"cup_type": 3})
    assert entity.available is True


def test_override_sliders_seed_from_the_picked_recipe() -> None:
    """Picking a recipe must pull its stored value into the customizer slider."""
    entity = _make(XBloomBrewGrindNumber, recipe_attrs={"grinder_size": 72})
    entity._seed_from_recipe()
    assert entity.native_value == 72.0


def test_override_sliders_ignore_a_recipe_missing_the_attribute() -> None:
    entity = _make(XBloomBrewRatioNumber, recipe_attrs={"name": "No ratio here"})
    before = entity.native_value
    entity._seed_from_recipe()
    assert entity.native_value == before


def test_override_sliders_ignore_a_non_numeric_recipe_value() -> None:
    entity = _make(XBloomBrewRatioNumber, recipe_attrs={"water_ratio": "1:16"})
    before = entity.native_value
    entity._seed_from_recipe()
    assert entity.native_value == before


# --------------------------------------------------------------------------- #
# Brew temperature — the DISPLAY domain                                       #
# --------------------------------------------------------------------------- #
def test_temperature_slider_uses_the_display_domain() -> None:
    """39..96, matching the knob and the app — not the 20..98 wire range."""
    assert XBloomBrewTemperatureNumber._attr_native_min_value == 39
    assert XBloomBrewTemperatureNumber._attr_native_max_value == 96


def test_display_ends_convert_to_the_wire_sentinels() -> None:
    """39 means 'room temperature' (20) and 96 means 'boiling point' (98)."""
    assert spec.brew_temp_display_to_wire(39) == spec.ROOM_TEMP_C
    assert spec.brew_temp_display_to_wire(96) == spec.BOILING_POINT_C


@pytest.mark.parametrize("value", [40, 55, 75, 93, 95])
def test_mid_range_temperatures_pass_through_unconverted(value: int) -> None:
    assert spec.brew_temp_display_to_wire(value) == float(value)


def test_wire_to_display_is_the_inverse_at_the_sentinels() -> None:
    assert spec.brew_temp_wire_to_display(spec.ROOM_TEMP_C) == 39
    assert spec.brew_temp_wire_to_display(spec.BOILING_POINT_C) == 96


@pytest.mark.parametrize("display", list(range(39, 97)))
def test_display_wire_display_round_trips(display: int) -> None:
    """Every reachable slider position must survive a save/reload cycle."""
    wire = spec.brew_temp_display_to_wire(display)
    assert spec.brew_temp_wire_to_display(wire) == display


def test_sentinels_are_named_for_speech() -> None:
    """A screen reader should say 'room temperature', not '39'."""
    assert spec.brew_temp_sentinel_name(39) == "RT"
    assert spec.brew_temp_sentinel_name(96) == "BP"
    assert spec.brew_temp_sentinel_name(93) is None


def test_knob_reports_in_celsius_pass_through() -> None:
    assert spec.brew_temp_knob_to_celsius(93) == 93


def test_knob_reports_in_fahrenheit_are_normalised() -> None:
    """The knob emits in the machine's display unit; 200 °F is not 200 °C."""
    assert spec.brew_temp_knob_to_celsius(200) == 93


def test_knob_value_outside_both_domains_is_rejected() -> None:
    assert spec.brew_temp_knob_to_celsius(5) is None
    assert spec.brew_temp_knob_to_celsius(400) is None


def test_celsius_and_fahrenheit_knob_domains_do_not_overlap() -> None:
    """The unit is inferred from the value, so an overlap would be ambiguous."""
    assert spec.BREW_TEMP_DISPLAY_MAX < spec.BREW_TEMP_DISPLAY_F_MIN


# --------------------------------------------------------------------------- #
# REFLECT — machine knob → slider                                             #
# --------------------------------------------------------------------------- #
def test_temperature_reflects_a_brewer_temperature_event() -> None:
    entity = _make(XBloomBrewTemperatureNumber)
    got = entity._reflect_from_event(
        EV_BREWER_SETTING, {"setting": "temperature", "value": 91}
    )
    assert got == 91.0


def test_temperature_ignores_other_brewer_settings() -> None:
    """The same event carries flow rate and pattern changes too."""
    entity = _make(XBloomBrewTemperatureNumber)
    assert entity._reflect_from_event(
        EV_BREWER_SETTING, {"setting": "flow_rate", "value": 3.0}
    ) is None


def test_temperature_ignores_unrelated_event_types() -> None:
    entity = _make(XBloomBrewTemperatureNumber)
    assert entity._reflect_from_event(
        EV_GRINDER_KNOB, {"setting": "temperature", "value": 91}
    ) is None


def test_reflect_writes_state_without_going_through_the_setter() -> None:
    """REFLECT must not look like a user edit, or it would drive the machine."""
    entity = _make(XBloomGrindSizeNumber)
    entity.async_set_native_value = MagicMock()
    entity._apply_reflected(42.0)
    assert entity.native_value == 42.0
    entity.async_write_ha_state.assert_called_once()
    entity.async_set_native_value.assert_not_called()


def test_reflecting_the_same_value_does_not_rewrite_state() -> None:
    """Knob events repeat; only a change is worth a state write."""
    entity = _make(XBloomGrindSizeNumber)
    entity._apply_reflected(entity.native_value)
    entity.async_write_ha_state.assert_not_called()


# --------------------------------------------------------------------------- #
# User edits                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_set_native_value_stores_and_writes() -> None:
    entity = _make(XBloomBrewVolumeNumber)
    await entity.async_set_native_value(250.0)
    assert entity.native_value == 250.0
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_temperature_set_does_not_drive_without_a_live_session() -> None:
    """No Connect session means nothing to write to; must not raise."""
    entity = _make(XBloomBrewTemperatureNumber)
    entity._entry.runtime_data.live_session_listener = None
    await entity.async_set_native_value(91.0)
    assert entity.native_value == 91.0


@pytest.mark.asyncio
async def test_temperature_set_ignores_a_stopped_live_session() -> None:
    """A listener object that isn't running is not a usable link."""
    entity = _make(XBloomBrewTemperatureNumber)
    listener = MagicMock()
    listener.is_running = False
    entity._entry.runtime_data.live_session_listener = listener
    await entity.async_set_native_value(91.0)
    assert entity._drive_unsub is None
