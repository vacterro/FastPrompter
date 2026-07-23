"""The settings panel is grouped, and it uses the width it has.

Reported as messy: unrelated switches side by side, and stripes of dead
panel on the right. Measured before the change - the Clock tab filled 449px
of 956, and "Always on Top" sat next to "Silo Color Box" and the cursor
buttons in one undifferentiated flow.

    uv run pytest tests_smoke/test_settings_layout.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_layout_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"l_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.data["hide_extra"] = "False"
    w.mini_settings_frame.setVisible(True)
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()


def _groups(win, index):
    win.settings_tabs.setCurrentIndex(index)
    _app.processEvents()
    win._fit_settings_tabs(index)
    _app.processEvents()
    return win.settings_tabs.widget(index).findChildren(QWidget, "SettingsGroup")


def _title(box):
    labels = box.findChildren(QLabel)
    return getattr(labels[0], "_en_text", labels[0].text()) if labels else ""


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_every_tab_is_split_into_titled_groups(win, index):
    boxes = _groups(win, index)
    assert len(boxes) >= 2, "a tab of loose controls is the mess this replaced"
    for box in boxes:
        assert _title(box).strip(), "a group with no title says nothing"


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_the_groups_reach_the_right_hand_edge(win, index):
    """The dead stripe: Clock used to stop at 449px of 956."""
    boxes = _groups(win, index)
    page = win.settings_tabs.widget(index)
    rightmost = max(b.geometry().right() for b in boxes)
    assert rightmost >= page.width() - 24, (
        f"{page.width() - rightmost}px of empty panel on the right")


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_no_group_towers_over_the_others(win, index):
    """One 186px column beside 49px stubs is the ragged look reported."""
    heights = [b.height() for b in _groups(win, index)]
    assert max(heights) <= max(120, min(heights) * 4), heights


def test_related_switches_ended_up_together(win):
    """Window behaviour is not mixed with silo looks or cursor buttons."""
    by_title = {_title(b): b for b in _groups(win, 0)}
    assert "Window behaviour" in by_title
    assert "Mouse cursors" in by_title

    def texts(box):
        return " ".join(w.text() for w in box.findChildren(QWidget)
                        if hasattr(w, "text"))

    behaviour = texts(by_title["Window behaviour"])
    assert "Always on Top" in behaviour
    assert "Color Box" not in behaviour, "silo look leaked into window behaviour"
    assert "Copy my set" not in behaviour, "cursor buttons leaked in"


def test_the_panel_still_hugs_its_content(win):
    """Spare height belongs to the editor, not to the settings panel."""
    tallest = 0
    for i in range(win.settings_tabs.count()):
        _groups(win, i)
        tallest = max(tallest, win.mini_settings_frame.height())
    assert tallest < 400, tallest
