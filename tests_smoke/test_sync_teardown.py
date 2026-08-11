"""Sync worker teardown safety (Phase-8 regression).

The sync worker used to be a per-window QThread; destroying it during window
teardown (especially the DeferredDelete-flush teardown the main smoke suite
uses) aborted the process with STATUS_STACK_BUFFER_OVERRUN. The worker is now
process-wide, so no window teardown can destroy a running thread. These tests
pin both teardown paths: a plain close and the aggressive DeferredDelete
flush, each after a real sync round-trip.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_sync_teardown_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"t_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    for timer in ("auto_save_timer", "topmost_timer", "_cache_timer"):
        t = getattr(w, timer, None)
        if t is not None and not sip.isdeleted(t):
            t.stop()
    w.state.conn = None
    w.conn = None
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def _sync_once(win, tmp_path, marker):
    root = str(tmp_path / "root")
    win.data["sync_path"] = root
    win.data["sync_mode"] = "Silo"
    win.data["temp_presets"][0] = "# t\n" + marker
    win._sync_written = {}
    win.sync_to_disk(force=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _app.processEvents()
        if win._sync_written:
            return root
        time.sleep(0.01)
    raise AssertionError("sync never landed before teardown")


def test_sync_roundtrip_then_plain_close(win, tmp_path):
    root = _sync_once(win, tmp_path, "one")
    assert any(f.endswith(".md") for _, _, fs in os.walk(root) for f in fs)


def test_process_exit_after_global_shutdown_is_clean():
    """A child process that dispatches a sync and then calls the global
    shutdown hook must exit WITHOUT an access violation. The hook's QThread
    wait is MILLISECONDS-bounded (a seconds/ms unit bug let the thread stay
    running past process exit — 0xC0000005 under full-suite load), and the
    window must be destroyed on the C++ side before the process exits (a
    window that survives to interpreter teardown races the retired worker
    and aborts the same way)."""
    import subprocess
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    child = r'''
import sys, os, tempfile, time
sys.path.insert(0, r"{src}")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import fastprompter.core.state as st
st.get_db_path = lambda p=1: os.path.join(tempfile.mkdtemp(), "d.db")
st.run_portable_backup = lambda d: None
from fastprompter.main import FastPrompter, sync_shutdown_global
FastPrompter.setup_single_instance_server = lambda s: None
FastPrompter.register_all_hotkeys = lambda s: None
FastPrompter.unregister_all_hotkeys = lambda s: None
from PyQt6.QtWidgets import QApplication
app = QApplication([])
w = FastPrompter()
w.show()
root = tempfile.mkdtemp()
w.data["sync_path"] = root
w.data["sync_mode"] = "Silo"
w.data["active_temp_slot"] = 0
w.data["temp_presets"][0] = "# t\nworker"
w._sync_written = {{}}
w.sync_to_disk(force=True)
w._sync_dispatch_pending()
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    app.processEvents()
    if w._sync_written:
        break
    time.sleep(0.01)
w.data["sync_path"] = ""
w.data["sync_mode"] = "Off"
w.auto_save_timer.stop()
w.topmost_timer.stop()
w.close()
# Destroy the window C++ side BEFORE the retired-worker hook quits the
# thread. A window that survives to interpreter teardown races the retired
# worker's destruction and aborts with 0xC0000005.
w.deleteLater()
app.processEvents()
sync_shutdown_global()
app.processEvents()                 # deliver any trailing queued results
print("CLEAN_EXIT")
'''
    proc = subprocess.run([sys.executable, "-c", child.format(src=src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN_EXIT" in proc.stdout



def test_sync_roundtrip_then_deferred_delete_teardown(win, tmp_path):
    root = _sync_once(win, tmp_path, "two")
    assert any(f.endswith(".md") for _, _, fs in os.walk(root) for f in fs)
    win.data["sync_path"] = ""
    win.data["sync_mode"] = "Off"
