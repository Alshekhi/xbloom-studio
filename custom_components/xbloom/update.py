"""Firmware update entity for the xBloom Studio integration.

Compares the machine's *installed* firmware (reported over BLE) against the
*latest* the xBloom cloud publishes, shows release notes, and — when the user
presses Install — flashes it over BLE.

Two data sources, mirroring the rest of the integration:
  * **installed_version** — decoded from the machine's BLE ``RD_MachineInfo``
    heartbeat (``fw_version`` in the dispatched event) whenever Home Assistant
    is connected to the machine. Persisted across restarts via RestoreEntity so
    it survives a reload even while disconnected.
  * **latest_version** — the version the xBloom cloud reports for this serial
    (``tUpToDateFirmwareVersion.thtml``). Cloud is a login-gated feature, so the
    entity is only *available* when logged in.

The **Install** flow downloads the ``.bin`` from the cloud-provided S3 URL
(plain GET, no auth), verifies its MD5 against the API value, then runs the
ACK-gated BLE flasher (``xbloom.ota``, byte-exact-validated against a real
capture). Any Connect session is paused for the duration so the flasher owns the
BLE link. ⚠️ Flashing can brick the machine if the link drops mid-transfer — it is a
deliberate, user-initiated action.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .ble_entities import signal_event
from .const import CONF_ENABLE_FLASHING, CONF_PRODUCT_ID, DOMAIN
from xbloom.exceptions import XBloomAPIError
from xbloom.ota import XBloomOtaError, XBloomOtaFlasher

_LOGGER = logging.getLogger(__name__)

# Firmware releases are rare — poll the cloud gently for the latest version.
SCAN_INTERVAL = timedelta(hours=6)
PARALLEL_UPDATES = 0

# BLE write pacing for the flash, supplied by this (HA) integration layer to the
# vendor flasher. 0 relies on the BLE stack's own backpressure (correct on
# BlueZ); a few ms is safer through an ESPHome BLE proxy. Conservative default;
# tune here if a real flash is flaky on your setup.
_OTA_CHUNK_DELAY_S = 0.004
_OTA_BLOCK_SETTLE_S = 0.02


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the firmware update entity."""
    async_add_entities([XBloomFirmwareUpdate(entry)])


class XBloomFirmwareUpdate(UpdateEntity, RestoreEntity):
    """Installed (BLE) vs latest (cloud) firmware — read-only."""

    _attr_has_entity_name = True
    _attr_translation_key = "xbloom_firmware"
    _attr_unique_id = "xbloom_firmware"

    def __init__(self, entry) -> None:
        self._entry = entry
        self._serial = entry.data.get(CONF_PRODUCT_ID)
        self._latest: str | None = None
        self._version_id = None
        self._release_summary: str | None = None
        self._release_url: str | None = None       # S3 .bin download URL
        self._md5: str | None = None
        self._was_logged_in = False
        self._flashing = False

    @property
    def supported_features(self) -> UpdateEntityFeature:
        # Install appears only when the user has explicitly armed firmware
        # flashing (off by default — the flash is validated byte-exact but not
        # yet proven on live hardware, and can brick the machine).
        if self._entry.data.get(CONF_ENABLE_FLASHING):
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
        return UpdateEntityFeature(0)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    @property
    def available(self) -> bool:
        # Firmware is a cloud feature — unavailable until logged in with a serial
        # and a fetched latest version to compare against.
        coordinator = self._entry.runtime_data.coordinator
        return bool(
            coordinator.cloud_logged_in and self._serial and self._latest
        )

    @property
    def installed_version(self) -> str | None:
        # Reported by the machine over BLE; None until a heartbeat is seen.
        return self._entry.runtime_data.installed_fw_version

    @property
    def latest_version(self) -> str | None:
        return self._latest

    @property
    def release_summary(self) -> str | None:
        return self._release_summary

    @property
    def release_url(self) -> str | None:
        return self._release_url

    async def async_added_to_hass(self) -> None:
        """Restore the last-seen installed version and subscribe to BLE events."""
        await super().async_added_to_hass()
        # Restore installed_version across restarts (the machine may be
        # disconnected at startup, so we can't re-read it immediately).
        if self._entry.runtime_data.installed_fw_version is None:
            last = await self.async_get_last_state()
            if last is not None:
                restored = last.attributes.get("installed_version")
                if restored:
                    self._entry.runtime_data.installed_fw_version = restored

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry.entry_id), self._on_ble_event
            )
        )

        # Re-check the cloud latest version when the login state flips on (so it
        # appears right after login, not on the next 6-hour tick) and clear it on
        # logout. Coordinator refreshes fire on recipe changes too, so we only act
        # on an actual login-state transition to avoid needless firmware calls.
        coordinator = self._entry.runtime_data.coordinator
        self._was_logged_in = coordinator.cloud_logged_in
        self.async_on_remove(
            coordinator.async_add_listener(self._on_coordinator_update)
        )

    def _on_coordinator_update(self) -> None:
        coordinator = self._entry.runtime_data.coordinator
        logged_in = coordinator.cloud_logged_in
        if logged_in and not self._was_logged_in:
            self._was_logged_in = True
            self.async_schedule_update_ha_state(force_refresh=True)
        elif not logged_in and self._was_logged_in:
            self._was_logged_in = False
            self._latest = None
            self.async_write_ha_state()

    def _on_ble_event(self, decoded: dict) -> None:
        """Capture the firmware version from the machine's BLE heartbeat."""
        version = decoded.get("fw_version")
        if not version or version == self._entry.runtime_data.installed_fw_version:
            return
        _LOGGER.debug("xbloom firmware: machine reports installed version %s", version)
        self._entry.runtime_data.installed_fw_version = version
        # The BLE notification can reach us off the event loop (bleak marshals
        # via run_coroutine_threadsafe, but HA still flags a direct state write
        # here as non-thread-safe). schedule_update_ha_state hops onto the loop.
        self.schedule_update_ha_state()

    async def async_update(self) -> None:
        """Poll the cloud for the latest firmware for this machine."""
        coordinator = self._entry.runtime_data.coordinator
        if not coordinator.cloud_logged_in or not self._serial:
            self._latest = None
            return
        cloud = self._entry.runtime_data.cloud
        try:
            info = await cloud.firmware_check(self._serial)
        except (XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.debug("xbloom firmware check failed: %s", err)
            return
        if info is None:
            self._latest = None
            return
        self._latest = info["version"]
        self._version_id = info.get("version_id")
        self._release_summary = info.get("notes_en") or info.get("notes_zh")
        self._release_url = info.get("download_url")
        self._md5 = info.get("md5")

    # -- install ------------------------------------------------------------ #
    async def async_install(self, version, backup, **kwargs) -> None:
        """Download, verify, and flash the firmware over BLE."""
        if not self._entry.data.get(CONF_ENABLE_FLASHING):
            raise HomeAssistantError(
                "Firmware flashing is disabled. Enable it in the integration's "
                "Configure menu first (it's off by default because a flash can "
                "brick the machine and isn't yet hardware-tested)."
            )
        if self._flashing:
            raise HomeAssistantError("A firmware update is already in progress.")
        coordinator = self._entry.runtime_data.coordinator
        if not coordinator.cloud_logged_in:
            raise HomeAssistantError("Log in to the xBloom cloud first.")
        if not self._release_url or not self._md5:
            raise HomeAssistantError(
                "No firmware download available — try again after the entity refreshes."
            )

        target = version or self._latest
        firmware = await self._download_and_verify()

        resolver = self._entry.runtime_data.ble_device_resolver
        device = await resolver() if resolver else None
        if device is None:
            raise HomeAssistantError(
                "The machine isn't reachable over Bluetooth right now. Make sure "
                "it's powered on and in range."
            )

        # The flasher needs an exclusive BLE link — pause any Connect session.
        await self._pause_live_session()

        self._flashing = True
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        def _on_progress(done: int, total: int) -> None:
            self._attr_update_percentage = int(done * 100 / total)
            self.async_write_ha_state()

        model = (self._serial or "J15")[:3] or "J15"
        try:
            flasher = XBloomOtaFlasher(
                device, progress=_on_progress,
                chunk_delay=_OTA_CHUNK_DELAY_S, block_settle=_OTA_BLOCK_SETTLE_S,
            )
            await flasher.flash(firmware, target, model)
        except XBloomOtaError as err:
            _LOGGER.error("xbloom firmware: flash failed: %s", err)
            raise HomeAssistantError(f"Firmware update failed: {err}") from err
        except Exception as err:  # noqa: BLE001 — surface any BLE/transport error
            _LOGGER.exception("xbloom firmware: unexpected flash error")
            raise HomeAssistantError(f"Firmware update failed: {err}") from err
        finally:
            self._flashing = False
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()

        # Optimistic; the machine's next heartbeat confirms the real version.
        self._entry.runtime_data.installed_fw_version = target
        _LOGGER.info(
            "xbloom firmware: flash to %s completed. The xBloom cloud still shows "
            "the old version until you open the official app once — reporting it "
            "ourselves would mean a full machine-settings sync (tuMachineUpdate) "
            "that could clobber your cloud-stored settings, so we don't.",
            target,
        )
        self.async_write_ha_state()

    async def _download_and_verify(self) -> bytes:
        session = async_get_clientsession(self.hass)
        _LOGGER.info("xbloom firmware: downloading %s", self._release_url)
        try:
            async with session.get(self._release_url) as resp:
                resp.raise_for_status()
                firmware = await resp.read()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"Firmware download failed: {err}") from err
        got = hashlib.md5(firmware).hexdigest().lower()
        if got != self._md5.lower():
            raise HomeAssistantError(
                f"Firmware MD5 mismatch (got {got}, expected {self._md5.lower()}) "
                "— refusing to flash."
            )
        _LOGGER.info("xbloom firmware: downloaded %d bytes, MD5 OK", len(firmware))
        return firmware

    async def _pause_live_session(self) -> None:
        """Stop any long-lived BLE listener so the flasher owns the link."""
        listener = getattr(
            self._entry.runtime_data, "live_session_listener", None,
        )
        if listener is not None:
            try:
                await listener.stop()
                self._entry.runtime_data.live_session_listener = None
                _LOGGER.info(
                    "xbloom firmware: paused the Connect session for the update "
                    "(re-enable it afterwards)"
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "xbloom firmware: could not pause the Connect session"
                )
