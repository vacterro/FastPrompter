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

from PyQt6.QtCore import QTimer

from fastprompter.core.logging import logger
from fastprompter.core.watcher import win32
from fastprompter.core.watcher.adapter import load_adapters
from fastprompter.core.watcher.engine import Engine
from fastprompter.core.watcher.probes import combine
from fastprompter.core.watcher.queue import queue_for
from fastprompter.core.watcher.sender import (
    PostMessageSender,
    SendLog,
    Target,
    build_sender,
)

TICK_MS = 900


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
        return load_adapters(path=user, fallback=example,
                             project=self._watcher_project())

    def _watcher_project(self):
        """What `{project}` expands to in a probe path."""
        return self.data.get("watcher_project", "") or ""

    # ---- arming -------------------------------------------------------
    def watcher_arm(self, hwnd, adapter, live=False):
        """Bind to one window and this silo's queue. Returns (ok, reason)."""
        self._watcher_init()
        info = win32.window_info(hwnd)
        if info is None:
            return False, "that window is gone"

        ok, reason = adapter.supported() if adapter else (False, "no agent chosen")
        if not ok:
            return False, reason

        self._watcher_adapter = adapter
        self._watcher_target = self._build_target(adapter, hwnd, info)
        if self._watcher_target is None:
            return False, ("that agent is not listening on its debug port - "
                           "launch it with --remote-debugging-port")
        self._watcher_sender = self._build_sender(live)
        self._watcher_engine.settle_ms = adapter.settle_ms
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
            target_ok = self._watcher_target.matches()[0]

        intent = engine.tick(now, queue, blocked=False, target_ok=target_ok)
        if intent is None:
            self._watcher_notify()
            if not engine.armed:
                self._watcher_stop_timer()
            return

        item = queue.find(intent.item_id)
        result = self._watcher_sender.send(intent, self._watcher_target)
        self._watcher_log.record(intent, result, self._watcher_target)
        if result.ok:
            engine.report_sent(item, now=now)
            if item is not None:
                self._watcher_mark_sent(engine.queue_key, item)
        else:
            engine.report_failed(item, result.reason, now=now)

        self.save_prompt_queues()
        self._watcher_notify()
        if not engine.armed:
            self._watcher_stop_timer()

    def _watcher_refresh_texts(self, slot, queue):
        """Re-read each pending item from the line it is anchored to.

        An item follows its source line rather than copying it, so the
        wording can change right up to the instant it goes. Reading here is
        what makes the send, and therefore the log, the truth rather than a
        snapshot from whenever Alt+C was pressed.
        """
        for item in queue.pending():
            try:
                text, detached = self.queue_item_live_text(slot, item)
            except Exception:
                continue
            if detached:
                item.mark_detached()
            elif text:
                item.text = text

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
