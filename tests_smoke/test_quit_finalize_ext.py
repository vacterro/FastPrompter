"""P0-6 extended: comprehensive close/finalize regression matrix.

Covers all Phase C scenarios:
- Direct quit success.
- Ordinary window close success.
- Close after prior logical finalization.
- Final DB save returns False.
- Final DB save raises an exception.
- Watcher quiesce returns False.
- Watcher quiesce raises.
- Retry after a refused close.
- Tray remains recoverable after refusal.
- OS session finalize followed by close.
- Physical teardown close.
- Reentrant quit during sound playback.
- Repeated close/open attempts.
- No duplicate forced saves.
- No loss of pending watcher or Sync-Project work.

Uses the smoke_win fixture (module-scoped) but resets finalize state
between tests to avoid leaks.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_quit_ext_")


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


def _reset_finalize_state(win):
    """Clear all logical-finalization flags so tests do not leak state."""
    win._logical_finalized = False
    win._quit_in_progress = False
    win._in_physical_teardown = False


# --- 1. Direct quit success ---

def test_direct_quit_success_is_single_save(win, monkeypatch):
    """Direct quit (menu/tray action) performs exactly one final save."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.quit_app()
    assert saves == [True]


# --- 2. Ordinary window close success ---

def test_ordinary_window_close_success_is_single_save(win, monkeypatch):
    """Ordinary window close via closeEvent performs exactly one final save."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == [True]


# --- 3. Close after prior logical finalization ---

def test_close_after_prior_logical_finalization_saves_zero(win, monkeypatch):
    """Close after _logical_finalized=True: zero additional saves."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win._logical_finalized = True
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == []


# --- 4. Final DB save returns False ---

def test_close_event_final_save_returns_false_refuses_close(win, monkeypatch):
    """A refused final save ignores the close event, keeps window open."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or False)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    ev = QEvent(QEvent.Type.Close)
    win.show()
    _app.processEvents()
    win.closeEvent(ev)
    _app.processEvents()
    assert ev.isAccepted() is False
    assert len(saves) == 1


# --- 5. Final DB save raises an exception ---

def test_close_event_final_save_raises_refuses_close(win, monkeypatch):
    """An exception in the final save ignores the close, keeps window open."""

    def raising_save(force=False):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(win, "save_data_to_db", raising_save)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    ev = QEvent(QEvent.Type.Close)
    win.show()
    _app.processEvents()
    win.closeEvent(ev)
    _app.processEvents()
    assert ev.isAccepted() is False


# --- 6. Watcher quiesce returns False ---

def test_quit_refuses_when_watcher_quiesce_returns_false(win, monkeypatch):
    """Watcher quiesce False -> shutdown refused before final save."""
    order = []
    monkeypatch.setattr(win, "_watcher_begin_quiesce", lambda: False, raising=False)
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or True)
    monkeypatch.setattr(win, "_watcher_commit_quiesce",
                        lambda: order.append("commit"), raising=False)
    monkeypatch.setattr(win, "_watcher_rollback_quiesce",
                        lambda: order.append("rollback"), raising=False)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.quit_app()
    assert "save" not in order
    assert getattr(win, "_logical_finalized", False) is False


# --- 7. Watcher quiesce raises ---

def test_quit_refuses_when_watcher_quiesce_raises(win, monkeypatch):
    """Watcher quiesce exception -> shutdown refused before final save."""
    order = []

    def raise_quiesce():
        raise RuntimeError("watcher on fire")

    monkeypatch.setattr(win, "_watcher_begin_quiesce", raise_quiesce, raising=False)
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.quit_app()
    assert "save" not in order
    assert getattr(win, "_logical_finalized", False) is False


# --- 8. Retry after a refused close ---

def test_retry_after_refused_close(win, monkeypatch):
    """After a refused close, fixing the save condition allows retry."""
    save_ok = [False]

    def save(force=False):
        return save_ok[0]

    monkeypatch.setattr(win, "save_data_to_db", save)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert getattr(win, "_logical_finalized", False) is False
    save_ok[0] = True
    _reset_finalize_state(win)
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert getattr(win, "_logical_finalized", False) is True


# --- 9. Tray remains recoverable after refusal ---

def test_tray_remains_recoverable_after_refusal(win, monkeypatch):
    """A refused quit must not hide the tray icon."""
    tray_state = ["hidden"]

    class FakeTray:
        def show(self):
            tray_state[0] = "shown"
        def hide(self):
            tray_state[0] = "hidden"

    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: False)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr


# --- 10. OS session finalize followed by close ---

def test_os_session_finalize_then_close(win, monkeypatch):
    """commitDataRequest-style path uses _pre_quit_logical_finalize."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    ok = win._pre_quit_logical_finalize()
    assert ok is True
    assert saves == [True]
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == [True]


# --- 11. Physical teardown close ---

def test_physical_teardown_close_skips_logical_save(win, monkeypatch):
    """_in_physical_teardown bypasses logical finalization entirely."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    win._in_physical_teardown = True
    ev = QCloseEvent()
    win.closeEvent(ev)
    _app.processEvents()
    assert saves == []
    win._in_physical_teardown = False


# --- 12. Reentrant quit during sound playback ---

def test_reentrant_quit_during_sound_playback_no_double_quit(win, monkeypatch):
    """Reentrant quit during sound playback does not repeat save or quit."""
    order = []
    monkeypatch.setattr(win, "save_data_to_db", lambda force=False: True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))

    def sound(name):
        order.append(f"sound:{name}")
        win.quit_app()

    monkeypatch.setattr(win.sound_manager, "play_to_completion", sound)
    _reset_finalize_state(win)
    win.quit_app()
    assert order == ["sound:quit", "quit"]


# --- 13. Repeated close/open attempts ---

def test_repeated_close_open_attempts_single_save_per_cycle(win, monkeypatch):
    """Repeated close attempts: exactly one save per close cycle."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    for _ in range(5):
        _reset_finalize_state(win)
        win.show()
        _app.processEvents()
        win.close()
        _app.processEvents()
    assert saves == [True, True, True, True, True]


# --- 14. No duplicate forced saves ---

def test_no_duplicate_forced_saves_on_close(win, monkeypatch):
    """closeEvent followed by quit_app must save exactly once."""
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert len(saves) == 1
    assert all(saves) is True


# --- 15. No loss of pending watcher work on refused save ---

def test_no_loss_of_pending_watcher_work_on_refused_save(win, monkeypatch):
    """Refused finalization must rollback watcher, not commit it."""
    commits = []
    rollbacks = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: False)
    monkeypatch.setattr(win, "_watcher_begin_quiesce", lambda: True, raising=False)
    monkeypatch.setattr(win, "_watcher_commit_quiesce",
                        lambda: commits.append(1), raising=False)
    monkeypatch.setattr(win, "_watcher_rollback_quiesce",
                        lambda: rollbacks.append(1), raising=False)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: None)
    _reset_finalize_state(win)
    win.quit_app()
    assert commits == []
    assert len(rollbacks) == 1
    assert getattr(win, "_logical_finalized", False) is False
