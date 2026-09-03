"""Phase-9: the watcher send runs off the GUI thread, and stale results are
never applied.

The CDP sender performs multiple network round trips with multi-second
timeouts; running it on the Qt event loop froze the window. The send now goes
to a worker thread and comes back through a signal with a generation token.
These tests prove:

* a valid result is applied exactly once (sent/hold/failed)
* a result whose generation is stale is DROPPED, even if it reports success
  (panic, disarm, rearm, superseding dispatch)
* a result arriving after the watcher stopped is DROPPED
* the tick dispatches to the worker (the GUI thread never calls send())
* the real worker thread actually delivers a result back
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.core.watcher.engine import SendIntent
from fastprompter.core.watcher.sender import SendResult
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_watcher_async_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"w_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


class _CaptureEmitter:
    """A stand-in for the worker's dispatch signal."""

    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _FakeWorker:
    def __init__(self):
        self.dispatch = _CaptureEmitter()


class _FakeWin32:
    alive = True
    hwnd = 1234

    def info(self, hwnd):
        if not self.alive:
            return None
        return {"title": "Agent", "cls": "Console"}


def _fake_adapter():
    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import Probe

    class Steady(Probe):
        kind = "steady"

        def _read(self):
            return "unchanging"

    return Adapter("claude", probes=[Steady(quiet_ms=0)],
                   settle_ms=0)


def _arm(win, monkeypatch):
    from fastprompter.core.watcher import win32 as win32_mod

    fake = _FakeWin32()
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: fake.info(hwnd))
    monkeypatch.setattr(win32_mod, "probe_for",
                        lambda api=None: (lambda h: fake.info(h)))
    ok, reason = win.watcher_arm(fake.hwnd, _fake_adapter(), live=False)
    assert ok, reason
    return fake


def _queue_with_item(win, text="prompt"):
    from fastprompter.core.watcher.queue import PENDING, QueueItem, SiloQueue

    slot = win._queue_slot_key()
    item = QueueItem(text, skill="", line=0, state=PENDING)
    win.prompt_queues[slot] = SiloQueue([item])
    return slot, item


def _intent_for(item, slot):
    return SendIntent(item.id, item.text, slot, item.skill, 0.0)


class TestResultApplication:
    def test_a_valid_send_result_is_applied_once(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        win.watcher_engine().state = "sending"
        win.watcher_engine().pending = intent
        gen = win._watcher_send_gen

        win._watcher_on_send_result(
            intent, gen, SendResult(True, "sent", "hello"), 0)

        assert win.watcher_engine().sent_count == 1
        assert item.state == "sent" or item.state != "pending"
        win.watcher_disarm("done")

    def test_a_failed_send_is_reported_as_failure(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        engine = win.watcher_engine()
        engine.state = "sending"
        engine.pending = intent

        win._watcher_on_send_result(
            intent, win._watcher_send_gen,
            SendResult(False, "target refused", "hello"), 0)

        assert engine.consecutive_failures == 1
        win.watcher_disarm("done")

    def test_a_hold_leaves_the_item_pending(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        engine = win.watcher_engine()
        engine.state = "sending"
        engine.pending = intent

        win._watcher_on_send_result(
            intent, win._watcher_send_gen,
            SendResult(False, "waiting", "hello", hold=True), 0)

        assert engine.consecutive_failures == 0
        assert engine.sent_count == 0
        assert item.state == "pending"
        win.watcher_disarm("done")


class TestStaleRejection:
    def test_stale_result_after_panic_is_dropped(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        old_gen = win._watcher_send_gen
        win.watcher_panic()          # bumps the generation

        win._watcher_on_send_result(
            intent, old_gen, SendResult(True, "sent", "hello"), 0)

        assert win.watcher_engine().sent_count == 0
        assert item.state == "pending"      # nothing was marked sent

    def test_stale_result_after_disarm_is_dropped(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        old_gen = win._watcher_send_gen
        win.watcher_disarm("stopped")   # bumps the generation

        win._watcher_on_send_result(
            intent, old_gen, SendResult(True, "sent", "hello"), 0)

        assert win.watcher_engine().sent_count == 0
        assert item.state == "pending"

    def test_stale_result_after_rearm_is_dropped(self, win, monkeypatch):
        _arm(win, monkeypatch)              # gen G1
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        old_gen = win._watcher_send_gen     # simulates an in-flight dispatch
        win.watcher_disarm("swap")          # G2
        _arm(win, monkeypatch)              # G3 — a brand new run

        win._watcher_on_send_result(
            intent, old_gen, SendResult(True, "sent", "hello"), 0)

        assert win.watcher_engine().sent_count == 0
        assert item.state == "pending"
        win.watcher_disarm("done")

    def test_stale_result_when_engine_no_longer_sending_is_dropped(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        gen = win._watcher_send_gen
        # engine has moved on (e.g. a panic raced past the generation bump)
        win.watcher_engine().state = "disarmed"
        win.watcher_engine().pending = None

        win._watcher_on_send_result(
            intent, gen, SendResult(True, "sent", "hello"), 0)

        assert win.watcher_engine().sent_count == 0


class TestDispatch:
    def test_the_tick_dispatches_to_the_worker_not_send_synchronously(
            self, win, monkeypatch):
        """The GUI thread must hand the send to the worker, never call
        sender.send() itself."""
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)

        engine = win.watcher_engine()
        monkeypatch.setattr(engine, "tick", lambda *a, **k: intent)
        engine.state = "sending"            # a real tick sets this itself
        fake_worker = _FakeWorker()
        monkeypatch.setattr(win, "_watcher_ensure_worker",
                            lambda: fake_worker)
        sent_directly = []
        monkeypatch.setattr(
            win._watcher_sender, "send",
            lambda *a, **k: sent_directly.append(1) or
            SendResult(True, "sent", "hello"))

        win._watcher_tick_inner()

        # PERF-003: the tick dispatches a probe sample to the worker thread
        # and holds until the verdict lands; pump events so the sample
        # arrives and the send is then handed to the fake worker.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not fake_worker.dispatch.calls:
            _app.processEvents()
            time.sleep(0.01)

        assert len(fake_worker.dispatch.calls) == 1
        sender, sent_intent, target, gen, token = fake_worker.dispatch.calls[0]
        assert sent_intent.item_id == intent.item_id
        assert gen == win._watcher_send_gen
        assert token in win._watcher_send_physical_tokens
        assert sent_directly == []          # the GUI thread never sent
        assert win._watcher_engine.state == "sending"
        win.watcher_disarm("done")


class TestRealWorker:
    def test_the_real_worker_thread_delivers_the_result(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)

        engine = win.watcher_engine()
        monkeypatch.setattr(engine, "tick", lambda *a, **k: intent)
        from fastprompter.core.watcher.sender import DryRunSender
        monkeypatch.setattr(win, "_watcher_sender", DryRunSender())
        # engine.tick above short-circuits the real decision; mark sending so
        # the result handler accepts the answer
        engine.state = "sending"
        engine.pending = intent

        win._watcher_tick_inner()          # dispatches to the real thread

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            _app.processEvents()
            if engine.sent_count == 1:
                break
            time.sleep(0.01)
        assert engine.sent_count == 1, "the worker result never arrived"
        assert win.watcher_log().to_list(), "the send must be logged"
        win.watcher_disarm("done")

    def test_worker_send_and_completion_use_expected_threads(self, win, monkeypatch):
        _arm(win, monkeypatch)
        slot, item = _queue_with_item(win, "hello")
        intent = _intent_for(item, slot)
        engine = win.watcher_engine()
        engine.state = "sending"
        engine.pending = intent
        worker_threads = []
        completion_threads = []

        class Sender:
            def send(self, _intent, _target):
                worker_threads.append(QThread.currentThread())
                return SendResult(True, "sent", "hello")

        real_done = win._watcher_on_send_result

        def record_done(*args):
            completion_threads.append(QThread.currentThread())
            return real_done(*args)

        assert win._watcher_shutdown() is True
        monkeypatch.setattr(win, "_watcher_sender", Sender())
        monkeypatch.setattr(win, "_watcher_on_send_result", record_done)
        win._watcher_dispatch_send(intent)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            _app.processEvents()
            if completion_threads:
                break
            time.sleep(0.01)

        assert worker_threads == [win._watcher_worker_thread]
        assert completion_threads == [_app.thread()]
        win.watcher_disarm("done")
