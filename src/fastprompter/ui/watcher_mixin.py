"""The watcher runtime: the timer that turns decisions into sends.

Everything that decides is in `core/watcher` and is Qt-free. This mixin only
supplies reality — the clock, the queue, the window layer — and carries the
engine's answers out to the sender.

Two rules shape the whole file:

* **The tick can never raise.** An exception inside a Qt slot takes the
  process down with no traceback, which is the most likely shape of the
  crash T-570 chased. So the tick catches everything and disarms: a watcher
  whose own loop is broken must not stay armed and keep firing.
* **Armed state is never persisted.** It belongs to a live session with a
  live window. Restoring it at startup would point a watcher at a handle
  that now belongs to somebody else's application.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from fastprompter.core.logging import logger
from fastprompter.core.watcher import win32
from fastprompter.core.watcher.adapter import load_adapters
from fastprompter.core.watcher.engine import Engine
from fastprompter.core.watcher.probes import combine
from fastprompter.core.watcher.queue import DETACHED, PENDING, queue_for
from fastprompter.core.watcher.sender import (
    PostMessageSender,
    SendLog,
    SendResult,
    Target,
    build_sender,
)

TICK_MS = 900

# How long the tick's CDP discovery pre-check may wait. The authoritative
# identity recheck (full timeout) happens inside the sender on the worker
# thread, so a slow debugger can cost the GUI a bounded 500 ms, never many
# seconds.
_CDP_PROBE_TIMEOUT = 0.5


class _WatcherSendWorker(QObject):
    """Runs the actual send on its own thread so CDP socket I/O with
    multi-second timeouts can never freeze the Qt event loop.

    `dispatch` is invoked from the GUI thread and runs `_run` in this
    object's thread (queued connection); `done` travels back to the GUI
    thread the same way. `gen` is the run's generation token — the GUI drops
    any result whose token is no longer current.
    """

    dispatch = pyqtSignal(object, object, object, int)   # sender, intent, target, gen
    done = pyqtSignal(object, int, object)                # intent, gen, SendResult

    def __init__(self):
        super().__init__()
        self.dispatch.connect(self._run)

    def _run(self, sender, intent, target, gen):
        try:
            result = sender.send(intent, target)
        except Exception as exc:
            result = SendResult(False, f"send failed in worker: {exc}",
                                getattr(intent, "text", ""))
        self.done.emit(intent, gen, result)


class WatcherMixin:
    """Arm/disarm, the tick loop, the panic key, and the send log."""

    # ---- lazy state ---------------------------------------------------
    def _watcher_init(self):
        if getattr(self, "_watcher_engine", None) is not None:
            return
        self._watcher_engine = Engine()
        self._watcher_log = SendLog()
        self._watcher_sender = build_sender()      # dry until armed live
        self._watcher_target = None
        self._watcher_adapter = None
        self._watcher_timer = None
        self._watcher_listeners = []
        # generation token for in-flight sends: bumped on arm/disarm/panic so
        # a result from an old run can never be reported against a new one
        self._watcher_send_gen = 0
        self._watcher_worker = None
        self._watcher_worker_thread = None
        # observe mode: its own state, so it can never reach the sender
        self._observe_adapter = None
        self._observe_timer = None
        self._observe_trace = []
        self._observe_last = None
        self._observe_bytes = 0
        self._observe_started = 0.0

    def watcher_engine(self):
        self._watcher_init()
        return self._watcher_engine

    def watcher_log(self):
        self._watcher_init()
        return self._watcher_log

    def watcher_adapters(self):
        """The configured agents, reloaded each time the dialog opens.

        Not cached: the user edits adapters.toml precisely when something is
        wrong, and a cache would hide the fix until a restart.
        """
        import os

        from fastprompter.utils.paths import get_data_dir

        try:
            user = os.path.join(get_data_dir(), "adapters.toml")
        except Exception:
            user = None
        # Beside the code, so it ships with the package. It lived under
        # .saipen at first, which is gitignored - a fresh clone had no
        # adapters at all and the dialog listed nothing.
        example = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "watcher", "adapters.example.toml")
        adapters, limits, errors = load_adapters(
            path=user, fallback=example, project=self._watcher_project())
        # The dialog holds them for its own reading; the ARMED engine needs
        # them too (min_gap_ms/max_sends), so keep the parsed set here (T-757).
        self._watcher_limits = limits
        return adapters, limits, errors

    def _watcher_project(self):
        """What `{project}` expands to in a probe path."""
        return self.data.get("watcher_project", "") or ""

    # ---- arming -------------------------------------------------------
    def watcher_arm(self, hwnd, adapter, live=False):
        """Bind to one target and this silo's queue. Returns (ok, reason)."""
        self._watcher_init()
        ok, reason = adapter.supported() if adapter else (False, "no agent chosen")
        if not ok:
            return False, reason

        # Only a window-driven transport needs a window. A cdp adapter is
        # bound to a debuggable PAGE, and demanding a handle for it made
        # arming fail with "that window is gone" against a perfectly healthy
        # agent - the branch below existed, but this check above it did not
        # know about it.
        info = None
        if getattr(adapter, "transport", "post") != "cdp":
            info = win32.window_info(hwnd)
            if info is None:
                return False, "that window is gone"

        self._watcher_adapter = adapter
        self._watcher_target = self._build_target(adapter, hwnd, info)
        if self._watcher_target is None:
            return False, ("that agent is not listening on its debug port - "
                           "launch it with --remote-debugging-port")
        self._watcher_sender = self._build_sender(live)
        self._watcher_engine.settle_ms = adapter.settle_ms
        # a fresh run: any result still in flight from an older run is stale
        self._watcher_send_gen += 1
        # The parsed [limits] must actually reach the engine (T-757): a
        # configured min_gap_ms/max_sends used to be stored and ignored.
        limits = getattr(self, "_watcher_limits", None) or {}
        try:
            self._watcher_engine.min_gap_ms = max(0, int(limits.get("min_gap_ms", 4000)))
        except (TypeError, ValueError):
            pass
        try:
            self._watcher_engine.max_sends = max(1, int(limits.get("max_sends", 25)))
        except (TypeError, ValueError):
            pass
        # The blocker runs only when the transport can read the target's
        # visible text (CDP). Anything else must not pretend to be armed with
        # protection that cannot execute. getattr-guarded: tests inject bare
        # fake adapters that carry none of these.
        if getattr(adapter, "blocker_pattern", ""):
            supported = getattr(adapter, "blocker_supported", lambda: False)()
            self._watcher_blocked_fn = adapter.blocked if supported else None
        else:
            self._watcher_blocked_fn = None
        self._watcher_engine.arm(
            self._watcher_target, self._queue_slot_key(), adapter.probes,
            adapter.skill_format or "", now=time.monotonic())
        self._watcher_start_timer()
        self._watcher_notify()
        return True, ("armed, live" if live else "armed, dry run")

    def _build_target(self, adapter, hwnd, info):
        """What the run is bound to: a debuggable page, or a window handle."""
        if getattr(adapter, "transport", "post") == "cdp":
            from fastprompter.core.watcher.cdp import CdpTarget
            return CdpTarget.from_port(adapter.live_cdp_port(),
                                       adapter.cdp_title)
        return Target(hwnd, info["title"], info["cls"], probe=win32.probe_for())

    def _build_sender(self, live):
        """The transport the adapter asks for. Silent or nothing.

        `build_sender` can still produce the focus-stealing one, but only
        for a caller that sets allow_focus_steal, and nothing in the UI
        does. Interrupting the user is what this feature exists to avoid.
        """
        adapter = self._watcher_adapter
        if not live:
            return build_sender()
        submit = getattr(adapter, "submit", "enter")
        multiline = getattr(adapter, "multiline", "join")

        if getattr(adapter, "transport", "post") == "cdp":
            from fastprompter.core.watcher.cdp import CdpSender
            return CdpSender(submit=submit, multiline=multiline,
                             selector=getattr(adapter, "cdp_selector", ""))
        if not win32.available():
            return build_sender()
        return PostMessageSender(win32.PostLayer(), submit=submit,
                                 multiline=multiline)

    def watcher_disarm(self, reason="disarmed"):
        self._watcher_init()
        self._watcher_send_gen += 1     # in-flight results become stale
        self._watcher_engine.disarm(reason)
        self._watcher_stop_timer()
        # A target exists only while armed. Leaving the old one behind is how
        # "it sent to the wrong window" bugs start: the next thing to consult
        # it would find a handle nobody chose for this run.
        self._watcher_target = None
        self._watcher_sender = build_sender()
        self._watcher_notify()

    def watcher_panic(self):
        """Stop everything, now. Bound to a global key so it works anywhere.

        Deliberately does more than disarm: it also drops whatever was in
        flight, so a report arriving afterwards cannot be counted against a
        run the user has already ended.
        """
        self._watcher_init()
        if not self._watcher_engine.armed:
            return False
        self._watcher_send_gen += 1     # whatever was in flight is now stale
        self._watcher_engine.panic()
        self._watcher_stop_timer()
        self._watcher_notify()
        self._watcher_announce("Watcher stopped",
                               "The queue will not send anything else.")
        return True

    def _watcher_announce(self, title, body):
        """Say it through the tray, the way the productivity timer does.

        The panic key works with the window hidden, so a dialog label alone
        would leave the user with no confirmation that anything happened.
        """
        try:
            from PyQt6 import sip
            if hasattr(self, "tray_icon") and not sip.isdeleted(self.tray_icon):
                self.tray_icon.showMessage(
                    title, body, self.tray_icon.icon(), 4000)
        except Exception:
            logger.debug("watcher notification failed")

    # ---- the loop -----------------------------------------------------
    def _watcher_start_timer(self):
        if self._watcher_timer is None:
            self._watcher_timer = QTimer(self)
            self._watcher_timer.setInterval(TICK_MS)
            self._watcher_timer.timeout.connect(self._watcher_tick)
        self._watcher_timer.start()

    def _watcher_stop_timer(self):
        if self._watcher_timer is not None:
            self._watcher_timer.stop()

    def _watcher_tick(self):
        """One decision. Catches everything, on purpose — see the module docstring."""
        try:
            self._watcher_tick_inner()
        except Exception:
            logger.exception("watcher tick failed")
            try:
                self._watcher_engine.disarm("the watcher hit an error and stopped")
                self._watcher_stop_timer()
                self._watcher_notify()
            except Exception:
                pass

    def _watcher_tick_inner(self):
        engine = self._watcher_engine
        if not engine.armed:
            self._watcher_stop_timer()
            return

        now = time.monotonic()
        queue = queue_for(self.prompt_queues, engine.queue_key)
        self._watcher_refresh_texts(engine.queue_key, queue)

        target_ok = True
        if self._watcher_target is not None:
            # The tick's identity pre-check is a fast bounded read on the GUI
            # thread; the authoritative recheck happens inside the sender on
            # the worker thread. A CDP target gets a short discover timeout so
            # a slow debugger cannot stall the loop for many seconds.
            if getattr(self._watcher_target, "ws_url", None):
                from fastprompter.core.watcher import cdp as _cdp

                def _bounded_discover(port):
                    return _cdp.discover(port, timeout=_CDP_PROBE_TIMEOUT)

                target_ok = self._watcher_target.matches(_bounded_discover)[0]
            else:
                target_ok = self._watcher_target.matches()[0]

        blocked = False
        blocked_fn = getattr(self, "_watcher_blocked_fn", None)
        if blocked_fn is not None and self._watcher_target is not None:
            try:
                text = self._watcher_target.visible_text()
                blocked = bool(blocked_fn(text))
            except Exception:
                blocked = False          # a read failure must not hang the tick

        intent = engine.tick(now, queue, blocked=blocked, target_ok=target_ok)
        if intent is None:
            self._watcher_notify()
            if not engine.armed:
                self._watcher_stop_timer()
            return

        # Hand the send to the worker thread. The engine is already in
        # SENDING state, so no second send can be dispatched before this one
        # reports back; a report that never arrives means the run just waits.
        self._watcher_dispatch_send(intent)

    def _watcher_dispatch_send(self, intent):
        """Send off-thread; the GUI never blocks on CDP socket I/O."""
        self._watcher_send_gen += 1
        gen = self._watcher_send_gen
        worker = self._watcher_ensure_worker()
        worker.dispatch.emit(self._watcher_sender, intent,
                             self._watcher_target, gen)

    def _watcher_ensure_worker(self):
        """The persistent worker thread, created once per window."""
        if self._watcher_worker is None:
            thread = QThread(self)
            thread.setObjectName("fastprompter-watcher-send")
            worker = _WatcherSendWorker()
            worker.moveToThread(thread)
            worker.done.connect(self._watcher_on_send_result)
            thread.start()
            self._watcher_worker = worker
            self._watcher_worker_thread = thread
        return self._watcher_worker

    def _watcher_shutdown(self):
        """Stop the send worker thread at window close.

        A send already running inside a blocking socket read cannot be
        interrupted cleanly, so the wait is bounded; at app exit a stuck
        worker is a leak, not a hazard.
        """
        thread = self._watcher_worker_thread
        self._watcher_worker_thread = None
        self._watcher_worker = None
        if thread is not None:
            try:
                thread.quit()
                thread.wait(5000)
            except Exception:
                pass

    def _watcher_on_send_result(self, intent, gen, result):
        """The worker's answer, applied on the GUI thread.

        A result is applied ONLY when its generation is still current and the
        engine is still waiting on exactly this send. A panic, a disarm, an
        arm of a new run, or a superseding dispatch bumps the token — the
        stale result is dropped rather than reported as if it happened.
        """
        try:
            if gen != self._watcher_send_gen:
                return                    # stale: a newer run owns the watcher
            engine = self._watcher_engine
            if not engine.armed or engine.state != "sending":
                return
            now = time.monotonic()
            queue = queue_for(self.prompt_queues, engine.queue_key)
            item = queue.find(intent.item_id) if queue is not None else None
            self._watcher_log.record(intent, result, self._watcher_target)
            if result.ok:
                engine.report_sent(item, now=now)
                if item is not None:
                    self._watcher_mark_sent(engine.queue_key, item)
            elif getattr(result, "hold", False):
                # not a failure: the item stays pending and nothing is counted
                engine.report_held(result.reason, now=now)
            else:
                engine.report_failed(item, result.reason, now=now)
            self.save_prompt_queues()
            self._watcher_notify()
            if not engine.armed:
                self._watcher_stop_timer()
        except Exception:
            logger.exception("watcher send-result handling failed")
            try:
                self._watcher_engine.disarm("the watcher hit an error and stopped")
                self._watcher_stop_timer()
            except Exception:
                pass

    def _watcher_refresh_texts(self, slot, queue):
        """Re-read each pending or detached item from the line it is anchored
        to.

        An item follows its source line rather than copying it, so the
        wording can change right up to the instant it goes. Reading here is
        what makes the send, and therefore the log, the truth rather than a
        snapshot from whenever Alt+C was pressed.

        DETACHED items are inspected too: when the source line comes back
        (undo of a delete, recreated text), the item revives to PENDING
        without needing the queue dialog (T-756).
        """
        for item in queue.items:
            if item.state not in (PENDING, DETACHED):
                continue
            try:
                text, detached = self.queue_item_live_text(slot, item)
            except Exception:
                continue
            if detached:
                if item.state != DETACHED:
                    item.mark_detached()
            else:
                if text:
                    item.text = text
                if item.state == DETACHED:
                    # the source line is back: revive it
                    item.reset()

    def _watcher_mark_sent(self, slot, item):
        """Tick the line in the gutter, when its silo is the open one."""
        if str(slot) != self._queue_slot_key():
            return
        try:
            self.text_area.mark_queue_sent(item.id)
        except Exception:
            pass

    # ---- observing ----------------------------------------------------
    #
    # A separate loop, deliberately. Observe mode is not "arm with a flag
    # that says do not send" - it never builds a target and never builds a
    # sender, so there is nothing here that COULD send. That is what makes
    # it safe to point at an agent mid-turn to learn its signal (W-09).

    def watcher_observe(self, adapter):
        """Watch an agent's signal without arming anything. (ok, reason)."""
        self._watcher_init()
        if self._watcher_engine.armed:
            # Both loops would poll the SAME probe objects at different
            # rates, each stamping the other's quiet window. One owner of the
            # probes at a time.
            return False, "already armed - disarm first to just watch"
        ok, reason = adapter.supported() if adapter else (False, "no agent chosen")
        if not ok:
            return False, reason

        self._observe_adapter = adapter
        self._observe_trace = []
        self._observe_last = None
        self._observe_started = time.monotonic()
        for probe in adapter.probes:
            probe.reset()
        if self._observe_timer is None:
            self._observe_timer = QTimer(self)
            self._observe_timer.setInterval(500)
            self._observe_timer.timeout.connect(self._observe_tick)
        self._observe_timer.start()
        self._watcher_notify()
        return True, f"watching {adapter.name}"

    def watcher_stop_observing(self):
        self._watcher_init()
        if self._observe_timer is not None:
            self._observe_timer.stop()
        self._observe_adapter = None
        self._watcher_notify()

    @property
    def watcher_observing(self):
        return getattr(self, "_observe_adapter", None) is not None

    def watcher_trace(self):
        self._watcher_init()
        return list(self._observe_trace)

    def _observe_tick(self):
        """Record what the probes say. Catches everything, like the send tick."""
        try:
            self._observe_tick_inner()
        except Exception:
            logger.exception("watcher observation failed")
            try:
                self.watcher_stop_observing()
            except Exception:
                pass

    def _observe_tick_inner(self):
        adapter = getattr(self, "_observe_adapter", None)
        if adapter is None:
            if self._observe_timer is not None:
                self._observe_timer.stop()
            return

        now = time.monotonic()
        idle, reasons = combine(adapter.probes, now)
        size = self._observe_size(adapter)

        # Only transitions are recorded. Polling twice a second, a line per
        # poll would bury the two moments that matter - when it started
        # working and when it stopped - under hundreds of identical rows.
        state = "idle" if idle else "busy"
        if state != self._observe_last:
            delta = size - (self._observe_bytes or size)
            self._observe_trace.append({
                "at": now - self._observe_started,
                "state": state,
                "reason": "; ".join(reasons)[:120],
                "bytes": size,
                "delta": delta,
                # In a real run this is the moment the queue would release a
                # prompt. Saying so without doing it is the whole point.
                "would_send": state == "idle" and self._observe_last == "busy",
            })
            del self._observe_trace[:-200]
            self._observe_last = state
            self._observe_bytes = size
        self._watcher_notify()

    def _observe_size(self, adapter):
        """Total bytes across the probes' stores — the response arriving."""
        total = 0
        for probe in adapter.probes:
            token = getattr(probe, "_last_token", None)
            if isinstance(token, tuple):
                total += sum(p for p in token if isinstance(p, int))
            elif isinstance(token, (list, tuple)):
                for part in token:
                    if isinstance(part, tuple):
                        total += sum(p for p in part if isinstance(p, int))
        return total

    # ---- listeners ----------------------------------------------------
    def watcher_listen(self, fn):
        """The dialog subscribes so it can follow a run it did not start."""
        self._watcher_init()
        if fn not in self._watcher_listeners:
            self._watcher_listeners.append(fn)

    def watcher_unlisten(self, fn):
        self._watcher_init()
        if fn in self._watcher_listeners:
            self._watcher_listeners.remove(fn)

    def _watcher_notify(self):
        for fn in list(self._watcher_listeners):
            try:
                fn()
            except Exception:
                # a dead dialog must not take the run down with it
                logger.exception("watcher listener failed")
                self._watcher_listeners.remove(fn)

    # ---- the dialog ---------------------------------------------------
    def open_watcher_dialog(self):
        from fastprompter.ui.watcher_dialog import WatcherDialog
        self._watcher_init()
        self._increment_focus_lock()
        try:
            WatcherDialog(self).exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
