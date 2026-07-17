"""Select entities for the xBloom Studio integration.

  * XBloomRecipeSelect — recipe library (Phase 6)
  * XBloomModeSelect / XBloomWaterSourceSelect / XBloomTempUnitSelect /
    XBloomWeightUnitSelect — machine settings (Phase 8 — 08-02). Each calls
    the matching `xbloom.set_*` service and remembers the user's last value
    via RestoreEntity (per CONTEXT D-11 we don't read state back from the
    machine).
"""
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import XBloomCoordinator
from .vendor.xbloom import spec

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0  # coordinator manages all updates; select is read-only


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the xBloom select entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        XBloomRecipeSelect(coordinator),
        # 08-02: machine setting selects
        XBloomModeSelect(),
        XBloomWaterSourceSelect(),
        XBloomTempUnitSelect(),
        XBloomWeightUnitSelect(),
        XBloomBrewPatternSelect(),
    ])


class XBloomRecipeSelect(CoordinatorEntity, SelectEntity):
    """Select entity that lists all recipes from the xBloom library.

    Selecting a recipe stores its name as state. The full recipe dict
    (all 20+ fields) is exposed via extra_state_attributes so Phase 7
    can read grinder_size, pours, dose_g, etc. without an extra API call.

    Phase 7 contract: Phase 7 reads extra_state_attributes['id'] (not the
    entity state string) to determine which recipe to brew. The entity state
    is the recipe name for human display only.
    """

    _attr_has_entity_name = True
    _attr_name = "Recipe"
    _attr_unique_id = "xbloom_recipe_select"

    def __init__(self, coordinator: XBloomCoordinator) -> None:
        super().__init__(coordinator)
        self._current_option: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group entity under 'xBloom Studio' device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def options(self) -> list[str]:
        """Return recipe names as select options."""
        return [r["name"] for r in (self.coordinator.data or [])]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected recipe name."""
        return self._current_option

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return full recipe detail as attributes when a recipe is selected.

        All Recipe TypedDict fields are JSON-safe primitives and lists of dicts.
        """
        if not self._current_option or not self.coordinator.data:
            return None
        for recipe in self.coordinator.data:
            if recipe["name"] == self._current_option:
                return dict(recipe)
        return None

    async def async_select_option(self, option: str) -> None:
        """Handle recipe selection from the HA UI or service call."""
        self._current_option = option
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Reset selected recipe if it was removed from the library after a refresh.

        Prevents HA warning: 'current_option X is not in options [...]'
        """
        if self._current_option and self._current_option not in self.options:
            _LOGGER.debug(
                "Selected recipe %r no longer in library after refresh; resetting",
                self._current_option,
            )
            self._current_option = None
        super()._handle_coordinator_update()


# ---------------------------------------------------------------------------
# Phase 8 — 08-02: machine setting selects
#
# Each one calls a single xbloom.set_* service and persists the last user-set
# value via RestoreEntity. Per CONTEXT D-11 we treat the select as the source
# of truth for "what HA last asked the machine to do" — not as a live read of
# the machine's actual state. Round-trip read-back via RD_MachineInfo (cmd
# 40521) is a possible future enhancement.
# ---------------------------------------------------------------------------
class _XBloomSettingSelect(SelectEntity, RestoreEntity):
    """Shared base for the machine setting selects."""

    _attr_has_entity_name = True
    _service: str = ""           # xbloom.<name>
    _service_arg: str = ""       # name of the call.data key
    _attr_options: list[str] = []
    _attr_entity_category = None  # default — show in main UI for accessibility

    def __init__(self) -> None:
        self._current_option: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def current_option(self) -> str | None:
        return self._current_option

    async def async_added_to_hass(self) -> None:
        """Restore the last user-set option across HA restarts."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._current_option = last.state

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            _LOGGER.warning(
                "%s: ignoring out-of-range option %r (allowed: %s)",
                self._attr_unique_id, option, self._attr_options,
            )
            return
        await self.hass.services.async_call(
            DOMAIN, self._service, {self._service_arg: option}, blocking=False,
        )
        self._current_option = option
        self.async_write_ha_state()


class XBloomModeSelect(_XBloomSettingSelect):
    """Auto (Easy) vs Pro mode (BLE cmd 11511)."""

    _attr_name = "Mode"
    _attr_unique_id = "xbloom_mode_select"
    _attr_icon = "mdi:cog"
    _attr_options = ["auto", "pro"]
    _service = "set_mode"
    _service_arg = "mode"


class XBloomWaterSourceSelect(_XBloomSettingSelect):
    """Internal tank vs external tap (BLE cmd 4508)."""

    _attr_name = "Water Source"
    _attr_unique_id = "xbloom_water_source_select"
    _attr_icon = "mdi:water"
    _attr_options = list(spec.WATER_SOURCE_CODES)
    _service = "set_water_source"
    _service_arg = "source"


class XBloomTempUnitSelect(_XBloomSettingSelect):
    """Display temperature unit (BLE cmd 8010)."""

    _attr_name = "Temperature Unit"
    _attr_unique_id = "xbloom_temp_unit_select"
    _attr_icon = "mdi:thermometer"
    _attr_options = list(spec.TEMP_UNIT_CODES)
    _service = "set_temp_unit"
    _service_arg = "unit"


class XBloomWeightUnitSelect(_XBloomSettingSelect):
    """Display weight unit (BLE cmd 8005)."""

    _attr_name = "Weight Unit"
    _attr_unique_id = "xbloom_weight_unit_select"
    _attr_icon = "mdi:scale"
    _attr_options = list(spec.WEIGHT_UNIT_CODES)
    _service = "set_weight_unit"
    _service_arg = "unit"


class XBloomBrewPatternSelect(_XBloomSettingSelect):
    """User's preferred pour pattern — read by the brew button/service.

    Pure storage entity: selecting an option stores the value in HA state
    and persists it via RestoreEntity. No service call is made to the machine.
    """

    _attr_name = "Brew Pattern"
    _attr_unique_id = "xbloom_brew_pattern_select"
    _attr_icon = "mdi:rotate-3d-variant"
    _attr_options = list(spec.PATTERN_NAMES)

    async def async_added_to_hass(self) -> None:
        """Restore last selected pattern; default to 'spiral' on first run."""
        await super().async_added_to_hass()
        if self._current_option is None:
            self._current_option = "spiral"

    async def async_select_option(self, option: str) -> None:
        """Store the chosen pattern without calling any machine service."""
        if option not in self._attr_options:
            return
        self._current_option = option
        self.async_write_ha_state()
