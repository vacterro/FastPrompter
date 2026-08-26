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
from fastprompter.core.watcher.queue import DETACHED, PENDING, SENT, queue_for
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
_WATCHER_SHUTDOWN_TIMEOUT_S = 5.0
# A verified CDP verdict is cached this long; the blocker exists to catch a
# prompt that APPEARS mid-run, so the cached "not blocked" must go stale
# and re-verify every few seconds (the re-check runs on the worker thread).
_VERIFY_INTERVAL_S = 5.0


class _WatcherSendWorker(QObject):
    """Runs the actual send on its own thread so CDP socket I/O with
    multi-second timeouts can never freeze the Qt event loop.

    `dispatch` is invoked from the GUI thread and runs `_run` in this
    object's thread (queued connection); `done` travels back to the GUI
    thread the same way. `gen` is the run's generation token — the GUI drops
    any result whose token is no longer current.
    """

    dispatch = pyqtSignal(object, object, object, int, int)
    #                               sender, intent, target, gen, token
    done = pyqtSignal(object, int, object, int)          # intent, gen, SendResult, token

    def __init__(self):
        super().__init__()

    def _run(self, sender, intent, target, gen, token):
        try:
            result = sender.send(intent, target)
        except Exception as exc:
            result = SendResult(False, f"send failed in worker: {exc}",
                                getattr(intent, "text", ""))
        self.done.emit(intent, gen, result, token)


class _WatcherVerifyWorker(QObject):
    """CDP identity probe + blocker visible-text read, on the worker thread.

    Both are SOCKET I/O. The tick's old in-line pre-check ran a 0.5s
    discovery timeout on the Qt timer thread and read the page's innerText
    over the socket there too — every tick could freeze the window for
    half a second or more. This worker moves both reads off the GUI thread
    entirely (P1-1).

    The result is TYPED, and every status is fail-closed:

    * "ready"        the page is confirmed and the blocker was readable;
                     ``target_ok``/``blocked`` carry the verdicts.
    * "hold_target"  the page is gone or not listening — the engine must
                     disarm exactly like a vanished win32 window.
    * "hold_blocked" the blocker could not be read (socket error, no
                     page text). The run must HOLD — never send, never
                     count a failure.
    """

    verify = pyqtSignal(object, object, int)   # target, blocked_fn, gen
    verified = pyqtSignal(str, int, bool, bool, str)
    #                                    status, gen, target_ok, blocked, reason

    def __init__(self):
        super().__init__()

    def _run(self, target, blocked_fn, gen):
        try:
            from fastprompter.core.watcher import cdp as _cdp
            target_ok, reason = target.matches(
                lambda port: _cdp.discover(port, timeout=_CDP_PROBE_TIMEOUT))
            if not target_ok:
                self.verified.emit("hold_target", gen, False, False, reason)
                return
            if blocked_fn is not None:
                try:
                    text = target.visible_text()
                except Exception as exc:
                    self.verified.emit(
                        "hold_blocked", gen, True, True,
                        f"blocker could not read the page: {exc}")
                    return
                try:
                    blocked = bool(blocked_fn(text))
                except Exception as exc:
                    self.verified.emit(
                        "hold_blocked", gen, True, True,
                        f"blocker check failed: {exc}")
                    return
                self.verified.emit("ready", gen, True, blocked, "")
                return
            self.verified.emit("ready", gen, True, False, "")
        except Exception as exc:
            self.verified.emit(
                "hold_target", gen, False, False,
                f"target verification failed: {exc}")


class _WatcherProbeWorker(QObject):
    """Samples the configured probes OFF the GUI thread (PERF-003).

    FileProbe does glob/stat (tens of milliseconds on large transcript
    directories) and SqliteProbe opens/queries a database with a 0.5s
    timeout. Running that inside the Qt timer callback froze the window
    every ~900 ms even when nothing was being sent. `sample` is emitted
    from the GUI thread and runs `_run` in this object's thread; `sampled`
    carries only the verdict (idle? reasons) and the observe-size payload
    back to the GUI thread, where the engine's state machine still runs.
    """

    sample = pyqtSignal(object, int)          # probes, gen
    sampled = pyqtSignal(int, bool, object, int)   # gen, idle, reasons, size

    def __init__(self):
        super().__init__()

    def _run(self, probes, gen):
        try:
            now = time.monotonic()
            idle, reasons = combine(probes, now)
            size = _probe_bytes(probes)
        except Exception as exc:
            idle, reasons = False, [f"probe sampling failed: {exc}"]
            size = 0
        self.sampled.emit(gen, idle, reasons, size)


def _probe_bytes(probes):
    """Total bytes across the probes' stores — the response arriving."""
    total = 0
    for probe in probes:
        token = getattr(probe, "_last_token", None)
        if isinstance(token, tuple):
            total += sum(p for p in token if isinstance(p, int))
        elif isinstance(token, (list, tuple)):
            for part in token:
                if isinstance(part, tuple):
                    total += sum(p for p in part if isinstance(p, int))
    return total


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
        # a send is logically owned by the current run (generation-gated); the
        # pre-quit quiesce must NOT treat this as the physical barrier.
        self._watcher_send_active = False
        # CORE-006: a send is physically in the air (worker dispatched, socket
        # result not yet returned). This is SEPARATE from logical generation
        # ownership: a disarm/panic may discard a stale result, but it cannot
        # claim the physical I/O has finished until the worker callback
        # actually returns. The quiesce barrier waits on THIS, never on the
        # logical flag.
        #
        # CORE-003: physical ownership is PER-DISPATCH. A single boolean was
        # wrong — a stale dispatch's late completion cleared the only barrier
        # while a NEWER dispatch was still physically in the air. Each
        # dispatch registers a unique token before emission and removes ONLY
        # its own token on completion; the barrier is empty only when every
        # physical dispatch has resolved.
        self._watcher_send_physical_tokens = set()
        self._watcher_send_token_seq = 0
        # W2-003: one authoritative LIVE owner per dispatch. token -> (category,
        # queue map object, data dict reference) captured when the send left;
        # a stale completion reconciles THIS object instead of deserializing a
        # second mutable copy that the next live save would overwrite.
        self._watcher_send_owners = {}
        # CORE-002: the queue an armed run drains is owned by (category, slot),
        # not by the slot key alone. The live UI alias `prompt_queues` is
        # rebound on every project switch, so resolving the queue against it
        # would drain the NEW project's slot while armed on the old one. Pin
        # the category and the queue map at arm; all watcher resolution uses
        # these, never the current UI alias.
        self._watcher_pinned_category = None
        self._watcher_pinned_queues = None
        self._watcher_quiescing = False
        self._watcher_worker = None
        self._watcher_worker_thread = None
        # CDP verification runs on the worker thread (P1-1); the GUI holds
        # the tick while a verification is pending. States: "unverified"
        # (no fresh answer) or "ready" (cached verdicts). hold_* results
        # revert to "unverified" so the next tick re-checks.
        self._watcher_verify_worker = None
        self._watcher_verify_gen = 0
        self._watcher_verify_state = "unverified"
        self._watcher_verify_inflight = False
        self._watcher_verify_target_ok = True
        self._watcher_verify_blocked = False
        self._watcher_verify_at = 0.0
        # observe mode: its own state, so it can never reach the sender
        self._observe_adapter = None
        self._observe_timer = None
        self._observe_trace = []
        self._observe_last = None
        self._observe_bytes = 0
        self._observe_started = 0.0
        # PERF-003: probe sampling runs on its own worker thread. The GUI
        # holds the tick while a sample is in flight and caches exactly one
        # verdict per generation; a stale sample (rearm/disarm/panic) is
        # dropped by the generation token. ``_watcher_sample_verdict`` is
        # (idle, reasons, size) or None.
        self._watcher_probe_worker = None
        self._watcher_probe_thread = None
        self._watcher_probe_gen = 0
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
        self._watcher_sample_size = 0

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
        """Bind to one target and this silo's queue. Returns (ok, reason).

        CORE-005: every candidate arm field is built and VALIDATED in locals
        before a single live field or generation token is touched. A failed
        candidate arm (unsupported blocker, missing window, dead CDP target)
        therefore leaves the existing run, its target/sender/pacing and ALL
        generations exactly as they were — the next dispatch still drives the
        old run, not a half-replaced one.
        """
        self._watcher_init()
        if getattr(self, "_observe_timer", None) is not None and self._observe_timer.isActive():
            return False, "already observing - stop watching first"
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

        # --- VALIDATE the whole candidate in locals first ---
        target = self._build_target(adapter, hwnd, info)
        if target is None:
            return False, ("that agent is not listening on its debug port - "
                           "launch it with --remote-debugging-port")
        sender = self._build_sender(live, adapter)

        # The blocker runs only when the transport can read the target's
        # visible text (CDP). Anything else must not pretend to be armed with
        # protection that cannot execute. getattr-guarded: tests inject bare
        # fake adapters that carry none of these.
        blocked_fn = None
        if getattr(adapter, "blocker_pattern", ""):
            supported = getattr(adapter, "blocker_supported", lambda: False)()
            if not supported:
                # P0-9: refuse to arm. A blocker that CANNOT run must not be
                # silently replaced by nothing — the old code armed with
                # _watcher_blocked_fn=None and the user believed the agent
                # was protected while every send was unprotected.
                return False, (
                    "this agent cannot read its visible text, so the "
                    "blocker cannot run - fix blocker_supported in the "
                    "adapter first")
            blocked_fn = adapter.blocked

        # The parsed [limits] must actually reach the engine (T-757): a
        # configured min_gap_ms/max_sends used to be stored and ignored.
        limits = getattr(self, "_watcher_limits", None) or {}
        try:
            min_gap_ms = max(0, int(limits.get("min_gap_ms", 4000)))
        except (TypeError, ValueError):
            min_gap_ms = 0
        try:
            max_sends = max(1, int(limits.get("max_sends", 25)))
        except (TypeError, ValueError):
            max_sends = 1

        # --- all validations passed: publish atomically ---
        self._watcher_adapter = adapter
        self._watcher_target = target
        self._watcher_sender = sender
        self._watcher_blocked_fn = blocked_fn
        self._watcher_engine.settle_ms = adapter.settle_ms
        self._watcher_engine.min_gap_ms = min_gap_ms
        self._watcher_engine.max_sends = max_sends
        # CORE-002: pin the queue owner BEFORE arming the engine. While this
        # category is the open one, `prompt_queues` IS the working map for
        # `pinned_category`; once the user switches projects that alias is
        # rebound to another map, but these references keep draining the
        # silo that was armed. Resolve nothing against `prompt_queues` from
        # here on in the watcher path.
        pinned_category = self.get_current_category() or ""
        self._watcher_pinned_category = pinned_category
        self._watcher_pinned_queues = self.prompt_queues
        # a fresh run: any result still in flight from an older run is stale
        self._watcher_send_gen += 1
        # ... and so is any verification still in flight from an older run
        self._watcher_verify_gen += 1
        # the prior run's in-flight send (if any) is logically discarded with
        # it; its late callback returns early on the stale gen, so drop active
        # ownership here to avoid quiesce waiting on a result that will never
        # apply (a newer dispatch re-sets this flag)
        self._watcher_send_active = False
        self._watcher_verify_state = "unverified"
        self._watcher_verify_inflight = False
        # PERF-003: probe sampling off the GUI thread — see
        # ``_watcher_dispatch_sample`` / ``_watcher_on_probe_sampled``.
        self._watcher_probe_gen += 1
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
        self._watcher_engine.arm(
            self._watcher_target, self._queue_slot_key(), adapter.probes,
            adapter.skill_format or "", now=time.monotonic(),
            queue_category=pinned_category)
        self._watcher_start_timer()
        self._watcher_notify()
        return True, ("armed, live" if live else "armed, dry run")

    def _build_target(self, adapter, hwnd, info):
        """What the run is bound to: a debuggable page, or a window handle."""
        if getattr(adapter, "transport", "post") == "cdp":
            from fastprompter.core.watcher.cdp import CdpTarget
            return CdpTarget.from_port(adapter.live_cdp_port(),
                                       adapter.cdp_title)
        # W2-002: pass the arm-time PID through so the safety recheck can
        # reject a reused HWND owned by a different process.
        return Target(hwnd, info["title"], info["cls"], probe=win32.probe_for(),
                      pid=info.get("pid"))

    def _build_sender(self, live, adapter):
        """The transport the adapter asks for. Silent or nothing.

        CORE-001: built from the validated CANDIDATE ``adapter`` passed in,
        never from ``self._watcher_adapter`` — that field is only published
        AFTER every validation passes, so during a candidate arm it would
        still hold the previous run's adapter (stale sender state).

        `build_sender` can still produce the focus-stealing one, but only
        for a caller that sets allow_focus_steal, and nothing in the UI
        does. Interrupting the user is what this feature exists to avoid.
        """
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

    def _watcher_release_run_ownership(self):
        """W2-004: end-of-run ownership cleanup, shared by disarm, panic and
        the fail-closed error paths.

        A run's mutable lease is (pinned category, pinned queue map, target,
        sender). Leaving it registered after the run died makes the dead run
        persistence-authoritative: ``_watcher_persist_queues`` would happily
        serialize a stale pin over newer queue state during shutdown or
        quiescence."""
        self._watcher_pinned_category = None
        self._watcher_pinned_queues = None
        self._watcher_target = None
        self._watcher_sender = build_sender()

    def watcher_disarm(self, reason="disarmed"):
        self._watcher_init()
        self._watcher_send_gen += 1     # in-flight results become stale
        self._watcher_verify_gen += 1   # in-flight verifications too
        # PERF-003: any probe sample in flight is stale for the next run
        self._watcher_probe_gen += 1
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
        self._watcher_verify_state = "unverified"
        self._watcher_verify_inflight = False
        # CORE-002/W2-004: an armed run's queue owner is no longer relevant
        # once disarmed; drop the pin so a later unarmed resolution never
        # touches a stale (category, slot) map.
        self._watcher_release_run_ownership()
        # The dispatched send is logically discarded with the run. Its worker
        # callback will arrive with the OLD generation and return early, so it
        # must NOT clear a newer dispatch's active flag — but the flag for THIS
        # (now stale) send must be dropped here, or quiesce would wait on a
        # result that can never be applied. A newer dispatch re-sets it.
        self._watcher_send_active = False
        self._watcher_engine.disarm(reason)
        self._watcher_stop_timer()
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
        self._watcher_verify_gen += 1   # in-flight verifications too
        self._watcher_probe_gen += 1    # PERF-003: in-flight probe sample too
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
        self._watcher_verify_state = "unverified"
        self._watcher_verify_inflight = False
        # See watcher_disarm: drop active-send ownership so a stale callback
        # cannot strand quiesce waiting on it.
        self._watcher_send_active = False
        # W2-004: panic terminates EXECUTION but must also terminate the
        # run's mutable OWNERSHIP lease. A pinned queue left behind here used
        # to stay eligible as a persistence source and could overwrite queue
        # edits made after the panic. A physical send that still needs its
        # owner carries it in the dispatch token (W2-003), never in the pin.
        self._watcher_release_run_ownership()
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
                # W2-004: an error-ended run must not leave a persistence-
                # authoritative pin behind either.
                self._watcher_release_run_ownership()
                self._watcher_stop_timer()
                self._watcher_notify()
            except Exception:
                pass

    def _watcher_armed_queue_map(self):
        """The queue map for the PINNED armed-run category (CORE-002).

        Never the live UI alias `prompt_queues`, which is rebound on every
        project switch. Falls back to the current alias when nothing is
        armed, so callers that run outside an armed run stay correct.
        """
        if self._watcher_pinned_queues is not None:
            return self._watcher_pinned_queues
        return self.prompt_queues

    def _watcher_current_category(self):
        """Defensive current-category getter for mixin-only test stubs that
        do not implement the full main window."""
        getter = getattr(self, "get_current_category", None)
        if getter is None:
            return ""
        return getter() or ""

    def _watcher_write_queues(self, cat, queues):
        """Serialize ``queues`` (a {slot: SiloQueue} map) into
        ``watcher_queues_all[cat]`` (CORE-002).

        The flat `watcher_queues` alias is kept in sync only when ``cat`` is
        still the open project, so writing a non-current owner never disturbs
        the live UI's store.
        """
        data = getattr(self, "data", None)
        if isinstance(data, dict):
            self._watcher_write_queues_into(data, cat, queues)

    def _watcher_write_queues_into(self, data, cat, queues):
        """W2-003: serialize ``queues`` into a SPECIFIC data dict.

        A stale completion must write its reconciled owner back to the
        profile the dispatch came FROM — ``self.data`` may already belong to
        another profile by then. The flat alias is touched only when that
        dict is still the live one and the category is still open."""
        from fastprompter.core.watcher.queue import save_queues

        if not isinstance(data, dict):
            return
        raw = save_queues(queues) if isinstance(queues, dict) else {}
        bucket = data.get("watcher_queues_all")
        if not isinstance(bucket, dict):
            bucket = {}
            data["watcher_queues_all"] = bucket
        bucket[cat] = raw
        if data is getattr(self, "data", None) \
                and cat == self._watcher_current_category():
            data["watcher_queues"] = raw
        if hasattr(self, "mark_dirty"):
            try:
                self.mark_dirty("settings")
            except TypeError:
                self.mark_dirty()

    def _watcher_persist_queues(self):
        """Persist the armed run's queue under its OWN pinned category
        (CORE-002), never under the live UI alias.
        """
        cat = self._watcher_pinned_category or self._watcher_current_category() or ""
        self._watcher_write_queues(cat, self._watcher_armed_queue_map())

    def _watcher_tick_inner(self):
        engine = self._watcher_engine
        if not engine.armed:
            self._watcher_stop_timer()
            return

        now = time.monotonic()
        queue = queue_for(self._watcher_armed_queue_map(), engine.queue_key)
        self._watcher_refresh_texts(engine.queue_key, queue)

        target_ok = True
        blocked = False
        if self._watcher_target is not None:
            # The tick's identity pre-check is a fast bounded read on the GUI
            # thread for WIN32 transports; the authoritative recheck happens
            # inside the sender on the worker thread. A CDP target's identity
            # probe and blocker text are SOCKET I/O and run on the worker
            # thread (P1-1): while the answer is pending, the tick HOLDS —
            # no engine.tick() runs, so the baseline tick counter is never
            # advanced by an unverified decision and a held run looks exactly
            # like a freshly armed one.
            if getattr(self._watcher_target, "ws_url", None):
                if not self._watcher_dispatch_verify():
                    return
                if self._watcher_verify_state != "ready":
                    return
                target_ok = self._watcher_verify_target_ok
                blocked = self._watcher_verify_blocked
            else:
                target_ok = self._watcher_target.matches()[0]

        # PERF-003: probe sampling (glob/stat/SQLite) runs on the probe
        # worker thread, never inside this Qt timer callback. The GUI holds
        # the tick while a sample is in flight and consumes exactly ONE
        # cached verdict per decision. A sample that a newer run has
        # superseded is dropped by the generation token.
        if self._watcher_sample_verdict is None:
            self._watcher_dispatch_sample(engine.probes)
            # An adapter with NO probes gets its verdict inline (still BUSY);
            # a real sample is in flight and the tick holds until it lands.
            if self._watcher_sample_verdict is None:
                return                     # HOLD: the sample is on the worker
        idle, reasons = self._watcher_sample_verdict
        self._watcher_sample_verdict = None

        intent = engine.tick(now, queue, blocked=blocked, target_ok=target_ok,
                             idle=idle, reasons=reasons)
        if intent is None:
            self._watcher_notify()
            if not engine.armed:
                self._watcher_stop_timer()
            return

        # Hand the send to the worker thread. The engine is already in
        # SENDING state, so no second send can be dispatched before this one
        # reports back; a report that never arrives means the run just waits.
        self._watcher_dispatch_send(intent)

    def _watcher_dispatch_verify(self):
        """Start a CDP verification on the worker thread when none is
        pending. Returns True when a verified answer is ALREADY cached (the
        tick may proceed), False while the answer is pending."""
        if self._watcher_verify_state == "ready":
            if time.monotonic() < self._watcher_verify_at:
                return True
            # the cached verdict is stale: re-verify on the next dispatch
            self._watcher_verify_state = "unverified"
        if self._watcher_verify_inflight:
            return False
        self._watcher_verify_inflight = True
        self._watcher_verify_gen += 1
        gen = self._watcher_verify_gen
        if self._watcher_verify_worker is None:
            self._watcher_ensure_worker()
        self._watcher_verify_worker.verify.emit(
            self._watcher_target,
            getattr(self, "_watcher_blocked_fn", None), gen)
        return False

    def _watcher_on_verify_result(self, status, gen, target_ok, blocked,
                                  reason):
        """The verification's answer, applied on the GUI thread.

        Only the CURRENT generation may be applied. "hold_target" disarms —
        the same consequence as a win32 window vanishing mid-run.
        "hold_blocked" ticks the engine ONCE with blocked=True: the run
        shows WATCHING and holds, no send fires and nothing is counted as a
        failure; the verify state reverts to unverified so the next tick
        re-checks. "ready" caches the verdicts for the next tick."""
        from fastprompter.main import is_gui_thread
        if not is_gui_thread():
            logger.critical("watcher verification rejected outside GUI thread")
            return
        try:
            if gen != self._watcher_verify_gen:
                return                    # stale: a newer run owns the watcher
            self._watcher_verify_inflight = False
            engine = self._watcher_engine
            if not engine.armed:
                return
            if status == "hold_target":
                engine.disarm(reason or "the target window is gone")
                # W2-004: the run ended — release its ownership lease too.
                self._watcher_release_run_ownership()
                self._watcher_stop_timer()
                self._watcher_notify()
                return
            if status == "hold_blocked":
                logger.warning("watcher blocked, holding: %s", reason)
                now = time.monotonic()
                queue = queue_for(self._watcher_armed_queue_map(),
                                  engine.queue_key)
                engine.tick(now, queue, blocked=True, target_ok=True)
                self._watcher_verify_state = "unverified"
                self._watcher_notify()
                return
            # "ready"
            self._watcher_verify_target_ok = target_ok
            self._watcher_verify_blocked = blocked
            self._watcher_verify_at = time.monotonic() + _VERIFY_INTERVAL_S
            self._watcher_verify_state = "ready"
        except Exception:
            logger.exception("watcher verification handling failed")
            try:
                self._watcher_engine.disarm(
                    "the watcher hit an error and stopped")
                self._watcher_release_run_ownership()
                self._watcher_stop_timer()
            except Exception:
                pass

    @property
    def _watcher_send_physical_active(self):
        """Compatibility alias: True while ANY physical dispatch is unresolved."""
        return bool(self._watcher_send_physical_tokens)

    def _watcher_dispatch_send(self, intent):
        """Send off-thread; the GUI never blocks on CDP socket I/O."""
        if getattr(self, "_watcher_quiescing", False):
            # P0-6: the app is quitting — no new sends. The item stays
            # PENDING and the final DB save persists it; nothing is marked
            # sent that never went out.
            return
        self._watcher_send_gen += 1
        gen = self._watcher_send_gen
        self._watcher_send_active = True
        # CORE-003: register this dispatch's OWN physical token BEFORE the
        # worker is asked to act, so the barrier is up the instant the send
        # leaves and only this token's completion can take it down.
        self._watcher_send_token_seq += 1
        token = self._watcher_send_token_seq
        self._watcher_send_physical_tokens.add(token)
        # W2-003: bind THIS dispatch to its authoritative LIVE owner — the
        # pinned queue map object the engine is draining, plus the data dict
        # it belongs to. A completion that arrives after the run ended
        # mutates exactly this object, so a delivered prompt can never flip
        # back to PENDING when a later live save re-serializes it.
        self._watcher_send_owners[token] = (
            self._watcher_pinned_category or self._watcher_current_category(),
            self._watcher_armed_queue_map(),
            getattr(self, "data", None),
        )
        worker = self._watcher_ensure_worker()
        worker.dispatch.emit(self._watcher_sender, intent,
                             self._watcher_target, gen, token)

    def _watcher_begin_quiesce(self, timeout_s=1.5):
        """W2-001: PAUSE the watcher run BEFORE a parent transaction commits.

        This is REVERSIBLE. It sets ``_watcher_quiescing`` (refusing new
        dispatch), stops the tick timer, and boundedly awaits the in-flight
        PHYSICAL send so a prompt that actually went out is still applied
        exactly once. Crucially it does NOT disarm the engine — the run stays
        ARMED. The irreversible disarm + queue persist is deferred to
        ``_watcher_commit_quiesce``, which the caller must invoke ONLY after
        the enclosing quit/profile-switch/restore transaction has committed.

        If the in-flight send does not resolve within the timeout the quiesce
        REFUSES: the watcher runtime is rolled back to exactly its prior state
        (timer restarted, engine still armed) so a refused quit/restore does
        not strand it paused, and the prompt stays in flight as it was.

        Returns True when the watcher is paused (barrier resolved, still
        armed); False when the barrier could not be cleared in time.
        """
        if getattr(self, "_watcher_quiescing", False):
            return not getattr(self, "_watcher_send_physical_active", False)
        self._watcher_quiescing = True
        was_armed = bool(getattr(self, "_watcher_engine", None)
                         and self._watcher_engine.armed)
        self._watcher_quiesce_was_armed = was_armed
        try:
            # Phase 1: pause new dispatch + stop the tick loop, but KEEP the
            # engine armed so an in-flight result is still applied.
            try:
                if self._watcher_timer is not None:
                    self._watcher_timer.stop()
            except Exception:
                pass
            deadline = time.monotonic() + max(0.0, float(timeout_s))
            # CORE-006: wait on the PHYSICAL send barrier, not the logical
            # generation flag — a disarm/panic may have already dropped the
            # logical flag while the worker is still on the socket.
            while self._watcher_send_physical_active and time.monotonic() < deadline:
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
                time.sleep(0.01)
            if self._watcher_send_physical_active:
                # Barrier refused: roll the watcher runtime back to its prior
                # state and refuse the quiesce. Nothing is marked sent or lost;
                # the prompt stays in flight exactly as it was.
                if was_armed and getattr(self, "_watcher_engine", None) \
                        and self._watcher_engine.armed:
                    self._watcher_start_timer()
                self._watcher_quiescing = False
                return False
            # The in-flight send has resolved (success/held/failure applied by
            # the worker callback). The run is now PAUSED but still armed —
            # leave _watcher_quiescing set so dispatch stays refused until the
            # parent transaction commits (or rolls back).
            return True
        except Exception:
            # Unexpected failure mid-pause: resume the run rather than strand
            # it paused and disarmed.
            if was_armed and getattr(self, "_watcher_engine", None) \
                    and self._watcher_engine.armed:
                try:
                    self._watcher_start_timer()
                except Exception:
                    pass
            self._watcher_quiescing = False
            return False

    def _watcher_commit_quiesce(self):
        """W2-001: the enclosing transaction committed — perform the
        irreversible disarm + queue persist that ``_watcher_begin_quiesce``
        deliberately deferred, then clear the paused flag.

        Safe to call when no quiesce is in progress (it is a no-op then)."""
        if not getattr(self, "_watcher_quiescing", False):
            return
        was_armed = getattr(self, "_watcher_quiesce_was_armed", False)
        try:
            if getattr(self, "_watcher_engine", None) is not None:
                self._watcher_engine.disarm("application is quitting")
        except Exception:
            logger.exception("watcher disarm failed during commit")
        # W2-004: persist ONLY a run that was actually live — never serialize
        # a dead-run pin (or an unrelated alias) over newer queue state.
        if was_armed or getattr(self, "_watcher_pinned_category", None) \
                is not None:
            try:
                self._watcher_persist_queues()
            except Exception:
                logger.exception("watcher queue persist failed during commit")
        self._watcher_quiescing = False

    def _watcher_rollback_quiesce(self):
        """W2-001: the enclosing transaction refused or raised — resume the
        exact pre-quiesce run (timer restarted, engine still armed) instead
        of leaving the watcher silently paused. Safe to call when no quiesce
        is in progress."""
        if not getattr(self, "_watcher_quiescing", False):
            return
        if getattr(self, "_watcher_engine", None) is not None \
                and self._watcher_engine.armed:
            try:
                self._watcher_start_timer()
            except Exception:
                pass
        self._watcher_quiescing = False

    def _watcher_ensure_worker(self):
        """The persistent worker thread, created once per window.

        Carries BOTH workers: the sender (socket writes with multi-second
        timeouts) and the verifier (CDP discovery + visible-text reads).
        Queued signals serialize them on the same thread — a verification
        waits for a stuck send, never blocks the GUI."""
        if self._watcher_worker is None:
            thread = QThread(self)
            thread.setObjectName("fastprompter-watcher-send")
            worker = _WatcherSendWorker()
            verify = _WatcherVerifyWorker()
            worker.moveToThread(thread)
            verify.moveToThread(thread)
            worker.dispatch.connect(worker._run)  # AFTER moveToThread: queued
            worker.done.connect(self._watcher_on_send_result)
            verify.verify.connect(verify._run)
            verify.verified.connect(self._watcher_on_verify_result)
            thread.start()
            self._watcher_worker = worker
            self._watcher_verify_worker = verify
            self._watcher_worker_thread = thread
        return self._watcher_worker

    def _watcher_shutdown(self):
        """Stop the send worker thread at window close.

        A send already running inside a blocking socket read cannot be
        interrupted cleanly, so the wait is bounded; at app exit a stuck
        worker is a leak, not a hazard.

        W2-006: the probe worker follows the same rule as the send worker —
        its Python/Qt owner references are cleared only after a CONFIRMED
        stop. On timeout the exact live objects stay strongly referenced
        (a destroyed-while-running QThread is an access-violation class
        failure) and the shutdown reports failure.
        """
        from fastprompter.main import wait_thread_seconds
        thread = self._watcher_worker_thread
        success = True
        if thread is not None and thread.isRunning():
            thread.quit()
            success = wait_thread_seconds(
                thread, _WATCHER_SHUTDOWN_TIMEOUT_S, "watcher worker"
            )
        if success:
            self._watcher_worker_thread = None
            self._watcher_worker = None
            owners = getattr(self, "_watcher_send_owners", None)
            if isinstance(owners, dict):
                owners.clear()
        else:
            logger.warning("watcher send worker shutdown TIMED_OUT; live "
                           "worker/thread retained (leak, never hang)")
        # PERF-003: stop the probe-sampling thread too.
        probe_thread = getattr(self, "_watcher_probe_thread", None)
        probe_ok = True
        if probe_thread is not None and probe_thread.isRunning():
            probe_thread.quit()
            probe_ok = wait_thread_seconds(
                probe_thread, _WATCHER_SHUTDOWN_TIMEOUT_S,
                "watcher probe worker")
        if probe_thread is not None:
            if probe_ok:
                self._watcher_probe_thread = None
                self._watcher_probe_worker = None
            else:
                # W2-006: keep the exact live references; never destroy a
                # running QThread wrapper during teardown.
                logger.warning("watcher probe worker shutdown TIMED_OUT; "
                               "live worker/thread retained")
        return success and probe_ok

    def _watcher_ensure_probe_worker(self):
        """The probe-sampling worker thread (PERF-003), separate from the
        send/verify thread so a slow glob/stat or a locked SQLite never
        queues behind a stuck socket send."""
        if self._watcher_probe_worker is None:
            thread = QThread(self)
            thread.setObjectName("fastprompter-watcher-probe")
            worker = _WatcherProbeWorker()
            worker.moveToThread(thread)
            worker.sample.connect(worker._run)
            worker.sampled.connect(self._watcher_on_probe_sampled)
            thread.start()
            self._watcher_probe_worker = worker
            self._watcher_probe_thread = thread
        return self._watcher_probe_worker

    def _watcher_dispatch_sample(self, probes):
        """PERF-003: ask the probe worker for one verdict for this run.

        Never overlaps: a sample is dispatched only when none is already in
        flight for the current generation. The result re-enters through
        ``_watcher_on_probe_sampled``, which re-runs the held tick."""
        if getattr(self, "_watcher_probe_inflight", False):
            return False
        probes = list(probes or ())
        if not probes:
            # An adapter with no probes must still be BUSY (uncertainty is
            # not idleness) — decide inline, nothing to sample.
            self._watcher_sample_verdict = (False, ["no probes configured"])
            return True
        worker = self._watcher_ensure_probe_worker()
        self._watcher_probe_gen += 1
        gen = self._watcher_probe_gen
        self._watcher_probe_inflight = True
        worker.sample.emit(probes, gen)
        return True

    def _watcher_on_probe_sampled(self, gen, idle, reasons, size):
        """PERF-003: the probe verdict, applied on the GUI thread.

        Only the CURRENT generation may be applied. The sample is cached for
        the next tick (which consumes exactly one verdict), then the held
        tick is re-run so a decision is not delayed until the next timer
        fire. Observe mode consumes the same cached verdict."""
        from fastprompter.main import is_gui_thread
        if not is_gui_thread():
            logger.critical("watcher probe sample rejected outside GUI thread")
            return
        self._watcher_probe_inflight = False
        if gen != self._watcher_probe_gen:
            return                     # stale: a newer run owns the sampler
        self._watcher_sample_verdict = (idle, list(reasons))
        self._watcher_sample_size = size
        try:
            if getattr(self, "_watcher_engine", None) and self._watcher_engine.armed:
                self._watcher_tick_inner()
            elif getattr(self, "_observe_adapter", None) is not None:
                self._observe_tick_inner()
        except Exception:
            logger.exception("watcher probe verdict handling failed")

    def _watcher_on_send_result(self, intent, gen, result, token):
        """The worker's answer, applied on the GUI thread.

        A result is applied ONLY when its generation is still current and the
        engine is still waiting on exactly this send. A panic, a disarm, an
        arm of a new run, or a superseding dispatch bumps the token — the
        stale result is dropped rather than reported as if it happened.
        """
        from fastprompter.main import is_gui_thread
        if not is_gui_thread():
            logger.critical("watcher completion rejected outside GUI thread")
            return
        try:
            # CORE-006/CORE-003: THIS dispatch's physical send has resolved.
            # Remove exactly its own token — never a sibling's — so an older
            # dispatch's late completion cannot clear the barrier while a
            # newer one is still physically in the air. Whether the result
            # may MUTATE the current run is a separate, generation-gated
            # question below.
            self._watcher_send_physical_tokens.discard(token)
            owner = self._watcher_send_owners.pop(token, None)
            if gen != self._watcher_send_gen:
                # Stale: a newer run owns the watcher. A send that actually
                # went out must still be recorded so it is never re-sent
                # (CORE-006 duplication guard); a failed one stays retryable.
                # A PARTIAL delivery is never retryable and never dropped:
                # resolve the original owner's item and persist it as failed.
                if result.ok:
                    # CORE-002/W2-003: a stale success belongs to the run
                    # that launched it. Reconcile the dispatch's OWN live
                    # owner object — never a freshly deserialized clone that
                    # the next live save would overwrite — and persist THAT
                    # object under the dispatch's original category/profile.
                    queue_key = getattr(intent, "queue_key", None)
                    if owner is not None:
                        _ocat, _omap, _odata = owner
                        queues = _omap if isinstance(_omap, dict) else {}
                        queue = queue_for(queues, queue_key)
                        item = (queue.find(intent.item_id)
                                if queue is not None else None)
                        if item is not None and item.state != SENT:
                            item.state = SENT
                            self._watcher_mark_sent(queue_key, item)
                            self._watcher_write_queues_into(
                                _odata if isinstance(_odata, dict)
                                else getattr(self, "data", {}),
                                _ocat, queues)
                            self._watcher_notify()
                    else:
                        # legacy fallback: no captured owner (pre-token
                        # dispatch), resolve from persisted state as before
                        from fastprompter.core.watcher.queue import load_queues
                        owner_raw = self.data.get("watcher_queues_all")
                        own = (owner_raw.get(intent.queue_category)
                               if isinstance(owner_raw, dict) else None)
                        queues = load_queues(own) if own else {}
                        queue = queue_for(queues, intent.queue_key)
                        item = (queue.find(intent.item_id)
                                if queue is not None else None)
                        if item is not None and item.state != SENT:
                            item.state = SENT
                            self._watcher_mark_sent(intent.queue_key, item)
                            self._watcher_write_queues(
                                intent.queue_category, queues)
                            self._watcher_notify()
                elif getattr(result, "partial", False):
                    # W2-001 stale uncertain: the original owner's item may
                    # already be in the target — persist FAILED/UNCERTAIN so
                    # it can never be re-sent, and stop the newer run that
                    # would share the contaminated physical target.
                    queue_key = intent.queue_key
                    if owner is not None:
                        _ocat, _omap, _odata = owner
                        queues = _omap if isinstance(_omap, dict) else {}
                        data_ref = (_odata if isinstance(_odata, dict)
                                    else getattr(self, "data", {}))
                    else:
                        from fastprompter.core.watcher.queue import (
                            load_queues as _lq,)
                        _ocat = intent.queue_category
                        owner_raw = self.data.get("watcher_queues_all")
                        own = (owner_raw.get(_ocat)
                               if isinstance(owner_raw, dict) else None)
                        queues = _lq(own) if own else {}
                        data_ref = self.data
                    queue = queue_for(queues, queue_key)
                    item = queue.find(intent.item_id) if queue is not None else None
                    if item is not None and item.state == PENDING:
                        item.mark_failed(
                            "uncertain delivery — the target may already "
                            "contain the prompt: " + result.reason)
                        self._watcher_write_queues_into(data_ref, _ocat,
                                                        queues)
                        self._watcher_notify()
                    engine = self._watcher_engine
                    if engine is not None and engine.armed:
                        engine.disarm(
                            "uncertain delivery — the target may already "
                            "contain the prompt; no further sends allowed")
                        self._watcher_stop_timer()
                return
            self._watcher_send_active = False
            engine = self._watcher_engine
            if not engine.armed or engine.state != "sending":
                return
            now = time.monotonic()
            queue = queue_for(self._watcher_armed_queue_map(), engine.queue_key)
            item = queue.find(intent.item_id) if queue is not None else None
            self._watcher_log.record(intent, result, self._watcher_target)
            if result.ok:
                engine.report_sent(item, now=now)
                if item is not None:
                    self._watcher_mark_sent(engine.queue_key, item)
            elif getattr(result, "partial", False):
                # W2-001: uncertain delivery. Hard barrier: persist the item
                # as failed, disarm immediately, never retry. report_uncertain
                # calls item.mark_failed() and disarms the engine.
                engine.report_uncertain(item, result.reason, now=now)
            elif getattr(result, "hold", False):
                # not a failure: the item stays pending and nothing is counted
                engine.report_held(result.reason, now=now)
            else:
                engine.report_failed(item, result.reason, now=now)
            self._watcher_persist_queues()
            self._watcher_notify()
            if not engine.armed:
                self._watcher_stop_timer()
        except Exception:
            logger.exception("watcher send-result handling failed")
            try:
                self._watcher_engine.disarm("the watcher hit an error and stopped")
                self._watcher_release_run_ownership()
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
        items_to_resolve = [item for item in queue.items if item.state in (PENDING, DETACHED)]
        if not items_to_resolve:
            return
            
        try:
            live_texts = self.queue_items_live_text(slot, items_to_resolve)
        except Exception:
            return
            
        for item in items_to_resolve:
            text, detached = live_texts.get(item, (item.text, True))
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
        self._observe_bytes = 0
        for probe in adapter.probes:
            probe.reset()
        # PERF-003: a fresh observe run owns the probe sampler. Any sample a
        # prior armed run left in flight is stale; bump the generation and
        # drop the cached verdict so this run's first sample is authoritative.
        self._watcher_probe_gen += 1
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
        self._watcher_sample_size = 0
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
        self._watcher_probe_gen += 1
        self._watcher_probe_inflight = False
        self._watcher_sample_verdict = None
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

        # PERF-003: sample the probes on the worker thread, like the armed
        # tick. The verdict (idle/reasons/size) is cached by the probe
        # worker; one cached verdict is consumed per observation pass.
        verdict = getattr(self, "_watcher_sample_verdict", None)
        if verdict is None:
            self._watcher_dispatch_sample(adapter.probes)
            return
        self._watcher_sample_verdict = None
        idle, reasons = verdict
        size = self._watcher_sample_size

        now = time.monotonic()
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
        return _probe_bytes(adapter.probes)

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
