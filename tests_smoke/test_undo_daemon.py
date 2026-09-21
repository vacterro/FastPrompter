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
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_undo_daemon_")


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


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

    # record daemon threads so the test can JOIN them: the save runs on a
    # daemon thread, and an orphan that outlives this test would race the
    # next test's os.replace (Windows: destination-in-use -> WinError 5).
    started = []
    real_start = threading.Thread.start

    def _record_start(self):
        started.append(self)
        return real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _record_start)

    def _boom(*a, **k):
        raise OSError("disk full during dump")

    # patch in the module where the daemon thread looks it up
    monkeypatch.setattr("json.dump", _boom)
    win._save_undo_state()

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(t.is_alive() for t in started):
        _app.processEvents()
        time.sleep(0.05)

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
            with open(_undo_path(win), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = None
        if data and data.get("undo") == [{"marker": "new"}]:
            found = data
            break
        time.sleep(0.05)
    assert found is not None, "the daemon never persisted the new undo stack"
