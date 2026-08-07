"""Reproduce "Ctrl+Z closes the program".

Symptom: pressing Ctrl+Z makes the window vanish (hide_and_save), exactly
like clicking away when close_on_focus_loss is on. Hypothesis: a data undo
touchs something that deactivates the main window, OR _smart_undo fires
twice per keypress (QShortcut + editor keyPressEvent), and the second
_apply_data_state triggers the focus loss path.
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
    w.data["close_on_focus_loss"] = "True"
    w.resize(960, 540)
    w.show()
    w._ever_activated = True
    w._shown_at = 0.0  # past the 2s grace period
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
        """The real T-750 failure: a deactivation queued by the undo arrives
        asynchronously, AFTER a synchronous lock release would have let it
        through. The lock is released deferred (300ms); waiting longer than
        that and then asserting visibility covers the actual event-loop path,
        not a mocked hide_and_save."""
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
        assert win._focus_lock_count == 0, (
            f"focus lock leaked ({win._focus_lock_count}), "
            "window is now permanently immune to click-away"
        )

    def test_focus_lock_blocks_deactivate_hide_and_release_unblocks(self, win):
        """The lock the undo path holds is what actually stops the hide: a
        WindowDeactivate arriving while `_increment_focus_lock` is held must
        NOT reach hide_and_save, and one arriving after the release must."""
        win._shown_at = 0.0  # past the 2s grace period
        win.isActiveWindow = lambda: False  # pretend the window lost focus

        hidden = []
        real_hide = win.hide_and_save
        win.hide_and_save = lambda *a, **k: hidden.append(1)
        deactivate = QEvent(QEvent.Type.WindowDeactivate)

        try:
            win.changeEvent(deactivate)
            assert len(hidden) == 1, (
                f"deactivate without lock must hide, got {len(hidden)}"
            )

            win._increment_focus_lock()
            win.changeEvent(deactivate)
            assert len(hidden) == 1, (
                f"deactivate under lock must NOT hide, got {len(hidden)}"
            )

            win._decrement_focus_lock()
            win.changeEvent(deactivate)
            assert len(hidden) == 2, (
                f"deactivate after release must hide again, got {len(hidden)}"
            )
        finally:
            win.hide_and_save = real_hide
