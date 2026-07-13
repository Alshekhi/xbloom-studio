"""xBloom Studio event platform — BLE-only.

`event.xbloom_studio_brew_event` fires `brew_started`, `brew_done`, and the
granular per-stage events (`pour_started`, `grinder_started`, …) decoded
from BLE notifications during the brew.
"""
from .ble_entities import XBloomBrewEventBleEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([XBloomBrewEventBleEntity(entry)])
