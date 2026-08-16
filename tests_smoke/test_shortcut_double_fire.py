"""Check that editor keyPressEvent shortcuts do not double-fire.

The editor's keyPressEvent has matches() fallbacks for the configurable
hotkeys (they handle the case where the QShortcut is remapped). This test
verifies that firing the editor's keyPressEvent directly applies each
command exactly once — the shared handler is the single action path.

    uv run pytest tests_smoke/test_shortcut_double_fire.py -v
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_doublefire_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"d_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
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


def _send_ctrl_key(editor, key):
    """Send a Ctrl+<key> event directly to the editor's keyPressEvent."""
    ev = QKeyEvent(
        QEvent.Type.KeyPress, key, Qt.KeyboardModifier.ControlModifier,
        "x", False, 1)
    editor.keyPressEvent(ev)


class TestEditorShortcutPath:
    """The editor's matches() fallback applies each command exactly once."""

    def test_ctrl_b_applies_bold_once(self, win):
        calls = []
        original = win.apply_bold_smart
        win.apply_bold_smart = lambda: calls.append("apply")
        try:
            _send_ctrl_key(win.text_area, Qt.Key.Key_B)
            _app.processEvents()
        finally:
            win.apply_bold_smart = original
        assert len(calls) == 1, f"Ctrl+B fired {len(calls)} times"

    def test_ctrl_z_applies_undo_once(self, win):
        calls = []
        original = win._smart_undo
        win._smart_undo = lambda: calls.append("undo")
        try:
            _send_ctrl_key(win.text_area, Qt.Key.Key_Z)
            _app.processEvents()
        finally:
            win._smart_undo = original
        assert len(calls) == 1, f"Ctrl+Z fired {len(calls)} times"

    def test_ctrl_i_applies_italic_once(self, win):
        calls = []
        original = win.apply_format
        win.apply_format = lambda fmt: calls.append(fmt)
        try:
            _send_ctrl_key(win.text_area, Qt.Key.Key_I)
            _app.processEvents()
        finally:
            win.apply_format = original
        assert calls.count("italic") == 1, f"Ctrl+I fired italic {calls.count('italic')} times"

    def test_ctrl_t_applies_strike_once(self, win):
        calls = []
        original = win.apply_format
        win.apply_format = lambda fmt: calls.append(fmt)
        try:
            _send_ctrl_key(win.text_area, Qt.Key.Key_T)
            _app.processEvents()
        finally:
            win.apply_format = original
        assert calls.count("strike") == 1, f"Ctrl+T fired strike {calls.count('strike')} times"
