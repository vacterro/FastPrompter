"""End-to-end smoke test: boots the real FastPrompter window offscreen.

Run standalone (NOT with the unit suite — tests/ stubs out PyQt6 globally):

    uv run pytest tests_smoke/ -q

Uses a temp database, disables the single-instance IPC server, global
hotkey registration, and portable backup so it never touches real user
data or a running FastPrompter instance.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])

_tmpdir = tempfile.mkdtemp(prefix="fastprompter_smoke_")


@pytest.fixture(scope="module")
def win():
    # Isolate from real data / running instances
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"smoke_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None

    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None  # skip final DB write on close
    w.conn = None
    w.close()


def test_window_constructs_with_all_mixins(win):
    from fastprompter.ui.formatting_mixin import FormattingMixin
    from fastprompter.ui.hotkey_mixin import HotkeyMixin
    from fastprompter.ui.scaling_mixin import ScalingMixin
    from fastprompter.ui.search_mixin import SearchMixin
    from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
    from fastprompter.ui.theme_mixin import ThemeMixin
    from fastprompter.ui.tray_mixin import TrayMixin
    from fastprompter.ui.window_mixin import WindowMixin

    for mixin in (FormattingMixin, HotkeyMixin, ScalingMixin, SearchMixin,
                  SnippetOpsMixin, ThemeMixin, TrayMixin, WindowMixin):
        assert isinstance(win, mixin)
    # The method whose absence crashed the app at startup
    assert callable(win._get_custom_colors)


def test_settings_properties_live(win):
    assert isinstance(win._font_size, int)
    assert isinstance(win._ui_scale, float)
    win.data["always_on_top"] = "False"
    assert win._always_on_top is False
    win.data["always_on_top"] = "True"
    assert win._always_on_top is True


def test_theme_and_font_apply(win):
    win.apply_theme()
    win.change_font_size(14)
    assert win.data["font_size"] == 14
    assert win.text_area.font().pointSize() == max(8, int(round(14 * win._ui_scale)))


def test_silo_switching_and_line_count_label(win):
    win.data["temp_presets"] = ["one\ntwo\nthree", "solo", ""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    assert win.active_temp_slot == 0
    assert win.text_area.toPlainText() == "one\ntwo\nthree"
    assert win.lbl_line_count.text() == "3 L"
    win._switch_to_slot(1)
    assert win.text_area.toPlainText() == "solo"
    assert win.lbl_line_count.text() == "1 L"


def test_navigate_silo_keyboard(win):
    win.data["temp_presets"] = ["a", "b", "c"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.navigate_silo(1)
    assert win.active_temp_slot == 1
    win.navigate_silo(1)
    assert win.active_temp_slot == 2
    win.navigate_silo(1)  # clamped at end
    assert win.active_temp_slot == 2
    win.navigate_silo(-1)
    assert win.active_temp_slot == 1


def test_pinned_silos_sort_first(win):
    win.data["temp_presets"] = ["a", "b", "c", ""]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._toggle_pin_silo(2)
    assert 2 in win.data["pinned_silos"]
    win.refresh_temp_presets()
    assert win.silo_buttons[0].global_idx == 2  # pinned silo displays first
    win._toggle_pin_silo(2)
    assert 2 not in win.data["pinned_silos"]


def test_empty_silo_cap_at_five(win):
    win.data["temp_presets"] = ["a", "b"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    for _ in range(10):
        win.select_empty_silo()
    empties = sum(1 for p in win.data["temp_presets"] if not p.strip())
    assert empties <= 5


def test_clear_on_empty_silo_deletes_slot(win):
    win.data["temp_presets"] = ["x", "", "y"]
    win.data["pinned_silos"] = []
    win.silo_last_edited = {2: 12345}
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(1)  # empty slot → removed entirely
    assert win.data["temp_presets"] == ["x", "y"]
    # last-edited tint followed "y" from slot 2 to slot 1
    assert win.silo_last_edited == {1: 12345}
    # clear on a non-empty slot only empties it
    win.clear_temp(0)
    assert win.data["temp_presets"][0] == ""


def test_move_temp_to_index_remaps_state(win):
    win.data["temp_presets"] = ["a", "b", "c", "d"]
    win.data["pinned_silos"] = [3]
    win.silo_last_edited = {0: 111, 3: 444}
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.move_temp_to_index(0, 2)
    assert win.data["temp_presets"] == ["b", "c", "a", "d"]
    assert win.silo_last_edited == {2: 111, 3: 444}
    assert win.data["pinned_silos"] == [3]
    assert win.active_temp_slot == 2  # selection followed the moved silo


def test_archive_single_silo(win):
    win.data["temp_presets"] = ["keep", "archive me"]
    win.data["archive_temp_presets"] = []
    win.archive_docs[:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.archive_single_silo(1)
    assert "archive me" in win.data["archive_temp_presets"]
    assert win.data["temp_presets"][1] == ""


def test_insert_divider_line_smart(win):
    win.data["temp_presets"] = ["hello world"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cursor = win.text_area.textCursor()
    cursor.setPosition(5)  # mid-line
    win.text_area.setTextCursor(cursor)
    win.insert_old_add_line()
    text = win.text_area.toPlainText()
    assert text == "hello world\n\n---\n\n\n• "
    # cursor lands right after the bullet, ready to type
    cur = win.text_area.textCursor()
    assert not cur.hasSelection()
    assert cur.position() == len(text)


def test_insert_divider_line_and_toolbar_button_share_one_implementation(win):
    # insert_add_line (toolbar "Line" button) and insert_divider_line
    # (Ctrl+W) must never diverge again -- one is a thin alias of the other
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_old_add_line()
    from_toolbar = win.text_area.toPlainText()
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_old_add_line()
    from_shortcut = win.text_area.toPlainText()
    assert from_toolbar == from_shortcut == "\n\n---\n\n\n• "


def test_insert_add_line_marks_dirty(win):
    # Regression: the toolbar entry point used to skip mark_dirty(),
    # silently risking the divider not being saved
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.state._db_dirty = False
    win.insert_old_add_line()
    assert win.state._db_dirty is True


def test_auto_bullet_space_and_enter(win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.data["auto_bullet"] = "True"
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    ta.insertPlainText("-")
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                               Qt.KeyboardModifier.NoModifier, " "))
    assert ta.toPlainText() == "• "
    ta.insertPlainText("item one")
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                               Qt.KeyboardModifier.NoModifier, "\r"))
    assert ta.toPlainText() == "• item one\n• "
    # Enter on the empty bullet clears it
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                               Qt.KeyboardModifier.NoModifier, "\r"))
    assert ta.toPlainText() == "• item one\n"
    win.data["auto_bullet"] = "False"


def test_double_line_bullet_toggle(win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.data["auto_bullet"] = "True"
    win.data["bullet_double_line"] = "True"
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    ta.insertPlainText("• item one")
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                               Qt.KeyboardModifier.NoModifier, "\r"))
    # blank line inserted before the next bullet
    assert ta.toPlainText() == "• item one\n\n• "
    ta.insertPlainText("item two")
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                               Qt.KeyboardModifier.NoModifier, "\r"))
    assert ta.toPlainText() == "• item one\n\n• item two\n\n• "
    # Enter on the empty bullet still just clears the marker (no extra blank line)
    ta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                               Qt.KeyboardModifier.NoModifier, "\r"))
    assert ta.toPlainText() == "• item one\n\n• item two\n\n"
    win.data["auto_bullet"] = "False"
    win.data["bullet_double_line"] = "False"


def test_double_line_setting_roundtrips_through_db(win):
    win.data["bullet_double_line"] = "True"
    win.mark_dirty()
    win.save_data_to_db(force=True)

    import fastprompter.core.state as state_mod

    fresh = state_mod.FastPrompterState()
    try:
        assert fresh.data.get("bullet_double_line") == "True"
    finally:
        if fresh.conn:
            fresh.conn.close()
    win.data["bullet_double_line"] = "False"
    win.mark_dirty()
    win.save_data_to_db(force=True)


def test_button_scale_persists_to_db(win):
    win.data["ui_scale"] = "1.0"
    win.data["button_scale"] = "1.0"
    win.cycle_button_scale()  # 1.0 -> 1.25, saves to DB (unified scale)
    assert win.data["button_scale"] == "1.25"
    assert win.data["ui_scale"] == "1.25"
    import fastprompter.core.state as state_mod

    fresh = state_mod.FastPrompterState()
    try:
        assert fresh.data.get("button_scale") == "1.25"
    finally:
        if fresh.conn:
            fresh.conn.close()
    # restore
    win.data["button_scale"] = "1.0"
    win.mark_dirty()
    win.save_data_to_db(force=True)


def test_button_scale_steps_are_distinct(win):
    from PyQt6.QtWidgets import QPushButton

    sizes = {}
    for scale in ("0.5", "0.75", "1.0", "1.5"):
        win.data["ui_scale"] = scale
        win.data["button_scale"] = scale
        btn = QPushButton("Clear Fmt")
        win.apply_button_size(btn, 24)
        sizes[scale] = (btn.height(), btn.font().pointSizeF())
    # fonts distinct at every step and never below the readable floor
    fonts = [sizes[k][1] for k in ("0.5", "0.75", "1.0", "1.5")]
    assert fonts == sorted(fonts) and len(set(fonts)) == 4, sizes
    assert all(pt >= 8.0 for pt in fonts), sizes
    # heights monotonically non-decreasing, clearly bigger at 150%
    heights = [sizes[k][0] for k in ("0.5", "0.75", "1.0", "1.5")]
    assert heights == sorted(heights) and heights[-1] > heights[0], sizes
    win.data["ui_scale"] = "1.0"
    win.data["button_scale"] = "1.0"


def test_middle_click_clear_is_undoable(win):
    win.data["temp_presets"] = ["keep me", "precious content"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(1)  # middle-click on a non-active silo
    assert win.data["temp_presets"][1] == ""
    win._smart_undo()  # Ctrl+Z routes to data undo
    assert win.data["temp_presets"][1] == "precious content"


def test_delete_empty_silo_is_undoable(win):
    win.data["temp_presets"] = ["a", "", "c"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(1)  # empty silo -> slot deleted
    assert win.data["temp_presets"] == ["a", "c"]
    win._smart_undo()
    assert win.data["temp_presets"] == ["a", "", "c"]


def _press_ctrl_z(win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.text_area.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "z")
    )


def test_undo_delete_active_silo(win):
    win.data["temp_presets"] = ["first", "the active one", "third"]
    win.data["pinned_silos"] = []
    win.silo_last_edited = {}
    win.silo_docs[:] = []
    win._switch_to_slot(1, initial=True)
    win.del_silo(1)  # delete the silo currently open in the editor
    assert win.data["temp_presets"] == ["first", "third"]
    _press_ctrl_z(win)  # real Ctrl+Z inside the editor
    assert win.data["temp_presets"] == ["first", "the active one", "third"]
    assert win.text_area.toPlainText() == "the active one"


def test_undo_clear_active_silo(win):
    win.data["temp_presets"] = ["precious active text", "other"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(0)  # middle-click clear of the ACTIVE silo
    assert win.data["temp_presets"][0] == ""
    assert win.text_area.toPlainText() == ""
    _press_ctrl_z(win)
    assert win.data["temp_presets"][0] == "precious active text"
    assert win.text_area.toPlainText() == "precious active text"


def test_undo_archive_active_silo(win):
    win.data["temp_presets"] = ["archive me please", "other"]
    win.data["archive_temp_presets"] = []
    win.data["pinned_silos"] = []
    win.archive_docs[:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.archive_single_silo(0)  # hover-button archive of the active silo
    assert win.data["temp_presets"][0] == ""
    assert "archive me please" in win.data["archive_temp_presets"]
    _press_ctrl_z(win)
    assert win.data["temp_presets"][0] == "archive me please"
    assert "archive me please" not in win.data["archive_temp_presets"]


def test_undo_after_typing_prefers_text_then_data(win):
    win.data["temp_presets"] = ["silo A", "silo B"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.text_area.insertPlainText("!!!")  # newest action: text edit
    win.clear_temp(1)  # then a data action (non-active silo)
    _press_ctrl_z(win)  # data action is newest -> restores silo B
    assert win.data["temp_presets"][1] == "silo B"
    _press_ctrl_z(win)  # next undo goes back to the text edit
    assert "!!!" not in win.text_area.toPlainText()


def test_undo_restores_pins_and_tints(win):
    win.data["temp_presets"] = ["a", "b", "c"]
    win.data["pinned_silos"] = [2]
    win.silo_last_edited = {2: 999}
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.del_silo(1)  # shifts pin 2 -> 1 and tint 2 -> 1
    assert win.data["pinned_silos"] == [1]
    win._smart_undo()
    assert win.data["temp_presets"] == ["a", "b", "c"]
    assert win.data["pinned_silos"] == [2]
    assert win.silo_last_edited == {2: 999}


def test_redo_after_undo(win):
    win.data["temp_presets"] = ["x", "y"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(1)
    win._smart_undo()
    assert win.data["temp_presets"][1] == "y"
    win.redo_action()
    assert win.data["temp_presets"][1] == ""


def test_undo_across_tabs_returns_and_restores(win):
    cats = win.data["cats_order"]
    if len(cats) < 2:
        import pytest as _pytest

        _pytest.skip("needs two tabs")
    a = cats[0]
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)  # ensure alias points at tab A
    win.data["temp_presets"][0] = "tab A treasure"
    while len(win.data["temp_presets"]) < 2:
        win.data["temp_presets"].append("")
    win.data["temp_presets"][1] = "other"
    win._switch_to_slot(1, initial=True)
    win.clear_temp(0)  # destroy the treasure on tab A
    assert win.data["temp_presets_all"][a][0] == ""
    win.cat_combo.setCurrentIndex(1)  # user wanders to tab B
    win._smart_undo()  # Ctrl+Z must return to tab A and restore
    assert win.get_current_category() == a
    assert win.data["temp_presets"][0] == "tab A treasure"
    # The alias must be intact — otherwise the restore dies on tab switch
    assert win.data["temp_presets_all"][a] is win.data["temp_presets"]


def test_undone_data_survives_tab_roundtrip_and_db_save(win):
    cats = win.data["cats_order"]
    a = cats[0]
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][0] = "must survive"
    win._switch_to_slot(0, initial=True)
    win.clear_temp(0)
    win._smart_undo()
    assert win.text_area.toPlainText() == "must survive"
    # tab away and back — restored data must not evaporate
    win.cat_combo.setCurrentIndex(1)
    win.cat_combo.setCurrentIndex(0)
    assert win.data["temp_presets"][0] == "must survive"
    # and it must actually reach the database
    win.mark_dirty()
    win.save_data_to_db(force=True)
    import fastprompter.core.state as state_mod

    fresh = state_mod.FastPrompterState()
    try:
        assert fresh.data["temp_presets_all"][a][0] == "must survive"
    finally:
        if fresh.conn:
            fresh.conn.close()


def test_pin_toggle_and_move_to_bottom_are_undoable(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["one", "two", "three"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._toggle_pin_silo(2)
    assert win.data["pinned_silos"] == [2]
    win._smart_undo()
    assert win.data["pinned_silos"] == []
    win._move_silo_to_bottom(0)
    assert win.data["temp_presets"] == ["two", "three", "one"]
    win._smart_undo()
    assert win.data["temp_presets"] == ["one", "two", "three"]


def test_undo_depth_multiple_operations(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["s1", "s2", "s3", "s4"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(1)
    win.clear_temp(2)
    win.clear_temp(3)
    assert win.data["temp_presets"] == ["s1", "", "", ""]
    win._smart_undo()
    assert win.data["temp_presets"] == ["s1", "", "", "s4"]
    win._smart_undo()
    assert win.data["temp_presets"] == ["s1", "", "s3", "s4"]
    win._smart_undo()
    assert win.data["temp_presets"] == ["s1", "s2", "s3", "s4"]


def test_all_settings_roundtrip_through_db(win):
    sentinels = {
        "font_family": "Consolas",
        "ui_scale": "1.35",
        "button_scale": "0.75",
        "theme": "Vintage Dark",
        "zebra_lines": "True",
        "zebra_opacity": "44",
        "zebra_stripe_color": "#112233",
        "sound_ui": "True",
        "sound_typewriter": "True",
        "sound_volume": "7",
        "word_wrap": "False",
        "show_line_numbers": "True",
        "sidebar_right": "True",
        "always_on_top": "False",
        "normal_window": "True",
        "lock_to_cursor": "True",
        "hide_shortkeys": "True",
        "silo_home": "True",
        "portable_backup_enabled": "False",
        "hide_extra": "False",
        "auto_bullet": "True",
        "last_geometry": "11,22,640,480",
    }
    saved_prior = {k: win.data.get(k) for k in sentinels}
    win.data.update(sentinels)
    # widget-driven keys go through their widgets
    win.font_spin.setValue(17)
    win.cb_tray.setChecked(False)
    win.mark_dirty()
    win.save_data_to_db(force=True)

    import fastprompter.core.state as state_mod

    fresh = state_mod.FastPrompterState()
    try:
        mismatches = {
            k: (v, fresh.data.get(k)) for k, v in sentinels.items() if fresh.data.get(k) != v
        }
        assert not mismatches, f"settings lost between sessions: {mismatches}"
        assert fresh.data.get("font_size") == 17
        assert fresh.data.get("tray_visible") == "False"
    finally:
        if fresh.conn:
            fresh.conn.close()
        # restore prior values so later tests aren't affected
        win.data.update({k: v for k, v in saved_prior.items() if v is not None})
        win.font_spin.setValue(11)
        win.cb_tray.setChecked(True)
        win.mark_dirty()
        win.save_data_to_db(force=True)


def test_trim_archive_keeps_backing_store_alias(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.get_current_category()
    win.data["archive_temp_presets"][:] = ["keep", "", "also keep", ""]
    win._trim_archive()
    assert win.data["archive_temp_presets"] == ["keep", "also keep"]
    # the rebind must reach the backing store or the trim never persists
    assert win.data["archive_temp_presets_all"][cat] is win.data["archive_temp_presets"]


def test_new_silo_at_top_shifts_pins(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["a", "b", "c"]
    win.data["pinned_silos"] = [1]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.select_empty_silo()  # inserts at top: every index shifts +1
    assert win.data["pinned_silos"] == [2]
    assert win.data["temp_presets"][2] == "b"  # pin still points at 'b'


def test_fuzz_random_operations_hold_invariants(win):
    import random

    rng = random.Random(20260709)
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [f"content {i}" for i in range(6)]
    win.data["archive_temp_presets"][:] = []
    win.data["pinned_silos"][:] = []
    win.silo_last_edited.clear()
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    def check_invariants(step, op):
        cat = win.get_current_category()
        assert cat, f"step {step} ({op}): no current category"
        assert win.data["temp_presets"] is win.data["temp_presets_all"][cat], (
            f"step {step} ({op}): temp_presets alias broken"
        )
        assert win.data["archive_temp_presets"] is win.data["archive_temp_presets_all"][cat], (
            f"step {step} ({op}): archive alias broken"
        )
        assert win.data["pinned_silos"] is win.data["pinned_silos_all"][cat], (
            f"step {step} ({op}): pins alias broken"
        )
        assert win.silo_last_edited is win.data["silo_last_edited_all"][cat], (
            f"step {step} ({op}): tints alias broken"
        )
        n = len(win.data["temp_presets"])
        assert n >= 1, f"step {step} ({op}): silo list empty"
        assert 0 <= win.active_temp_slot < max(
            n, len(win.data["archive_temp_presets"]), 1
        ), f"step {step} ({op}): active slot out of range"
        for p in win.data.get("pinned_silos", []):
            assert 0 <= p < n, f"step {step} ({op}): pin {p} out of range 0..{n - 1}"
        for k in win.silo_last_edited:
            assert 0 <= k < 100, f"step {step} ({op}): last-edited key {k} out of range"

    n_silos = lambda: len(win.data["temp_presets"])  # noqa: E731
    ops = [
        ("switch", lambda: win._switch_to_slot(rng.randrange(n_silos()))),
        ("clear", lambda: win.clear_temp(rng.randrange(n_silos()))),
        ("delete", lambda: win.del_silo(rng.randrange(n_silos()))),
        ("new_top", win.select_empty_silo),
        ("pin", lambda: win._toggle_pin_silo(rng.randrange(n_silos()))),
        ("move", lambda: win.move_temp_to_index(rng.randrange(n_silos()), rng.randrange(n_silos()))),
        ("bottom", lambda: win._move_silo_to_bottom(rng.randrange(n_silos()))),
        ("archive", lambda: win.archive_single_silo(rng.randrange(n_silos()))),
        ("swap", lambda: win.swap_temp_slots(rng.randrange(n_silos()), rng.randrange(n_silos()))),
        ("type", lambda: win.text_area.insertPlainText("x")),
        ("tab", lambda: (win.cat_combo.setCurrentIndex(rng.randrange(win.cat_combo.count())))),
        ("undo", win._smart_undo),
        ("redo", win.redo_action),
        ("divider", win.insert_divider_line),
        ("header", win.apply_header_timestamp),
    ]
    for step in range(300):
        name, op = rng.choice(ops)
        op()
        check_invariants(step, name)


def test_fuzz_snippets_and_archive_mode(win):
    """Fuzz round 2: snippet CRUD, archive-mode ops, cross-category moves,
    silo<->snippet conversion, undo/redo — with auto-confirmed dialogs."""
    import random
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    rng = random.Random(77)
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [f"silo {i}" for i in range(4)]
    win.data["archive_temp_presets"][:] = ["arc one", "arc two"]
    win.data["pinned_silos"][:] = []
    win.silo_last_edited.clear()
    win.silo_docs[:] = []
    win.archive_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cats = win.data["cats_order"]

    def any_snippet():
        pairs = [
            (c, i)
            for c in cats
            for i, s in enumerate(win.data["categories"].get(c, []))
            if s
        ]
        return rng.choice(pairs) if pairs else None

    def check(step, op):
        cat = win.get_current_category()
        assert win.data["temp_presets"] is win.data["temp_presets_all"][cat], (
            f"step {step} ({op}): temp alias broken"
        )
        assert win.data["archive_temp_presets"] is win.data["archive_temp_presets_all"][cat], (
            f"step {step} ({op}): archive alias broken"
        )
        es = getattr(win, "editing_snippet", None)
        if es:
            c, i = es
            assert c in win.data["categories"], f"step {step} ({op}): editing dead category"
            assert 0 <= i < len(win.data["categories"][c]), (
                f"step {step} ({op}): editing index out of range"
            )
        for c in cats:
            slots = win.data["categories"].get(c, [])
            assert len(slots) <= 100, f"step {step} ({op}): category {c} grew past 100"

    def op_save_snippet():
        win.text_area.insertPlainText(f"snippet body {rng.randrange(1000)}")
        # silent path must never open a dialog; real path auto-accepts below
        win.save_snippet(silent=True)
        win.save_snippet()

    def op_load_snippet():
        p = any_snippet()
        if p:
            win.load_snippet_for_edit(p[0], p[1])

    def op_delete_snippet():
        p = any_snippet()
        if p:
            win.delete_preset_by_index(p[0], p[1])

    def op_move_cross():
        p = any_snippet()
        if p:
            win.move_preset_cross_category(p[0], p[1], rng.choice(cats), rng.randrange(10))

    def op_arc_mode():
        if win.data["archive_temp_presets"]:
            win._switch_to_arc_slot(rng.randrange(len(win.data["archive_temp_presets"])))

    def op_arc_clear():
        if win.data["archive_temp_presets"]:
            win.clear_temp(rng.randrange(len(win.data["archive_temp_presets"])), is_archive=True)

    def op_back_to_silos():
        win._switch_to_slot(rng.randrange(len(win.data["temp_presets"])))

    ops = [
        ("save_snip", op_save_snippet),
        ("load_snip", op_load_snippet),
        ("del_snip", op_delete_snippet),
        ("move_cross", op_move_cross),
        ("convert", win.convert_to_snippet),
        ("arc_item", win.archive_active_item),
        ("arc_mode", op_arc_mode),
        ("arc_clear", op_arc_clear),
        ("silos", op_back_to_silos),
        ("cancel", win.cancel_editing),
        ("type", lambda: win.text_area.insertPlainText("y")),
        ("tab", lambda: win.cat_combo.setCurrentIndex(rng.randrange(win.cat_combo.count()))),
        ("undo", win._smart_undo),
        ("redo", win.redo_action),
    ]
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"), \
         patch.object(QInputDialog, "getText", return_value=("fuzzed name", True)):
        for step in range(250):
            name, op = rng.choice(ops)
            op()
            check(step, name)


def test_delete_category_is_undoable(win):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMessageBox

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cats_before = list(win.data["cats_order"])
    if len(cats_before) < 2:
        pytest.skip("needs two tabs")
    win.cat_combo.setCurrentIndex(1)
    victim = win.data["cats_order"][1]
    win.data["categories"][victim][0] = {"name": "keep", "text": "keep me", "last_edited": 0}
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        win.del_category()
    assert victim not in win.data["cats_order"]
    win._smart_undo()
    assert victim in win.data["cats_order"], "deleted tab not restored by undo"
    assert win.data["categories"][victim][0]["text"] == "keep me"
    assert win.cat_combo.count() == len(win.data["cats_order"])


def test_fuzz_ui_surfaces(win):
    """Fuzz round 3: themes, formatting ops on random selections,
    search/replace, unified scale, view modes, focus/sidebar toggles,
    help dialog — mixed with light silo ops and undo."""
    import random
    from unittest.mock import patch as _patch

    from PyQt6.QtWidgets import QMessageBox as _QMB

    ctx1 = _patch.object(_QMB, "information")
    ctx2 = _patch.object(_QMB, "question", return_value=_QMB.StandardButton.Yes)
    ctx1.start()
    ctx2.start()
    try:
        _run_fuzz_ui(win, random.Random(31337))
    finally:
        ctx1.stop()
        ctx2.stop()


def _run_fuzz_ui(win, rng):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha beta gamma\ndelta epsilon\n\nzeta", "line one\nline two"]
    win.data["pinned_silos"][:] = []
    win.silo_last_edited.clear()
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    themes = ["Default", "Golden Vintage", "Golden Default", "Vintage Dark",
              "Vintage Classic", "Dark 2 (OLED)", "Custom"]

    def random_selection():
        doc_len = max(1, win.text_area.document().characterCount() - 1)
        a = rng.randrange(doc_len)
        b = rng.randrange(doc_len)
        cur = win.text_area.textCursor()
        cur.setPosition(min(a, b))
        from PyQt6.QtGui import QTextCursor
        cur.setPosition(max(a, b), QTextCursor.MoveMode.KeepAnchor)
        win.text_area.setTextCursor(cur)

    def op_theme():
        win.change_theme(rng.choice(themes))

    def op_search():
        win.show_find()
        win.search_input.setText(rng.choice(["a", "e", "line", "zzz-none"]))
        win.find_next()
        win.find_prev()
        win.close_search()

    def op_replace_all():
        win.show_replace()
        win.search_input.setText(rng.choice(["a", "beta"]))
        win.replace_input.setText("Q")
        win.replace_all()
        win.close_search()

    def op_format():
        random_selection()
        rng.choice([
            lambda: win.apply_format("**"),
            lambda: win.apply_format("*"),
            win.apply_bold_smart,
            win.toggle_header_line,
            win.clear_formatting,
            win.toggle_bullet_conversion,
        ])()

    def op_view():
        win.preview_combo.setCurrentIndex(rng.randrange(3))

    def op_zebra():
        win.data["zebra_lines"] = rng.choice(["True", "False"])
        win.text_area.viewport().update()

    def op_help():
        win.open_help_dialog()
        win._help_dialog.close()

    def op_focus():
        win.toggle_focus_mode()
        win.toggle_focus_mode()

    def op_sidebar():
        win.toggle_sidebar_position(rng.choice([True, False]))

    def op_scale():
        win.cycle_button_scale()

    def op_fine_scale():
        win.adjust_ui_scale(rng.choice([-0.05, 0.05]))

    def op_wrap():
        win.on_wrap_toggled(rng.choice([True, False]))

    ops = [
        ("theme", op_theme),
        ("search", op_search),
        ("replace", op_replace_all),
        ("format", op_format),
        ("view", op_view),
        ("zebra", op_zebra),
        ("help", op_help),
        ("focus", op_focus),
        ("sidebar", op_sidebar),
        ("scale", op_scale),
        ("fine_scale", op_fine_scale),
        ("wrap", op_wrap),
        ("type", lambda: win.text_area.insertPlainText("w ")),
        ("switch", lambda: win._switch_to_slot(rng.randrange(len(win.data["temp_presets"])))),
        ("clear", lambda: win.clear_temp(rng.randrange(len(win.data["temp_presets"])))),
        ("divider", win.insert_divider_line),
        ("header", win.apply_header_timestamp),
        ("undo", win._smart_undo),
        ("redo", win.redo_action),
    ]
    for step in range(200):
        name, op = rng.choice(ops)
        op()
        cat = win.get_current_category()
        assert win.data["temp_presets"] is win.data["temp_presets_all"][cat], (
            f"step {step} ({name}): alias broken"
        )
        assert win.text_area.document() is not None
        assert len(win.data["temp_presets"]) >= 1
    # leave the app in a sane state for following tests
    win.change_theme("Default")
    win.data["ui_scale"] = "1.0"
    win.data["button_scale"] = "1.0"
    win._refresh_settings_cache()
    win.preview_combo.setCurrentIndex(1)
    win.data["word_wrap"] = "True"
    win.data["zebra_lines"] = "False"
    if getattr(win, "focus_mode", False):
        win.toggle_focus_mode()
    win.toggle_sidebar_position(False)


def test_markdown_marker_toggles(win):
    from PyQt6.QtGui import QTextCursor

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["hello brave world"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    def select(a, b):
        cur = ta.textCursor()
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
        ta.setTextCursor(cur)

    # bold wrap + unwrap (Ctrl+B semantics)
    select(6, 11)  # 'brave'
    win.apply_format("bold")
    assert ta.toPlainText() == "hello **brave** world"
    win.apply_format("bold")  # selection is kept on the content -> unwrap
    assert ta.toPlainText() == "hello brave world"

    # italic on word under cursor (no selection)
    cur = ta.textCursor()
    cur.setPosition(8)
    ta.setTextCursor(cur)
    win.apply_format("italic")
    assert ta.toPlainText() == "hello *brave* world"
    win.apply_format("italic")
    assert ta.toPlainText() == "hello brave world"

    # underline + strike markers
    select(6, 11)
    win.apply_format("underline")
    assert ta.toPlainText() == "hello __brave__ world"
    win.apply_format("strike")
    assert ta.toPlainText() == "hello __~~brave~~__ world"

    # italic toggle on a bold word wraps (doesn't eat the bold markers)
    win.data["temp_presets"][:] = ["**bold**"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    select(0, 8)
    win.apply_format("italic")
    assert ta.toPlainText() == "***bold***"


def test_ctrl_return_skips_empty_lines(win):
    from PyQt6.QtGui import QTextCursor

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["task one\n\ntask two\n\n"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    cur = ta.textCursor()
    cur.setPosition(0)
    cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)
    ta._toggle_checkboxes()
    assert ta.toPlainText() == "[ ] task one\n\n[ ] task two\n\n"
    # single Ctrl+Enter on an empty line does nothing
    cur = ta.textCursor()
    cur.setPosition(len("[ ] task one") + 1)  # the blank line
    cur.clearSelection()
    ta.setTextCursor(cur)
    before = ta.toPlainText()
    ta._toggle_checkboxes()
    assert ta.toPlainText() == before


def test_inline_timestamp_refresh_glyph(win):
    import re as _re

    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Log (01.01 - 00:00)\n\nbody"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    block = ta.document().firstBlock()
    # the stamped line exposes an inline refresh glyph right after the text
    rect = ta._ts_glyph_rect(block)
    assert rect is not None
    # a real click on the glyph re-stamps the line to now
    center = rect.center()
    pt = center.toPointF() if hasattr(center, "toPointF") else center
    ta.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    # button shows the pushed state between press and release
    assert ta._ts_pressed_block == 0
    ta.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert ta._ts_pressed_block is None
    first = ta.document().firstBlock().text()
    assert "(01.01 - 00:00)" not in first
    assert _re.search(r"\(.*?\d{2}\.\d{2} - \d{2}:\d{2}.*?\)", first)
    assert first.startswith("# Log ")
    # plain lines get no glyph
    win.data["temp_presets"][:] = ["plain text"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    assert ta._ts_glyph_rect(ta.document().firstBlock()) is None


def test_code_fence_gutter_and_states(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["show_line_numbers"] = "False"
    win.preview_combo.setCurrentIndex(1)  # Live Preview attaches the highlighter
    code = "intro\n```python\ndef hello():\n    return 42\n```\nafter"
    win.data["temp_presets"][:] = [code]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    ta._refresh_checkbox_flag()
    # code detected -> gutter auto-appears even with line numbers off
    assert ta._doc_has_code is True
    assert ta.line_number_area_width() > 0
    # highlighter tracked the fence: inner code lines carry the CODE bit
    from fastprompter.ui.markdown_highlighter import CODE_BIT

    win.highlighter.rehighlight()
    doc = ta.document()
    assert max(0, doc.findBlockByNumber(1).userState()) & CODE_BIT  # ```python
    assert max(0, doc.findBlockByNumber(2).userState()) & CODE_BIT  # def hello():
    assert not max(0, doc.findBlockByNumber(5).userState()) & CODE_BIT  # after
    # plain text -> flag clears and the gutter hides again
    win.data["temp_presets"][:] = ["no code here"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta._refresh_checkbox_flag()
    assert ta._doc_has_code is False
    assert ta.line_number_area_width() == 0


def test_margin_marks_survive_code_highlighting(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.preview_combo.setCurrentIndex(1)
    win.data["temp_presets"][:] = ["```\ncode line\n```"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    win.highlighter.rehighlight()
    from fastprompter.ui.markdown_highlighter import CODE_BIT

    block = ta.document().findBlockByNumber(1)
    assert max(0, block.userState()) & CODE_BIT
    # place a margin mark on the code line the same way the gutter click does
    state = max(0, block.userState())
    mark = state & 0xFF
    block.setUserState((state & ~0xFF) | ((mark + 1) % 4))
    assert max(0, block.userState()) & 0xFF == 1
    assert max(0, block.userState()) & CODE_BIT  # code bit intact
    # a rehighlight must NOT wipe the mark
    win.highlighter.rehighlight()
    block = ta.document().findBlockByNumber(1)
    assert max(0, block.userState()) & 0xFF == 1
    assert max(0, block.userState()) & CODE_BIT


def test_bold_hash_titles_toggle(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["bold_hash_titles"] = "True"
    win.data["temp_presets"][:] = ["# Important title\nbody", "plain silo"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_temp_presets()
    assert win.silo_buttons[0].global_idx in (0, 1)
    by_idx = {b.global_idx: b for b in win.silo_buttons[:2]}
    assert by_idx[0]._lbl_text.font().bold() is True
    assert by_idx[1]._lbl_text.font().bold() is False
    # toggle off -> refresh -> no bold
    win.data["bold_hash_titles"] = "False"
    win.refresh_temp_presets()
    by_idx = {b.global_idx: b for b in win.silo_buttons[:2]}
    assert by_idx[0]._lbl_text.font().bold() is False
    win.data["bold_hash_titles"] = "True"

    # snippets: a '#'-starting snippet gets a bold sidebar title
    cat = win.get_current_category()
    win.data["categories"][cat][0] = {"name": "hdr", "text": "# heading note", "last_edited": 0}
    win.data["categories"][cat][1] = {"name": "plain", "text": "just text", "last_edited": 0}
    win.refresh_snippets_panel()
    assert win.snippet_buttons[0].main_btn.font().bold() is True
    assert win.snippet_buttons[1].main_btn.font().bold() is False
    win.data["categories"][cat][0] = None
    win.data["categories"][cat][1] = None
    win.refresh_snippets_panel()


def test_code_block_copy_button(win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication as _QApp

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["```python\nprint(1)\nprint(2)\n```\nafter"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    opener = ta.document().firstBlock()
    assert ta._fence_is_opener(opener) is True
    closer = ta.document().findBlockByNumber(3)
    assert ta._fence_is_opener(closer) is False
    rect = ta._code_copy_rect(opener)
    center = rect.center()
    for etype in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(etype,
                         center.toPointF() if hasattr(center, "toPointF") else center,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        if etype == QEvent.Type.MouseButtonPress:
            ta.mousePressEvent(ev)
        else:
            ta.mouseReleaseEvent(ev)
    assert _QApp.clipboard().text() == "print(1)\nprint(2)"


def test_file_container_slug_and_dirs(win):
    from fastprompter.ui.file_container import silo_files_dir, silo_slug

    assert silo_slug("# My **Cool** Title\nbody") == "my-cool-title"
    assert silo_slug("") == "untitled"
    assert silo_slug("!!!???") == "untitled"
    assert silo_slug("x" * 100).startswith("x")
    assert len(silo_slug("x" * 100)) <= 40
    d = silo_files_dir(_tmpdir, "Main", "# Hello World")
    assert d.endswith(os.path.join("main", "hello-world"))


def test_file_container_import_export_delete(win):
    from fastprompter.ui.file_container import FileContainerPanel, silo_file_count

    root = os.path.join(_tmpdir, "files_root")
    src_dir = os.path.join(_tmpdir, "files_src")
    os.makedirs(src_dir, exist_ok=True)
    src = os.path.join(src_dir, "note.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write("hello")

    panel = FileContainerPanel(win)
    panel.open_for(root, "Main", "# Asset Silo")
    assert os.path.isdir(panel.folder)

    panel.import_paths([src])
    assert os.path.isfile(os.path.join(panel.folder, "note.txt"))
    assert panel.file_list.count() == 1
    # same name again -> collision-safe copy, not overwrite
    panel.import_paths([src])
    assert os.path.isfile(os.path.join(panel.folder, "note (2).txt"))
    assert panel.file_list.count() == 2
    assert silo_file_count(root, "Main", "# Asset Silo") == 2

    # reopening for the same title lands in the same folder (reorder-stable)
    panel.open_for(root, "Main", "# Asset Silo\nnew body text")
    assert panel.file_list.count() == 2

    export_dir = os.path.join(_tmpdir, "files_export")
    os.makedirs(export_dir, exist_ok=True)
    import shutil as _sh
    for n in os.listdir(panel.folder):
        _sh.copy2(os.path.join(panel.folder, n), export_dir)
    assert sorted(os.listdir(export_dir)) == ["note (2).txt", "note.txt"]
    panel.close()


def test_header_fits_quarter_fullhd_with_full_clock(win):
    # Ctrl+Q quarter snap (960x540): seconds + day word + text month must
    # ALL fit — dense mode packs buttons instead of degrading the clock
    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "True"
    win.data["date_daypart"] = "True"
    win.data["date_text_month"] = "True"
    win.data["analog_clock"] = "True"
    win.resize(960, 540)
    win._header_dense = None
    win._apply_header_density()
    win._update_date_label()
    assert win._header_dense is True
    # full clock string survived (seconds present, day word present)
    import re as _re
    assert _re.search(r"\d{2}:\d{2}:\d{2} · (Morning|Day|Evening|Night)",
                      win.lbl_date.text()), win.lbl_date.text()
    total = win.header_widget.sizeHint().width()
    assert total <= 960, f"header wants {total}px at quarter-FullHD"
    # restore defaults used by other tests
    win.data["date_text_month"] = "False"
    win.data["analog_clock"] = "False"
    win._header_dense = None
    win._apply_header_density()
    win._update_date_label()


def test_header_ultra_mode_fits_portrait_sliver(win):
    # 9:16-friendly: below 700px only the essentials remain and the
    # header still fits; clock shrinks to DD.MM - hh:mm
    import re as _re
    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "True"
    win.data["date_daypart"] = "True"
    win.resize(500, 900)
    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    win._update_date_label()
    assert win._header_ultra is True
    assert _re.fullmatch(r"\d{2}\.\d{2} - \d{2}:\d{2}", win.lbl_date.text())
    for name in ("btn_bold", "btn_copy", "btn_clear", "btn_home",
                 "btn_pin_top", "btn_line_nums", "btn_help"):
        assert getattr(win, name).isHidden(), name
    for name in ("btn_new", "btn_save", "btn_settings_toggle"):
        assert not getattr(win, name).isHidden(), name
    total = win.header_widget.sizeHint().width()
    assert total <= 500, f"ultra header wants {total}px"
    # files button lives in the sidebar now, not the header
    assert win.btn_files.parent() is not win.header_widget
    # widen back: everything returns
    win.resize(1400, 700)
    win._apply_header_density()
    win._update_date_label()
    assert not win.btn_copy.isHidden()
    assert win._header_ultra is False


def test_drop_overlay_zones_and_routing(win):
    from PyQt6.QtCore import QPoint

    ta = win.text_area
    ov = ta._drop_overlay()
    # 4 zones for text files: top_left=text, bot_left=files, top_right=editor_link, bot_right=files_link
    ov.begin(has_text_option=True)
    assert not ov.isHidden()
    h = ov.height()
    w = ov.width()
    assert ov.zone_at(QPoint(10, 5)) == "text"
    assert ov.zone_at(QPoint(w - 10, 5)) == "editor_link"
    assert ov.zone_at(QPoint(10, h - 5)) == "files"
    assert ov.zone_at(QPoint(w - 10, h - 5)) == "files_link"
    ov.track(QPoint(10, h - 5))
    assert ov._hot == "files"
    # 3 zones for binary-only drags
    ov.begin(has_text_option=False)
    assert ov.zone_at(QPoint(10, 5)) == "files"
    assert ov.zone_at(QPoint(10, h // 2)) == "files_link"
    assert ov.zone_at(QPoint(10, h - 5)) == "editor_link"
    ov.end()
    assert ov.isHidden()

    # routing: text zone inserts content, files zone goes to the container
    win.data["temp_presets"][:] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    src = os.path.join(_tmpdir, "routed.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write("routed text")
    ta._drop_paths([src], "text")
    assert "routed text" in ta.toPlainText()
    sent = []
    win.add_files_to_active_silo = lambda paths: sent.extend(paths)
    ta._drop_paths([src], "files")
    assert sent == [src]
    del win.__dict__["add_files_to_active_silo"]


def test_trash_silo_writes_md_and_removes_slot(win):
    root = os.path.join(_tmpdir, "files_root_trash2")
    win._files_root = lambda: root
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Doomed Silo\nprecious text", "stays"]
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.trash_silo(0)
    assert win.data["temp_presets"] == ["stays"]
    trash = os.path.join(root, "_trash")
    mds = [n for n in os.listdir(trash) if n.startswith("doomed-silo") and n.endswith(".md")]
    assert len(mds) == 1
    with open(os.path.join(trash, mds[0]), encoding="utf-8") as f:
        assert "precious text" in f.read()
    del win.__dict__["_files_root"]


def test_hide_on_clickout_toggle_and_header_mirrors(win):
    before = win.cb_focus.isChecked()
    win.toggle_hide_on_clickout()
    assert win.cb_focus.isChecked() != before
    win.toggle_hide_on_clickout()
    assert win.cb_focus.isChecked() == before

    # header 📌 / # buttons mirror their checkboxes both ways
    win.cb_top.setChecked(True)
    assert win.btn_pin_top.isChecked() is True
    win.cb_top.setChecked(False)
    assert win.btn_pin_top.isChecked() is False
    win.btn_line_nums.setChecked(True)
    assert win.cb_line_numbers.isChecked() is True
    win.btn_line_nums.setChecked(False)
    assert win.cb_line_numbers.isChecked() is False


def test_theme_switch_keeps_button_labels(win):
    win.resize(1400, 700)  # non-dense: full labels expected
    win.data["theme"] = "Default"
    win.apply_theme()
    win._header_dense = None
    win._apply_header_density()
    assert win.btn_copy.text() == "Copy"
    win.data["theme"] = "OLED" if "OLED" in __import__("fastprompter.theme.themes", fromlist=["THEMES"]).THEMES else "Default"
    win.apply_theme()
    win._header_dense = None
    win._apply_header_density()
    # labels survive the repack — no truncation to fixed stale widths
    assert win.btn_copy.text()
    assert win.btn_clear.text()
    assert win.btn_save.minimumWidth() <= max(1, win.btn_save.fontMetrics().horizontalAdvance(win.btn_save.text()) + 8)
    win.data["theme"] = "Default"
    win.apply_theme()


def test_live_retitle_renames_folder_no_duplicates(win):
    # 1 silo = 1 folder: typing a new title renames the folder at once —
    # opening the container right after a retitle must find the SAME folder
    from fastprompter.ui.file_container import silo_files_dir

    root = os.path.join(_tmpdir, "files_root_live")
    win._files_root = lambda: root
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Old Title\nbody"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    folder = silo_files_dir(root, win.get_current_category(), "# Old Title")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "asset.bin"), "wb") as f:
        f.write(b"x")

    # live edit of the first line (textChanged fires the sync)
    win.text_area.setPlainText("# New Title\nbody")
    new_folder = silo_files_dir(root, win.get_current_category(), "# New Title")
    assert os.path.isfile(os.path.join(new_folder, "asset.bin"))
    assert not os.path.exists(folder)
    cat_dir = os.path.dirname(new_folder)
    assert len(os.listdir(cat_dir)) == 1, "exactly one folder per silo"
    del win.__dict__["_files_root"]


def test_move_silo_to_top_and_bottom_remap(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["a", "b", "c"]
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = [2]
    win.data["silo_children"].clear()
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._move_silo_to_top(2)
    assert win.data["temp_presets"] == ["c", "a", "b"]
    assert win.data["silo_ticked"] == [0]  # tick followed the silo
    win._move_silo_to_bottom(0)
    assert win.data["temp_presets"] == ["a", "b", "c"]
    assert win.data["silo_ticked"] == [2]
    win.data["silo_ticked"][:] = []


def test_silo_hierarchy_nest_collapse_promote(win):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMessageBox as _QMB

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["parent", "childA", "loner", "childB"]
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = []
    win.data["silo_children"].clear()
    win.data["silo_collapsed"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    # nest two children under parent (no files -> no dialog)
    win.make_silo_child(1, 0)
    win.make_silo_child(3, 0)
    assert win.data["silo_children"] == {0: [1, 3]}
    # alias holds
    cat = win.get_current_category()
    assert win.data["silo_children_all"][cat] is win.data["silo_children"]

    # no grandchildren: nesting onto a child is refused
    win.make_silo_child(2, 1)
    assert win.silo_parent_of(2) is None

    # display order: parent, kids, then loner
    win.refresh_temp_presets()
    shown = [b.global_idx for b in win.silo_buttons if not b.isHidden()]
    assert shown[:4] == [0, 1, 3, 2]
    assert win.silo_buttons[0]._btn_collapse.text().startswith("▾")
    assert win.silo_buttons[1].full_name.startswith("↳")

    # collapse hides children
    win.toggle_silo_collapse(0)
    shown = [b.global_idx for b in win.silo_buttons if not b.isHidden()]
    assert shown[:2] == [0, 2] and 1 not in shown and 3 not in shown
    win.toggle_silo_collapse(0)

    # deleting the parent promotes the children
    with patch.object(_QMB, "question", return_value=_QMB.StandardButton.Yes):
        win.del_silo(0)
    assert win.data["silo_children"] == {}
    assert win.data["temp_presets"] == ["childA", "loner", "childB"]

    # unnest by hand
    win.make_silo_child(1, 0)
    assert win.silo_parent_of(1) == 0
    win.unnest_silo(1)
    assert win.silo_parent_of(1) is None
    win.data["silo_children"].clear()


def test_silo_tick_toggle_persists_and_remaps(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["a", "b", "c"]
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    win._toggle_tick_silo(2)
    assert 2 in win.data["silo_ticked"]
    # alias check: the per-category store sees the same list
    cat = win.get_current_category()
    assert win.data["silo_ticked_all"][cat] is win.data["silo_ticked"]
    # deleting an earlier silo remaps the tick index
    win.del_silo(0)
    assert win.data["silo_ticked"] == [1]
    # toggle off
    win._toggle_tick_silo(1)
    assert win.data["silo_ticked"] == []


def test_delete_silo_keeps_snippets_visible(win):
    # Regression check for "deleting a silo hides a snippet"
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.get_current_category()
    win.data["categories"][cat] = [None] * 100
    for i in range(3):
        win.data["categories"][cat][i] = {"name": f"snip{i}", "text": f"body{i}"}
    win.data["temp_presets"][:] = ["one", "two", "three"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_snippets_panel()
    visible_before = sum(1 for b in win.snippet_buttons if not b.isHidden())
    assert visible_before == 3
    win.del_silo(1)
    visible_after = sum(1 for b in win.snippet_buttons if not b.isHidden())
    assert visible_after == 3, "snippet buttons must survive a silo delete"
    win.data["categories"][cat] = [None] * 100
    win.refresh_snippets_panel()


def test_header_restamp_keeps_files_folder(win):
    # Regression: Ctrl+E re-stamping the title changed the slug and buried
    # the silo's files under a fresh folder. Timestamps are slug-invisible
    # and retitles rename the folder in the switch path.
    from fastprompter.ui.file_container import silo_files_dir, silo_slug

    assert silo_slug("# CODE (17.07 - 04:19)") == silo_slug("# CODE (18.07 - 09:00:11)")
    assert silo_slug("# CODE (17 Jul - 04:19)") == "code"

    root = os.path.join(_tmpdir, "files_root_restamp")
    win._files_root = lambda: root
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Proj (17.07 - 01:00)\nbody", "other"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    folder = silo_files_dir(root, win.get_current_category(), "# Proj (17.07 - 01:00)")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "asset.txt"), "w", encoding="utf-8") as f:
        f.write("keep me")

    # re-stamp (same slug) — folder untouched
    win.text_area.setPlainText("# Proj (18.07 - 02:22)\nbody")
    win._switch_to_slot(1)
    assert os.path.isfile(os.path.join(folder, "asset.txt"))

    # real retitle — folder follows
    win._switch_to_slot(0)
    win.text_area.setPlainText("# Renamed Proj\nbody")
    win._switch_to_slot(1)
    new_folder = silo_files_dir(root, win.get_current_category(), "# Renamed Proj")
    assert os.path.isfile(os.path.join(new_folder, "asset.txt"))
    assert not os.path.exists(folder)
    del win.__dict__["_files_root"]


def test_fold_code_blocks_and_headers(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [
        "# Title\nbody1\nbody2\n# Next\nother\n```python\ncode1\ncode2\n```\ntail"
    ]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()

    # header fold: hides body1+body2, stops before "# Next"
    header = doc.firstBlock()
    assert ta._is_fold_anchor(header)
    first, last = ta._fold_range(header)
    assert first.text() == "body1" and last.text() == "body2"
    ta.toggle_fold(header)
    assert not doc.findBlockByNumber(1).isVisible()
    assert not doc.findBlockByNumber(2).isVisible()
    assert doc.findBlockByNumber(3).isVisible()  # "# Next" survives
    assert max(0, header.userState()) & ta.FOLD_BIT
    ta.toggle_fold(header)
    assert doc.findBlockByNumber(1).isVisible()
    assert not (max(0, header.userState()) & ta.FOLD_BIT)

    # fence fold: hides code lines through the closing fence
    fence = doc.findBlockByNumber(5)
    assert ta._is_fold_anchor(fence)
    ta.toggle_fold(fence)
    assert not doc.findBlockByNumber(6).isVisible()
    assert not doc.findBlockByNumber(8).isVisible()  # closing ```
    assert doc.findBlockByNumber(9).isVisible()      # tail

    # text survives folding intact; unfold_all restores everything
    assert "code1" in ta.toPlainText()
    ta.unfold_all()
    b = doc.firstBlock()
    while b.isValid():
        assert b.isVisible()
        b = b.next()


def test_file_container_views_links_clipboard(win):
    from PyQt6.QtWidgets import QApplication as _QApp

    from fastprompter.ui.file_container import FileContainerPanel

    root = os.path.join(_tmpdir, "files_root_views")
    panel = FileContainerPanel(win)
    panel.open_for(root, "Main", "# Views Silo")

    # view cycle: Details -> Icons -> List -> Details, persisted in data
    assert panel._view_mode() == "Details"
    panel._cycle_view()
    assert win.data["file_panel_view"] == "Icons"
    panel._cycle_view()
    assert win.data["file_panel_view"] == "List"
    panel._cycle_view()
    assert win.data["file_panel_view"] == "Details"

    # link import: .url file pointing at the original, no copy
    target = os.path.join(_tmpdir, "linked_asset.psd")
    with open(target, "wb") as f:
        f.write(b"fake")
    panel.import_links([target])
    url_path = os.path.join(panel.folder, "linked_asset.psd.url")
    assert os.path.isfile(url_path)
    with open(url_path, encoding="utf-8") as f:
        body = f.read()
    assert body.startswith("[InternetShortcut]")
    assert "linked_asset.psd" in body
    assert not os.path.exists(os.path.join(panel.folder, "linked_asset.psd"))

    # clipboard -> file (prompts for a name; mock the dialog)
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog
    _QApp.clipboard().setText("clipboard payload")
    with patch.object(QInputDialog, "getText", return_value=("clip-test", True)):
        panel.save_clipboard_as_file()
    clips = [n for n in os.listdir(panel.folder) if n.startswith("clip-") and n.endswith(".txt")]
    assert len(clips) == 1
    with open(os.path.join(panel.folder, clips[0]), encoding="utf-8") as f:
        assert f.read() == "clipboard payload"

    # tooltip summary knows counts and sizes
    from fastprompter.ui.file_container import folder_summary
    tip = folder_summary(root, "Main", "# Views Silo")
    assert "2 item(s)" in tip and ".url" in tip and ".txt" in tip
    panel.close()


def test_files_root_configurable_and_header_counter(win):
    custom = os.path.join(_tmpdir, "custom_files_root")
    os.makedirs(custom, exist_ok=True)
    win.data["files_root"] = custom
    assert win._files_root() == custom
    win.data["files_root"] = ""
    assert win._files_root().endswith(os.path.join("data", "files"))
    win.data["files_root"] = custom

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Counter Silo"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    from fastprompter.ui.file_container import silo_files_dir
    folder = silo_files_dir(custom, win.get_current_category(), "# Counter Silo")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "a.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    win._update_files_button()
    assert win.btn_files.text() == "📁1"
    assert "1 item(s)" in win.btn_files.toolTip()
    win.data["files_root"] = ""
    win._update_files_button()


def test_clear_silo_moves_files_to_trash_not_delete(win):
    # Regression: clearing a silo must NEVER destroy its container files —
    # they go to data/files/_trash/ (silo text is undoable; files can't be less safe)
    root = os.path.join(_tmpdir, "files_root_trash")
    win._files_root = lambda: root  # keep the test out of the real data dir
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Trash Test Silo", "other"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    from fastprompter.ui.file_container import silo_files_dir
    folder = silo_files_dir(root, win.get_current_category(), "# Trash Test Silo")
    os.makedirs(folder, exist_ok=True)
    keep = os.path.join(folder, "precious.txt")
    with open(keep, "w", encoding="utf-8") as f:
        f.write("do not lose me")

    win.clear_temp(0)
    assert not os.path.exists(keep)  # moved away from the silo folder
    trash = os.path.join(root, "_trash")
    rescued = []
    for base, _dirs, files in os.walk(trash):
        rescued += [os.path.join(base, n) for n in files if n == "precious.txt"]
    assert rescued, "file must survive in _trash after silo clear"
    with open(rescued[0], encoding="utf-8") as f:
        assert f.read() == "do not lose me"


def test_file_container_button_wired(win):
    assert win.btn_files is not None
    assert callable(win.open_file_container)
    assert win.silo_buttons[0]._btn_files.toolTip().startswith("Files")


def test_header_line_number_button_fast_toggles(win):
    # The header # button must reliably flip the line-number gutter and stay
    # in sync with the settings checkbox (no dead first click from drift).
    win.text_area.setPlainText("a\nb\nc")
    win.set_line_numbers(False)
    assert win.text_area.line_number_area_width() == 0
    assert not win.btn_line_nums.isChecked()
    assert not win.cb_line_numbers.isChecked()

    win.btn_line_nums.click()  # one click enables
    assert win.data["show_line_numbers"] == "True"
    assert win.text_area.line_number_area_width() > 0
    assert win.btn_line_nums.isChecked() and win.cb_line_numbers.isChecked()

    win.btn_line_nums.click()  # one click disables
    assert win.data["show_line_numbers"] == "False"
    assert win.text_area.line_number_area_width() == 0

    # settings checkbox mirrors back to the header button
    win.cb_line_numbers.click()
    assert win.btn_line_nums.isChecked() is True
    win.set_line_numbers(False)


def test_open_file_container_actually_opens(win):
    # Regression: open_file_container had its FileContainerPanel import at
    # class-body scope, invisible to the method -> NameError on first open.
    win.data["temp_presets"][:] = ["# Assets silo", "other"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._file_container = None
    win.open_file_container(0)  # must not raise
    from fastprompter.ui.file_container import FileContainerPanel
    assert isinstance(win._file_container, FileContainerPanel)
    win._file_container.close()


def test_date_rectangle_formats_and_toggles(win):
    import re
    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "True"
    win.data["date_daypart"] = "False"
    win._update_date_label()
    assert re.fullmatch(r".*?\d{2}\.\d{2} - \d{2}:\d{2}(:\d{2})?.*?", win.lbl_date.text())
    win.data["date_seconds"] = "False"
    win._update_date_label()
    assert re.fullmatch(r"\d{2}\.\d{2} - \d{2}:\d{2}(:\d{2})?", win.lbl_date.text())
    win.data["date_daypart"] = "True"
    win.resize(1920, 1080)
    win._update_date_label()
    assert re.fullmatch(
        r"\d{2}\.\d{2} - \d{2}:\d{2}(:\d{2})?( · (Morning|Day|Evening|Night))?",
        win.lbl_date.text())
    assert win._day_part(6) == "Morning"
    assert win._day_part(13) == "Day"
    assert win._day_part(19) == "Evening"
    assert win._day_part(2) == "Night"
    win.data["show_date_rect"] = "False"
    win._update_date_label()
    assert win.lbl_date.isVisible() is False
    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "True"


def test_divider_spacing_configurable(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["divider_lines_before"] = "1"
    win.data["divider_lines_after"] = "2"
    win.data["temp_presets"][:] = ["x"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_old_add_line()
    assert win.text_area.toPlainText() == "x\n---\n\n• "
    win.data["divider_lines_before"] = "2"
    win.data["divider_lines_after"] = "3"
    win.data["temp_presets"][:] = ["x"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_old_add_line()
    assert win.text_area.toPlainText() == "x\n\n---\n\n\n• "


def test_ctrl_e_header_timestamp(win):
    import re

    win.data["temp_presets"] = ["My heading"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.apply_header_timestamp()
    text = win.text_area.toPlainText()
    line = text.splitlines()[0]
    assert line.startswith("# **__My heading__** ("), line
    assert re.search(r"\(.*?\d{2}\.\d{2} - \d{2}:\d{2}.*?\)$", line), line
    # Cursor jumped two lines below onto a fresh plain bullet
    cur = win.text_area.textCursor()
    assert cur.blockNumber() == 2, text
    assert cur.block().text() == "\u2022 "
    fmt = win.text_area.currentCharFormat()
    assert fmt.fontWeight() < 700 and not fmt.fontUnderline()
    # Press again ON the header line: title untouched, stamp REFRESHED
    # in place (no duplicates), no extra blank lines, cursor jumps below
    back = win.text_area.textCursor()
    back.setPosition(0)
    win.text_area.setTextCursor(back)
    win.apply_header_timestamp()
    line2 = win.text_area.toPlainText().splitlines()[0]
    assert line2 == "My heading", line2


def test_ctrl_e_refreshes_stale_stamp_in_place(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# **__Journal__** (01.01 - 00:00)\n\n\u2022 old entry"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cur = win.text_area.textCursor()
    cur.setPosition(0)
    win.text_area.setTextCursor(cur)
    win.apply_header_timestamp()
    line = win.text_area.toPlainText().splitlines()[0]
    assert line == "Journal", line
    assert "\u2022 old entry" in win.text_area.toPlainText()


def test_transfer_to_snippet_target_category(win):
    cats = win.data["cats_order"]
    target = cats[1] if len(cats) > 1 else cats[0]
    win.data["temp_presets"] = ["transfer this text"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._transfer_to_snippet(0, False, target_cat=target)
    texts = [s["text"] for s in win.data["categories"][target] if s]
    assert "transfer this text" in texts


def test_sounds_do_not_crash_and_fall_back(win):
    from fastprompter.core.sound_manager import _SOUND_FALLBACKS, _SOUND_FILE_MAP

    win.data["sound_ui"] = "True"
    win.data["sound_typewriter"] = "True"
    for name in _SOUND_FILE_MAP:
        win.play_sound(name)  # missing files must fall back / no-op, never raise
    sounds_dir = win.sound_manager._sounds_dir
    for preferred, fallback in _SOUND_FALLBACKS.items():
        assert os.path.exists(os.path.join(sounds_dir, fallback)), fallback
    win.data["sound_ui"] = "False"
    win.data["sound_typewriter"] = "False"


def test_zebra_and_line_numbers_paint(win):
    win.data["zebra_lines"] = "True"
    win.data["show_line_numbers"] = "True"
    win.data["temp_presets"] = ["\n".join(f"line {i}" for i in range(30))]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.text_area.update_line_number_area_width()
    win.show()
    _app.processEvents()
    pixmap = win.text_area.grab()  # forces a real paintEvent pass
    assert not pixmap.isNull()
    win.hide()
    win.data["zebra_lines"] = "False"
    win.data["show_line_numbers"] = "False"


def test_paging_clamped(win):
    win.data["temp_presets"] = ["a"] * 3
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.silo_page = 0
    win.change_silo_page(1)  # only one page of content
    assert win.silo_page == 0
    win.change_silo_page(-1)
    assert win.silo_page == 0


def _wheel(widget, delta_y, ctrl=False):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent

    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    ev = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta_y),
        Qt.MouseButton.NoButton, mods,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(widget, ev)


def test_mouse_wheel_pages_silos(win):
    win.resize(600, 400)
    win.data["temp_presets"] = [f"silo {i}" for i in range(25)]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.silo_page = 0
    win.refresh_temp_presets()
    _wheel(win.silos_section, -120)  # wheel down → next page
    assert win.silo_page == 1
    _wheel(win.silos_section, 120)  # wheel up → back
    assert win.silo_page == 0
    _wheel(win.silos_section, 120)  # clamped at first page
    assert win.silo_page == 0


def test_ctrl_wheel_selects_silos(win):
    win.data["temp_presets"] = [f"silo {i}" for i in range(5)]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    _wheel(win.silos_section, -120, ctrl=True)  # Ctrl+wheel down → next silo
    assert win.active_temp_slot == 1
    _wheel(win.silos_section, -120, ctrl=True)
    assert win.active_temp_slot == 2
    _wheel(win.silos_section, 120, ctrl=True)  # Ctrl+wheel up → previous silo
    assert win.active_temp_slot == 1
    win.silo_page = 0
    _wheel(win.silos_section, -120)  # plain wheel still pages, not selects
    assert win.active_temp_slot == 1


def test_line_number_margin_marks_paint(win):
    # Regression: QPen was used unimported in line_number_area_paint_event —
    # crashed the moment any margin mark was drawn. Exercise all 4 marks.
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPaintEvent

    win.data["line_marks"] = "True"
    ta = win.text_area
    ta.setPlainText("alpha\nbeta")
    blk = ta.document().firstBlock()
    ev = QPaintEvent(QRect(0, 0, 40, 60))
    for mark in (1, 2, 3, 4):  # checkbox, red dot, yellow rhombus, blue square
        blk.setUserState(mark)
        ta.line_number_area_paint_event(ev)  # must not raise
    win.data["line_marks"] = "False"


def test_no_cyrillic_in_codebase():
    import glob
    import re

    # Cyrillic + Cyrillic Supplement blocks, written as escapes so this
    # file doesn't flag itself.
    cyr = re.compile("[\\u0400-\\u04FF\\u0500-\\u052F]")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    offenders = []
    for pattern in ("src/**/*.py", "tests/**/*.py", "tests_smoke/*.py", "tools/*.py"):
        for f in glob.glob(os.path.join(root, pattern), recursive=True):
            if "__pycache__" in f:
                continue
            # translations.py is the RU/EN dictionary — Cyrillic is its job
            if os.path.basename(f) == "translations.py":
                continue
            with open(f, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if cyr.search(line):
                        offenders.append(f"{f}:{i}")
    assert not offenders, f"Cyrillic characters found: {offenders}"


def test_mouse_wheel_switches_tabs(win):
    if win.cat_combo.count() < 2:
        import pytest as _pytest

        _pytest.skip("needs at least two tabs")
    win.cat_combo.setCurrentIndex(0)
    _wheel(win.cat_combo, -120)  # wheel down → next tab
    assert win.cat_combo.currentIndex() == 1
    _wheel(win.cat_combo, 120)  # wheel up → previous tab
    assert win.cat_combo.currentIndex() == 0


def test_escape_closes_search_before_hiding(win):
    win.show()
    _app.processEvents()
    win.show_find()
    assert win.search_frame.isVisible()
    win._on_escape()  # first Esc: closes search, window stays
    assert not win.search_frame.isVisible()
    assert win.isVisible()
    win._on_escape()  # second Esc: hides the window
    assert not win.isVisible()


def test_add_category_capped_at_five(win):
    from unittest.mock import patch

    win.data["cats_order"] = ["A", "B", "C", "D", "E"]
    before = list(win.data["cats_order"])
    with patch("fastprompter.main.QMessageBox"):  # suppress blocking info dialog
        win.add_category()
    assert win.data["cats_order"] == before
