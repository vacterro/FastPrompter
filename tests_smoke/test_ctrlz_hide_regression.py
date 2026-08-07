"""Reproduce "Ctrl+Z closes the program".

The window used to vanish on Ctrl+Z: a data undo queued a transient
WindowDeactivate and the old changeEvent -> close_on_focus_loss path hid the
window (hide_and_save), exactly like clicking away. The whole Hide on
Click-Out feature has since been REMOVED — there is no hide-on-deactivate at
all — so these tests guard the invariant that survives it: undo never hides
the window, and Ctrl+Z fires _smart_undo exactly once.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_ctrlz_")

# NOTE: real shortcuts ARE registered (no noop override)


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"z_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


def _real_ctrl_z(win):
    """Send Ctrl+Z through the real widget keyPressEvent (as the OS does)."""
    win.text_area.setFocus()
    win.text_area.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z,
                  Qt.KeyboardModifier.ControlModifier, "z", False, 1))
    _app.processEvents()


class TestCtrlZWindowHide:
    def test_data_undo_does_not_hide_window(self, win):
        """A data undo (silO/switch action) must not hide the main window."""

        win.data["temp_presets"][:] = ["alpha", "bravo"]
        win.data["pinned_silos"] = []
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.data_undo_stack = []
        win.data_redo_stack = []
        win._undo_kinds().clear()
        win.add_data_undo_state("probe")
        win.data["temp_presets"][1] = "changed"
        win.refresh_temp_presets()
        _app.processEvents()

        # Guard hide_and_save
        hidden = []
        real_hide = win.hide_and_save
        win.hide_and_save = lambda *a, **k: hidden.append(1)

        try:
            win._smart_undo()  # simulate what Ctrl+Z does
            _app.processEvents()
        finally:
            win.hide_and_save = real_hide

        assert not hidden, "Ctrl+Z data undo triggered hide_and_save (window vanishes)"

    def test_ctrl_z_via_editor_fires_smart_undo_once(self, win):
        """The editor keyPressEvent path must fire _smart_undo exactly once."""
        calls = []
        real = win._smart_undo
        win._smart_undo = lambda: calls.append("undo")
        try:
            _real_ctrl_z(win)
        finally:
            win._smart_undo = real
        assert len(calls) == 1, f"Ctrl+Z fired _smart_undo {len(calls)} times"

    def test_hide_and_save_not_called_on_real_ctrl_z(self, win):
        """Pressing Ctrl+Z must not hide the window at all."""
        win.data["temp_presets"][:] = ["alpha", "bravo"]
        win.data["pinned_silos"] = []
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.data_undo_stack = []
        win.data_redo_stack = []
        win._undo_kinds().clear()
        win.add_data_undo_state("probe")
        win.data["temp_presets"][1] = "changed"
        win.refresh_temp_presets()
        _app.processEvents()

        hidden = []
        real_hide = win.hide_and_save
        win.hide_and_save = lambda *a, **k: hidden.append(1)

        try:
            _real_ctrl_z(win)
            _app.processEvents()
        finally:
            win.hide_and_save = real_hide

        assert not hidden, "real Ctrl+Z hid the window (hide_and_save called)"
        assert win.isVisible(), "window must still be visible after Ctrl+Z"

    def test_text_undo_does_not_hide(self, win):
        """A plain text undo (native QTextEdit) must not hide the window."""
        hidden = []
        real_hide = win.hide_and_save
        win.hide_and_save = lambda *a, **k: hidden.append(1)
        try:
            win.text_area.setPlainText("hello world")
            win.text_area.undo()
            _app.processEvents()
        finally:
            win.hide_and_save = real_hide
        assert not hidden, "text undo hid the window"

    def test_real_ctrl_z_lives_through_the_deferred_lock_window(self, win):
        """The real T-750 failure: a deactivation queued by the undo used to
        hide the window. The hide-on-focus-loss feature is gone, so a real
        Ctrl+Z through the event loop must leave the window visible."""
        win.data["temp_presets"][:] = ["alpha", "bravo"]
        win.data["pinned_silos"] = []
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.data_undo_stack = []
        win.data_redo_stack = []
        win._undo_kinds().clear()
        win.add_data_undo_state("probe")
        win.data["temp_presets"][1] = "changed"
        win.refresh_temp_presets()
        _app.processEvents()

        hidden = []
        real_hide = win.hide_and_save
        win.hide_and_save = lambda *a, **k: hidden.append(1)

        try:
            _real_ctrl_z(win)
            for _ in range(8):
                _app.processEvents()
                _app.sendPostedEvents()
        finally:
            win.hide_and_save = real_hide

        assert not hidden, "real Ctrl+Z hid the window (hide_and_save called)"
        assert win.isVisible(), "window must still be visible after Ctrl+Z"

        time.sleep(0.4)
        for _ in range(8):
            _app.processEvents()
            _app.sendPostedEvents()
        assert win.isVisible(), "the window must stay visible after the event loop settles"
