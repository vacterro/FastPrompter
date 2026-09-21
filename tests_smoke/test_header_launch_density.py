import os
import sys
import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_app = QApplication.instance() or QApplication.instance() or QApplication(sys.argv)
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_launch_")



def _assert_no_header_intersections(win):
    rects = []
    for index in range(win.header_layout.count()):
        widget = win.header_layout.itemAt(index).widget()
        if widget is None or widget.isHidden() or widget.width() <= 0:
            continue
        rects.append((widget.x(), widget))
    rects.sort(key=lambda pair: pair[0])
    for (_, left), (_, right) in zip(rects, rects[1:]):
        assert not left.geometry().intersects(right.geometry()), (
            left.objectName() or type(left).__name__,
            right.objectName() or type(right).__name__,
            left.geometry(), right.geometry())


@pytest.fixture
def win(smoke_win):
    w = smoke_win.create()
    yield w
    smoke_win.retire(w)


def test_cat_numbox_has_fixed_size(win):
    """cat_numbox must have explicit fixed width and height so it cannot be squished by QHBoxLayout."""
    win.show()
    _app.processEvents()

    cats = win.visible_categories()
    fitted = win._cat_num_buttons[0].width()
    expected_w = len(cats) * fitted + max(0, len(cats) - 1) * 1
    assert 14 <= fitted <= win.numbox_button_size()
    assert win.cat_numbox.minimumWidth() == expected_w
    assert win.cat_numbox.width() == expected_w


def test_header_settles_spacious_on_launch_without_ctrl_q(win):
    """Medium launch preserves status widgets and uses one fit result.

    The line counter's SEMANTIC state is "has text" (an empty editor hides
    it by design - semantic absence beats a user Show rule), so the test
    seeds a real document to exercise the medium-range preservation."""
    win.data["cats_order"] = [f"Cat {i}" for i in range(1, 9)]
    win.data["analog_clock"] = "True"
    win.rebuild_cat_combo()
    win.text_area.setPlainText("alpha\nbeta\ngamma")
    win._update_line_count_label()
    win.resize(1100, 679)
    win.show()
    _app.processEvents()

    assert win._topbar_active_range == "medium"
    assert win.btn_new.width() >= 40
    assert win.btn_save.width() >= 50
    assert not win.lbl_line_count.isHidden()
    assert not win.lbl_date.isHidden()
    assert not win.analog_clock.isHidden()
    assert not hasattr(win, "_priority_fit_hidden")
    assert win.header_widget.sizeHint().width() <= win.header_widget.width()
    _assert_no_header_intersections(win)


def test_narrow_launch_shrinks_project_buttons_before_clipping(win):
    win.data["cats_order"] = [f"Cat {i}" for i in range(1, 11)]
    win.data["numbox_per_row"] = "10"
    win.data["numbox_btn_size"] = "22"
    win.rebuild_cat_combo()
    win.resize(560, 679)
    win.show()
    _app.processEvents()

    widths = {button.width() for button in win._cat_num_buttons}
    assert len(widths) == 1
    fitted = widths.pop()
    assert 14 <= fitted < 22
    assert win.cat_numbox.width() == fitted * 10 + 9
    assert win.header_widget.sizeHint().width() <= win.header_widget.width()
    assert not win.btn_new.isHidden() and win.btn_new.isEnabled()
    assert not win.cat_numbox.geometry().intersects(win.btn_new.geometry())
    _assert_no_header_intersections(win)


def test_ctrl_alt_click_new_creates_child_silo(win):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    win.data["temp_presets"] = ["Parent Silo", "Another Silo"]
    win.refresh_temp_presets()
    win.active_temp_slot = 0
    initial_count = len(win.data["temp_presets"])

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    handled = win.eventFilter(win.btn_new, event)
    assert handled is True
    assert len(win.data["temp_presets"]) == initial_count + 1
    assert win.active_temp_slot == 1
    assert win.silo_parent_of(1) == 0


def test_project_sound_on_tab_change_and_click(win, monkeypatch):
    played = []
    monkeypatch.setattr(win, "play_project_sound", lambda: played.append(True))
    win.data["cats_order"] = ["Cat 1", "Cat 2"]
    win.rebuild_cat_combo()
    win._initializing_ui = False
    played.clear()

    win.on_tab_changed(1)
    assert len(played) == 1

    # Re-clicking already-selected tab in cat_numbox also plays project click sound
    win._cat_numbox_clicked(1)
    assert len(played) == 2


def test_interactive_shrink_and_expand_resizing(win):
    win.data["cats_order"] = [f"Cat {i}" for i in range(1, 11)]
    win.data["numbox_per_row"] = "10"
    win.data["numbox_btn_size"] = "22"
    win.rebuild_cat_combo()
    # Ten project cards plus the complete Wide rule set need more than a
    # typical laptop width.  At 1400 the cards are allowed to shrink before
    # useful status widgets are sacrificed; at 2200 there is enough room to
    # prove that their configured dimensions are restored.
    win.resize(2200, 679)
    win.show()
    _app.processEvents()

    assert win.cat_numbox.width() == 229

    # Shrink to narrow width
    win.resize(560, 679)
    _app.processEvents()

    fitted = win._cat_num_buttons[0].width()
    assert 14 <= fitted < 22
    assert win.cat_numbox.width() == fitted * 10 + 9
    assert win.header_widget.sizeHint().width() <= win.header_widget.width()

    # Expand back to wide
    win.resize(2200, 679)
    _app.processEvents()
    assert win.cat_numbox.width() == 229


def test_visibility_result_is_resize_path_independent(win):
    win.data["analog_clock"] = "True"
    win.data["show_date_rect"] = "True"

    def travel(widths):
        for width in widths:
            win.resize(width, 679)
            _app.processEvents()
            win._apply_header_density()
        return (win._topbar_visible_tokens,
                tuple(button.width() for button in win._cat_num_buttons))

    assert travel([1600, 500, 1000]) == travel([500, 1600, 1000])


def test_custom_visibility_hide_never_enters_overflow(win):
    from fastprompter.core.topbar_visibility import default_topbar_visibility

    config = default_topbar_visibility()
    config["items"]["lbl_line_count"]["narrow"] = "show"
    config["items"]["analog_clock"]["narrow"] = "show"
    config["items"]["btn_copy"]["narrow"] = "hide"
    win.data["topbar_visibility"] = config
    win.data["analog_clock"] = "True"
    # line-count semantic = "has text"; an empty editor is hidden by design
    win.text_area.setPlainText("alpha\nbeta\ngamma")
    win._update_line_count_label()
    win.resize(700, 679)
    win.show()
    _app.processEvents()
    win._apply_header_density()

    assert not win.lbl_line_count.isHidden()
    assert not win.analog_clock.isHidden()
    assert win.btn_copy.isHidden()
    assert "btn_copy" not in win._topbar_overflow_tokens
    _assert_no_header_intersections(win)


def test_project_run_show_rule_never_overrides_semantic_absence(win):
    from fastprompter.core.topbar_visibility import default_topbar_visibility

    config = default_topbar_visibility()
    config["items"]["btn_project_run"]["wide"] = "show"
    win.data["topbar_visibility"] = config
    win.data["silo_project_paths"] = {
        str(win.active_temp_slot): {"folder": "C:/project"},
    }
    win.resize(2200, 679)
    win.show()
    _app.processEvents()
    win._update_project_buttons(is_archive=False)
    assert win.btn_project_run.isHidden()
    assert "btn_project_run" not in win._topbar_overflow_tokens

    win.data["silo_project_paths"][str(win.active_temp_slot)][
        "executable"] = "C:/project/run.exe"
    win._update_project_buttons(is_archive=False)
    assert not win.btn_project_run.isHidden()

    del win.data["silo_project_paths"][str(win.active_temp_slot)]["executable"]
    win._update_project_buttons(is_archive=False)
    assert win.btn_project_run.isHidden()


def test_effective_width_and_project_new_geometry(win):
    win.data["ui_scale"] = "1.5"
    win.data["numbox_tabs"] = "True"
    win.resize(1168, 679)
    win.show()
    _app.processEvents()
    win._apply_header_density()

    assert int(round(win._topbar_effective_width())) == 779
    assert win._topbar_active_range == "narrow"
    if not win.cat_numbox.isHidden() and not win.btn_new.isHidden():
        assert not win.cat_numbox.geometry().intersects(win.btn_new.geometry())


def test_ai_reset_label_keeps_hour_and_minute_precision(win):
    import time

    from fastprompter.core.usage_limits.model import (
        AccountRef,
        UsageSnapshot,
        UsageWindow,
    )

    account = AccountRef("claude", "precision", "Claude", "test")
    epoch = time.time() + 3 * 3600 + 19 * 60 + 20
    snapshot = UsageSnapshot(account, "OK", [
        UsageWindow("five_hour", 300, True, 50, 50, epoch),
    ])
    with win.limit_service._lock:
        win.limit_service._state.accounts = [account]
        win.limit_service._state.snapshots = {account.key: snapshot}
    win.data["limit_gauges"] = "True"
    win._header_dense = True
    win._update_limit_timer_label()
    assert win.lbl_limit_timer.text() == "↻ 3h 19m"


def test_topbar_visibility_dialog_is_wired_and_applies(win):
    from fastprompter.ui.topbar_visibility_dialog import TopbarVisibilityDialog

    original_order = win.data.get("toolbar_order")
    win.data["toolbar_order"] = "btn_help,btn_new,<stretch>,btn_save"
    try:
        dialog = TopbarVisibilityDialog(win)
        combo = dialog._range_boxes[("btn_copy", "medium")]
        hide_index = next(i for i in range(combo.count())
                          if combo.itemData(i)[0] == "hide")
        combo.setCurrentIndex(hide_index)
        dialog.apply_changes()
        assert win.data["topbar_visibility"]["items"]["btn_copy"][
            "medium"] == "hide"
        assert win.data["toolbar_order"] == (
            "btn_help,btn_new,<stretch>,btn_save")
        dialog.close()
    finally:
        win.data["toolbar_order"] = original_order
        win.apply_toolbar_order()


def test_topbar_visibility_dialog_user_friendly_controls(win):
    from fastprompter.core.topbar_visibility import TOPBAR_ITEMS
    from fastprompter.ui.topbar_visibility_dialog import TopbarVisibilityDialog

    dialog = TopbarVisibilityDialog(win)
    try:
        # 1. Advanced Priority column is hidden by default for clean UX
        assert dialog.table.isColumnHidden(5) is True
        dialog.cb_show_priority.setChecked(True)
        assert dialog.table.isColumnHidden(5) is False
        dialog.cb_show_priority.setChecked(False)
        assert dialog.table.isColumnHidden(5) is True

        # 2. Search filter filters items live
        dialog.in_filter.setText("clock")
        for row_idx, item in enumerate(TOPBAR_ITEMS):
            if "clock" in item.label.lower():
                assert not dialog.table.isRowHidden(row_idx)
            else:
                assert dialog.table.isRowHidden(row_idx)
        dialog.in_filter.clear()
        assert not any(dialog.table.isRowHidden(i) for i in range(len(TOPBAR_ITEMS)))

        # 3. Category selector filters by group
        status_idx = next(i for i in range(dialog.combo_category.count())
                          if dialog.combo_category.itemData(i) == "Status")
        dialog.combo_category.setCurrentIndex(status_idx)
        for row_idx, item in enumerate(TOPBAR_ITEMS):
            if item.group == "Status":
                assert not dialog.table.isRowHidden(row_idx)
            else:
                assert dialog.table.isRowHidden(row_idx)
        dialog.combo_category.setCurrentIndex(0)
        assert not any(dialog.table.isRowHidden(i) for i in range(len(TOPBAR_ITEMS)))

        # 4. Presets apply rules cleanly across controls
        minimal_idx = next(i for i in range(dialog.combo_preset.count())
                           if dialog.combo_preset.itemData(i) == "minimal")
        dialog.combo_preset.setCurrentIndex(minimal_idx)
        assert dialog._range_boxes[("btn_bold", "medium")].currentData()[0] == "hide"
        assert dialog._range_boxes[("lbl_date", "medium")].currentData()[0] == "show"

        # 5. Restore defaults resets state
        dialog.btn_defaults.click()
        assert dialog._range_boxes[("btn_bold", "medium")].currentData()[0] == "auto"
        assert dialog._range_boxes[("lbl_date", "medium")].currentData()[0] == "show"
        assert dialog.in_filter.text() == ""
        assert dialog.combo_category.currentIndex() == 0
        assert dialog.cb_show_priority.isChecked() is False
    finally:
        dialog.close()
