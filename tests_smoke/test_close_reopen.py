"""P0-11/P0-12: resident window close vs process quit.

The application is configured to survive the loss of its last window
(``setQuitOnLastWindowClosed(False)``), so a window close must NOT retire
process-owned workers — the old closeEvent stopped the watcher thread and
set ``_sync_shutting_down = True`` forever, so a tray-reopened resident
process had permanently dead Sync/automation. And ``quit_app`` used to
dismantle IPC/SQLite itself, racing the close-path final save; the ONE
canonical retirement owner is ``_shutdown_application``.

These tests pin the split:

* resident close/reopen -> workers alive, Sync writes again, DB saves
* quit_app -> only requests quit, dismantles nothing
* _shutdown_application -> retires window workers exactly once, in order
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter import main as m
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_close_reopen_")


@pytest.fixture
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"cr_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    for timer in ("auto_save_timer", "topmost_timer", "_cache_timer", "_undo_timer"):
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


def _sync_mirror_files(win, tmp_path, marker):
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
    raise AssertionError("sync never landed")


def _db_text(win):
    conn = sqlite3.connect(win.state.db_path)
    try:
        rows = conn.execute(
            "SELECT content FROM temp_presets_v2 WHERE category=? AND slot=0",
            (win.get_current_category(),)).fetchall()
        return rows[0][0] if rows else ""
    finally:
        conn.close()


def test_resident_close_keeps_workers_alive_and_reopen_still_saves(
        win, monkeypatch, tmp_path):
    retired = []
    monkeypatch.setattr(win, "_watcher_shutdown",
                        lambda: retired.append("watcher") or True)
    monkeypatch.setattr(win, "_sync_shutdown",
                        lambda: retired.append("sync") or None)

# resident close: the window hides, the process keeps running
    win.close()
    _app.processEvents()
    assert retired == [], "a resident close must not retire workers"
    assert getattr(win, "_sync_shutting_down", False) is False

    # reopen from the tray and edit/save: Sync must still function
    win.show()
    _app.processEvents()
    root = _sync_mirror_files(win, tmp_path, "after reopen")
    assert any(f.endswith(".md") for _, _, fs in os.walk(root) for f in fs)

    # DB save after reopen lands in the database
    win.text_area.setPlainText("survives the reopen")
    win.save_data_to_db(force=True)
    _app.processEvents()
    assert _db_text(win) == "survives the reopen"
    assert retired == [], "nothing may have retired during reopen work"


def test_quit_app_only_requests_quit(win, monkeypatch):
    quit_calls = []
    monkeypatch.setattr(m.QApplication, "quit",
                        lambda: quit_calls.append("quit"))
    closed = []
    win.ipc = type("Ipc", (), {"close": lambda self: closed.append("ipc")})()
    win.conn = type("Conn", (), {"close": lambda self: closed.append("conn")})()
    win.state.conn = win.conn
    # P0-6: quit_app is refused when the final save fails — the fake conn
    # cannot write, so the save is stubbed clean to keep THIS test on its
    # own contract (quit wiring, not save behavior; see test_quit_finalize).
    monkeypatch.setattr(win, "save_data_to_db", lambda force=False: True)

    win.quit_app()

    assert quit_calls == ["quit"]
    assert closed == [], ("quit_app must not dismantle IPC/SQLite; "
                          "_shutdown_application owns the retirement")
    assert win.conn is not None
    assert win.state.conn is not None


def test_shutdown_application_retires_window_workers_exactly_once(monkeypatch):
    events = []

    class _CloseRec:
        def close(self):
            events.append("CLOSE_REC")

    class _DbCloseRec:
        def close(self):
            events.append("DB_CLOSE")

    class _Window:
        _close_workers_clean = True

        def __init__(self):
            self.ipc = _CloseRec()
            self.conn = _DbCloseRec()
            self.state = type("State", (), {"conn": self.conn})()

        def close(self):
            events.append("FINAL_CLOSE")

        def _watcher_shutdown(self):
            events.append("WATCHER_RETIRED")
            return True

        def _sync_shutdown(self):
            events.append("SYNC_RETIRED")

        def _wait_for_undo_saves(self):
            events.append("UNDO_STOPPED")
            return True

        def deleteLater(self):
            events.append("WINDOW_DELETE")

    class _App:
        def processEvents(self):
            pass

    class _Lock:
        def __init__(self):
            self.released = False

        def release(self):
            self.released = True
            events.append("LOCK_RELEASE")

    monkeypatch.setattr(m, "sync_shutdown_global",
                        lambda: events.append("SYNC_GLOBAL") or True)
    monkeypatch.setattr(m, "backup_worker_shutdown_global",
                        lambda: events.append("BACKUP_GLOBAL") or True)
    monkeypatch.setattr(
        "fastprompter.ui.file_container.container_worker_shutdown_global",
        lambda: events.append("CONTAINER_GLOBAL") or True)

    window = _Window()
    lock = _Lock()
    assert m._shutdown_application(window, _App(), lock) is True
    assert lock.released

    assert events.count("FINAL_CLOSE") == 1
    assert events.count("WATCHER_RETIRED") == 1
    assert events.count("SYNC_RETIRED") == 1
    # final save -> window workers -> persistence close -> global drain -> lock
    assert events.index("FINAL_CLOSE") < events.index("WATCHER_RETIRED")
    assert events.index("WATCHER_RETIRED") < events.index("SYNC_RETIRED")
    assert events.index("SYNC_RETIRED") < events.index("CLOSE_REC")
    assert events.index("CLOSE_REC") < events.index("DB_CLOSE")
    assert events.index("DB_CLOSE") < events.index("LOCK_RELEASE")
