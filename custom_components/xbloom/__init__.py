"""xBloom Studio integration for Home Assistant — BLE-only.

Architecture:

  * Recipe data comes from the public xBloom share endpoint
    (`RecipeDetail.html`) — no authentication.
  * Recipes the user wants in HA are stored in HA's local storage and added
    via the integration's options flow.
  * Brewing is BLE-only: connect-on-demand via HA's bluetooth integration.
    The recipe blob is built locally by `vendor.xbloom.ble.encode_recipe_blob`
    and the 5-frame brew sequence is written to the machine. Live status
    (scale weight, brew state, brew events) streams from FFE2 notifications
    during the brew, then HA disconnects so the iOS app can take BLE.

Earlier phases shipped a Pi MQTT bridge + cloud auth + always-on listener;
all gone. See `git log` for the full evolution.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import json

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BLE_NAME, CONF_PRODUCT_ID, DOMAIN
from .coordinator import XBloomCoordinator
from .vendor.xbloom.client import XBloomClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "button", "number", "sensor", "event", "switch"]

# A start_brew call within this many seconds of the previous dispatch is
# treated as a duplicate (e.g. a voice-agent HTTP retry) and ignored. A call
# after the window preempts the earlier session instead — see handle_start_brew.
BREW_DUP_WINDOW_S = 20.0


@dataclass
class XBloomRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: XBloomCoordinator
    client: XBloomClient
    # BLE device resolver — set in async_setup_entry. Phase 8 mode
    # listeners (08-04+) re-resolve on every start so adapter routing
    # stays correct after rediscovery.
    ble_device_resolver: object = None
    # Long-lived listeners — created by switch.py during platform setup.
    # We keep refs here so they're stoppable from async_unload_entry.
    scale_listener: object = None       # legacy slot (Voice Mode replaces it)
    grinder_listener: object = None     # legacy slot
    brewer_listener: object = None      # legacy slot
    voice_listener: object = None       # unified Voice Mode listener


type XBloomConfigEntry = ConfigEntry[XBloomRuntimeData]


def _resolve_ble_name(entry: ConfigEntry) -> str | None:
    """Pick a BLE advertiser name from entry data — explicit or derived."""
    name = entry.data.get(CONF_BLE_NAME)
    if name:
        return name
    serial = entry.data.get(CONF_PRODUCT_ID, "") or ""
    return f"XBLOOM {serial[-6:]}" if serial else None


async def _resolve_ble_device(hass: HomeAssistant, ble_name: str):
    """Look up a connectable BLEDevice for this advertiser name through HA's
    bluetooth integration.

    Going through HA's bluetooth coordination (instead of a direct
    `BleakScanner.find_device_by_name`) routes the connection via the
    correct adapter (local Pi BlueZ vs an ESPHome BLE proxy on the same
    network) and lets `bleak_retry_connector` clean up stale handles.
    """
    from homeassistant.components import bluetooth
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        if info.name == ble_name:
            return info.device
    return None


async def async_setup_entry(hass: HomeAssistant, entry: XBloomConfigEntry) -> bool:
    """Set up xBloom Studio from a config entry."""
    session = async_get_clientsession(hass)
    client = XBloomClient(session)

    coordinator = XBloomCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # BLE device resolver — captures `entry` so the switch platform doesn't
    # need to reach back here. Mode listeners call this on every start().
    async def _ble_device_for_listener():
        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            return None
        return await _resolve_ble_device(hass, ble_name)

    entry.runtime_data = XBloomRuntimeData(
        coordinator=coordinator,
        client=client,
        ble_device_resolver=_ble_device_for_listener,
    )

    # ------------------------------------------------------------------ #
    # Shared recipe-resolution helper                                    #
    # Source priority: share_url → share_id → recipe_name → select state #
    # Used by start_brew (Phase 7) and write_slot (08-03).               #
    # ------------------------------------------------------------------ #
    async def _resolve_recipe(
        *,
        share_url: str | None = None,
        share_id: str | None = None,
        recipe_name: str | None = None,
        log_label: str = "xbloom",
    ) -> tuple[dict | None, str]:
        """Resolve a recipe dict + display name.

        Returns (recipe, name). If recipe is None the failure was already
        logged with `log_label` as the prefix.
        """
        api_client = entry.runtime_data.client

        if share_url or share_id:
            try:
                resolved_id = (
                    api_client.share_id_from_url(share_url) if share_url else share_id
                )
                recipe = await api_client.get_recipe_by_share_id(resolved_id)
                name = recipe.get("name", "(shared)")
                _LOGGER.info(
                    "%s: resolved shared recipe '%s' (id=%s)",
                    log_label, name, recipe.get("id"),
                )
                return recipe, name
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("%s: share lookup failed: %s", log_label, err)
                return None, ""

        if recipe_name is None:
            select_state = hass.states.get("select.xbloom_studio_recipe")
            if (
                select_state is None
                or select_state.state in ("unknown", "unavailable", "")
            ):
                _LOGGER.error(
                    "%s: no recipe selected and no "
                    "share_url/share_id/recipe_name provided",
                    log_label,
                )
                return None, ""
            recipe_name = select_state.state

        recipes: list[dict] = entry.runtime_data.coordinator.data or []
        recipe = next((r for r in recipes if r.get("name") == recipe_name), None)
        if recipe is None:
            _LOGGER.error(
                "%s: recipe '%s' not in local library — add it via the "
                "integration's Configure menu, or pass share_url",
                log_label, recipe_name,
            )
            return None, recipe_name
        return recipe, recipe_name

    # ------------------------------------------------------------------ #
    # Service: xbloom.start_brew                                         #
    # ------------------------------------------------------------------ #
    # Only one BLE brew session at a time. The session lives in a
    # background task so the service call returns immediately — voice-agent
    # callers (Sage) time out after ~10 s and retry, which used to start
    # overlapping brew sessions (observed June 2026: 6 calls for 3 brews).
    #
    # The guard is time-boxed, not permanent. A repeat within
    # BREW_DUP_WINDOW_S is a retry and is swallowed; a genuine later press
    # preempts the previous session (cancelling its task, which releases the
    # held BLE link) and starts fresh. Without this, a brew that never reaches
    # RD_ENJOY — low water, a machine fault, or a brew stopped from the app —
    # left the task blocked in wait_for_completion for the full 10-minute
    # timeout, holding both the guard and BLE so no restart was possible until
    # the integration reloaded.
    brew_session: dict = {"task": None, "started_at": 0.0}

    async def _cancel_active_brew(reason: str) -> None:
        """Cancel the in-flight brew task (if any) and wait for it to unwind.

        Cancelling propagates through ``_run_brew``'s ``async with
        ble_client`` block, so the held BLE connection is released and the
        machine/app are free again. A no-op when nothing is running.
        """
        active = brew_session["task"]
        if active is None or active.done():
            return
        _LOGGER.info("xbloom: cancelling active brew session (%s)", reason)
        active.cancel()
        try:
            await active
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            _LOGGER.exception("xbloom: active brew task errored during cancel")
        finally:
            brew_session["task"] = None

    async def handle_start_brew(call) -> None:
        """Validate + resolve the recipe, then brew in a background task:
        open BLE → send the brew frames → stream notifications → disconnect
        when RD_ENJOY arrives (or after 10 min as a safety net).

        Recipe source priority:
          1. share_url   — fetch fresh from share-h5 (no auth, no setup)
          2. share_id    — same, with the raw token
          3. recipe_name — lookup in coordinator data (locally stored)
          4. fallback    — current state of `select.xbloom_studio_recipe`
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        from .ble_entities import signal_brew_lifecycle, signal_event
        from .vendor.xbloom.ble import XBloomBleClient

        active = brew_session["task"]
        if active is not None and not active.done():
            elapsed = hass.loop.time() - brew_session["started_at"]
            if elapsed < BREW_DUP_WINDOW_S:
                _LOGGER.warning(
                    "xbloom.start_brew: a brew was dispatched %.1fs ago — "
                    "ignoring duplicate call (within %.0fs retry window)",
                    elapsed, BREW_DUP_WINDOW_S,
                )
                return
            # A genuine later press: the previous session is stale or wedged
            # (e.g. stuck waiting on a brew that will never complete). We
            # preempt it below, once the new brew is confirmed dispatchable.
            _LOGGER.info(
                "xbloom.start_brew: previous session still active after "
                "%.0fs — preempting it", elapsed,
            )

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error(
                "xbloom.start_brew: BLE name unknown — set ble_name or product_id"
            )
            return

        recipe, recipe_name = await _resolve_recipe(
            share_url=call.data.get("share_url"),
            share_id=call.data.get("share_id"),
            recipe_name=call.data.get("recipe_name"),
            log_label="xbloom.start_brew",
        )
        if recipe is None:
            return

        # Per-brew grinder override — does NOT modify the stored recipe.
        # Grinder choice: an explicit use_preground wins; otherwise fall back to
        # the switch.xbloom_studio_use_grinder toggle (OFF = pre-ground / skip).
        if "use_preground" in call.data:
            use_preground = bool(call.data["use_preground"])
        else:
            grinder_switch = hass.states.get("switch.xbloom_studio_use_grinder")
            use_preground = (
                grinder_switch is not None and grinder_switch.state == "off"
            )
        if use_preground:
            recipe = {**recipe, "grinder_size_enabled": 2}
            _LOGGER.info("xbloom.start_brew: grinder skipped (pre-ground override)")

        async def _on_event(decoded: dict) -> None:
            async_dispatcher_send(hass, signal_event(entry.entry_id), decoded)

        total_pours = len(recipe.get("pours", []) or [])

        async def _run_brew() -> None:
            # Fire the brew_started bus event so the event entity captures the
            # recipe name to attach to the eventual brew_done event, and the
            # current-recipe/current-pour sensors can show progress.
            hass.bus.async_fire(
                "xbloom_brew_started",
                {"recipe_name": recipe_name, "total_pours": total_pours},
            )

            async_dispatcher_send(hass, signal_brew_lifecycle(entry.entry_id), "started")

            _LOGGER.info("xbloom.start_brew: looking up %r in HA bluetooth …", ble_name)
            ble_device = await _resolve_ble_device(hass, ble_name)
            if ble_device is None:
                _LOGGER.error(
                    "xbloom.start_brew: HA bluetooth has not seen %r — "
                    "make sure the machine is on and within range",
                    ble_name,
                )
                async_dispatcher_send(hass, signal_brew_lifecycle(entry.entry_id), "ended")
                return
            _LOGGER.info("xbloom.start_brew: ✓ found device %s", ble_device.address)

            try:
                _LOGGER.info("xbloom.start_brew: opening BLE connection …")
                ble_client = XBloomBleClient(ble_device, on_event=_on_event)
                async with ble_client:
                    _LOGGER.info("xbloom.start_brew: ✓ connected, sending brew frames …")
                    await ble_client.brew(recipe)
                    _LOGGER.info(
                        "xbloom.start_brew: ✓ frames sent, waiting for RD_ENJOY (≤10min) …"
                    )
                    completed = await ble_client.wait_for_completion(timeout=600.0)
                _LOGGER.info(
                    "xbloom.start_brew: '%s' over BLE '%s' (%s)",
                    recipe_name, ble_name,
                    "completed" if completed else "timeout — disconnected anyway",
                )
                hass.bus.async_fire(
                    "xbloom_brew_done_ble" if completed else "xbloom_brew_timeout",
                    {"recipe_name": recipe_name},
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "xbloom.start_brew: BLE dispatch failed for '%s': %s",
                    recipe_name, err,
                )
            finally:
                async_dispatcher_send(hass, signal_brew_lifecycle(entry.entry_id), "ended")

        # Preempt any still-running (stale/wedged) session now that we're
        # committed to dispatching a new brew. No-op on the normal path.
        await _cancel_active_brew("preempted by a new start_brew")

        brew_session["task"] = entry.async_create_background_task(
            hass, _run_brew(), name=f"xbloom_brew_{recipe_name}"
        )
        brew_session["started_at"] = hass.loop.time()
        _LOGGER.info(
            "xbloom.start_brew: brew '%s' dispatched to background — "
            "service call returning", recipe_name,
        )

    # ------------------------------------------------------------------ #
    # Service: xbloom.stop_brew                                          #
    # ------------------------------------------------------------------ #
    async def handle_stop_brew(call) -> None:
        """Cancel an in-progress brew.

        First stop HA's own brew task (which releases the BLE link it was
        holding and clears the duplicate-guard), then send APP_BREWER_STOP
        (4507) so the machine halts too. Cancelling the task first is what
        makes Cancel Brew a reliable reset: it frees the connection a stuck
        brew was holding, so the stop frame — and the next start_brew — can
        get their own connection.
        """
        from .vendor.xbloom.ble import FFE1_UUID, XBloomBleClient, _build_frame

        await _cancel_active_brew("stop_brew requested")

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.stop_brew: BLE name unknown")
            return

        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error("xbloom.stop_brew: HA bluetooth has not seen %r", ble_name)
            return

        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                stop_frame = _build_frame(4507)  # APP_BREWER_STOP, no data
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, stop_frame, response=False,
                )
            _LOGGER.info("xbloom.stop_brew: stop command sent via BLE '%s'", ble_name)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.stop_brew: BLE dispatch failed: %s", err)

    # ------------------------------------------------------------------ #
    # Debug services: xbloom.ble_connect / xbloom.ble_disconnect         #
    # Probe the BLE link without touching the brew flow — useful when    #
    # diagnosing connection failures.                                     #
    # ------------------------------------------------------------------ #
    async def handle_ble_connect(call) -> None:
        """Open BLE → handshake → start_notify → release → disconnect.
        Logs every step with success/failure detail."""
        from .vendor.xbloom.ble import (
            CMD_HANDSHAKE,
            FFE1_UUID,
            FFE2_UUID,
            HANDSHAKE_DATA,
            XBloomBleClient,
            _build_frame,
        )

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.ble_connect: BLE name unknown")
            return

        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error("xbloom.ble_connect: HA bluetooth has not seen %r", ble_name)
            return

        _LOGGER.info("xbloom.ble_connect: opening connection to %s …", ble_name)
        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                _LOGGER.info("xbloom.ble_connect: ✓ connected")
                handshake = _build_frame(CMD_HANDSHAKE, list(HANDSHAKE_DATA))
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, handshake, response=False,
                )
                _LOGGER.info("xbloom.ble_connect: ✓ handshake written")
                try:
                    await ble_client._client.start_notify(  # noqa: SLF001
                        FFE2_UUID, lambda *_: None
                    )
                    _LOGGER.info("xbloom.ble_connect: ✓ FFE2 notify subscribed")
                    await ble_client._client.stop_notify(FFE2_UUID)  # noqa: SLF001
                    _LOGGER.info("xbloom.ble_connect: ✓ FFE2 notify released")
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "xbloom.ble_connect: ✗ FFE2 notify failed: %s "
                        "(brew flow tolerates this — it just skips live status)",
                        err,
                    )
            _LOGGER.info("xbloom.ble_connect: ✓ disconnected cleanly")
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.ble_connect: connection failed: %s", err)

    # ------------------------------------------------------------------ #
    # Simple-command services (08-01)                                    #
    # tare / back_to_home / brew_pause / brew_resume — every one is a    #
    # single-frame BLE write with no parameters. Factor through one      #
    # helper so the connect-on-demand boilerplate isn't repeated.        #
    # ------------------------------------------------------------------ #
    async def _send_simple_command(*, label: str, packet: bytes) -> None:
        """Resolve BLE → connect → write one frame to FFE1 → disconnect."""
        from .vendor.xbloom.ble import FFE1_UUID, XBloomBleClient

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.%s: BLE name unknown", label)
            return

        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.%s: HA bluetooth has not seen %r", label, ble_name,
            )
            return

        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, packet, response=False,
                )
            _LOGGER.info("xbloom.%s: ✓ command sent over BLE %r", label, ble_name)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.%s: BLE dispatch failed: %s", label, err)

    async def handle_tare(call) -> None:
        from .vendor.xbloom.ble import packet_tare
        await _send_simple_command(label="tare", packet=packet_tare())

    async def handle_back_to_home(call) -> None:
        from .vendor.xbloom.ble import packet_back_to_home
        await _send_simple_command(
            label="back_to_home", packet=packet_back_to_home(),
        )

    async def handle_brew_pause(call) -> None:
        from .vendor.xbloom.ble import packet_brew_pause
        await _send_simple_command(
            label="brew_pause", packet=packet_brew_pause(),
        )

    async def handle_brew_resume(call) -> None:
        from .vendor.xbloom.ble import packet_brew_resume
        await _send_simple_command(
            label="brew_resume", packet=packet_brew_resume(),
        )

    # ------------------------------------------------------------------ #
    # 08-02 — Standalone grinder + mode/source/unit set-* services       #
    # ------------------------------------------------------------------ #
    async def handle_grind(call) -> None:
        """xbloom.grind {size, speed, seconds} — 3-frame standalone grind.

        Holds BLE for the full grind duration (enter → start → sleep(seconds)
        → stop → disconnect). Caller sets `seconds`; the on-the-wire
        duration_ms is a fallback if the stop frame is lost.
        """
        import asyncio as _asyncio

        from .vendor.xbloom.ble import (
            FFE1_UUID, XBloomBleClient, packets_grind,
        )

        size = int(call.data.get("size", 63))
        speed = int(call.data.get("speed", 100))
        seconds = float(call.data.get("seconds", 5))

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.grind: BLE name unknown")
            return
        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.grind: HA bluetooth has not seen %r", ble_name,
            )
            return

        enter, start, stop = packets_grind(size, speed)
        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, enter, response=False,
                )
                await _asyncio.sleep(0.5)
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, start, response=False,
                )
                _LOGGER.info(
                    "xbloom.grind: grinding for %.1fs (size=%d, speed=%d)",
                    seconds, size, speed,
                )
                await _asyncio.sleep(seconds)
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, stop, response=False,
                )
                # Per brAzzi64: small post-stop hold so the machine settles.
                await _asyncio.sleep(1.5)
            _LOGGER.info("xbloom.grind: ✓ done")
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.grind: BLE dispatch failed: %s", err)

    async def handle_brew_standalone(call) -> None:
        """xbloom.brew_standalone — brew using standalone brewer mode (CMD 4506).

        Reads flow rate, volume, temperature, and pattern from their respective
        number/select entities. Reads water source from XBloomWaterSourceSelect.
        """
        from .vendor.xbloom.ble import (
            FFE1_UUID, XBloomBleClient, build_brewer_standalone_frame,
        )

        def _state_float(entity_id: str, default: float) -> float:
            s = hass.states.get(entity_id)
            if s is None or s.state in ("unknown", "unavailable"):
                return default
            try:
                return float(s.state)
            except ValueError:
                return default

        def _state_str(entity_id: str, default: str) -> str:
            s = hass.states.get(entity_id)
            if s is None or s.state in ("unknown", "unavailable"):
                return default
            return s.state

        flow_rate = _state_float("number.brew_flow_rate", 3.0)
        volume_ml = _state_float("number.brew_volume", 120.0)
        temp_c    = _state_float("number.brew_temperature", 93.0)

        pattern_name = _state_str("select.brew_pattern", "spiral")
        pattern_map = {"centered": 0, "circular": 1, "spiral": 2}
        pattern_code = pattern_map.get(pattern_name, 2)  # default → spiral

        water_source = _state_str("select.water_source", "tank")
        water_feed = 1 if water_source == "tap" else 0

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.brew_standalone: BLE name unknown")
            return
        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.brew_standalone: HA bluetooth has not seen %r", ble_name,
            )
            return

        frame = build_brewer_standalone_frame(flow_rate, volume_ml, temp_c, water_feed, pattern_code)
        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, frame, response=False,
                )
            _LOGGER.info(
                "xbloom.brew_standalone: ✓ sent (flow=%.1f, vol=%.0fml, temp=%.0f°C, "
                "pattern=%s, water=%s)",
                flow_rate, volume_ml, temp_c, pattern_name, water_source,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.brew_standalone: BLE dispatch failed: %s", err)

    async def handle_set_mode(call) -> None:
        from .vendor.xbloom.ble import packet_mode
        mode = call.data["mode"]
        await _send_simple_command(
            label=f"set_mode[{mode}]", packet=packet_mode(mode),
        )

    async def handle_set_water_source(call) -> None:
        from .vendor.xbloom.ble import packet_water_source
        source = call.data["source"]
        await _send_simple_command(
            label=f"set_water_source[{source}]",
            packet=packet_water_source(source),
        )

    async def handle_set_temp_unit(call) -> None:
        from .vendor.xbloom.ble import packet_temp_unit
        unit = call.data["unit"]
        await _send_simple_command(
            label=f"set_temp_unit[{unit}]", packet=packet_temp_unit(unit),
        )

    async def handle_set_weight_unit(call) -> None:
        from .vendor.xbloom.ble import packet_weight_unit
        unit = call.data["unit"]
        await _send_simple_command(
            label=f"set_weight_unit[{unit}]", packet=packet_weight_unit(unit),
        )

    # ------------------------------------------------------------------ #
    # 08-03 — Easy Mode slot writer                                      #
    # Push any locally-stored recipe (or a freshly-fetched share URL) to #
    # one of the machine's 3 on-device slots A/B/C.                      #
    # ------------------------------------------------------------------ #
    async def handle_write_slot(call) -> None:
        from .vendor.xbloom.ble import (
            FFE1_UUID, SLOT_INDEX, XBloomBleClient, packet_slot_write,
        )

        slot_letter = call.data["slot"].upper()
        slot_index = SLOT_INDEX[slot_letter]
        scale_on = bool(call.data.get("scale_on", True))

        recipe, recipe_name = await _resolve_recipe(
            share_url=call.data.get("share_url"),
            share_id=call.data.get("share_id"),
            recipe_name=call.data.get("recipe_name"),
            log_label=f"xbloom.write_slot[{slot_letter}]",
        )
        if recipe is None:
            return

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.write_slot: BLE name unknown")
            return
        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.write_slot: HA bluetooth has not seen %r", ble_name,
            )
            return

        try:
            packet = packet_slot_write(slot_index, recipe, scale_on=scale_on)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xbloom.write_slot: failed to encode slot packet for '%s': %s",
                recipe_name, err,
            )
            return

        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, packet, response=False,
                )
            _LOGGER.info(
                "xbloom.write_slot: ✓ '%s' written to slot %s on %s "
                "(%d bytes, scale=%s)",
                recipe_name, slot_letter, ble_name, len(packet), scale_on,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xbloom.write_slot: BLE dispatch failed for '%s' → slot %s: %s",
                recipe_name, slot_letter, err,
            )

    async def handle_ble_disconnect(call) -> None:
        """Force-disconnect any HA-held BLE link to the machine (best-effort).

        We don't keep a long-lived client; this is mostly useful if a previous
        brew left a stale handle.
        """
        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.ble_disconnect: BLE name unknown")
            return

        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.warning("xbloom.ble_disconnect: HA bluetooth has not seen %r", ble_name)
            return

        try:
            from bleak import BleakClient
            client = BleakClient(ble_device)
            if client.is_connected:
                await client.disconnect()
                _LOGGER.info("xbloom.ble_disconnect: ✓ disconnected %s", ble_name)
            else:
                _LOGGER.info("xbloom.ble_disconnect: %s was already disconnected", ble_name)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("xbloom.ble_disconnect: %s", err)

    hass.services.async_register(
        DOMAIN,
        "start_brew",
        handle_start_brew,
        schema=vol.Schema({
            vol.Optional("recipe_name"): str,
            vol.Optional("share_url"): str,
            vol.Optional("share_id"): str,
            vol.Optional("use_preground"): bool,
        }),
    )
    hass.services.async_register(DOMAIN, "stop_brew", handle_stop_brew)
    hass.services.async_register(DOMAIN, "ble_connect", handle_ble_connect)
    hass.services.async_register(DOMAIN, "ble_disconnect", handle_ble_disconnect)
    hass.services.async_register(DOMAIN, "tare", handle_tare)
    hass.services.async_register(DOMAIN, "back_to_home", handle_back_to_home)
    hass.services.async_register(DOMAIN, "brew_pause", handle_brew_pause)
    hass.services.async_register(DOMAIN, "brew_resume", handle_brew_resume)

    # 08-02 — standalone grind + mode/source/unit setters
    hass.services.async_register(
        DOMAIN, "grind", handle_grind,
        schema=vol.Schema({
            vol.Optional("size", default=63): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100),
            ),
            vol.Optional("speed", default=100): vol.All(
                vol.Coerce(int), vol.Range(min=60, max=120),
            ),
            vol.Optional("seconds", default=5): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=30),
            ),
        }),
    )
    hass.services.async_register(DOMAIN, "brew_standalone", handle_brew_standalone)
    hass.services.async_register(
        DOMAIN, "set_mode", handle_set_mode,
        schema=vol.Schema({vol.Required("mode"): vol.In(["auto", "pro"])}),
    )
    hass.services.async_register(
        DOMAIN, "set_water_source", handle_set_water_source,
        schema=vol.Schema({vol.Required("source"): vol.In(["tank", "tap"])}),
    )
    hass.services.async_register(
        DOMAIN, "set_temp_unit", handle_set_temp_unit,
        schema=vol.Schema({vol.Required("unit"): vol.In(["C", "F"])}),
    )
    hass.services.async_register(
        DOMAIN, "set_weight_unit", handle_set_weight_unit,
        schema=vol.Schema({vol.Required("unit"): vol.In(["g", "oz", "ml"])}),
    )

    # ------------------------------------------------------------------ #
    # 08-04 debug — xbloom.dump_notifications {seconds}                  #
    # Open BLE, subscribe to FFE2, log every decoded packet for N        #
    # seconds. Used in 08-05 Phase A to identify knob-change cmd codes.  #
    # ------------------------------------------------------------------ #
    async def handle_dump_notifications(call) -> None:
        import asyncio as _asyncio

        from .vendor.xbloom.ble import (
            CMD_HANDSHAKE, FFE1_UUID, FFE2_UUID, HANDSHAKE_DATA,
            XBloomBleClient, _build_frame, decode_notification,
        )

        seconds = float(call.data.get("seconds", 30))
        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.dump_notifications: BLE name unknown")
            return
        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.dump_notifications: HA bluetooth has not seen %r",
                ble_name,
            )
            return

        captured: list[str] = []

        def _on_notify(_char, data: bytes) -> None:
            decoded = decode_notification(bytes(data))
            ts = _asyncio.get_event_loop().time()
            line = (
                f"[t+{ts:9.3f}] raw={bytes(data).hex()}  decoded={decoded}"
            )
            captured.append(line)
            _LOGGER.info("dump_notifications | %s", line)

        try:
            ble_client = XBloomBleClient(ble_device)
            async with ble_client:
                try:
                    await ble_client._client.start_notify(  # noqa: SLF001
                        FFE2_UUID, _on_notify,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "xbloom.dump_notifications: notify subscription "
                        "failed: %s", err,
                    )
                    return

                # Kickstart: handshake first (some firmware paths only
                # emit FFE2 after seeing it).
                handshake = _build_frame(CMD_HANDSHAKE, list(HANDSHAKE_DATA))
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, handshake, response=False,
                )
                _LOGGER.info(
                    "xbloom.dump_notifications: handshake sent (%s)",
                    handshake.hex(),
                )

                # Self-test: 2 seconds in, fire a TARE. The machine MUST
                # emit at least one notification in response (the new
                # zero weight). If we don't see it, our notify
                # subscription is broken; if we do see it, the BLE pipe
                # is fine and any subsequent quiet from knobs means the
                # machine doesn't broadcast UI events.
                from .vendor.xbloom.ble import packet_tare
                _LOGGER.info(
                    "xbloom.dump_notifications: capturing FFE2 for "
                    "%.1fs (TARE self-test in 2s)",
                    seconds,
                )
                await _asyncio.sleep(2)
                _LOGGER.info(
                    "xbloom.dump_notifications: → firing TARE "
                    "self-test now"
                )
                await ble_client._client.write_gatt_char(  # noqa: SLF001
                    FFE1_UUID, packet_tare(), response=False,
                )
                await _asyncio.sleep(seconds - 2)

            _LOGGER.info(
                "xbloom.dump_notifications: ✓ done — %d frames captured",
                len(captured),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.dump_notifications: BLE failed: %s", err)

    # 08-03 — Easy Mode slot writer
    hass.services.async_register(
        DOMAIN, "write_slot", handle_write_slot,
        schema=vol.Schema({
            vol.Required("slot"): vol.In(["A", "B", "C"]),
            vol.Optional("recipe_name"): str,
            vol.Optional("share_url"): str,
            vol.Optional("share_id"): str,
            vol.Optional("scale_on", default=True): bool,
        }),
    )

    # 08-04 — debug notification dump
    hass.services.async_register(
        DOMAIN, "dump_notifications", handle_dump_notifications,
        schema=vol.Schema({
            vol.Optional("seconds", default=30): vol.All(
                vol.Coerce(float), vol.Range(min=5, max=300),
            ),
        }),
    )

    # ── Recipe CRUD services (voice OS / external callers) ────────────────
    # All five return response data so REST callers get results directly.

    async def handle_list_recipes(call) -> dict:
        coordinator = entry.runtime_data.coordinator
        return {"recipes": coordinator.data or []}

    async def handle_get_recipe(call) -> dict:
        name = call.data["name"]
        coordinator = entry.runtime_data.coordinator
        recipe = next(
            (r for r in (coordinator.data or []) if r.get("name") == name), None
        )
        return {"recipe": recipe}

    async def handle_add_recipe(call) -> dict:
        try:
            recipe = json.loads(call.data["recipe_json"])
        except (json.JSONDecodeError, KeyError) as err:
            return {"ok": False, "error": f"Invalid recipe_json: {err}"}
        name = (recipe.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "recipe_json is missing a non-empty 'name'"}
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_add_recipe(recipe)
        _LOGGER.info("xbloom.add_recipe: added '%s'", name)
        return {"ok": True, "name": name}

    async def handle_update_recipe(call) -> dict:
        try:
            recipe = json.loads(call.data["recipe_json"])
        except (json.JSONDecodeError, KeyError) as err:
            return {"ok": False, "error": f"Invalid recipe_json: {err}"}
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_replace_recipe(recipe)
        _LOGGER.info("xbloom.update_recipe: updated '%s'", recipe.get("name"))
        return {"ok": True}

    async def handle_delete_recipe(call) -> dict:
        name = call.data["name"]
        coordinator = entry.runtime_data.coordinator
        removed = await coordinator.async_remove_recipe(name)
        if removed:
            _LOGGER.info("xbloom.delete_recipe: deleted '%s'", name)
        else:
            _LOGGER.warning("xbloom.delete_recipe: '%s' not found", name)
        return {"ok": removed, "name": name}

    hass.services.async_register(
        DOMAIN, "list_recipes", handle_list_recipes,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_recipe", handle_get_recipe,
        schema=vol.Schema({vol.Required("name"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "add_recipe", handle_add_recipe,
        schema=vol.Schema({vol.Required("recipe_json"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "update_recipe", handle_update_recipe,
        schema=vol.Schema({vol.Required("recipe_json"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "delete_recipe", handle_delete_recipe,
        schema=vol.Schema({vol.Required("name"): str}),
        supports_response=SupportsResponse.ONLY,
    )

    for svc in (
        "start_brew", "stop_brew", "ble_connect", "ble_disconnect",
        "tare", "back_to_home", "brew_pause", "brew_resume",
        "grind", "set_mode", "set_water_source",
        "set_temp_unit", "set_weight_unit",
        "write_slot", "dump_notifications",
        "list_recipes", "get_recipe", "add_recipe", "update_recipe", "delete_recipe",
    ):
        entry.async_on_unload(
            lambda s=svc: hass.services.async_remove(DOMAIN, s)
        )

    _LOGGER.debug("xbloom: loading platforms %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XBloomConfigEntry) -> bool:
    """Unload a config entry — make sure mode listeners are stopped first."""
    runtime = entry.runtime_data
    for attr in (
        "voice_listener",
        "scale_listener", "grinder_listener", "brewer_listener",
    ):
        listener = getattr(runtime, attr, None)
        if listener is not None:
            try:
                await listener.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to stop %s during unload", attr)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older config entries to the current schema.

    v1 (cloud era):  access_token, refresh_token, device_id, product_id,
                     ble_name, mqtt_host, mqtt_port
    v2 (transition): same minus tokens/device_id, plus optional status_source
    v3 (BLE-only):   product_id + ble_name (mqtt_* / status_source dropped)
    """
    if entry.version >= 3:
        return True

    drop = {
        "access_token", "refresh_token", "device_id",
        "mqtt_host", "mqtt_port", "status_source",
    }
    new_data = {k: v for k, v in entry.data.items() if k not in drop}
    _LOGGER.info(
        "Migrating xBloom config entry %s from v%s to v3 (BLE-only); kept keys: %s",
        entry.entry_id, entry.version, sorted(new_data.keys()),
    )
    hass.config_entries.async_update_entry(entry, data=new_data, version=3)
    return True
