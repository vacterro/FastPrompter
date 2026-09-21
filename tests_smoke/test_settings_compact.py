"""Settings determinism: the whole current tab, every launch, no scrolling.

T-1205 SETTINGS LAYOUT OVERRIDE supersedes the old E-1643 contract
("bounded settings scroll prevents editor overlap"): the embedded
Settings panel always shows the complete current tab, the editor yields
vertical room to Settings, and the same window geometry + same tab always
produces the same Settings geometry regardless of startup/open/close/
resize history.

    uv run pytest tests_smoke/test_settings_compact.py -q
"""

import os
import tempfile
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

_tmpdir = tempfile.mkdtemp(prefix="fastprompter_determinism_")


GEOMS = [(1150, 700), (1033, 679), (960, 600), (857, 600)]
EDITOR = 1
TYPOS_TITLE = "Typos"


@pytest.fixture(scope="module", autouse=True)
def _native_fonts():
    # The offscreen Windows plugin has no system font discovery. Load the
    # actual shipped UI font so geometry and screenshots match the desktop.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf",
                 "consola.ttf", "seguiemj.ttf"):
        path = fonts / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def _settle(win, width=None, height=None):
    """Run the event loop + the fitter until the layout stops moving."""
    if width is not None:
        win.resize(width, height)
    for _ in range(4):
        QApplication.processEvents()
        win._fit_settings_tabs()
    QTest.qWait(30)
    QApplication.processEvents()
    win._fit_settings_tabs()
    QApplication.processEvents()


def _open_settings(win, width=None, height=None):
    win._ensure_settings_built()
    win.is_locked = False
    win._locked_geometry = None
    win.mini_settings_frame.setVisible(True)
    win.show()
    _settle(win, width, height)


def _close_settings(win):
    win.mini_settings_frame.setVisible(False)
    QApplication.processEvents()


def _unlock(win):
    win.is_locked = False
    win._locked_geometry = None


def _capture(win):
    """The geometry contract: frame, tabs, page, deepest group, editor top."""
    page = win.settings_tabs.currentWidget()
    groups = page.findChildren(QWidget, "SettingsGroup")
    bottom = max((g.y() + g.height() for g in groups), default=0)
    return (win.settings_tabs.height(),
            win.mini_settings_frame.height(),
            page.height(),
            bottom,
            win.splitter.y())


def _assert_close(a, b, tol=2, ctx=""):
    assert len(a) == len(b) and len(a) == 5
    for i, (x, y) in enumerate(zip(a, b)):
        assert abs(x - y) <= tol, f"{ctx} metric[{i}]: {x} != {y} ({a} vs {b})"


def _assert_no_overlap(win):
    """E: the frame never overlaps the editor — where the window can fit it.

    Section 9 of the override: if the physical height genuinely cannot
    hold header + full Settings + minimum editor, the overflow is
    recorded, not papered over with a new budget or scrollbar.
    """
    frame = win.mini_settings_frame
    ml = win.main_layout
    margins = ml.contentsMargins()
    header_h = ml.itemAt(0).geometry().height()
    needed = (margins.top() + margins.bottom() + ml.spacing() * 2
              + header_h + frame.minimumHeight()
              + win.splitter.minimumSizeHint().height())
    frame_bottom = frame.geometry().bottom()
    if needed <= win.height():
        assert frame_bottom < win.splitter.y(), (
            frame_bottom, win.splitter.y(), frame.geometry())
    else:
        # Recorded physical overflow: full Settings simply does not fit.
        # The internal contract (complete page, no internal scrolling)
        # still holds — only the window edge clips it.
        print(f"SETTINGS PHYSICAL OVERFLOW: need {needed}px, "
              f"window {win.height()}px — recorded, not solved")
        assert frame.minimumHeight() == frame.maximumHeight()


def _assert_no_internal_scroll(win):
    assert not hasattr(win, "settings_scroll"), "fake-fixed scroll wrapper back"
    assert win.findChild(QScrollArea, "SettingsScroll") is None
    assert win.mini_settings_frame.findChild(QScrollArea) is None
    assert win.settings_tabs.parentWidget() is win.mini_settings_frame


# --------------------------------------------------------------- A: no scroll

def test_settings_has_no_scroll_wrapper(win):
    _open_settings(win)
    _assert_no_internal_scroll(win)


# ------------------------------------------- B/C/D: every tab fits, fully seen

@pytest.mark.parametrize("size", GEOMS)
@pytest.mark.parametrize("tab", range(4))
def test_every_group_fits_inside_its_page(win, size, tab):
    _open_settings(win)
    try:
        win.resize(*size)
        win.settings_tabs.setCurrentIndex(tab)
        _settle(win)
        _assert_no_internal_scroll(win)
        page = win.settings_tabs.currentWidget()
        groups = page.findChildren(QWidget, "SettingsGroup")
        assert groups, "a tab without groups cannot be organised"
        for g in groups:
            origin = g.mapTo(page, QPoint())
            assert origin.x() >= 0 and origin.y() >= 0, (tab, origin)
            assert origin.x() + g.width() <= page.width() + 1, (
                win.settings_tabs.tabText(tab), g)
            assert origin.y() + g.height() <= page.height() + 1, (
                win.settings_tabs.tabText(tab), origin.y() + g.height(),
                page.height())
            needed = g.heightForWidth(g.width())
            assert g.height() >= needed - 1, (
                win.settings_tabs.tabText(tab), g.height(), needed)
        _assert_no_overlap(win)
    finally:
        win.mini_settings_frame.setVisible(False)


@pytest.mark.parametrize("tab", range(4))
def test_editor_full_content_at_1033x679(win, tab):
    """C + D: at the user's real geometry nothing needs ensureWidgetVisible."""
    _open_settings(win, 1033, 679)
    try:
        win.settings_tabs.setCurrentIndex(tab)
        _settle(win)
        page = win.settings_tabs.currentWidget()
        groups = page.findChildren(QWidget, "SettingsGroup")
        assert groups
        for g in groups:
            r = g.visibleRegion().boundingRect()
            assert r.height() >= g.height(), (
                win.settings_tabs.tabText(tab), g, r,
                "group clipped — would need ensureWidgetVisible")
        _assert_no_overlap(win)
        if tab == EDITOR:
            titles = []
            for g in groups:
                labels = g.findChildren(QWidget)
                texts = [w.text() for w in labels
                         if hasattr(w, "text") and w.text()]
                titles.append(" ".join(texts))
            assert any(TYPOS_TITLE in t for t in titles), titles
            typos = next(g for g, t in zip(groups, titles)
                         if TYPOS_TITLE in t)
            assert typos.y() + typos.height() <= page.height()
            assert typos.visibleRegion().boundingRect().height() >= typos.height()
    finally:
        win.mini_settings_frame.setVisible(False)
        win.resize(1400, 700)


# --------------------------------- determinism: same geometry, same layout

def _lifecycle_path_metrics(win, path):
    """Drive one lifecycle to a final 1033x679 Editor state and measure it."""
    _unlock(win)
    win.settings_tabs.setCurrentIndex(EDITOR)
    if path == "A":            # create/show -> open Settings -> select Editor
        _open_settings(win, 1033, 679)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
    elif path == "B":          # start with Settings already open
        win.mini_settings_frame.setVisible(True)
        win.show()
        QApplication.processEvents()
        win.resize(1033, 679)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
    elif path == "C":          # open -> close -> reopen
        _open_settings(win, 1033, 679)
        _close_settings(win)
        _open_settings(win)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
    elif path == "D":          # tab wander ending back on Editor
        _open_settings(win, 1033, 679)
        for idx in (0, EDITOR, 2, 3, EDITOR):
            win.settings_tabs.setCurrentIndex(idx)
            _settle(win)
    elif path == "E":          # resize wide -> narrow -> target
        _open_settings(win, 1400, 679)
        _settle(win, 800, 679)
        _settle(win, 1033, 679)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
    elif path == "F":          # resize narrow -> wide -> target
        _open_settings(win, 800, 679)
        _settle(win, 1400, 679)
        _settle(win, 1033, 679)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
    else:
        raise AssertionError(f"unknown path {path}")
    metrics = _capture(win)
    _assert_no_internal_scroll(win)
    page = win.settings_tabs.currentWidget()
    bottom = metrics[3]
    assert bottom <= page.height() + 1, (path, bottom, page.height())
    _assert_no_overlap(win)
    return metrics


def test_same_geometry_same_settings_layout_after_every_lifecycle(win, fresh_win):
    """The headline regression: history must not change the layout."""
    shared = win
    baselines = {}
    for path in ("A", "C", "D", "E", "F"):
        try:
            baselines[path] = _lifecycle_path_metrics(shared, path)
        finally:
            _close_settings(shared)
            shared.settings_tabs.setCurrentIndex(EDITOR)
            shared.resize(1400, 700)
    # B: a second, untouched window that opens with Settings already visible.
    baselines["B"] = _lifecycle_path_metrics(fresh_win, "B")
    reference = baselines["A"]
    for path in ("B", "C", "D", "E", "F"):
        _assert_close(baselines[path], reference, ctx=f"path {path}")


def test_repeated_open_close_always_shows_full_editor(win):
    """20 open/close rounds at 1033x679: never once clipped, never shorter."""
    _unlock(win)
    win.settings_tabs.setCurrentIndex(EDITOR)
    win.resize(1033, 679)
    QApplication.processEvents()
    baseline = None
    try:
        for i in range(20):
            _open_settings(win)
            win.settings_tabs.setCurrentIndex(EDITOR)
            _settle(win)
            metrics = _capture(win)
            page = win.settings_tabs.currentWidget()
            groups = page.findChildren(QWidget, "SettingsGroup")
            assert groups
            for g in groups:
                assert g.visibleRegion().boundingRect().height() >= g.height(), (
                    i, g, "clipped viewport")
            frame_bottom = win.mini_settings_frame.geometry().bottom()
            assert frame_bottom < win.splitter.y(), (i, frame_bottom)
            if baseline is None:
                baseline = metrics
            else:
                _assert_close(metrics, baseline, ctx=f"iteration {i}")
            _close_settings(win)
            QApplication.processEvents()
    finally:
        win.resize(1400, 700)


def test_tab_height_follows_content_not_window(win):
    """Settings height = f(current tab, current width) — never the budget.

    Shorter content must shrink the frame, taller must grow it, and a
    narrower width must wrap more and grow taller.
    """
    _open_settings(win, 1033, 679)
    try:
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
        editor_frame = win.mini_settings_frame.height()
        win.settings_tabs.setCurrentIndex(2)   # Clock: clearly less content
        _settle(win)
        clock_frame = win.mini_settings_frame.height()
        assert clock_frame < editor_frame, (clock_frame, editor_frame)
        win.settings_tabs.setCurrentIndex(EDITOR)
        _settle(win)
        assert win.mini_settings_frame.height() == editor_frame
        # width reflow: narrower -> FlowLayout wraps more -> frame taller
        _settle(win, 857, 679)
        narrow_frame = win.mini_settings_frame.height()
        assert narrow_frame >= editor_frame, (narrow_frame, editor_frame)
        _settle(win, 1033, 679)
        assert win.mini_settings_frame.height() == editor_frame
    finally:
        _close_settings(win)
        win.resize(1400, 700)


def test_empty_editor_does_not_leave_blank_header_counters(win):
    saved = win.text_area.toPlainText()
    tokens = win.data.get("show_token_count", "False")
    win.data["show_token_count"] = "True"
    win.resize(1400, 700)
    win.show()
    try:
        win.text_area.setPlainText("A readable line with enough words for tokens")
        win._update_line_count_label()
        win._apply_topbar_visibility()
        assert not win.lbl_line_count.isHidden()
        assert not win.lbl_token_count.isHidden()
        win.text_area.clear()
        win._update_line_count_label()
        win._apply_topbar_visibility()
        assert win.lbl_line_count.isHidden()
        assert win.lbl_token_count.isHidden()
        assert win._counter_sep.isHidden()
        win.text_area.setPlainText("Counters return when text returns")
        win._update_line_count_label()
        assert not win.lbl_line_count.isHidden()
        assert not win.lbl_token_count.isHidden()
    finally:
        win.data["show_token_count"] = tokens
        win.text_area.setPlainText(saved)
        win._update_line_count_label()
        win._apply_topbar_visibility()
