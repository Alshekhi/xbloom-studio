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
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .ble_entities import send_brewer_pattern_live, signal_event
from .const import DOMAIN
from .coordinator import XBloomCoordinator
from .vendor.xbloom import spec

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0  # coordinator manages all updates; select is read-only

# Live-session bus event (emitted by live_session.py) the pattern select uses.
EV_BREWER_SETTING = "xbloom_brewer_setting_changed"
# Module-entered event (live_session.py) — the mode select reflects off it, since
# the machine's screen tracks Auto/Pro 1:1 and arrives promptly (the 40521
# heartbeat that carries `mode` is infrequent).
EV_MODULE_ENTERED = "xbloom_module_entered"
# Fired when the mode is changed from HA (dashboard/service) so the announce
# blueprint can speak it — a commanded 11511 emits no machine screen-event.
EV_MODE_CHANGED = "xbloom_mode_changed"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the xBloom select entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        XBloomRecipeSelect(coordinator),
        # 08-02: machine setting selects — pass entry so they can sync their
        # current value from the machine's heartbeat (signal_event).
        XBloomModeSelect(entry),
        XBloomWaterSourceSelect(entry),
        XBloomTempUnitSelect(entry),
        XBloomWeightUnitSelect(entry),
        XBloomBrewPatternSelect(entry),
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
# Each calls a single xbloom.set_* service on change. It now ALSO syncs its
# current value from the machine's RD_MachineInfo heartbeat (cmd 40521, via
# signal_event) whenever a connection delivers one — so the select reflects the
# machine's ACTUAL state, not just "what HA last asked for". Selecting an option
# updates optimistically and sends the command; the next heartbeat confirms.
# (This supersedes the old CONTEXT D-11 "no read-back" stance now that the
# heartbeat field map is app-confirmed — see ble.decode_notification.)
# ---------------------------------------------------------------------------
class _XBloomSettingSelect(SelectEntity, RestoreEntity):
    """Shared base for the machine setting selects."""

    _attr_has_entity_name = True
    _service: str = ""           # xbloom.<name>
    _service_arg: str = ""       # name of the call.data key
    _attr_options: list[str] = []
    _attr_entity_category = None  # default — show in main UI for accessibility
    # Heartbeat field (from ble.decode_notification) this select mirrors. None
    # for pure-storage selects (e.g. brew pattern) that never read the machine.
    _heartbeat_key: str | None = None

    def __init__(self, entry=None) -> None:
        self._entry = entry
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
        """Restore the last option, then keep it synced to the machine heartbeat."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._current_option = last.state

        if self._heartbeat_key and self._entry is not None:
            @callback
            def _on_event(decoded: dict) -> None:
                val = decoded.get(self._heartbeat_key)
                if val in self._attr_options and val != self._current_option:
                    self._current_option = val
                    self.async_write_ha_state()

            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, signal_event(self._entry.entry_id), _on_event,
                )
            )

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

    _attr_translation_key = "mode"
    _attr_unique_id = "xbloom_mode_select"
    _attr_icon = "mdi:cog"
    _attr_options = list(spec.MODES)
    _service = "set_mode"
    _service_arg = "mode"
    # Heartbeat (40521) carries the authoritative "auto"/"pro", but it's
    # infrequent — kept as the backstop. Prompt reflection comes from the module
    # screen below.
    _heartbeat_key = "mode"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()   # restore + heartbeat reflect

        # PROMPT REFLECT: the machine has no async mode notify and the mode-
        # carrying heartbeat is infrequent, so a machine-side switch (triple-
        # press the centre knob) wasn't moving this dropdown. The SCREEN tracks
        # the mode 1:1 and is reported at once via xbloom_module_entered: the
        # Auto/EasyMode screen == Auto mode; every Pro screen (home/grinder/
        # brewer/scale) == Pro mode. Reflect that SILENTLY — the module path
        # already speaks the screen, so firing our own announce here would
        # double it. The heartbeat stays the authoritative backstop.
        @callback
        def _on_module(event) -> None:
            module = event.data.get("module")
            if module == "auto":
                mode = "auto"
            elif module in ("home", "grinder", "brewer", "scale"):
                mode = "pro"
            else:
                return
            if mode in self._attr_options and mode != self._current_option:
                self._current_option = mode
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(EV_MODULE_ENTERED, _on_module)
        )

    async def async_select_option(self, option: str) -> None:
        await super().async_select_option(option)   # sends 11511 + optimistic set
        # ANNOUNCE (HA/dashboard path only): a commanded mode switch produces no
        # machine screen-event, so a screen-reader user would otherwise hear
        # nothing. Fire a dedicated event the announce blueprint speaks. A
        # machine-side switch is voiced via the module path instead, so this
        # fires ONLY here — no double announce.
        if option in self._attr_options:
            self.hass.bus.async_fire(EV_MODE_CHANGED, {"mode": option})


class XBloomWaterSourceSelect(_XBloomSettingSelect):
    """Internal tank vs external tap (BLE cmd 4508)."""

    _attr_translation_key = "water_source"
    _attr_unique_id = "xbloom_water_source_select"
    _attr_icon = "mdi:water"
    _attr_options = list(spec.WATER_SOURCE_CODES)
    _service = "set_water_source"
    _service_arg = "source"
    _heartbeat_key = "water_source"  # heartbeat "tank"/"tap"


class XBloomTempUnitSelect(_XBloomSettingSelect):
    """Display temperature unit (BLE cmd 8010)."""

    _attr_translation_key = "temperature_unit"
    _attr_unique_id = "xbloom_temp_unit_select"
    _attr_icon = "mdi:thermometer"
    _attr_options = list(spec.TEMP_UNIT_CODES)
    _service = "set_temp_unit"
    _service_arg = "unit"
    _heartbeat_key = "temp_unit"     # heartbeat "C"/"F"


class XBloomWeightUnitSelect(_XBloomSettingSelect):
    """Display weight unit (BLE cmd 8005)."""

    _attr_translation_key = "weight_unit"
    _attr_unique_id = "xbloom_weight_unit_select"
    _attr_icon = "mdi:scale"
    _attr_options = list(spec.WEIGHT_UNIT_CODES)
    _service = "set_weight_unit"
    _service_arg = "unit"
    _heartbeat_key = "weight_unit"   # heartbeat "g"/"oz"/"ml"


class XBloomBrewPatternSelect(_XBloomSettingSelect):
    """Pour pattern — two-way, like the grinder/temperature sliders.

    REFLECT: mirrors the brewer's pattern knob (RD_BREWER_MODE 8107) while a
    Connect session streams. DRIVE: while Connected, choosing a pattern sends
    8016 (APP_BREWER_SET_PATTERN, pattern-only) — the app's live pattern command,
    independent of temperature — then speaks it. When not Connected it's a plain
    stored preference (read by the standalone brew button/service).
    """

    _attr_translation_key = "brew_pattern"
    _attr_unique_id = "xbloom_brew_pattern_select"
    _attr_icon = "mdi:rotate-3d-variant"
    _attr_options = list(spec.PATTERN_NAMES)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()   # restore last option
        if self._current_option is None:
            self._current_option = "spiral"   # sensible first-run default

        # REFLECT — the pattern knob fires xbloom_brewer_setting_changed
        # {setting:"pattern", value:<byte>, value_name:<name>}. Update directly
        # (never via async_select_option) so it can't re-drive the machine.
        @callback
        def _on_event(event) -> None:
            data = event.data
            if data.get("setting") != "pattern":
                return
            name = data.get("value_name") or spec.PATTERN_BYTE_TO_NAME.get(
                data.get("value")
            )
            if name in self._attr_options and name != self._current_option:
                self._current_option = name
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(EV_BREWER_SETTING, _on_event)
        )

    def _live_listener(self):
        listener = getattr(
            getattr(self._entry, "runtime_data", None),
            "live_session_listener", None,
        )
        return listener if (listener is not None and listener.is_running) else None

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            _LOGGER.warning(
                "%s: ignoring out-of-range option %r (allowed: %s)",
                self._attr_unique_id, option, self._attr_options,
            )
            return
        self._current_option = option
        self.async_write_ha_state()

        # DRIVE — only when a live session holds the link; else it's a setpoint.
        if self._live_listener() is None:
            return
        pattern_byte = spec.PATTERN_NAME_TO_BYTE.get(option)
        if pattern_byte is None:
            return
        # Pattern-only live set (cmd 8016), independent of temperature — the app's
        # brewer-screen pattern command.
        ok = await send_brewer_pattern_live(self._entry, pattern_byte)
        if ok:
            # Speak it (parity with a knob turn — a commanded set emits no
            # machine knob-event, so a screen-reader user gets no feedback).
            self.hass.bus.async_fire(
                EV_BREWER_SETTING,
                {"setting": "pattern", "value": pattern_byte, "value_name": option},
            )
