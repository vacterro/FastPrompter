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
    win.insert_divider_line()
    assert "hello world\n\n---\n\n" in win.text_area.toPlainText()


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


def test_button_scale_persists_to_db(win):
    win.data["button_scale"] = "1.0"
    win.cycle_button_scale()  # 1.0 -> 1.25, saves to DB
    assert win.data["button_scale"] == "1.25"
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
    for scale in ("0.5", "0.75", "1.0"):
        win.data["button_scale"] = scale
        btn = QPushButton("Clear Fmt")
        win.apply_button_size(btn, 24)
        sizes[scale] = (btn.height(), round(btn.font().pointSizeF(), 1))
    assert sizes["0.5"][0] < sizes["0.75"][0] < sizes["1.0"][0], sizes
    # fonts shrink below 100% so text isn't clipped
    assert sizes["0.5"][1] < sizes["1.0"][1]
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
    win.tab_bar.setCurrentIndex(0)
    win.on_tab_changed(0)  # ensure alias points at tab A
    win.data["temp_presets"][0] = "tab A treasure"
    while len(win.data["temp_presets"]) < 2:
        win.data["temp_presets"].append("")
    win.data["temp_presets"][1] = "other"
    win._switch_to_slot(1, initial=True)
    win.clear_temp(0)  # destroy the treasure on tab A
    assert win.data["temp_presets_all"][a][0] == ""
    win.tab_bar.setCurrentIndex(1)  # user wanders to tab B
    win._smart_undo()  # Ctrl+Z must return to tab A and restore
    assert win.get_current_category() == a
    assert win.data["temp_presets"][0] == "tab A treasure"
    # The alias must be intact — otherwise the restore dies on tab switch
    assert win.data["temp_presets_all"][a] is win.data["temp_presets"]


def test_undone_data_survives_tab_roundtrip_and_db_save(win):
    cats = win.data["cats_order"]
    a = cats[0]
    win.tab_bar.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][0] = "must survive"
    win._switch_to_slot(0, initial=True)
    win.clear_temp(0)
    win._smart_undo()
    assert win.text_area.toPlainText() == "must survive"
    # tab away and back — restored data must not evaporate
    win.tab_bar.setCurrentIndex(1)
    win.tab_bar.setCurrentIndex(0)
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
    win.tab_bar.setCurrentIndex(0)
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
    win.tab_bar.setCurrentIndex(0)
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
    win.tab_bar.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.get_current_category()
    win.data["archive_temp_presets"][:] = ["keep", "", "also keep", ""]
    win._trim_archive()
    assert win.data["archive_temp_presets"] == ["keep", "also keep"]
    # the rebind must reach the backing store or the trim never persists
    assert win.data["archive_temp_presets_all"][cat] is win.data["archive_temp_presets"]


def test_new_silo_at_top_shifts_pins(win):
    win.tab_bar.setCurrentIndex(0)
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
    win.tab_bar.setCurrentIndex(0)
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
        ("tab", lambda: (win.tab_bar.setCurrentIndex(rng.randrange(win.tab_bar.count())))),
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
    win.tab_bar.setCurrentIndex(0)
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
        ("tab", lambda: win.tab_bar.setCurrentIndex(rng.randrange(win.tab_bar.count()))),
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

    win.tab_bar.setCurrentIndex(0)
    win.on_tab_changed(0)
    cats_before = list(win.data["cats_order"])
    if len(cats_before) < 2:
        pytest.skip("needs two tabs")
    win.tab_bar.setCurrentIndex(1)
    victim = win.data["cats_order"][1]
    win.data["categories"][victim][0] = {"name": "keep", "text": "keep me", "last_edited": 0}
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        win.del_category()
    assert victim not in win.data["cats_order"]
    win._smart_undo()
    assert victim in win.data["cats_order"], "deleted tab not restored by undo"
    assert win.data["categories"][victim][0]["text"] == "keep me"
    assert win.tab_bar.count() == len(win.data["cats_order"])


def test_ctrl_e_header_timestamp(win):
    import re

    win.data["temp_presets"] = ["My heading"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.apply_header_timestamp()
    line = win.text_area.toPlainText().splitlines()[0]
    assert line.startswith("# My heading")
    assert re.search(r"\(\d{2}\.\d{2} - \d{2}:\d{2}\)$", line), line
    # Second press must not stack another header or timestamp
    win.apply_header_timestamp()
    line2 = win.text_area.toPlainText().splitlines()[0]
    assert line2 == line


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
            with open(f, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if cyr.search(line):
                        offenders.append(f"{f}:{i}")
    assert not offenders, f"Cyrillic characters found: {offenders}"


def test_mouse_wheel_switches_tabs(win):
    if win.tab_bar.count() < 2:
        import pytest as _pytest

        _pytest.skip("needs at least two tabs")
    win.tab_bar.setCurrentIndex(0)
    _wheel(win.tab_bar, -120)  # wheel down → next tab
    assert win.tab_bar.currentIndex() == 1
    _wheel(win.tab_bar, 120)  # wheel up → previous tab
    assert win.tab_bar.currentIndex() == 0


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
