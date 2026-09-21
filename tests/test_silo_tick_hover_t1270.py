"""T-1270 — the SILO done/tick hover affordance contract.

The operator's report
---------------------
The silo checkbox/tick affordance can fail to appear under the cursor; it often
shows up only after moving the mouse away and back over the silo. That is not a
matter of taste: a row can be under the pointer while it is *painted* as if it
were not.

The root cause this suite pins
------------------------------
``DraggableSiloButton.update_data()`` (the refresh path used by
``refresh_temp_presets``, reorder, rebind, setting toggles and
selection/pin/tick changes) ends by calling ``_apply_tick_state(is_ticked)``.
For a row that is hovered but not itself ticked that paints the tick column
BLANK -- while ``_update_hover_buttons()``, the only code that ever painted the
✅, runs exclusively from the 80 ms timer started by ``enterEvent``. Changing
row state does not synthesize a new enterEvent, so the row stayed blank under a
stationary cursor until the pointer left and came back. Every test below that
says "under the cursor" reproduces exactly that sequence.

The contract
------------
* the done/tick control and the non-destructive hover state are IMMEDIATE --
  the 80 ms reveal is kept only for the destructive archive button;
* after every refresh, ``underMouse()`` and the visible hover state agree;
* enabling ticks, ticking a row, or repinning it while the pointer is already
  over the row must not require a leave/re-enter ritual;
* the tick column is reserved, so nothing about the row moves when the mark
  appears (geometry guard).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QApplication, QWidget

import fastprompter.ui.snippet_panel as snippet_panel
from fastprompter.ui.snippet_panel import DraggableSiloButton

_APP = QApplication.instance() or QApplication([])

TICK = "\u2705"


class MockMainWindow(QWidget):
    """The smallest owner ``DraggableSiloButton`` can be bound to."""

    def __init__(self):
        super().__init__()
        self._current_lang = "EN"
        self.data = {
            "theme": "Default",
            "silo_ticked": [],
            "silo_ticks_enabled": "False",
            "silo_color_box": "True",
            "silo_colors": {},
            "bold_hash_titles": "False",
            "target_editor": "auto",
        }
        self.dirty = 0
        self.refreshes = 0

    def _silo_sel(self):
        return getattr(self, "selection", set())

    def _toggle_tick_silo(self, idx):
        ticked = self.data["silo_ticked"]
        if idx in ticked:
            ticked.remove(idx)
        else:
            ticked.append(idx)
        self.mark_dirty()

    def mark_dirty(self, domain=None):
        self.dirty += 1

    def refresh_temp_presets(self):
        self.refreshes += 1


@pytest.fixture(autouse=True)
def _probe_off_unless_a_test_says_otherwise():
    """Headless Qt reports a meaningless cursor position; keep it out of the way."""
    original = DraggableSiloButton._STATIONARY_POINTER_PROBE
    DraggableSiloButton._STATIONARY_POINTER_PROBE = False
    try:
        yield
    finally:
        DraggableSiloButton._STATIONARY_POINTER_PROBE = original


@pytest.fixture(autouse=True)
def pointer(monkeypatch):
    """The platform's pointer-over-this-row state, supplied explicitly.

    The offscreen platform has no mouse and sets WA_UnderMouse on show, so
    ``underMouse()`` there is an artifact of the test platform, not input.
    Because the production hover contract is decided from exactly this query
    (plus the stationary-cursor probe), the test supplies the input state
    instead of pretending the platform has one -- nothing in the code under
    test is stubbed.
    """
    state = {"over": False}
    monkeypatch.setattr(DraggableSiloButton, "underMouse",
                        lambda self: state["over"])
    return state


@pytest.fixture
def win():
    w = MockMainWindow()
    return w


@pytest.fixture
def btn(win):
    b = DraggableSiloButton(win)
    b.global_idx = 0
    # A fixed width is what the real sidebar gives the row, and it is what makes
    # "nothing moved" a meaningful assertion: hover must paint into a column
    # that is already reserved, never resize the row.
    b.setFixedWidth(220)
    b.move(400, 400)
    b.show()
    _APP.processEvents()
    return b


def _refresh(btn, fcount=0, is_pinned=False, is_child=False,
             has_children=False, is_collapsed=False, line_count="12"):
    """One ordinary row refresh, exactly as the panel issues it."""
    btn.update_data(
        "Alpha silo", 0, "#101010", font_family="Verdana", scale=1.0,
        line_count_str=line_count, is_pushed=False, title_bold=False,
        is_child=is_child, fcount=fcount, has_children=has_children,
        is_collapsed=is_collapsed, has_hash=False, color_hex="",
        is_pinned=is_pinned)
    _APP.processEvents()


def _enter(btn):
    """Real enter handlers, the way the platform delivers them."""
    btn.enterEvent(QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(40, 40)))
    _APP.processEvents()


def _leave(btn):
    btn.leaveEvent(QEvent(QEvent.Type.Leave))
    _APP.processEvents()


def _tick_visible(btn):
    return btn._btn_tick.isVisible() and btn._btn_tick.text() == TICK


# ---------------------------------------------------------------------------
# A. one enter is enough
# ---------------------------------------------------------------------------

class TestEnterOnce:
    def test_enter_once_reveals_the_tick(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        assert not _tick_visible(btn)          # at rest the column is blank
        _enter(btn)
        assert _tick_visible(btn)

    def test_enter_reveals_the_tick_without_waiting_for_the_delay(self, win, btn):
        """The tick is IMMEDIATE: no 80 ms hunt for a checkbox."""
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        assert _tick_visible(btn)
        assert btn._hover_delay_elapsed is False   # timer has not fired yet
        assert btn._btn_archive.isHidden()         # only the archive waits

    def test_the_delayed_reveal_still_guards_only_the_archive_button(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        assert btn._btn_pin.isVisible()
        assert btn._btn_archive.isHidden()
        btn._update_hover_buttons()                # the timer slot fires
        assert btn._btn_archive.isVisible()
        assert _tick_visible(btn)

    def test_leave_restores_the_rest_presentation(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        assert btn._lbl_count.isHidden()
        _leave(btn)
        assert not _tick_visible(btn)
        assert btn._btn_pin.isHidden()
        assert btn._btn_archive.isHidden()
        assert btn._lbl_count.isVisible()


# ---------------------------------------------------------------------------
# B. refresh under a stationary cursor
# ---------------------------------------------------------------------------

class TestStationaryCursorRefresh:
    def test_refresh_while_hovered_keeps_the_tick_visible(self, win, btn):
        """RED before the repair: update_data blanked the tick column."""
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        assert _tick_visible(btn)

        _refresh(btn, line_count="99")             # row state changes, no re-enter
        assert _tick_visible(btn)
        assert btn._hover_showing is True

    def test_refresh_while_hovered_keeps_the_non_destructive_controls(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn, fcount=4)
        _enter(btn)
        _refresh(btn, fcount=5)                    # files count changed under cursor
        assert btn._btn_pin.isVisible()
        assert btn._btn_files.isVisible()
        assert btn._lbl_count.isHidden()
        assert _tick_visible(btn)

    def test_enabling_ticks_while_under_the_cursor_needs_no_re_enter(self, win, btn):
        _refresh(btn)                              # feature OFF: no tick column
        _enter(btn)
        assert btn._btn_tick.isHidden()

        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)                              # the setting toggle refreshes rows
        assert _tick_visible(btn)
        assert btn._hover_showing is True

    def test_ticking_the_silo_under_the_cursor_shows_the_mark_immediately(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        win._toggle_tick_silo(0)                   # the real toggle
        _refresh(btn)
        assert _tick_visible(btn)

    def test_a_row_appearing_under_a_stationary_cursor_is_hover_dressed(
            self, win, btn, monkeypatch):
        """The pointer never moved, yet the row IS under it."""
        DraggableSiloButton._STATIONARY_POINTER_PROBE = True
        win.data["silo_ticks_enabled"] = "True"
        inside = btn.mapToGlobal(QPoint(3, 3))
        monkeypatch.setattr(snippet_panel.QCursor, "pos",
                            staticmethod(lambda: inside))
        assert btn._pointer_is_over_row() is True
        _refresh(btn)
        assert _tick_visible(btn)                  # revealed without a re-enter
        assert btn.underMouse() is False or btn._hover_showing is True

    def test_the_geometry_probe_stops_making_things_up_when_disabled(
            self, win, btn, monkeypatch):
        DraggableSiloButton._STATIONARY_POINTER_PROBE = False
        inside = btn.mapToGlobal(QPoint(3, 3))
        monkeypatch.setattr(snippet_panel.QCursor, "pos",
                            staticmethod(lambda: inside))
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        assert btn._pointer_is_over_row() is False
        assert not _tick_visible(btn)


# ---------------------------------------------------------------------------
# C. ON -> OFF removes only the hover control
# ---------------------------------------------------------------------------

class TestTickSettingTransitions:
    def test_on_to_off_removes_the_hover_control_only(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        _enter(btn)
        assert _tick_visible(btn)

        win.data["silo_ticks_enabled"] = "False"
        _refresh(btn)                              # still hovered
        assert not _tick_visible(btn)
        assert btn._btn_tick.isHidden()            # column reclaimed, no blank gap
        assert btn._hover_showing is True          # hover itself survives

    def test_a_ticked_silo_stays_ticked_after_the_pointer_leaves(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        win.data["silo_ticked"] = [0]
        _refresh(btn)
        _enter(btn)
        _leave(btn)
        assert _tick_visible(btn)                  # persisted mark, not a hover

    def test_a_ticked_silo_keeps_its_mark_with_the_feature_off(self, win, btn):
        win.data["silo_ticked"] = [0]
        win.data["silo_ticks_enabled"] = "False"
        _refresh(btn)
        assert _tick_visible(btn)                  # Ctrl+Shift+click can set it
        _enter(btn)
        assert _tick_visible(btn)
        _leave(btn)
        _refresh(btn)
        assert _tick_visible(btn)


# ---------------------------------------------------------------------------
# D. no layout movement
# ---------------------------------------------------------------------------

class TestNoLayoutShift:
    def test_revealing_the_tick_moves_nothing(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn, fcount=2)
        _leave(btn)
        before = (btn._lbl_text.x(), btn.width(), btn.height(),
                  btn.sizeHint().height())
        _enter(btn)
        assert _tick_visible(btn)
        assert btn._btn_files.isVisible()
        after = (btn._lbl_text.x(), btn.width(), btn.height(),
                 btn.sizeHint().height())
        assert after == before, "hover must not move the title or the row"

    def test_the_tick_column_is_reserved_on_every_reachable_row(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        assert btn._tick_column_reserved() is True
        assert btn._btn_tick.isVisible()           # occupied (blank) at rest
        assert btn._btn_tick.text() == ""

    def test_a_row_that_can_never_show_a_tick_keeps_no_gap(self, win, btn):
        win.data["silo_ticks_enabled"] = "False"
        _refresh(btn)
        assert btn._tick_column_reserved() is False
        assert btn._btn_tick.isHidden()


# ---------------------------------------------------------------------------
# E. neighbours keep their behaviour
# ---------------------------------------------------------------------------

class TestNeighbourAffordances:
    def test_files_count_keeps_the_button_at_rest(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn, fcount=3)
        assert btn._btn_files.isVisible()
        assert "3" in btn._btn_files.text()
        _enter(btn)
        assert btn._btn_files.isVisible()

    def test_empty_row_reveals_the_files_button_only_on_hover(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn, fcount=0)
        assert btn._btn_files.isHidden()
        _enter(btn)
        assert btn._btn_files.isVisible()

    def test_pin_stays_visible_only_when_pinned_or_hovered(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn, is_pinned=False)
        assert btn._btn_pin.isHidden()
        _enter(btn)
        assert btn._btn_pin.isVisible()
        _leave(btn)
        assert btn._btn_pin.isHidden()

        _refresh(btn, is_pinned=True)
        assert btn._btn_pin.isVisible()
        _enter(btn)
        _leave(btn)
        assert btn._btn_pin.isVisible()

    def test_archive_rows_never_hover_dress(self, win):
        b = DraggableSiloButton(win, is_archive=True)
        b.global_idx = 0
        b.resize(220, b.sizeHint().height())
        b.show()
        _APP.processEvents()
        _refresh(b)
        b.enterEvent(QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(40, 40)))
        _APP.processEvents()
        assert b._pointer_is_over_row() is False
        assert b._btn_tick.isHidden()
        assert b._btn_archive.isHidden()


# ---------------------------------------------------------------------------
# F. the pointer state and the painted state agree
# ---------------------------------------------------------------------------

class TestPointerAgreement:
    def test_under_mouse_agrees_with_the_visible_hover_state(self, win, btn,
                                                             pointer):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        assert btn._pointer_is_over_row() is False
        assert not _tick_visible(btn)

        pointer["over"] = True
        _refresh(btn)                     # refresh while the pointer is over it
        assert btn.underMouse() is True
        assert btn._pointer_is_over_row() is True
        assert btn._btn_pin.isVisible()
        assert _tick_visible(btn)
        assert btn._lbl_count.isHidden()

        pointer["over"] = False
        _refresh(btn)
        assert btn.underMouse() is False
        assert not _tick_visible(btn)
        assert btn._lbl_count.isVisible()

    def test_a_platform_enter_event_still_drives_the_same_state(self, win, btn):
        from PyQt6.QtTest import QTest
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        QTest.mouseMove(btn, QPoint(5, 5))
        _APP.processEvents()
        if not btn._hover_showing:
            pytest.skip("this Qt platform does not synthesize Enter on mouseMove")
        assert btn._pointer_is_over_row() is True
        assert btn._btn_pin.isVisible()
        assert _tick_visible(btn)

    def test_leave_then_enter_round_trips(self, win, btn):
        win.data["silo_ticks_enabled"] = "True"
        _refresh(btn)
        for _ in range(3):
            _enter(btn)
            assert _tick_visible(btn)
            _leave(btn)
            assert not _tick_visible(btn)
