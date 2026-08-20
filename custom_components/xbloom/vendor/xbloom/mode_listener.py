"""Long-lived BLE listener for the live/streaming session (Method 2).

Unlike the connect-on-demand snapshot path (Method 1 —
``XBloomBleClient.read_status_snapshot``), this holds a ``BleakClient``
open for as long as the caller keeps the listener started. Auto-disconnects
after ``idle_timeout_s`` of silence on relevant notifications so the iOS
app can reclaim BLE.

This module is **pure vendor** — it has no Home Assistant dependency.
All host coupling is injected by the integration layer:

    on_lifecycle(phase, payload) — sync callback for lifecycle transitions.
        phase ∈ {"connecting", "ready", "failed", "auto_stopped"}:
            "connecting"   {}                    — only on slow connect (>1s)
            "ready"        {"summary": {...}}     — connect succeeded; subclass
                                                    populates summary via
                                                    ``_read_initial_state()``
            "failed"       {"reason": <str>}      — reason ∈ {machine_not_found,
                                                    machine_busy, connection_lost}
            "auto_stopped" {"reason": "idle_timeout"} — idle timeout fired
        The integration layer typically bridges these onto the HA event bus
        as ``xbloom_<mode>_<phase>`` events.

    task_factory(coro, name) -> Task — optional. Spawns the long-lived run
        loop. The integration passes HA's ``async_create_background_task``
        (empirically the only spawn that reliably delivers bleak
        notifications); when omitted, falls back to ``loop.create_task``.

Subclasses customise behaviour via three hooks:
    notification_filter — decide if a decoded notify is "interesting"
                          (returns event payload dict, or None to ignore)
    on_event            — async callback fired for each kept event
    _read_initial_state — async, returns summary dict for the "ready" phase
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Coroutine

from .ble import (
    CMD_HANDSHAKE, FFE1_UUID, FFE2_UUID, HANDSHAKE_DATA, _build_frame,
    decode_notification,
)

_LOGGER = logging.getLogger("xbloom.mode_listener")

# Tunables — see CONTEXT D-33 / D-36
IDLE_TIMEOUT_SEC = 300              # vendor default: auto-stop after 5 min silence
                                    # (integration may override — CONF_IDLE_TIMEOUT)
SLOW_CONNECT_THRESHOLD_SEC = 1.0    # only announce "connecting…" beyond this
INITIAL_STATE_TIMEOUT_SEC = 3.0     # how long to wait for RD_MachineInfo

NotificationFilter = Callable[[dict], "dict | None"]
LifecycleCallback = Callable[[str, dict], None]
TaskFactory = Callable[[Coroutine[Any, Any, None], str], "asyncio.Task"]


class XBloomModeListener:
    """Hold a BLE link, route filtered notifications to an async callback.

    Args:
        ble_device_resolver: async callable returning a BLEDevice (or None).
                             Called fresh on each ``start()`` so adapter routing
                             stays correct when devices rediscover.
        mode_name: short tag used in lifecycle phase routing ("connect", …).
        notification_filter: see module docstring.
        on_event: async callback invoked once per kept notification.
        on_lifecycle: sync callback for lifecycle transitions (see module
                      docstring). Called on the event loop thread.
        task_factory: optional spawner for the long-lived run loop; defaults
                      to ``loop.create_task``.
        idle_timeout_s: seconds of notification silence before auto-stopping.
    """

    def __init__(
        self,
        ble_device_resolver: Callable[[], Awaitable["object | None"]],
        mode_name: str,
        notification_filter: NotificationFilter,
        on_event: Callable[[dict], Awaitable[None]],
        on_lifecycle: LifecycleCallback,
        task_factory: TaskFactory | None = None,
        idle_timeout_s: float = IDLE_TIMEOUT_SEC,
        on_raw: Callable[[dict], None] | None = None,
    ) -> None:
        self._resolve_device = ble_device_resolver
        self.mode_name = mode_name
        self._filter = notification_filter
        self._on_event = on_event
        self._on_lifecycle = on_lifecycle
        self._task_factory = task_factory
        self._idle_timeout_s = idle_timeout_s
        # Optional sync hook fired for EVERY decoded notification (before the
        # filter), so the integration can keep its status sensors/settings in
        # sync with the machine's heartbeat during a held session — not just the
        # filtered knob/weight events. Scheduled on the loop (bleak calls us on a
        # worker thread). Injected → the vendor stays HA-free.
        self._on_raw = on_raw

        self._loop: asyncio.AbstractEventLoop | None = None
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
        # Capture the running loop here (start() runs on the host loop). The
        # bleak notification callback fires from a worker thread and needs
        # this reference to hand coroutines back to the loop.
        self._loop = asyncio.get_running_loop()
        coro = self._run()
        name = f"xbloom_{self.mode_name}_mode_listener"
        # The integration injects HA's BACKGROUND task helper (not
        # async_create_task and not raw create_task — both empirically failed
        # to deliver bleak notifications). Background tasks have different
        # lifecycle semantics designed for long-lived monitors. Fall back to
        # a plain loop task when no factory is supplied (pure/testing use).
        if self._task_factory is not None:
            self._task = self._task_factory(coro, name)
        else:
            self._task = self._loop.create_task(coro)

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

    async def send_live(self, frame: bytes) -> bool:
        """Write a command frame over the *held* session, fire-and-forget.

        For live knob-setting (e.g. dragging a grind-size slider) the official
        app writes without ACK-gating — gating would make the control lag — so
        we match that: a single unconfirmed write to FFE1 over the connection
        the session already holds. Returns False if no session is active (the
        caller then treats the value as a plain setpoint).
        """
        client = self._client
        if client is None:
            return False
        try:
            await client.write_gatt_char(FFE1_UUID, frame, response=False)
            return True
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s mode] send_live failed: %s", self.mode_name, err)
            return False

    # ---- Subclass hooks ------------------------------------------------ #
    async def _read_initial_state(self) -> dict:
        """Override to populate the ``summary`` field of the "ready" phase.

        Default: empty dict (Scale Mode has no summary — the next stable
        weight will fire on its own).
        """
        return {}

    # ---- Internals ----------------------------------------------------- #
    async def _run(self) -> None:
        """All BLE work happens inside a single ``async with XBloomBleClient``
        — the pattern that empirically receives notifications. Splitting
        connect and wait into separate methods (with manual __aenter__)
        silently broke notification delivery, so we keep them in the same
        coroutine scope.
        """
        from .ble import XBloomBleClient

        # Resolve device first (no BLE traffic yet).
        device = await self._resolve_device()
        if device is None:
            self._on_lifecycle("failed", {"reason": "machine_not_found"})
            _LOGGER.warning("[%s mode] machine not found", self.mode_name)
            return

        # Slow-connect detection: schedule a "connecting…" announcement
        # if connect takes >1s, cancel if it finishes faster.
        assert self._loop is not None
        slow_handle = self._loop.call_later(
            SLOW_CONNECT_THRESHOLD_SEC,
            lambda: self._on_lifecycle("connecting", {}),
        )

        try:
            ble = XBloomBleClient(device)
            async with ble:
                slow_handle.cancel()
                self._client = ble._client  # noqa: SLF001
                self._ble = ble

                # Local sync callback — proven-working pattern. Holds
                # reference via closure.
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
                    self._on_lifecycle("failed", {"reason": "connection_lost"})
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

                self._on_lifecycle("ready", {"summary": summary})
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
                    if idle > self._idle_timeout_s:
                        _LOGGER.info(
                            "[%s mode] idle %ds — auto-stopping listener",
                            self.mode_name, int(idle),
                        )
                        self._on_lifecycle(
                            "auto_stopped", {"reason": "idle_timeout"},
                        )
                        break
        except Exception as err:  # noqa: BLE001
            slow_handle.cancel()
            reason = self._classify_connect_error(err)
            _LOGGER.warning(
                "[%s mode] run failed: %s (%s)",
                self.mode_name, err, reason,
            )
            self._on_lifecycle("failed", {"reason": reason})
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
        # Forward every raw decode to the host (before the filter) so status
        # sensors / settings stay in sync with the machine during the session.
        # Runs on the loop — bleak invoked us from a worker thread.
        if self._on_raw is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._on_raw, decoded)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("[%s mode] on_raw failed", self.mode_name)
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
        # captured event loop. Dispatch exactly once — a prior duplicate call
        # here fired every event twice.
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._on_event(event), loop)
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
