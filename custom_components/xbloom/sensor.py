"""xBloom Studio sensor platform — BLE-only.

Two sensors backed by notifications streamed from the machine during a brew
(see `ble_entities` for the full implementation):

  * `sensor.xbloom_studio_brew_status` — `idle | grinding | brewing | done`
  * `sensor.xbloom_studio_scale_weight` — live grams during a pour
"""
from .ble_entities import (
    XBloomBrewStatusBleSensor,
    XBloomLastUpdatedSensor,
    XBloomMachineStatusBleSensor,
    XBloomScaleWeightBleSensor,
)
from .reading_sensors import READING_SENSORS
from .coffee_lab.entities import entities_for as coffee_lab_entities

PARALLEL_UPDATES = 0  # event-driven; no polling


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([
        XBloomBrewStatusBleSensor(entry),
        XBloomMachineStatusBleSensor(entry),
        XBloomScaleWeightBleSensor(entry),
        XBloomLastUpdatedSensor(entry),
        *[cls(entry) for cls in READING_SENSORS],
    ])
    # Coffee Lab's, only while it is switched on.
    async_add_entities(coffee_lab_entities(entry.runtime_data.coffee_lab, "sensor"))
