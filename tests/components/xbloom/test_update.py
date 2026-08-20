"""Tests for update.py — the firmware update entity and its flash guards.

This is the highest-consequence surface in the integration: a bad flash can
brick the machine. So most of what is asserted here is *refusal* — every
precondition that must hold before a single byte reaches the BLE link, and the
MD5 check that stands between a corrupted download and the flasher.

The shared conftest injects the homeassistant stubs, so the entity class can be
constructed and driven without a live hass.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom.const import CONF_ENABLE_FLASHING, CONF_PRODUCT_ID
from custom_components.xbloom.update import XBloomFirmwareUpdate

# HomeAssistantError is a stub-injected class; import it the same way update.py does
# so `pytest.raises` matches the exact type the entity raises.
from homeassistant.exceptions import HomeAssistantError


FIRMWARE = b"\x00\x01\x02\x03" * 64
FIRMWARE_MD5 = hashlib.md5(FIRMWARE).hexdigest()


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #
def _make_entry(
    *,
    flashing_enabled: bool = False,
    serial: str | None = "J15ABC123",
    logged_in: bool = True,
    installed: str | None = None,
    listener: object = None,
):
    coordinator = MagicMock()
    coordinator.cloud_logged_in = logged_in
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    runtime = SimpleNamespace(
        coordinator=coordinator,
        cloud=AsyncMock(),
        installed_fw_version=installed,
        ble_device_resolver=AsyncMock(return_value=MagicMock(name="BLEDevice")),
        live_session_listener=listener,
    )

    entry = MagicMock()
    entry.data = {CONF_PRODUCT_ID: serial, CONF_ENABLE_FLASHING: flashing_enabled}
    entry.entry_id = "test_entry"
    entry.runtime_data = runtime
    return entry


def _make_entity(**kwargs) -> XBloomFirmwareUpdate:
    entry = _make_entry(**kwargs)
    entity = XBloomFirmwareUpdate(entry)
    entity.hass = MagicMock()
    # Entity plumbing that normally arrives via async_added_to_hass.
    entity.async_write_ha_state = MagicMock()
    entity.schedule_update_ha_state = MagicMock()
    entity.async_schedule_update_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


def _armed_entity(**kwargs) -> XBloomFirmwareUpdate:
    """An entity that would actually be allowed to flash — every guard satisfied."""
    entity = _make_entity(flashing_enabled=True, **kwargs)
    entity._latest = "1.2.3"
    entity._release_url = "https://example.invalid/fw.bin"
    entity._md5 = FIRMWARE_MD5
    return entity


# --------------------------------------------------------------------------- #
# supported_features — Install must be hidden unless explicitly armed          #
# --------------------------------------------------------------------------- #
def test_install_not_offered_when_flashing_disabled() -> None:
    """Flashing is opt-in; with the flag off the entity offers no features."""
    entity = _make_entity(flashing_enabled=False)
    assert int(entity.supported_features) == 0


def test_install_offered_when_flashing_enabled() -> None:
    """Arming exposes exactly Install + Progress — not Backup, which we can't do."""
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(flashing_enabled=True)
    assert entity.supported_features == (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )


# --------------------------------------------------------------------------- #
# available — firmware comparison is a cloud feature                          #
# --------------------------------------------------------------------------- #
def test_unavailable_when_logged_out() -> None:
    entity = _make_entity(logged_in=False)
    entity._latest = "1.2.3"
    assert entity.available is False


def test_unavailable_without_serial() -> None:
    entity = _make_entity(serial=None)
    entity._latest = "1.2.3"
    assert entity.available is False


def test_unavailable_before_latest_is_known() -> None:
    entity = _make_entity()
    assert entity._latest is None
    assert entity.available is False


def test_available_when_logged_in_with_serial_and_latest() -> None:
    entity = _make_entity()
    entity._latest = "1.2.3"
    assert entity.available is True


# --------------------------------------------------------------------------- #
# installed_version — captured from the BLE heartbeat                         #
# --------------------------------------------------------------------------- #
def test_ble_event_captures_firmware_version() -> None:
    entity = _make_entity()
    entity._on_ble_event({"fw_version": "1.2.0"})
    assert entity.installed_version == "1.2.0"
    entity.schedule_update_ha_state.assert_called_once()


def test_ble_event_without_version_is_ignored() -> None:
    """Most heartbeats carry no fw_version — they must not write state."""
    entity = _make_entity()
    entity._on_ble_event({"weight": 18.2})
    assert entity.installed_version is None
    entity.schedule_update_ha_state.assert_not_called()


def test_repeated_same_version_does_not_rewrite_state() -> None:
    """The heartbeat repeats forever; only a *change* is worth a state write."""
    entity = _make_entity(installed="1.2.0")
    entity._on_ble_event({"fw_version": "1.2.0"})
    entity.schedule_update_ha_state.assert_not_called()


def test_ble_event_uses_threadsafe_state_write() -> None:
    """Notifications can arrive off-loop, so the direct write would be unsafe."""
    entity = _make_entity()
    entity._on_ble_event({"fw_version": "9.9.9"})
    entity.schedule_update_ha_state.assert_called_once()
    entity.async_write_ha_state.assert_not_called()


# --------------------------------------------------------------------------- #
# Login-state transitions                                                     #
# --------------------------------------------------------------------------- #
def test_login_transition_triggers_refresh() -> None:
    """Latest version should appear right after login, not 6 hours later."""
    entity = _make_entity(logged_in=False)
    entity._was_logged_in = False
    entity._entry.runtime_data.coordinator.cloud_logged_in = True
    entity._on_coordinator_update()
    entity.async_schedule_update_ha_state.assert_called_once_with(force_refresh=True)


def test_logout_clears_latest_version() -> None:
    entity = _make_entity()
    entity._was_logged_in = True
    entity._latest = "1.2.3"
    entity._entry.runtime_data.coordinator.cloud_logged_in = False
    entity._on_coordinator_update()
    assert entity._latest is None


def test_coordinator_update_without_transition_does_nothing() -> None:
    """Recipe changes also tick the coordinator — don't call the cloud for those."""
    entity = _make_entity(logged_in=True)
    entity._was_logged_in = True
    entity._on_coordinator_update()
    entity.async_schedule_update_ha_state.assert_not_called()
    entity.async_write_ha_state.assert_not_called()


# --------------------------------------------------------------------------- #
# async_update — cloud poll                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_populates_from_cloud() -> None:
    entity = _make_entity()
    entity._entry.runtime_data.cloud.firmware_check = AsyncMock(
        return_value={
            "version": "1.3.0",
            "version_id": 42,
            "notes_en": "Fixes grinding",
            "download_url": "https://example.invalid/fw.bin",
            "md5": FIRMWARE_MD5,
        }
    )
    await entity.async_update()
    assert entity.latest_version == "1.3.0"
    assert entity.release_summary == "Fixes grinding"
    assert entity.release_url == "https://example.invalid/fw.bin"


@pytest.mark.asyncio
async def test_update_skips_cloud_when_logged_out() -> None:
    entity = _make_entity(logged_in=False)
    entity._latest = "stale"
    await entity.async_update()
    assert entity.latest_version is None
    entity._entry.runtime_data.cloud.firmware_check.assert_not_called()


@pytest.mark.asyncio
async def test_update_falls_back_to_chinese_notes() -> None:
    """notes_en is often empty; the zh notes are better than no summary."""
    entity = _make_entity()
    entity._entry.runtime_data.cloud.firmware_check = AsyncMock(
        return_value={"version": "1.3.0", "notes_en": "", "notes_zh": "修复"}
    )
    await entity.async_update()
    assert entity.release_summary == "修复"


@pytest.mark.asyncio
async def test_update_survives_cloud_error() -> None:
    """A failed poll must not blow up the entity or wipe a known version."""
    from custom_components.xbloom.vendor.xbloom.exceptions import XBloomAPIError

    entity = _make_entity()
    entity._latest = "1.2.3"
    entity._entry.runtime_data.cloud.firmware_check = AsyncMock(
        side_effect=XBloomAPIError("boom")
    )
    await entity.async_update()
    assert entity.latest_version == "1.2.3"


# --------------------------------------------------------------------------- #
# async_install — the guards that stand between a user and a bricked machine   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_install_refused_when_flashing_disabled() -> None:
    entity = _make_entity(flashing_enabled=False)
    entity._latest = "1.2.3"
    entity._release_url = "https://example.invalid/fw.bin"
    entity._md5 = FIRMWARE_MD5
    with pytest.raises(HomeAssistantError, match="disabled"):
        await entity.async_install(None, False)


@pytest.mark.asyncio
async def test_install_refused_while_already_flashing() -> None:
    """A second Install mid-flash would interleave writes on the same link."""
    entity = _armed_entity()
    entity._flashing = True
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await entity.async_install(None, False)


@pytest.mark.asyncio
async def test_install_refused_when_logged_out() -> None:
    entity = _armed_entity(logged_in=False)
    with pytest.raises(HomeAssistantError, match="[Ll]og in"):
        await entity.async_install(None, False)


@pytest.mark.asyncio
async def test_install_refused_without_download_url() -> None:
    entity = _armed_entity()
    entity._release_url = None
    with pytest.raises(HomeAssistantError, match="No firmware download"):
        await entity.async_install(None, False)


@pytest.mark.asyncio
async def test_install_refused_without_md5() -> None:
    """No published MD5 means no way to prove the bytes are intact."""
    entity = _armed_entity()
    entity._md5 = None
    with pytest.raises(HomeAssistantError, match="No firmware download"):
        await entity.async_install(None, False)


# --------------------------------------------------------------------------- #
# _download_and_verify — the MD5 gate                                         #
# --------------------------------------------------------------------------- #
def _patch_session(entity, payload: bytes) -> None:
    """Wire async_get_clientsession so `session.get(url)` yields `payload`."""
    import custom_components.xbloom.update as update_mod

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.read = AsyncMock(return_value=payload)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    update_mod.async_get_clientsession = MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_download_returns_bytes_when_md5_matches() -> None:
    entity = _armed_entity()
    _patch_session(entity, FIRMWARE)
    assert await entity._download_and_verify() == FIRMWARE


@pytest.mark.asyncio
async def test_download_refuses_on_md5_mismatch() -> None:
    """A corrupted or substituted image must never reach the flasher."""
    entity = _armed_entity()
    _patch_session(entity, b"tampered payload")
    with pytest.raises(HomeAssistantError, match="MD5 mismatch"):
        await entity._download_and_verify()


@pytest.mark.asyncio
async def test_md5_comparison_is_case_insensitive() -> None:
    """The API returns uppercase hex in some responses; hexdigest() is lower."""
    entity = _armed_entity()
    entity._md5 = FIRMWARE_MD5.upper()
    _patch_session(entity, FIRMWARE)
    assert await entity._download_and_verify() == FIRMWARE


# --------------------------------------------------------------------------- #
# _pause_live_session — the flasher needs an exclusive link                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_pause_live_session_stops_and_clears_listener() -> None:
    listener = AsyncMock()
    entity = _make_entity(listener=listener)
    await entity._pause_live_session()
    listener.stop.assert_awaited_once()
    assert entity._entry.runtime_data.live_session_listener is None


@pytest.mark.asyncio
async def test_pause_live_session_is_a_noop_without_a_session() -> None:
    entity = _make_entity(listener=None)
    await entity._pause_live_session()  # must not raise
    assert entity._entry.runtime_data.live_session_listener is None


@pytest.mark.asyncio
async def test_pause_live_session_swallows_stop_failure() -> None:
    """A listener that won't stop shouldn't abort the update with a raw traceback."""
    listener = AsyncMock()
    listener.stop = AsyncMock(side_effect=RuntimeError("link already gone"))
    entity = _make_entity(listener=listener)
    await entity._pause_live_session()  # must not raise
