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
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_sync_teardown_")


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


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
    """A child that dispatches a real sync, then calls the global shutdown
    hook, must retire the worker INSIDE the hook's bound.

    The hook's QThread wait is MILLISECONDS-bounded; a seconds/ms unit bug let
    the thread stay running past process exit (0xC0000005 under full-suite
    load). The child therefore asserts the hook's own verdict and that the
    thread really stopped, rather than merely reaching the end of the script.

    It then exits via os._exit: the window is destroyed on the C++ side first,
    and what remains at interpreter finalization is CPython tearing down live
    Qt globals in a headless session — a native fault in this environment, not
    the contract under test (same precedent as test_close_save_contract.py).
    """
    import subprocess
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    child = r'''
import sys, os, tempfile, time
sys.path.insert(0, r"{src}")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import fastprompter.core.state as st
st.get_db_path = lambda p=1: os.path.join(tempfile.mkdtemp(), "d.db")
st.run_portable_backup = lambda d, profile_id=1: None
import fastprompter.main as fp_main
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
problems = []
if not w._sync_written:
    problems.append("sync-never-landed")
w.data["sync_path"] = ""
w.data["sync_mode"] = "Off"
w.auto_save_timer.stop()
w.topmost_timer.stop()
w.close()
# Destroy the window C++ side BEFORE the retired-worker hook quits the
# thread. A window that survives to interpreter teardown races the retired
# worker's destruction and aborts with 0xC0000005. Whether the offscreen
# platform actually completes the delete is not asserted: it does not on this
# runner, and forcing it (sendPostedEvents DeferredDelete) aborts the process.
w.deleteLater()
app.processEvents()
# Captured BEFORE the hook: on success it nulls the global, so reading it
# afterwards could never observe a still-running thread.
thread = fp_main._SYNC_SHARED_THREAD
stopped = sync_shutdown_global()
app.processEvents()                 # deliver any trailing queued results
if not stopped:
    problems.append("shutdown-hook-timed-out")
if thread is not None and thread.isRunning():
    problems.append("sync-thread-still-running")
if problems:
    print("FAIL " + " ".join(problems), flush=True)
    os._exit(1)
print("CLEAN_EXIT", flush=True)
os._exit(0)
'''
    proc = subprocess.run([sys.executable, "-c", child.format(src=src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "CLEAN_EXIT" in proc.stdout



def test_sync_roundtrip_then_deferred_delete_teardown(win, tmp_path):
    root = _sync_once(win, tmp_path, "two")
    assert any(f.endswith(".md") for _, _, fs in os.walk(root) for f in fs)
    win.data["sync_path"] = ""
    win.data["sync_mode"] = "Off"
