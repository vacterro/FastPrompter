"""P0-6: quit refuses a failed final save; watcher is quiesced BEFORE the
event loop dies; closeEvent does not double-save after the pre-quit
finalize; watcher quiesce keeps unresolved sends pending.

Run with the smoke suite (needs a real Qt)::

    uv run pytest tests_smoke/test_quit_finalize.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_quit_")


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


def test_quit_refuses_when_final_save_fails(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or False)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: order.append(f"sound:{name}"))
    win._logical_finalized = False
    win.quit_app()
    assert order == ["save"]
    assert getattr(win, "_logical_finalized", False) is False


def test_quit_finalizes_then_quits_when_save_ok(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: order.append(f"sound:{name}"))
    win._logical_finalized = False
    win.quit_app()
    assert order == ["save", "sound:quit", "quit"]
    assert getattr(win, "_logical_finalized", False) is True


def test_quit_sound_nested_loop_rejects_reentrant_quit(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "save_data_to_db", lambda force=False: True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))

    def sound(name):
        order.append(f"sound:{name}")
        win.quit_app()

    monkeypatch.setattr(win.sound_manager, "play_to_completion", sound)
    win._logical_finalized = False

    win.quit_app()

    assert order == ["sound:quit", "quit"]




def test_close_event_skips_save_after_pre_quit_finalize(win, monkeypatch):
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    win._logical_finalized = True
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == []


def test_close_event_saves_when_not_pre_finalized(win, monkeypatch):
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    win._logical_finalized = False
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == [True]


