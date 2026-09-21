"""Tests for Silo Color Box Ctrl+MiddleButton gesture (contracts A through N)."""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QCheckBox, QWidget

from fastprompter.core.state import bind_active_category
from fastprompter.ui.snippet_panel import DraggableSiloButton

_APP = QApplication.instance() or QApplication([])


def _mouse(kind, mods, button=Qt.MouseButton.MiddleButton):
    return QMouseEvent(kind, QPoint(5, 5).toPointF(), button, button, mods)


class MockMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {
            "silo_colors": {},
            "silo_colors_all": {"Default": {}},
            "silo_color_palette": ["#ff4444", "#ffaa00", "#ffff00", "#00ff00", "#00ffff", ""],
            "silo_color_box": "True",
            "bold_hash_titles": "True",
            "active_tab": "Default",
            "theme": "Default",
        }
        self.data["silo_colors"] = self.data["silo_colors_all"]["Default"]
        self.dirty = False
        self.refreshed = False
        self.trashed = []
        self.cleared = []
        self.cb_silo_color_box = QCheckBox()
        self.cb_silo_color_box.setChecked(True)

    def mark_dirty(self, domain=None):
        self.dirty = True

    def refresh_temp_presets(self):
        self.refreshed = True

    def trash_silo(self, idx, is_archive=False):
        self.trashed.append((idx, is_archive))

    def clear_silo(self, idx, is_archive=False):
        self.cleared.append((idx, is_archive))


@pytest.fixture
def dummy_win():
    return MockMainWindow()


@pytest.fixture
def silo_btn(dummy_win):
    b = DraggableSiloButton(dummy_win)
    b.global_idx = 0
    return b


class TestSiloColorGesture:
    # A. Ctrl+MiddleButton on uncolored silo:
    #    => silo_colors[index] becomes one valid palette color
    #    => trash_silo not called
    #    => clear_silo not called
    def test_a_ctrl_middle_on_uncolored_silo_assigns_valid_palette_color(self, dummy_win, silo_btn):
        ctrl = Qt.KeyboardModifier.ControlModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        color = dummy_win.data["silo_colors"].get("0")
        assert color, "Color should have been assigned"
        assert color in ["#ff4444", "#ffaa00", "#ffff00", "#00ff00", "#00ffff"]
        assert color != "", "Empty entries in palette must be excluded"
        assert not dummy_win.trashed
        assert not dummy_win.cleared
        assert dummy_win.dirty
        assert dummy_win.refreshed

    # B. Ctrl+MiddleButton on colored silo:
    #    => silo_colors[index] becomes ""
    #    => trash_silo not called
    #    => clear_silo not called
    def test_b_ctrl_middle_on_colored_silo_removes_color(self, dummy_win, silo_btn):
        dummy_win.data["silo_colors"]["0"] = "#ff4444"
        ctrl = Qt.KeyboardModifier.ControlModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        assert dummy_win.data["silo_colors"].get("0") == ""
        assert not dummy_win.trashed
        assert not dummy_win.cleared

    # C. Patch random.choice deterministically:
    #    => expected palette color assigned
    def test_c_patch_random_choice_deterministic(self, dummy_win, silo_btn):
        ctrl = Qt.KeyboardModifier.ControlModifier
        with patch("random.choice", return_value="#00ff00"):
            silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        assert dummy_win.data["silo_colors"].get("0") == "#00ff00"

    # D. Ctrl+MiddleButton:
    #    patch trash_silo to raise AssertionError
    #    => gesture completes without invoking it
    def test_d_trash_silo_raising_assertion_error_is_never_reached(self, dummy_win, silo_btn):
        ctrl = Qt.KeyboardModifier.ControlModifier
        dummy_win.trash_silo = lambda *args, **kwargs: pytest.fail("trash_silo called on Ctrl+Middle")
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        assert dummy_win.data["silo_colors"].get("0")

    # E. Ctrl+MiddleButton:
    #    patch clear_silo to raise AssertionError
    #    => gesture completes without invoking it
    def test_e_clear_silo_raising_assertion_error_is_never_reached(self, dummy_win, silo_btn):
        ctrl = Qt.KeyboardModifier.ControlModifier
        dummy_win.clear_silo = lambda *args, **kwargs: pytest.fail("clear_silo called on Ctrl+Middle")
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        assert dummy_win.data["silo_colors"].get("0")

    # F. Plain MiddleButton:
    #    => existing trash behavior remains unchanged
    def test_f_plain_middle_button_trashes_silo(self, dummy_win, silo_btn):
        none = Qt.KeyboardModifier.NoModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, none))
        assert dummy_win.trashed == [(0, False)]
        assert not dummy_win.cleared

    # G. Shift+MiddleButton:
    #    => existing clear behavior remains unchanged
    def test_g_shift_middle_button_clears_silo(self, dummy_win, silo_btn):
        shift = Qt.KeyboardModifier.ShiftModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, shift))
        assert dummy_win.cleared == [(0, False)]
        assert not dummy_win.trashed

    # H. Ctrl+Shift+MiddleButton:
    #    => no destructive action
    def test_h_ctrl_shift_middle_button_is_safe_noop(self, dummy_win, silo_btn):
        ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl_shift))
        assert not dummy_win.trashed
        assert not dummy_win.cleared
        assert dummy_win.data["silo_colors"].get("0") is None

    # I. Rapid Ctrl+MiddleButton press/double-click routing:
    #    => add
    #    => remove
    #    => no trash call
    def test_i_rapid_press_double_click_routing(self, dummy_win, silo_btn):
        ctrl = Qt.KeyboardModifier.ControlModifier
        # 1st press: add
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        color1 = dummy_win.data["silo_colors"].get("0")
        assert color1

        # 2nd press (delivered by Qt as MouseButtonDblClick): remove
        silo_btn.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, ctrl))
        assert dummy_win.data["silo_colors"].get("0") == ""

        # 3rd press: add again
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))
        assert dummy_win.data["silo_colors"].get("0")

        assert not dummy_win.trashed
        assert not dummy_win.cleared

    # J. Project alias persistence:
    #    set random color
    #    switch project
    #    switch back
    #    => original project's silo color remains attached to the correct slot
    def test_j_project_alias_persistence(self, dummy_win, silo_btn):
        dummy_win.data["silo_colors_all"] = {"A": {}, "B": {}}
        bind_active_category(dummy_win.data, "A")
        ctrl = Qt.KeyboardModifier.ControlModifier

        with patch("random.choice", return_value="#ff4444"):
            silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))

        assert dummy_win.data["silo_colors_all"]["A"]["0"] == "#ff4444"

        # Switch to project B
        bind_active_category(dummy_win.data, "B")
        assert dummy_win.data["silo_colors"].get("0") is None

        # Switch back to A
        bind_active_category(dummy_win.data, "A")
        assert dummy_win.data["silo_colors"].get("0") == "#ff4444"

    # K. Silo reorder/delete remap:
    #    existing silo_colors remapping behavior remains intact
    def test_k_silo_colors_remapping_contract(self, dummy_win):
        from fastprompter.main import FastPrompter
        dummy_win._SILO_INDEX_STATE = FastPrompter._SILO_INDEX_STATE
        dummy_win._remove_silo_view_key = lambda *a, **kw: None
        dummy_win._remap_silo_view_state = lambda *a, **kw: None
        dummy_win.state = type("State", (), {"remap_silo_identities": lambda *a, **kw: None})()
        dummy_win.data["silo_colors"] = {"0": "#ff0000", "1": "#00ff00", "2": "#0000ff"}
        FastPrompter._remove_silo_index_key(dummy_win, 1, is_archive=False)
        FastPrompter._remap_silo_indices(
            dummy_win, lambda i: i - 1 if i > 1 else i, is_archive=False
        )
        assert dummy_win.data["silo_colors"] == {"0": "#ff0000", "1": "#0000ff"}

    # L. Explicit manual color on non-# silo:
    #    => assigned swatch remains visible after refresh
    def test_l_manual_color_on_non_hash_silo_is_visible(self, dummy_win, silo_btn):
        # Silo label has NO '#'
        raw_text = "Plain Silo Name"
        dummy_win.data["silo_colors"]["0"] = "#00ffff"
        dummy_win.data["silo_color_box"] = "True"

        # Simulate update_data as done by main.py
        color_val = dummy_win.data["silo_colors"].get("0", "")
        has_hash = (raw_text.lstrip().startswith("#") and dummy_win.data.get("silo_color_box") == "True")
        color_hex = color_val if (has_hash or (color_val and dummy_win.data.get("silo_color_box") == "True")) else ""

        assert color_hex == "#00ffff", "color_hex must be passed for non-# silo with manual color"
        silo_btn.update_data(
            "1: Plain Silo Name", 0, "#333333", color_hex=color_hex, has_hash=has_hash
        )
        assert silo_btn._btn_color_box.isVisible()
        assert not silo_btn._swatch_empty
        assert silo_btn._btn_color_box.isEnabled()
        assert "#00ffff" in silo_btn._btn_color_box.styleSheet()

    # M. Silo Color Box setting initially OFF:
    #    Ctrl+MiddleButton
    #    => resulting color is visible
    #    => UI setting/state remain synchronized
    def test_m_color_box_setting_initially_off_enables_and_syncs(self, dummy_win, silo_btn):
        dummy_win.data["silo_color_box"] = "False"
        dummy_win.cb_silo_color_box.setChecked(False)

        ctrl = Qt.KeyboardModifier.ControlModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))

        assert dummy_win.data["silo_color_box"] == "True"
        assert dummy_win.cb_silo_color_box.isChecked()
        assert dummy_win.data["silo_colors"].get("0")

    # N. Archive Ctrl+MiddleButton:
    #    => no destructive action
    #    => no active-project color corruption
    def test_n_archive_ctrl_middle_is_safe_noop(self, dummy_win, silo_btn):
        silo_btn.is_archive = True
        ctrl = Qt.KeyboardModifier.ControlModifier
        silo_btn.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, ctrl))

        assert not dummy_win.trashed
        assert not dummy_win.cleared
        assert dummy_win.data["silo_colors"].get("0") is None
