"""Manual refresh and brew control buttons for the xBloom Studio integration.

XBloomRefreshButton:    triggers an immediate recipe library refresh.
XBloomStartBrewButton:  delegates to the `xbloom.start_brew` service, which
                        builds the recipe blob locally and dispatches over BLE.
XBloomCancelBrewButton: delegates to the `xbloom.stop_brew` service, which
                        sends the BLE APP_BREWER_STOP (4507) command.
"""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import XBloomCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1  # action entity — serialize concurrent button presses


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the xBloom button entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        XBloomRefreshButton(coordinator),
        XBloomStartBrewButton(coordinator, entry),   # Phase 7 — D-01
        XBloomCancelBrewButton(entry),               # Phase 7 — D-03
        # Phase 8 — 08-01: simple-command primitives
        XBloomTareButton(entry),
        XBloomBackToHomeButton(entry),
        XBloomBrewPauseButton(entry),
        XBloomBrewResumeButton(entry),
        # Phase 8 — 08-02: standalone grind shortcut
        XBloomGrindButton(entry),
        XBloomBrewStandaloneButton(entry),
        # Phase 8 — 08-04: BLE link probes (also reachable as services)
        XBloomBleConnectButton(entry),
        XBloomBleDisconnectButton(entry),
        XBloomRefreshStatusButton(entry),
        # Module-enter navigation (over the held Connect session)
        XBloomEnterGrinderButton(entry),
        XBloomEnterBrewerButton(entry),
        XBloomEnterScaleButton(entry),
        # Brew customizer — save the slider-scaled recipe as a new one
        XBloomSaveAsNewRecipeButton(entry),
    ])


class XBloomRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that triggers an immediate coordinator refresh.

    Uses async_request_refresh() (rate-limited) rather than async_refresh()
    to prevent hammering the API on rapid button presses.
    """

    _attr_has_entity_name = True
    _attr_name = "Refresh Recipes"
    _attr_unique_id = "xbloom_refresh_button"
    _attr_icon = "mdi:refresh"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group entity under 'xBloom Studio' device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    async def async_press(self) -> None:
        """Trigger an immediate recipe list refresh."""
        _LOGGER.debug("Manual recipe refresh requested")
        await self.coordinator.async_request_refresh()


class XBloomStartBrewButton(CoordinatorEntity, ButtonEntity):
    """Triggers a cloud brew for the currently selected recipe.

    D-01: Phase 7 brew control button on device card.
    D-02: available returns False when no recipe is selected (HA greys out automatically).
    Reads recipe from select.xbloom_studio_recipe extra_state_attributes (Phase 7 contract).
    Fires 'xbloom_brew_started' bus event so event.py can capture the recipe name (D-09).
    """

    _attr_has_entity_name = True
    _attr_name = "Start Brew"
    _attr_unique_id = "xbloom_start_brew_button"
    _attr_icon = "mdi:coffee-maker-check"

    def __init__(self, coordinator: XBloomCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Group entity under 'xBloom Studio' device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def available(self) -> bool:
        """Return False when no recipe is selected (D-02)."""
        select_state = self.hass.states.get("select.xbloom_studio_recipe")
        if select_state is None or select_state.state in ("unknown", "unavailable", ""):
            return False
        return True

    async def async_added_to_hass(self) -> None:
        """Subscribe to select.xbloom_studio_recipe so `available` re-evaluates on selection."""
        await super().async_added_to_hass()

        @callback
        def _on_select_change(_event: Event[EventStateChangedData]) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, ["select.xbloom_studio_recipe"], _on_select_change
            )
        )

    @staticmethod
    def _num(hass, entity_id: str):
        """Read a NumberEntity state as float, or None if it isn't usable."""
        st = hass.states.get(entity_id)
        if st is None or st.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None

    async def async_press(self) -> None:
        """Delegate to xbloom.start_brew for the currently selected recipe.

        The brew customizer's three sliders are folded in as one-off overrides:
        left untouched they equal the recipe's own values, so a plain press
        still brews the recipe exactly. Grinder use is governed by
        ``switch.xbloom_studio_use_grinder`` (start_brew reads it when
        ``use_preground`` isn't passed), so the button doesn't compute it here.
        """
        select_state = self.hass.states.get("select.xbloom_studio_recipe")
        if select_state is None or select_state.state in ("unknown", "unavailable", ""):
            _LOGGER.warning("Start Brew pressed but no recipe selected — ignoring")
            return
        data: dict = {}
        ratio = self._num(self.hass, "number.xbloom_studio_brew_ratio")
        grind = self._num(self.hass, "number.xbloom_studio_brew_grind_size")
        dose = self._num(self.hass, "number.xbloom_studio_brew_dose")
        if ratio is not None:
            data["ratio"] = ratio
        if grind is not None:
            data["grind_size"] = int(grind)
        if dose is not None:          # absent/unavailable (xPod) → keep recipe dose
            data["dose"] = dose
        await self.hass.services.async_call(
            DOMAIN, "start_brew", data, blocking=False
        )


class XBloomCancelBrewButton(ButtonEntity):
    """Sends stop command (FFFF11) to cancel an in-progress brew.

    D-03: bruw_curve "FFFF11" is the confirmed stop command.
    Does NOT require CoordinatorEntity — no coordinator dependency.
    """

    _attr_has_entity_name = True
    _attr_name = "Cancel Brew"
    _attr_unique_id = "xbloom_cancel_brew_button"
    _attr_icon = "mdi:coffee-maker-off"

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Group entity under 'xBloom Studio' device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    async def async_press(self) -> None:
        """Delegate to xbloom.stop_brew (sends BLE APP_BREWER_STOP)."""
        await self.hass.services.async_call(DOMAIN, "stop_brew", {}, blocking=False)


# ---------------------------------------------------------------------------
# Phase 8 — 08-01: simple-command primitives
# Each button is a thin shim over its corresponding xbloom.* service. They are
# always available — pressing has no precondition. Same device-card grouping
# as the existing buttons so VoiceOver reads them under "xBloom Studio".
# ---------------------------------------------------------------------------
class _XBloomSimpleCommandButton(ButtonEntity):
    """Shared base for the 08-01 single-frame command buttons."""

    _attr_has_entity_name = True
    _service: str = ""  # subclass overrides

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    async def async_press(self) -> None:
        await self.hass.services.async_call(DOMAIN, self._service, {}, blocking=False)


class XBloomTareButton(_XBloomSimpleCommandButton):
    """Zero the scale on the machine (BLE cmd 8500)."""

    _attr_name = "Tare Scale"
    _attr_unique_id = "xbloom_tare_button"
    _attr_icon = "mdi:scale-balance"
    _service = "tare"


class XBloomBackToHomeButton(_XBloomSimpleCommandButton):
    """Return the machine UI to the home screen (BLE cmd 8022)."""

    _attr_name = "Back to Home"
    _attr_unique_id = "xbloom_back_to_home_button"
    _attr_icon = "mdi:home"
    _service = "back_to_home"


class XBloomBrewPauseButton(_XBloomSimpleCommandButton):
    """Pause an in-flight brew (BLE cmd 40518)."""

    _attr_name = "Pause Brew"
    _attr_unique_id = "xbloom_brew_pause_button"
    _attr_icon = "mdi:pause"
    _service = "brew_pause"


class XBloomBrewResumeButton(_XBloomSimpleCommandButton):
    """Resume a paused brew (BLE cmd 8021)."""

    _attr_name = "Resume Brew"
    _attr_unique_id = "xbloom_brew_resume_button"
    _attr_icon = "mdi:play"
    _service = "brew_resume"


class XBloomGrindButton(_XBloomSimpleCommandButton):
    """One-press standalone grind — reads size and speed from number entities."""

    _attr_name = "Grind"
    _attr_unique_id = "xbloom_grind_button"
    _attr_icon = "mdi:grain"
    _service = "grind"

    async def async_press(self) -> None:
        size_state = self.hass.states.get("number.grind_size")
        speed_state = self.hass.states.get("number.grind_speed")
        size = int(float(size_state.state)) if size_state and size_state.state not in ("unknown", "unavailable") else 65
        speed = int(float(speed_state.state)) if speed_state and speed_state.state not in ("unknown", "unavailable") else 60
        await self.hass.services.async_call(
            DOMAIN, "grind",
            {"size": size, "speed": speed, "seconds": 5},
            blocking=False,
        )


class XBloomBrewStandaloneButton(_XBloomSimpleCommandButton):
    """One-press standalone brew — reads volume, temp, flow rate, and pattern from entities."""

    _attr_name = "Brew (standalone)"
    _attr_unique_id = "xbloom_brew_standalone_button"
    _attr_icon = "mdi:coffee"
    _service = "brew_standalone"

    async def async_press(self) -> None:
        await self.hass.services.async_call(DOMAIN, "brew_standalone", {}, blocking=False)


class XBloomBleConnectButton(_XBloomSimpleCommandButton):
    """Probe the BLE link without brewing — connect, handshake, subscribe to
    FFE2, release, disconnect. Surfaces every step in the log. Useful when
    diagnosing connection failures (especially if a Mode listener fails).
    """

    _attr_name = "BLE Connect"
    _attr_unique_id = "xbloom_ble_connect_button"
    _attr_icon = "mdi:bluetooth-connect"
    _service = "ble_connect"


class XBloomBleDisconnectButton(_XBloomSimpleCommandButton):
    """Force-disconnect any HA-held BLE link to the machine (best-effort).
    Use if a previous brew or mode-listener left a stale handle and the iOS
    app can't connect.
    """

    _attr_name = "BLE Disconnect"
    _attr_unique_id = "xbloom_ble_disconnect_button"
    _attr_icon = "mdi:bluetooth-off"
    _service = "ble_disconnect"


class XBloomRefreshStatusButton(_XBloomSimpleCommandButton):
    """Method-1 snapshot: briefly open BLE, capture one status heartbeat, then
    disconnect — refreshes every machine-status sensor (and stamps "Status
    updated") without holding a Connect session. Thin shim over the
    ``xbloom.refresh_status`` service so the dashboard has a real, named button
    entity instead of an entity-less button card.
    """

    _attr_name = "Refresh Status"
    _attr_unique_id = "xbloom_refresh_status_button"
    _attr_icon = "mdi:cloud-sync"
    _service = "refresh_status"


# ---------------------------------------------------------------------------
# Module-ENTER (navigation) buttons — route the machine to a module over the
# HELD Connect session, exactly like tapping Grinder/Brewer/Scale on the app's
# home screen. They NAVIGATE only (no grind/brew/heat). The dashboard shows
# them only while Connected; pressing while disconnected is a quiet no-op.
# When Connected the HA sliders reflect the machine, so entering re-sends the
# machine's own values (grinder 8006 / brewer 8007) — effectively pure routing.
# ---------------------------------------------------------------------------
class _XBloomEnterModuleButton(_XBloomSimpleCommandButton):
    """Base for the three module-enter buttons (send a frame over the session)."""

    def _num(self, entity_id: str, default: float) -> float:
        st = self.hass.states.get(entity_id)
        if st is None or st.state in ("unknown", "unavailable"):
            return default
        try:
            return float(st.state)
        except ValueError:
            return default

    async def _send(self, frame: bytes) -> None:
        from .ble_entities import send_live_frame
        if not await send_live_frame(self._entry, frame):
            _LOGGER.info(
                "%s: no live Connect session — connect first", self._attr_unique_id,
            )


class XBloomEnterGrinderButton(_XBloomEnterModuleButton):
    """Route the machine to the Grinder screen (cmd 8006 [size, speed])."""

    _attr_name = "Go to Grinder"
    _attr_unique_id = "xbloom_enter_grinder_button"
    _attr_icon = "mdi:grain"

    async def async_press(self) -> None:
        from .vendor.xbloom.ble import packet_grinder_set
        size = int(self._num("number.xbloom_studio_grind_size", 65))
        speed = int(self._num("number.xbloom_studio_grind_speed", 60))
        await self._send(packet_grinder_set(size, speed))


class XBloomEnterBrewerButton(_XBloomEnterModuleButton):
    """Route the machine to the Brewer screen (cmd 8007 [pattern, temp×10])."""

    _attr_name = "Go to Brewer"
    _attr_unique_id = "xbloom_enter_brewer_button"
    _attr_icon = "mdi:cup-water"

    async def async_press(self) -> None:
        from .vendor.xbloom import spec
        from .vendor.xbloom.ble import packet_brewer_set
        st = self.hass.states.get("select.xbloom_studio_brew_pattern")
        name = st.state if st is not None else None
        pattern = spec.PATTERN_NAME_TO_BYTE.get(
            name, spec.PATTERN_NAME_TO_BYTE[spec.PATTERN_NAMES[0]],
        )
        wire_temp = spec.brew_temp_display_to_wire(
            self._num("number.xbloom_studio_brew_temperature", 93),
        )
        await self._send(packet_brewer_set(pattern, wire_temp))


class XBloomEnterScaleButton(_XBloomEnterModuleButton):
    """Route the machine to the Scale screen (cmd 8003, no data)."""

    _attr_name = "Go to Scale"
    _attr_unique_id = "xbloom_enter_scale_button"
    _attr_icon = "mdi:scale-balance"

    async def async_press(self) -> None:
        from .vendor.xbloom.ble import packet_scale_enter
        await self._send(packet_scale_enter())


class XBloomSaveAsNewRecipeButton(ButtonEntity):
    """Brew customizer 'Save as new recipe'.

    Saves the picked recipe — scaled by the customizer sliders — under the
    ``New Recipe Name`` as a brand-new recipe (local when logged out; cloud +
    local mirror when logged in). Never touches the source. Greys out until a
    recipe is picked and a non-empty name is entered.
    """

    _attr_has_entity_name = True
    _attr_name = "Save as New Recipe"
    _attr_unique_id = "xbloom_save_as_new_recipe_button"
    _attr_icon = "mdi:content-save-plus"

    _SELECT = "select.xbloom_studio_recipe"
    _NAME = "text.xbloom_studio_new_recipe_name"

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    def _recipe_state(self):
        st = self.hass.states.get(self._SELECT)
        if st is None or st.state in ("unknown", "unavailable", ""):
            return None
        return st

    def _name(self) -> str:
        st = self.hass.states.get(self._NAME)
        return (st.state if st else "").strip()

    @property
    def available(self) -> bool:
        return self._recipe_state() is not None and bool(self._name())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _reeval(_event: Event[EventStateChangedData]) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._SELECT, self._NAME], _reeval
            )
        )

    async def async_press(self) -> None:
        sel = self._recipe_state()
        if sel is None:
            _LOGGER.warning("Save as new recipe pressed but no recipe selected")
            return
        new_name = self._name()
        if not new_name:
            _LOGGER.warning("Save as new recipe pressed but name is empty")
            return
        ratio = XBloomStartBrewButton._num(self.hass, "number.xbloom_studio_brew_ratio")
        grind = XBloomStartBrewButton._num(self.hass, "number.xbloom_studio_brew_grind_size")
        dose = XBloomStartBrewButton._num(self.hass, "number.xbloom_studio_brew_dose")
        if dose is None:
            # xPod (fixed dose) hides the slider — fall back to the recipe's dose.
            try:
                dose = float(sel.attributes.get("dose_g"))
            except (TypeError, ValueError):
                dose = None
        if ratio is None or grind is None or dose is None:
            _LOGGER.warning(
                "Save as new recipe: missing values (ratio=%s grind=%s dose=%s)",
                ratio, grind, dose,
            )
            return
        await self.hass.services.async_call(
            DOMAIN, "save_scaled_recipe",
            {
                "new_name": new_name,
                "recipe_name": sel.state,
                "dose": dose,
                "ratio": ratio,
                "grind_size": int(grind),
            },
            blocking=False,
        )
