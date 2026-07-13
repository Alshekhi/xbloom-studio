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

    async def async_press(self) -> None:
        """Delegate to xbloom.start_brew for the currently selected recipe.

        Grinder use is governed by ``switch.xbloom_studio_use_grinder``: the
        start_brew service reads it when ``use_preground`` isn't passed, so the
        button doesn't need to compute it here.
        """
        select_state = self.hass.states.get("select.xbloom_studio_recipe")
        if select_state is None or select_state.state in ("unknown", "unavailable", ""):
            _LOGGER.warning("Start Brew pressed but no recipe selected — ignoring")
            return
        await self.hass.services.async_call(
            DOMAIN, "start_brew", {}, blocking=False
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
