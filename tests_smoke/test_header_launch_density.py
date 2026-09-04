import os
import sys
import tempfile
import pytest
from PyQt6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_app = QApplication.instance() or QApplication.instance() or QApplication(sys.argv)
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_launch_")

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

@pytest.fixture
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"test_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    FastPrompter._init_limit_service = lambda self: None

    w = FastPrompter()
    yield w

    w.close()


def test_cat_numbox_has_fixed_size(win):
    """cat_numbox must have explicit fixed width and height so it cannot be squished by QHBoxLayout."""
    win.show()
    _app.processEvents()

    cats = win.visible_categories()
    expected_w = len(cats) * win.numbox_button_size() + max(0, len(cats) - 1) * 1
    assert win.cat_numbox.minimumWidth() == expected_w
    assert win.cat_numbox.width() == expected_w


def test_header_settles_spacious_on_launch_without_ctrl_q(win):
    """Header priority fit must shed optional widgets on initial launch, matching Screen 2 without Ctrl+Q."""
    win.data["cats_order"] = [f"Cat {i}" for i in range(1, 9)]
    win.rebuild_cat_combo()
    win.resize(900, 679)
    win.show()
    _app.processEvents()

    # Right on launch, cat_numbox must be roomy and buttons un-squished
    assert win.cat_numbox.width() == 183
    assert win.btn_new.width() >= 40
    assert win.btn_save.width() >= 50

    # Optional items on right must be dropped so main toolbar is spacious
    hidden = getattr(win, "_priority_fit_hidden", ())
    assert "btn_settings_toggle_right" in hidden
    assert "lbl_line_count" in hidden
