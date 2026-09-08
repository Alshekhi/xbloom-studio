"""`brew_status` must reach `done` on a presumed completion, not just on ENJOY.

Only CMD_ENJOY moved the sensor to `done`. When ENJOY never arrives — the
2026-09-08 brew — the home-activity reconciliation instead pushed `brewing`
back to `idle`, so the machine that had just made coffee looked like one that
had never started. Anything reading `brew_status` to decide whether coffee is
ready got the wrong answer.

The completion contract now settles that question, so the sensor follows it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom.ble_entities import XBloomBrewStatusBleSensor


def _make_sensor():
    """A sensor wired to a fake bus, with its listeners registered."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = XBloomBrewStatusBleSensor(entry)
    # RestoreSensor is stubbed by conftest; nothing to restore in these tests.
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

    listeners: dict[str, callable] = {}

    hass = MagicMock()

    def _listen(event_type, handler):
        listeners[event_type] = handler
        return lambda: None

    hass.bus.async_listen = _listen
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()
    return sensor, listeners


@pytest.mark.asyncio
async def test_presumed_completion_sets_done():
    sensor, listeners = _make_sensor()
    await sensor.async_added_to_hass()

    sensor._attr_native_value = "brewing"
    handler = listeners["xbloom_brew_completed"]
    handler(MagicMock(data={"outcome": "presumed"}))

    assert sensor._attr_native_value == "done"


@pytest.mark.asyncio
async def test_confirmed_completion_sets_done():
    sensor, listeners = _make_sensor()
    await sensor.async_added_to_hass()

    sensor._attr_native_value = "brewing"
    listeners["xbloom_brew_completed"](MagicMock(data={"outcome": "confirmed"}))

    assert sensor._attr_native_value == "done"


@pytest.mark.asyncio
async def test_completion_after_reconciliation_still_sets_done():
    """The real 09-08 order: the machine went home first, so the sensor had
    already been reconciled to `idle` before the grace window closed."""
    sensor, listeners = _make_sensor()
    await sensor.async_added_to_hass()

    sensor._attr_native_value = "idle"          # home-activity reconciliation
    listeners["xbloom_brew_completed"](MagicMock(data={"outcome": "presumed"}))

    assert sensor._attr_native_value == "done"
