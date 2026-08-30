"""xBloom Studio integration for Home Assistant — BLE-only.

Architecture:

  * Recipe data comes from the public xBloom share endpoint
    (`RecipeDetail.html`) — no authentication.
  * Recipes the user wants in HA are stored in HA's local storage and added
    via the integration's options flow.
  * Brewing is BLE-only: connect-on-demand via HA's bluetooth integration.
    The recipe blob is built locally by `xbloom.ble.encode_recipe_blob`
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
from xbloom.client import XBloomClient
from xbloom.cloud import XBloomCloudClient, language_type_for
from xbloom import recipe_build, spec
from xbloom.recipe_validate import normalize_recipe, validate_recipe

_LOGGER = logging.getLogger(__name__)


def _describe_errors(errors: dict[str, str]) -> str:
    """Flatten validate_recipe's field->key map into one human-readable line.

    Callers that can render per-field errors should read the `errors` key of
    the service response instead; this is the fallback for logs and for voice
    or REST callers that only surface a single message.
    """
    return "; ".join(f"{field}: {key}" for field, key in sorted(errors.items()))


PLATFORMS = ["select", "button", "number", "sensor", "event", "switch", "update", "text"]

# A start_brew call within this many seconds of the previous dispatch is
# treated as a duplicate (e.g. a voice-agent HTTP retry) and ignored. A call
# after the window preempts the earlier session instead — see handle_start_brew.
BREW_DUP_WINDOW_S = 20.0


@dataclass
class XBloomRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: XBloomCoordinator
    client: XBloomClient
    cloud: XBloomCloudClient
    # Installed firmware version as last reported by the machine over BLE
    # (RD_MachineInfo / ScanDeviceModel.theVersion). None until decoded — the
    # firmware update entity reads it for its `installed_version`. Wiring the
    # BLE decode that fills this is a follow-up; the cloud-side "latest version"
    # check works today regardless.
    installed_fw_version: str | None = None
    # BLE device resolver — set in async_setup_entry. Phase 8 mode
    # listeners (08-04+) re-resolve on every start so adapter routing
    # stays correct after rediscovery.
    ble_device_resolver: object = None
    # Long-lived live-session listener — created by switch.py during platform
    # setup. Kept here so it's stoppable from async_unload_entry.
    live_session_listener: object = None


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
    # Speak the user's HA language to the cloud so server-returned messages
    # match their locale (Arabic HA → Arabic API messages, etc.).
    cloud = XBloomCloudClient(
        session, language_type=language_type_for(hass.config.language)
    )

    coordinator = XBloomCoordinator(hass, entry, cloud)
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
        cloud=cloud,
        ble_device_resolver=_ble_device_for_listener,
    )

    # ------------------------------------------------------------------ #
    # Shared BLE-event dispatcher (piggyback refresh)                     #
    # Every integration BLE connection passes this as on_event, so the    #
    # machine's heartbeat + notifications reach the entities on ANY        #
    # connection (a tare, a grind, a status refresh — not just a brew or  #
    # a Connect session). Any action refreshes the sensors as a side      #
    # effect.                                                             #
    # ------------------------------------------------------------------ #
    from homeassistant.helpers.dispatcher import (
        async_dispatcher_send as _async_dispatcher_send,
    )
    from .ble_entities import signal_event as _signal_event

    async def _dispatch_ble_event(decoded: dict) -> None:
        _async_dispatcher_send(hass, _signal_event(entry.entry_id), decoded)

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
        from xbloom.ble import XBloomBleClient

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

        # Brew-customizer overrides (one-off; never saved). Rescale the resolved
        # recipe's pours to the requested dose × ratio and override the grind.
        _ovr_dose = call.data.get("dose")
        _ovr_ratio = call.data.get("ratio")
        _ovr_grind = call.data.get("grind_size")
        if _ovr_dose is not None or _ovr_ratio is not None or _ovr_grind is not None:
            from xbloom.brew_scale import scale_recipe
            recipe = scale_recipe(
                recipe,
                dose_g=(float(_ovr_dose) if _ovr_dose is not None
                        else float(recipe.get("dose_g") or 0)),
                ratio=(float(_ovr_ratio) if _ovr_ratio is not None
                       else float(recipe.get("water_ratio") or 16)),
                grind_size=(int(_ovr_grind) if _ovr_grind is not None else None),
            )
            _LOGGER.info(
                "xbloom.start_brew: customizer overrides dose=%s ratio=%s grind=%s",
                _ovr_dose, _ovr_ratio, _ovr_grind,
            )

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
        holding and clears the duplicate-guard), then send the full-process
        brew stop (CMD_BREW_STOP 40519) so the machine halts the recipe too.
        (40519 is the recipe/auto stop from AppJ15AutoManager; the standalone
        brewer's APP_BREWER_STOP 4507 is a different command for manual pours.)
        Cancelling the task first is what makes Cancel Brew a reliable reset: it
        frees the connection a stuck brew was holding, so the stop frame — and
        the next start_brew — can get their own connection.
        """
        from xbloom.ble import (
            CMD_BREW_STOP, FFE1_UUID, XBloomBleClient, _build_frame,
        )

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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                stop_frame = _build_frame(CMD_BREW_STOP)  # 40519 full-process stop
                await ble_client.send_command("stop_brew", stop_frame)
            _LOGGER.info("xbloom.stop_brew: stop command sent via BLE '%s'", ble_name)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.stop_brew: BLE dispatch failed: %s", err)

    # ------------------------------------------------------------------ #
    # Debug services: xbloom.ble_connect / xbloom.ble_disconnect         #
    # Probe the BLE link without touching the brew flow — useful when    #
    # diagnosing connection failures.                                     #
    # ------------------------------------------------------------------ #
    async def handle_ble_connect(call) -> None:
        """Open BLE → handshake (echo-gated) → disconnect. Logs every step.

        Doubles as the safe, no-coffee validation of the send-and-confirm
        (ACK-gating) layer: it drives the real send path for the harmless
        handshake (8100, no grind/brew/motion) and reports whether the
        machine's FFE2 echo arrived — confirming the echo stream works over
        this host's actual BLE stack without touching the brew flow.
        """
        from xbloom.ble import (
            CMD_HANDSHAKE,
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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                _LOGGER.info("xbloom.ble_connect: ✓ connected")
                handshake = _build_frame(CMD_HANDSHAKE, list(HANDSHAKE_DATA))
                # send_command subscribes to FFE2 (best-effort) and waits for
                # the 8100 echo — the ACK layer exercised end-to-end, safely.
                confirmed = await ble_client.send_command("handshake", handshake)
                if confirmed:
                    _LOGGER.info(
                        "xbloom.ble_connect: ✓ handshake echo CONFIRMED on FFE2 "
                        "— send-and-confirm layer works on this BLE stack"
                    )
                elif ble_client._notify_active:  # noqa: SLF001
                    _LOGGER.warning(
                        "xbloom.ble_connect: ✗ FFE2 subscribed but NO handshake "
                        "echo arrived — echo stream is not delivering (brew will "
                        "degrade to fixed-delay pacing)"
                    )
                else:
                    _LOGGER.warning(
                        "xbloom.ble_connect: ✗ FFE2 start_notify failed — no echo "
                        "stream available (brew tolerates this via fixed delays)"
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
        """Send a single FFE1 command frame to the machine.

        If a Connect (live) session is holding the BLE link, send the frame over
        THAT session and stop — the machine accepts only one connection, so
        opening our own would fight the live session and tear it down. (That is
        exactly what made the dashboard Back-to-home drop Connect mid-navigation:
        the standalone service opened a second link and, on disconnect, killed
        the session, silencing every announcement after it.) When no session is
        held, fall back to the one-shot connect → echo-gated write → disconnect.
        """
        from .ble_entities import send_live_frame
        from xbloom.ble import XBloomBleClient

        if await send_live_frame(entry, packet):
            _LOGGER.info("xbloom.%s: ✓ sent over the held Connect session", label)
            return

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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                confirmed = await ble_client.send_command(label, packet)
            _LOGGER.info(
                "xbloom.%s: ✓ command sent over BLE %r (echo %s)",
                label, ble_name, "confirmed" if confirmed else "unconfirmed",
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.%s: BLE dispatch failed: %s", label, err)

    async def handle_tare(call) -> None:
        from xbloom.ble import packet_tare
        await _send_simple_command(label="tare", packet=packet_tare())

    async def handle_back_to_home(call) -> None:
        # 8022 is state-gated: the firmware REJECTS it from a live module screen
        # (grinder/brewer/scale) — it only exits from home/standby — yet still
        # echoes 8022, which previously read as a FALSE "home" while the machine
        # stayed on the module. The app leaves a module with its QUIT command
        # (grinder 8012 / brewer 8013 / scale 8014), which the fw routes home
        # (fw:1769-1783) and then emits 8023 activity=1. Pick the quit that
        # matches where we are; fall back to 8022 only from home/unknown.
        from xbloom.ble import (
            packet_back_to_home, packet_quit_brewer,
            packet_quit_grinder, packet_quit_scale,
        )
        st = hass.states.get("sensor.xbloom_studio_current_module")
        module = st.state if st and st.state not in ("unknown", "unavailable") else None
        builder = {
            "grinder": packet_quit_grinder,
            "brewer": packet_quit_brewer,
            "scale": packet_quit_scale,
        }.get(module, packet_back_to_home)
        await _send_simple_command(
            label=f"back_to_home({module or 'home'})", packet=builder(),
        )

    async def handle_brew_pause(call) -> None:
        from xbloom.ble import packet_brew_pause
        await _send_simple_command(
            label="brew_pause", packet=packet_brew_pause(),
        )

    async def handle_brew_resume(call) -> None:
        from xbloom.ble import packet_brew_resume
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

        from xbloom.ble import (
            XBloomBleClient, packets_grind,
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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                # enter → start are echo-gated (send_command); the grind
                # DURATION between start and stop is caller-controlled, and the
                # post-stop settle mirrors brAzzi64. send_command uses the
                # app-exact policy (retry only while sleeping) — safe for a
                # motion command like grind_start: it never re-sends while the
                # machine is awake, so it can't double-start a grind.
                await ble_client.send_command("grind_enter", enter)
                await ble_client.send_command("grind_start", start)
                _LOGGER.info(
                    "xbloom.grind: grinding for %.1fs (size=%d, speed=%d)",
                    seconds, size, speed,
                )
                await _asyncio.sleep(seconds)
                await ble_client.send_command("grind_stop", stop)
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
        from xbloom.ble import (
            XBloomBleClient, build_brewer_standalone_frame,
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

        pattern_name = _state_str("select.brew_pattern", spec.DEFAULT_PATTERN)
        pattern_code = spec.PATTERN_NAME_TO_BYTE.get(
            pattern_name, spec.PATTERN_NAME_TO_BYTE["spiral"]
        )

        water_source = _state_str("select.water_source", spec.DEFAULT_WATER_SOURCE)
        water_feed = spec.WATER_SOURCE_CODES.get(
            water_source, spec.WATER_SOURCE_CODES["tank"]
        )

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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                # brew_standalone (4506) is a motion command; the app-exact
                # send_command policy (retry only while sleeping) never re-sends
                # it while the machine is awake, so it can't restart a pour.
                await ble_client.send_command("brew_standalone", frame)
            _LOGGER.info(
                "xbloom.brew_standalone: ✓ sent (flow=%.1f, vol=%.0fml, temp=%.0f°C, "
                "pattern=%s, water=%s)",
                flow_rate, volume_ml, temp_c, pattern_name, water_source,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.brew_standalone: BLE dispatch failed: %s", err)

    async def handle_set_mode(call) -> None:
        from xbloom.ble import packet_mode
        mode = call.data["mode"]
        await _send_simple_command(
            label=f"set_mode[{mode}]", packet=packet_mode(mode),
        )

    async def handle_set_water_source(call) -> None:
        from xbloom.ble import packet_water_source
        source = call.data["source"]
        await _send_simple_command(
            label=f"set_water_source[{source}]",
            packet=packet_water_source(source),
        )

    async def handle_set_temp_unit(call) -> None:
        from xbloom.ble import packet_temp_unit
        unit = call.data["unit"]
        await _send_simple_command(
            label=f"set_temp_unit[{unit}]", packet=packet_temp_unit(unit),
        )

    async def handle_set_weight_unit(call) -> None:
        from xbloom.ble import packet_weight_unit
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
        from xbloom.ble import (
            SLOT_INDEX, XBloomBleClient, packet_slot_write,
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
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                await ble_client.send_command("write_slot", packet)
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

    async def handle_refresh_status(call) -> None:
        """Briefly open BLE, capture one heartbeat snapshot, then disconnect.

        This is Method 1 (snapshot), decoupled from the Connect session: it
        refreshes the machine's status sensors (water, grind size, mode, water
        source, units, voltage, …) on demand — no persistent session required.
        Awaitable, so an automation can call this and *then* act on fresh data.
        If a brew or a Connect session already holds the link, the readings are
        streaming anyway and this connect will just no-op/fail harmlessly.
        """
        from xbloom.ble import XBloomBleClient

        ble_name = _resolve_ble_name(entry)
        if not ble_name:
            _LOGGER.error("xbloom.refresh_status: BLE name unknown")
            return
        ble_device = await _resolve_ble_device(hass, ble_name)
        if ble_device is None:
            _LOGGER.error(
                "xbloom.refresh_status: HA bluetooth has not seen %r", ble_name,
            )
            return
        try:
            ble_client = XBloomBleClient(ble_device, on_event=_dispatch_ble_event)
            async with ble_client:
                snap = await ble_client.read_status_snapshot(timeout=4.0)
            if snap is not None:
                _LOGGER.info("xbloom.refresh_status: ✓ refreshed from heartbeat")
            else:
                _LOGGER.warning(
                    "xbloom.refresh_status: connected but no heartbeat captured "
                    "(FFE2 notify may be unavailable)"
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.refresh_status: BLE dispatch failed: %s", err)

    hass.services.async_register(
        DOMAIN,
        "start_brew",
        handle_start_brew,
        schema=vol.Schema({
            vol.Optional("recipe_name"): str,
            vol.Optional("share_url"): str,
            vol.Optional("share_id"): str,
            vol.Optional("use_preground"): bool,
            # Brew-customizer one-off overrides (scale pours to dose×ratio).
            vol.Optional("dose"): vol.Coerce(float),
            vol.Optional("ratio"): vol.Coerce(float),
            vol.Optional("grind_size"): vol.Coerce(int),
        }),
    )
    hass.services.async_register(DOMAIN, "stop_brew", handle_stop_brew)
    hass.services.async_register(DOMAIN, "ble_connect", handle_ble_connect)
    hass.services.async_register(DOMAIN, "ble_disconnect", handle_ble_disconnect)
    hass.services.async_register(DOMAIN, "refresh_status", handle_refresh_status)
    hass.services.async_register(DOMAIN, "tare", handle_tare)
    hass.services.async_register(DOMAIN, "back_to_home", handle_back_to_home)
    hass.services.async_register(DOMAIN, "brew_pause", handle_brew_pause)
    hass.services.async_register(DOMAIN, "brew_resume", handle_brew_resume)

    # 08-02 — standalone grind + mode/source/unit setters
    hass.services.async_register(
        DOMAIN, "grind", handle_grind,
        schema=vol.Schema({
            vol.Optional("size", default=63): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=int(spec.field("grind_size").min),
                    max=int(spec.field("grind_size").max),
                ),
            ),
            vol.Optional("speed", default=100): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=int(spec.field("grinder_speed_rpm").min),
                    max=int(spec.field("grinder_speed_rpm").max),
                ),
            ),
            vol.Optional("seconds", default=5): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=30),
            ),
        }),
    )
    hass.services.async_register(DOMAIN, "brew_standalone", handle_brew_standalone)
    hass.services.async_register(
        DOMAIN, "set_mode", handle_set_mode,
        schema=vol.Schema({vol.Required("mode"): vol.In(list(spec.MODES))}),
    )
    hass.services.async_register(
        DOMAIN, "set_water_source", handle_set_water_source,
        schema=vol.Schema({vol.Required("source"): vol.In(list(spec.WATER_SOURCE_CODES))}),
    )
    hass.services.async_register(
        DOMAIN, "set_temp_unit", handle_set_temp_unit,
        schema=vol.Schema({vol.Required("unit"): vol.In(list(spec.TEMP_UNIT_CODES))}),
    )
    hass.services.async_register(
        DOMAIN, "set_weight_unit", handle_set_weight_unit,
        schema=vol.Schema({vol.Required("unit"): vol.In(list(spec.WEIGHT_UNIT_CODES))}),
    )

    # 08-03 — Easy Mode slot writer
    hass.services.async_register(
        DOMAIN, "write_slot", handle_write_slot,
        schema=vol.Schema({
            vol.Required("slot"): vol.In(list(spec.SLOTS)),
            vol.Optional("recipe_name"): str,
            vol.Optional("share_url"): str,
            vol.Optional("share_id"): str,
            vol.Optional("scale_on", default=True): bool,
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

    async def handle_build_recipe(call) -> dict:
        """Snap loose recipe fields onto the machine's grid, then validate.

        The entry point for callers who have a recipe in the shape a person
        described it — a web recipe, something asked for out loud — rather
        than a form-validated draft. Values that are merely off the grid are
        moved onto it and reported in `adjustments`, so the caller can say
        what changed; only faults that cannot be snapped away come back as
        `errors`. With `save`, the result is stored in one round trip:
        replacing the recipe named by `id` when one is given, otherwise
        adding a new one.
        """
        fields = dict(call.data)
        save = bool(fields.pop("save", False))
        apply_defaults = bool(fields.pop("apply_brew_defaults", True))
        # The rest of the service surface calls this field `dose`; the recipe
        # dict and the validator call it `dose_g`.
        if "dose" in fields:
            fields["dose_g"] = fields.pop("dose")
        raw_pours = fields.pop("pours_json", None)
        if raw_pours is not None:
            try:
                pours = json.loads(raw_pours)
            except json.JSONDecodeError as err:
                return {"ok": False, "error": f"Invalid pours_json: {err}"}
            if not isinstance(pours, list):
                return {"ok": False, "error": "pours_json must be a JSON array"}
            fields["pours"] = pours

        result = recipe_build.build(fields, apply_brew_defaults=apply_defaults)
        payload: dict = {
            "ok": result.ok,
            "recipe": result.recipe,
            "adjustments": result.adjustments,
            "errors": result.errors,
        }
        if not result.ok:
            payload["error"] = _describe_errors(result.errors)
            _LOGGER.warning("xbloom.build_recipe: rejected — %s", result.errors)
            return payload
        if result.adjustments:
            _LOGGER.info(
                "xbloom.build_recipe: adapted '%s' — %s",
                result.recipe["name"], "; ".join(result.adjustments),
            )
        if save:
            coordinator = entry.runtime_data.coordinator
            try:
                if call.data.get("id"):
                    await coordinator.async_replace_recipe(result.recipe)
                else:
                    await coordinator.async_add_recipe(result.recipe)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("xbloom.build_recipe: save failed: %s", err)
                return {**payload, "ok": False, "error": str(err)}
            _LOGGER.info("xbloom.build_recipe: saved '%s'", result.recipe["name"])
        payload["saved"] = save
        payload["name"] = result.recipe["name"]
        return payload

    async def handle_add_recipe(call) -> dict:
        try:
            recipe = json.loads(call.data["recipe_json"])
        except (json.JSONDecodeError, KeyError) as err:
            return {"ok": False, "error": f"Invalid recipe_json: {err}"}
        recipe = normalize_recipe(recipe)
        errors = validate_recipe(recipe)
        if errors:
            _LOGGER.warning("xbloom.add_recipe: rejected — %s", errors)
            return {"ok": False, "error": _describe_errors(errors), "errors": errors}
        name = recipe["name"].strip()
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_add_recipe(recipe)
        _LOGGER.info("xbloom.add_recipe: added '%s'", name)
        return {"ok": True, "name": name}

    async def handle_update_recipe(call) -> dict:
        try:
            recipe = json.loads(call.data["recipe_json"])
        except (json.JSONDecodeError, KeyError) as err:
            return {"ok": False, "error": f"Invalid recipe_json: {err}"}
        recipe = normalize_recipe(recipe)
        errors = validate_recipe(recipe)
        if errors:
            _LOGGER.warning("xbloom.update_recipe: rejected — %s", errors)
            return {"ok": False, "error": _describe_errors(errors), "errors": errors}
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_replace_recipe(recipe)
        _LOGGER.info("xbloom.update_recipe: updated '%s'", recipe.get("name"))
        return {"ok": True, "name": recipe["name"].strip()}

    async def handle_save_scaled_recipe(call) -> dict:
        """Brew customizer 'Save as new recipe': scale the selected recipe by the
        customizer's dose/ratio/grind and save it as a NEW recipe (local when
        logged out; cloud + local mirror when logged in). Never overwrites the
        source (the id is stripped)."""
        from xbloom.brew_scale import scale_recipe

        new_name = (call.data.get("new_name") or "").strip()
        if not new_name:
            return {"ok": False, "error": "new_name is required"}
        recipe, _ = await _resolve_recipe(
            recipe_name=call.data.get("recipe_name"),
            log_label="xbloom.save_scaled_recipe",
        )
        if recipe is None:
            return {"ok": False, "error": "recipe not found"}
        scaled = scale_recipe(
            recipe,
            dose_g=float(call.data["dose"]),
            ratio=float(call.data["ratio"]),
            grind_size=int(call.data["grind_size"]),
        )
        scaled["name"] = new_name
        scaled.pop("id", None)          # a NEW recipe, not an overwrite
        coordinator = entry.runtime_data.coordinator
        try:
            await coordinator.async_add_recipe(scaled)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("xbloom.save_scaled_recipe: %s", err)
            return {"ok": False, "error": str(err)}
        _LOGGER.info("xbloom.save_scaled_recipe: saved '%s'", new_name)
        return {"ok": True, "name": new_name}

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
        DOMAIN, "build_recipe", handle_build_recipe,
        # `name` is deliberately Optional here: the builder reports a missing
        # name as a structured `name_required` error the caller can relay,
        # which is more use to a voice agent than a schema exception.
        schema=vol.Schema({
            vol.Optional("name"): str,
            vol.Optional("dose"): vol.Coerce(float),
            vol.Optional("ratio"): vol.Any(str, vol.Coerce(float)),
            vol.Optional("grind_size"): vol.Coerce(int),
            vol.Optional("grinder_speed_rpm"): vol.Coerce(int),
            vol.Optional("cup_type"): vol.Any(str, vol.Coerce(int)),
            vol.Optional("pour_count"): vol.Coerce(int),
            vol.Optional("pours_json"): str,
            vol.Optional("id"): str,
            vol.Optional("save", default=False): bool,
            vol.Optional("apply_brew_defaults", default=True): bool,
        }),
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
    hass.services.async_register(
        DOMAIN, "save_scaled_recipe", handle_save_scaled_recipe,
        schema=vol.Schema({
            vol.Required("new_name"): str,
            vol.Required("dose"): vol.Coerce(float),
            vol.Required("ratio"): vol.Coerce(float),
            vol.Required("grind_size"): vol.Coerce(int),
            vol.Optional("recipe_name"): str,
        }),
        supports_response=SupportsResponse.ONLY,
    )

    for svc in (
        "start_brew", "stop_brew", "ble_connect", "ble_disconnect",
        "refresh_status",
        "tare", "back_to_home", "brew_pause", "brew_resume",
        "brew_standalone",
        "grind", "set_mode", "set_water_source",
        "set_temp_unit", "set_weight_unit",
        "write_slot",
        "build_recipe",
        "list_recipes", "get_recipe", "add_recipe", "update_recipe", "delete_recipe",
        "save_scaled_recipe",
    ):
        entry.async_on_unload(
            lambda s=svc: hass.services.async_remove(DOMAIN, s)
        )

    _LOGGER.debug("xbloom: loading platforms %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XBloomConfigEntry) -> bool:
    """Unload a config entry — make sure the live session is stopped first."""
    runtime = entry.runtime_data
    listener = getattr(runtime, "live_session_listener", None)
    if listener is not None:
        try:
            await listener.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to stop live session during unload")
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
