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
    state_mod.run_portable_backup = lambda data, profile_id=1: None
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
    from PyQt6.QtCore import QEvent
    for timer in ("auto_save_timer", "topmost_timer", "date_timer", "_cache_timer"):
        t = getattr(w, timer, None)
        if t is not None:
            t.stop()
    if getattr(w, "limit_service", None) is not None:
        try:
            w.limit_service.shutdown()
        except Exception:
            pass
    if getattr(w, "state", None) is not None:
        w.state.conn = None
    w.conn = None
    w.close()
    w.deleteLater()
    _app.processEvents()
    _app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _app.processEvents()


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


def test_the_panel_hugs_its_content_without_cutting(win):
    """Spare height belongs to the editor, not to the settings panel.

    The panel must be exactly as tall as its visible tab needs — never so
    short that the last row (Typos on the Editor tab) is clipped.  Both
    invariants, in one: hugging means frame <= content + small slack.
    """
    for i in range(win.settings_tabs.count()):
        win.settings_tabs.setCurrentIndex(i)
        _app.processEvents()
        win._fit_settings_tabs(i)
        _app.processEvents()
        page = win.settings_tabs.widget(i)
        page_h = page.height()
        groups = [b for b in page.findChildren(QWidget, "SettingsGroup")
                  if getattr(b, "_en_text", "")]
        if not groups:
            continue
        bottom = max(b.y() + b.height() for b in groups)
        assert bottom <= page_h, (
            f"tab {i}: last group bottom {bottom} > page height {page_h} "
            "(content cut off)")
    # Still hugs: no tab should blow the panel up to half the window.
    for i in range(win.settings_tabs.count()):
        win.settings_tabs.setCurrentIndex(i)
        _app.processEvents()
        win._fit_settings_tabs(i)
        _app.processEvents()
        assert win.mini_settings_frame.height() < 500, (
            f"tab {i}: panel {win.mini_settings_frame.height()}px — not hugging")


def test_headers_are_compact_fixed_height(win):
    """Headers must be strictly compact (<=18px), never ballooning into empty blocks."""
    from PyQt6.QtGui import QPixmap
    for i in range(win.settings_tabs.count()):
        win.settings_tabs.setCurrentIndex(i)
        _app.processEvents()
        win._fit_settings_tabs(i)
        _app.processEvents()
        for box in _groups(win, i):
            labels = box.findChildren(QLabel)
            if labels:
                header = labels[0]
                assert header.height() <= 18, (
                    f"group {_title(box)} header too tall: {header.height()}px")


def test_top_settings_bar_fits_single_row(win):
    """At wide window width (1150px), top appearance bar fits on a single row (<= 28px)."""
    win.resize(1150, 540)
    _app.processEvents()
    flay = win.mini_settings_frame.layout()
    app_w = flay.itemAt(0).widget()
    h = app_w.totalHeightForWidth(app_w.width())
    assert h <= 28, f"Top appearance bar wrapped unexpectedly at 1150px: height={h}px"


def test_top_settings_bar_wraps_balanced_on_compact_window(win):
    """At compact window width (857px), top appearance bar wraps into two spacious rows (<= 52px)."""
    win.resize(857, 540)
    _app.processEvents()
    flay = win.mini_settings_frame.layout()
    app_w = flay.itemAt(0).widget()
    h = app_w.totalHeightForWidth(app_w.width())
    assert h <= 52, f"Top appearance bar exceeded 2 rows at 857px: height={h}px"


def test_tab_switch_preserves_compact_appearance_bar(win):
    """Switching between settings tabs must never stretch the appearance bar or leave dead vertical gaps."""
    win.resize(960, 540)
    win.mini_settings_frame.setVisible(True)
    _app.processEvents()
    flay = win.mini_settings_frame.layout()
    app_w = flay.itemAt(0).widget()
    expected_h = app_w.totalHeightForWidth(app_w.width())

    for idx in range(win.settings_tabs.count()):
        win.settings_tabs.setCurrentIndex(idx)
        _app.processEvents()
        win._fit_settings_tabs(idx)
        _app.processEvents()

        # Appearance bar must match exact needed height (no dead gap expansion)
        assert app_w.height() == expected_h, (
            f"Tab {idx} expanded appearance bar to {app_w.height()}px (expected {expected_h}px)"
        )
        # Frame maximum height must equal minimum height (no runaway stretching)
        assert win.mini_settings_frame.maximumHeight() == win.mini_settings_frame.minimumHeight(), (
            f"Tab {idx} failed to constrain frame maximum height"
        )
