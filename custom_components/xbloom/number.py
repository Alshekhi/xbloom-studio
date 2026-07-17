"""Number entities for the xBloom Studio integration.

Stores user-configured brew parameters (grind size, grind speed, brew volume,
brew temperature, brew flow rate) using RestoreEntity so values survive HA
restarts. No machine services are called from these entities — they are
pure storage that other parts of the integration read at brew time.
"""
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .vendor.xbloom import spec

_LOGGER = logging.getLogger(__name__)


def _range(field_name: str) -> tuple[float, float, float]:
    """(min, max, step) for a NumberEntity slider, from the shared spec field.

    Only the *range* is shared with the spec; each entity keeps its own
    `_default_value` because the standalone-brew defaults differ from the
    recipe-wizard defaults.
    """
    r = spec.field(field_name)
    return float(r.min), float(r.max), float(r.step)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([
        XBloomGrindSizeNumber(),
        XBloomGrindSpeedNumber(),
        XBloomBrewVolumeNumber(),
        XBloomBrewTemperatureNumber(),
        XBloomBrewFlowRateNumber(),
    ])


class _XBloomNumberBase(NumberEntity, RestoreEntity):
    """Shared base for xBloom number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _default_value: float = 0.0

    def __init__(self) -> None:
        self._current_value: float = self._default_value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def native_value(self) -> float | None:
        return self._current_value

    async def async_set_native_value(self, value: float) -> None:
        self._current_value = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                self._current_value = float(last.state)
            except ValueError:
                pass


class XBloomGrindSizeNumber(_XBloomNumberBase):
    _attr_name = "Grind Size"
    _attr_unique_id = "xbloom_grind_size"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("grind_size")
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:grain"
    _default_value = 65.0


class XBloomGrindSpeedNumber(_XBloomNumberBase):
    _attr_name = "Grind Speed"
    _attr_unique_id = "xbloom_grind_speed"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("grinder_speed_rpm")
    _attr_native_unit_of_measurement = "RPM"
    _attr_icon = "mdi:rotate-right"
    _default_value = 60.0


class XBloomBrewVolumeNumber(_XBloomNumberBase):
    _attr_name = "Brew Volume"
    _attr_unique_id = "xbloom_brew_volume"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("pour_volume_ml")
    _attr_native_unit_of_measurement = "ml"
    _attr_icon = "mdi:cup-water"
    _default_value = 120.0


class XBloomBrewTemperatureNumber(_XBloomNumberBase):
    _attr_name = "Brew Temperature"
    _attr_unique_id = "xbloom_brew_temperature"
    # NOT spec.field("pour_temperature_c"): that floor is 40 (recipe rule),
    # but this standalone-brew slider has historically allowed 20. Left as-is
    # pending confirmation of the machine's real standalone-brew floor.
    _attr_native_min_value = 20.0
    _attr_native_max_value = 98.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"
    _default_value = 93.0


class XBloomBrewFlowRateNumber(_XBloomNumberBase):
    _attr_name = "Brew Flow Rate"
    _attr_unique_id = "xbloom_brew_flow_rate"
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = _range("pour_flow_rate")
    _attr_native_unit_of_measurement = "ml/s"
    _attr_icon = "mdi:water-pump"
    _default_value = 3.0
