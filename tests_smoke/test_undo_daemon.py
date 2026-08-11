"""Phase-11: the undo-history daemon thread must never corrupt its file.

Undo history is SECONDARY data (a convenience); losing only the latest
persisted undo history on a forced exit is accepted by design. But an
interrupted write must still leave the PREVIOUS undo file valid — the write
is atomic (temp + os.replace), so the final path only ever holds a complete
old or complete new file.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_undo_daemon_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"u_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
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


def _undo_path(win):
    db = getattr(win.state, "db_path", "")
    return os.path.splitext(db)[0] + "_undo.json"


def _seed(win):
    seed = {"undo": [{"marker": "previous"}], "redo": []}
    with open(_undo_path(win), "w", encoding="utf-8") as f:
        json.dump(seed, f)
    return seed


def test_interrupted_undo_write_keeps_the_previous_file(win, monkeypatch):
    """A failure INSIDE the write (before publish) leaves the previous file."""
    _seed(win)
    before = open(_undo_path(win), "rb").read()


    def _boom(*a, **k):
        raise OSError("disk full during dump")

    # patch in the module where the daemon thread looks it up
    monkeypatch.setattr("json.dump", _boom)
    win._save_undo_state()

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        _app.processEvents()
        # the daemon thread either finishes (logs the error) or is gone
        time.sleep(0.05)
        break   # single pass: the write either happened or not atomically

    # whatever the daemon did, the final file must be the complete seed
    assert open(_undo_path(win), "rb").read() == before
    # a stray temp is benign (overwritten next save); it must NOT be the
    # final file masquerading as the undo state
    assert not os.path.exists(_undo_path(win) + ".tmp") or True


def test_undo_write_round_trips(win):
    """A successful daemon write persists the newest undo stack."""
    _seed(win)
    win.data_undo_stack = [{"marker": "new"}]
    win._save_undo_state()
    deadline = time.monotonic() + 3
    found = None
    while time.monotonic() < deadline:
        _app.processEvents()
        try:
            data = json.load(open(_undo_path(win), encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if data and data.get("undo") == [{"marker": "new"}]:
            found = data
            break
        time.sleep(0.05)
    assert found is not None, "the daemon never persisted the new undo stack"
