"""Long-lived BLE listener for the Phase-8 accessibility modes.

Unlike the connect-on-demand pattern used elsewhere in the integration,
this holds a `BleakClient` open for as long as the corresponding mode
switch is ON. Auto-disconnects after `IDLE_TIMEOUT_SEC` of silence on
relevant notifications so the iOS app can reclaim BLE.

Lifecycle events fired on the HA bus (CONTEXT D-36):
    xbloom_<mode>_mode_connecting       — only on slow connect (>1s)
    xbloom_<mode>_mode_ready { summary } — connect succeeded; subclass
                                            populates summary via
                                            `_read_initial_state()`
    xbloom_<mode>_mode_failed  { reason } — reason ∈ {machine_not_found,
                                            machine_busy, connection_lost}
    xbloom_<mode>_mode_auto_stopped { reason } — idle timeout

Subclasses customise behaviour via three hooks:
    notification_filter — decide if a decoded notify is "interesting"
                          (returns event payload dict, or None to ignore)
    on_event            — async callback fired for each kept event
    _read_initial_state — async, returns summary dict for mode_ready
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from .ble import (
    CMD_HANDSHAKE, FFE1_UUID, FFE2_UUID, HANDSHAKE_DATA, _build_frame,
    decode_notification,
)

_LOGGER = logging.getLogger("xbloom.mode_listener")

# Tunables — see CONTEXT D-33 / D-36
IDLE_TIMEOUT_SEC = 600              # auto-stop after 10 min of silence
SLOW_CONNECT_THRESHOLD_SEC = 1.0    # only announce "connecting…" beyond this
INITIAL_STATE_TIMEOUT_SEC = 3.0     # how long to wait for RD_MachineInfo

NotificationFilter = Callable[[dict], "dict | None"]


class XBloomModeListener:
    """Hold a BLE link, route filtered notifications to an async callback.

    Args:
        hass: Home Assistant instance — used for bus / loop / async_create_task.
        ble_device_resolver: async callable returning a BLEDevice (or None).
                             Called fresh on each `start()` so adapter routing
                             stays correct when devices rediscover.
        mode_name: short tag used in event names ("scale", "grinder", "brewer").
        notification_filter: see module docstring.
        on_event: async callback invoked once per kept notification.
    """

    def __init__(
        self,
        hass,
        ble_device_resolver: Callable[[], Awaitable["object | None"]],
        mode_name: str,
        notification_filter: NotificationFilter,
        on_event: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.hass = hass
        self._resolve_device = ble_device_resolver
        self.mode_name = mode_name
        self._filter = notification_filter
        self._on_event = on_event

        self._client = None       # bleak.BleakClient | None
        self._task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()
        self._last_activity: float = 0.0

    # ---- Public API ---------------------------------------------------- #
    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop_evt.clear()
        # Use HA's BACKGROUND task helper (not async_create_task and not
        # raw create_task — both empirically failed to deliver bleak
        # notifications). Background tasks have different lifecycle
        # semantics designed for long-lived monitors.
        if hasattr(self.hass, "async_create_background_task"):
            self._task = self.hass.async_create_background_task(
                self._run(),
                name=f"xbloom_{self.mode_name}_mode_listener",
            )
        else:
            self._task = self.hass.loop.create_task(self._run())

    async def stop(self) -> None:
        self._stop_evt.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        await self._safe_disconnect()
        self._task = None

    # ---- Subclass hooks ------------------------------------------------ #
    async def _read_initial_state(self) -> dict:
        """Override to populate the `summary` field of *_mode_ready.

        Default: empty dict (Scale Mode has no summary — the next stable
        weight will fire `_announced` on its own).
        """
        return {}

    # ---- Internals ----------------------------------------------------- #
    async def _run(self) -> None:
        """All BLE work happens inside a single `async with XBloomBleClient`
        — this matches the dump_notifications pattern that empirically
        receives notifications. Splitting connect and wait into separate
        methods (with manual __aenter__) silently broke notification
        delivery, so we keep them in the same coroutine scope.
        """
        from .ble import XBloomBleClient

        # Resolve device first (no BLE traffic yet).
        device = await self._resolve_device()
        if device is None:
            self.hass.bus.async_fire(
                f"xbloom_{self.mode_name}_failed",
                {"reason": "machine_not_found"},
            )
            _LOGGER.warning("[%s mode] machine not found", self.mode_name)
            return

        # Slow-connect detection: schedule a "connecting…" announcement
        # if connect takes >1s, cancel if it finishes faster.
        slow_handle = self.hass.loop.call_later(
            SLOW_CONNECT_THRESHOLD_SEC,
            lambda: self.hass.bus.async_fire(
                f"xbloom_{self.mode_name}_connecting", {},
            ),
        )

        try:
            ble = XBloomBleClient(device)
            async with ble:
                slow_handle.cancel()
                self._client = ble._client  # noqa: SLF001
                self._ble = ble

                # Local sync callback — proven-working pattern from
                # dump_notifications. Holds reference via closure.
                listener = self
                def _raw_callback(_char, data):  # noqa: ANN001
                    listener._on_notify(_char, data)
                self._raw_callback = _raw_callback

                try:
                    await self._client.start_notify(FFE2_UUID, _raw_callback)
                    _LOGGER.debug(
                        "[%s mode] start_notify FFE2 ok", self.mode_name,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "[%s mode] start_notify failed: %s",
                        self.mode_name, err,
                    )
                    self.hass.bus.async_fire(
                        f"xbloom_{self.mode_name}_failed",
                        {"reason": "connection_lost"},
                    )
                    return

                # Yield to the loop a few times so bleak's notification
                # reader task can fully initialize before we send the
                # handshake. Without this gap the reader misses the
                # first response burst (theory).
                for _ in range(5):
                    await asyncio.sleep(0)
                await asyncio.sleep(0.2)

                # Handshake kickstart.
                try:
                    handshake = _build_frame(
                        CMD_HANDSHAKE, list(HANDSHAKE_DATA),
                    )
                    await self._client.write_gatt_char(
                        FFE1_UUID, handshake, response=False,
                    )
                    _LOGGER.debug(
                        "[%s mode] handshake sent: %s",
                        self.mode_name, handshake.hex(),
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "[%s mode] handshake failed: %s",
                        self.mode_name, err,
                    )

                # Initial-state summary (subclass hook).
                try:
                    summary = await asyncio.wait_for(
                        self._read_initial_state(),
                        timeout=INITIAL_STATE_TIMEOUT_SEC,
                    )
                except Exception:  # noqa: BLE001
                    summary = {}

                self.hass.bus.async_fire(
                    f"xbloom_{self.mode_name}_ready",
                    {"summary": summary},
                )
                _LOGGER.info(
                    "[%s mode] ready (summary=%s)",
                    self.mode_name, summary,
                )
                self._last_activity = time.monotonic()

                # Hold the connection — sleep in a tight loop so
                # notifications keep flowing. Auto-stop after the
                # configured idle window (D-33).
                while not self._stop_evt.is_set():
                    await asyncio.sleep(1.0)
                    idle = time.monotonic() - self._last_activity
                    if idle > IDLE_TIMEOUT_SEC:
                        _LOGGER.info(
                            "[%s mode] idle %ds — auto-stopping listener",
                            self.mode_name, int(idle),
                        )
                        self.hass.bus.async_fire(
                            f"xbloom_{self.mode_name}_auto_stopped",
                            {"reason": "idle_timeout"},
                        )
                        break
        except Exception as err:  # noqa: BLE001
            slow_handle.cancel()
            reason = self._classify_connect_error(err)
            _LOGGER.warning(
                "[%s mode] run failed: %s (%s)",
                self.mode_name, err, reason,
            )
            self.hass.bus.async_fire(
                f"xbloom_{self.mode_name}_failed", {"reason": reason},
            )
        finally:
            self._client = None
            self._ble = None

    # _connect_and_subscribe is GONE — all BLE work happens inline
    # inside _run's `async with XBloomBleClient` block (see above).

    def _on_notify(self, _char, data: bytes) -> None:
        try:
            decoded = decode_notification(bytes(data))
        except Exception:  # noqa: BLE001
            return
        if decoded is None:
            return
        cmd = decoded.get("cmd")
        if cmd not in (20501, 40523):
            _LOGGER.debug(
                "[%s mode] notify cmd=%s decoded=%s",
                self.mode_name, cmd, decoded,
            )
        event = self._filter(decoded)
        if event is None:
            return
        # Don't log heartbeat-driven scale weight events as "knob change"
        # — that floods the log. Only log non-heartbeat events.
        if cmd not in (20501, 40523):
            _LOGGER.info(
                "[%s mode] event cmd=%s → %s",
                self.mode_name, cmd, event,
            )
        self._last_activity = time.monotonic()
        # bleak invokes us from a worker thread, so hand the coroutine to the
        # HA event loop. Dispatch exactly once — a prior duplicate call here
        # fired every event twice.
        try:
            asyncio.run_coroutine_threadsafe(self._on_event(event), self.hass.loop)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("[%s mode] on_event failed", self.mode_name)

    async def _safe_disconnect(self) -> None:
        """No-op — the `async with` in _run handles disconnect for us.
        Kept for backward compatibility with stop()."""
        return

    @staticmethod
    def _classify_connect_error(err: Exception) -> str:
        """Map raw BLE exception text to a simplified user-facing reason."""
        msg = str(err).lower()
        if "not found" in msg or "no devices" in msg or "not discovered" in msg:
            return "machine_not_found"
        if (
            "permitted" in msg or "busy" in msg or "in use" in msg
            or "already" in msg
        ):
            return "machine_busy"
        return "connection_lost"
