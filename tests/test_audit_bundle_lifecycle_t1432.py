"""T-1432 (SRC-093) — CORE-001 dedicated bundle-thread lifecycle suite.

Dedicated silo-bundle ``QThread``s are NOT members of the global Qt thread
pool, so no existing barrier owns them. They must be quiesced and PHYSICALLY
retired (a) before the profile-switch commit point can rebind ``self.data``
and (b) before shutdown retires SQLite/window ownership. A completion that
arrives from a profile that is no longer active must not mutate the live
profile's history, coverage, clipboard or UI.
"""

from __future__ import annotations

import inspect
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtCore import QThread

from fastprompter import main as main_mod
from fastprompter.main import FastPrompter


class _FakeThread:
    """Stand-in for the op's QThread with a controllable ``wait``."""

    def __init__(self, stopped=True):
        self.stopped = stopped
        self.waits = []

    def wait(self, ms):
        self.waits.append(ms)
        return bool(self.stopped)


class _FakeOp:
    def __init__(self, profile_id=1, silo_id="A", stopped=True):
        self.capture = {"cancel": threading.Event(), "silo_id": silo_id}
        self.dialog = MagicMock()
        self.thread = _FakeThread(stopped)
        self.profile_id = profile_id


class _Window:
    """A bare host carrying the two shipped lifecycle methods."""

    _bundle_ops_retire = FastPrompter._bundle_ops_retire
    _bundle_on_finished = FastPrompter._bundle_on_finished

    def __init__(self, profile_id=1):
        self.state = SimpleNamespace(profile_id=profile_id)
        self._bundle_ops = {}
        self._current_lang = "EN"
        self._last_bundle_path = None
        self._silo_bundle_record_success = MagicMock()
        self._silo_bundle_apply_retention = MagicMock()
        self._record_bundle_coverage = MagicMock()
        self._show_in_app_toast = MagicMock()
        self._reveal_path = MagicMock()


def _ok_result():
    return SimpleNamespace(
        zip_path="C:/x/a.zip", fingerprint="f" * 64, items=("a",), missing=(),
        index_status="full", archive_size=10, archive_mtime_ns=20,
        signatures={})


# --- bounded, truthful physical retirement --------------------------------

def test_core001_retire_refuses_while_thread_blocked_then_succeeds():
    window = _Window(profile_id=1)
    op = _FakeOp(stopped=False)
    window._bundle_ops = {7: op}

    assert window._bundle_ops_retire(timeout_s=0.2) is False
    assert op.capture["cancel"].is_set()      # cancellation was signalled
    assert 7 in window._bundle_ops            # NOT silently abandoned

    op.thread.stopped = True                  # the worker retired
    assert window._bundle_ops_retire(timeout_s=0.2) is True
    assert 7 not in window._bundle_ops


def test_core001_retire_is_a_noop_without_operations():
    assert _Window()._bundle_ops_retire(timeout_s=1.0) is True


class _CooperativeThread(QThread):
    """Exits its run() only when the op's cancel Event is set."""

    def __init__(self, cancel):
        super().__init__()
        self._cancel = cancel
        self.reached = threading.Event()

    def run(self):
        self.reached.set()
        while not self._cancel.is_set():
            time.sleep(0.005)


class _StubbornThread(QThread):
    """Deliberately ignores the cancel Event within the bound."""

    def __init__(self):
        super().__init__()
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            time.sleep(0.005)


def test_core001_retire_physically_stops_a_real_qthread(qapp):
    cancel = threading.Event()
    thread = _CooperativeThread(cancel)
    window = _Window()
    op = _FakeOp()
    op.capture["cancel"] = cancel
    op.thread = thread
    window._bundle_ops = {1: op}

    thread.start()
    assert thread.reached.wait(2.0)
    assert thread.isRunning()

    started = time.monotonic()
    assert window._bundle_ops_retire(timeout_s=5.0) is True
    assert not thread.isRunning()
    assert time.monotonic() - started < 5.0
    assert 1 not in window._bundle_ops


def test_core001_retire_reports_false_for_a_stubborn_thread(qapp):
    thread = _StubbornThread()
    window = _Window()
    op = _FakeOp()
    op.thread = thread
    window._bundle_ops = {1: op}

    thread.start()
    while not thread.isRunning():
        time.sleep(0.005)
    assert window._bundle_ops_retire(timeout_s=0.3) is False
    assert 1 in window._bundle_ops          # ownership is not released

    thread.stop.set()
    assert thread.wait(5000)


# --- the two production call sites ---------------------------------------

def test_core001_change_profile_retires_bundles_before_the_rebind():
    src = inspect.getsource(FastPrompter.change_profile)
    i_retire = src.index("_bundle_ops_retire")
    i_switch = src.index("self.state.switch_profile(")
    assert i_retire < i_switch
    # the refusal path returns without reaching the state switch
    assert "return" in src[i_retire:i_switch]


def test_core001_shutdown_retires_bundles_and_reports_non_clean():
    src = inspect.getsource(main_mod._shutdown_application)
    i_retire = src.index("_bundle_ops_retire")
    assert "clean = False" in src[i_retire:i_retire + 700]


# --- stale completion cannot mutate the wrong profile --------------------

def test_core001_stale_completion_cannot_mutate_the_new_profile(monkeypatch):
    window = _Window(profile_id=2)               # B is active
    op = _FakeOp(profile_id=1)                   # the op belongs to A
    window._bundle_ops = {}

    window._bundle_on_finished(op, ("ok", _ok_result()))

    assert window._silo_bundle_record_success.call_count == 0
    assert window._record_bundle_coverage.call_count == 0
    assert window._show_in_app_toast.call_count == 0
    assert window._last_bundle_path is None
    assert op.dialog.close.called                # the dialog is still closed


def test_core001_matching_profile_completion_still_reports(monkeypatch):
    from fastprompter.ui import image_viewer
    monkeypatch.setattr(image_viewer, "copy_files_to_clipboard",
                        lambda paths: True)

    window = _Window(profile_id=1)
    op = _FakeOp(profile_id=1)
    op.capture.update({
        "title": "Silo", "target_dir": "C:/x", "silo_dir": "C:/x",
        "effective_options": {}, "plan_kwargs": {"include_text": True,
                                                 "text": "body"},
    })
    window._bundle_ops = {}

    window._bundle_on_finished(op, ("ok", _ok_result()))

    assert window._silo_bundle_record_success.call_count == 1
    assert window._record_bundle_coverage.call_count == 1
    assert window._show_in_app_toast.call_count == 1
    assert window._last_bundle_path == "C:/x/a.zip"
