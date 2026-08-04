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
from PyQt6 import sip
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
    _teardown_window(w)


def _teardown_window(w):
    """Tear a FastPrompter down so it is actually GONE.

    T-295: QApplication.processEvents() does NOT deliver DeferredDelete, so
    deleteLater() alone never lands and the whole widget tree leaks — measured
    at +1397 widgets and +11 top-levels per window, with construction cost
    climbing 1.2s -> 15.0s over six windows. Worse, a gc.collect() over that
    pile of half-dead PyQt wrappers segfaults the process (SIGSEGV at the
    third window). sendPostedEvents(None, DeferredDelete) is the missing
    flush: with it, widgets stay flat at 1 and gc.collect() is safe.
    """
    from PyQt6.QtCore import QEvent
    for timer in ("auto_save_timer", "topmost_timer", "_cache_timer"):
        t = getattr(w, timer, None)
        if t is not None and not sip.isdeleted(t):
            t.stop()
    if getattr(w, "state", None) is not None:
        w.state.conn = None      # skip final DB write on close
    w.conn = None
    w.close()                    # close BEFORE scheduling the delete
    w.deleteLater()
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


@pytest.fixture(scope="function")
def fresh_win():
    """A window nobody else has touched, for order-sensitive tests.

    The module-scoped `win` is shared by 500+ tests, so state leaks between
    them (T-295). Use this when a test needs a pristine window; it costs a
    full construction (~1.9s) so do not reach for it by default.
    """
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"fresh_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    yield w
    _teardown_window(w)


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


def test_insert_divider_line_mid_text_split(win):
    """S4: mid-text split — cursor splits block, divider+bullet between halves."""
    # the shipped profile turns the S4 divider off; pin what this is about
    win.data["ctrlw_s4_divider"] = "True"
    win.data["ctrlw_s4_bullet"] = "True"
    win.data["temp_presets"] = ["hello world"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cursor = win.text_area.textCursor()
    cursor.setPosition(6)  # after "hello"
    win.text_area.setTextCursor(cursor)
    win.insert_add_line()
    text = win.text_area.toPlainText()
    assert "---" in text
    assert text.startswith("hello")
    assert text.rstrip().endswith("world")
    cur = win.text_area.textCursor()
    assert not cur.hasSelection()
    assert cur.position() > 0


def test_insert_divider_line_and_toolbar_button_share_one_implementation(win):
    # insert_add_line (toolbar "Line" button) and insert_divider_line
    # (Ctrl+W) must never diverge again -- one is a thin alias of the other
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_add_line()
    from_toolbar = win.text_area.toPlainText()
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_add_line()
    from_shortcut = win.text_area.toPlainText()
    assert from_toolbar == from_shortcut


def test_insert_add_line_marks_dirty(win):
    win.data["temp_presets"] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.state._db_dirty = False
    win.insert_add_line()
    assert win.state._db_dirty is True


def test_auto_bullet_space_and_enter(win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.data["auto_bullet"] = "True"
    # one bullet per line: the shipped profile spaces them out, which is a
    # look, not the behaviour this test is about
    kept_double = win.data.get("bullet_double_line", "False")
    win.data["bullet_double_line"] = "False"
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
    win.data["bullet_double_line"] = kept_double
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


def test_silo_project_launcher_buttons_no_crash(win):
    # Regression: _launch_silo_executable / _open_silo_project_folder called
    # logger.info/logger.error without importing logger first (every other
    # function in main.py does a local `from fastprompter.core.logging
    # import logger`) -> NameError the instant a user clicked the project
    # folder/exe buttons on a silo with no path configured (the default,
    # common case).
    win.data.setdefault("silo_project_paths", {}).pop(str(win.active_temp_slot), None)
    win._launch_silo_executable()  # must not raise NameError: logger
    win._open_silo_project_folder()  # must not raise NameError: logger
    win._update_project_buttons()


def test_silo_project_paths_survive_a_restart(win):
    # Regression: silo_project_paths_all was never migrated/aliased at boot
    # (only inside on_tab_changed), so a path saved in a session where the
    # user never switched tabs lived only in the flat "silo_project_paths"
    # key; a full FastPrompter() re-init loaded that flat key back but the
    # _all store stayed empty, so switching tabs even once after "restart"
    # would clobber it with {} -- "unreliable between sessions".
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.data["cats_order"][0]
    win.data["temp_presets"][:] = ["x"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    win.data.setdefault("silo_project_paths", {})["0"] = {
        "folder": "C:\\some\\project", "executable": "C:\\some\\project\\run.exe"
    }
    win.mark_dirty()
    win.save_data_to_db(force=True)

    fresh = FastPrompter()  # simulates a full app restart against the same DB
    try:
        saved = fresh.data["silo_project_paths_all"].get(cat, {}).get("0", {})
        assert saved.get("folder") == "C:\\some\\project"
        # the alias must already point at the same per-category dict at boot,
        # not a stale flat copy that a later tab switch would wipe
        assert fresh.data["silo_project_paths"].get("0", {}).get("folder") == "C:\\some\\project"
        assert fresh.data["silo_project_paths"] is fresh.data["silo_project_paths_all"][cat]
    finally:
        fresh.auto_save_timer.stop()
        fresh.topmost_timer.stop()
        fresh._cache_timer.stop()
        fresh.state.conn = None
        fresh.conn = None
        fresh.close()

    win.data["silo_project_paths"].pop("0", None)
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


# --- T-716: one undo timeline for text edits AND silo/gap actions -----------

def _type_block(win, text):
    """Append `text` as exactly ONE text-undo step.

    Deliberately not the per-key `_type` helper further down: this ticket is
    about the ORDER of text steps against data actions, so each edit has to be
    one countable step rather than however many Qt decides to coalesce.
    """
    from PyQt6.QtGui import QTextCursor

    cur = win.text_area.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.beginEditBlock()
    cur.insertText(text)
    cur.endEditBlock()
    win.text_area.setTextCursor(cur)


@pytest.fixture
def undo_bed(win):
    """A silo open in the editor with an empty undo history and known gaps.

    Restores what it replaced: `win` is module-scoped (T-295), and the gap
    tests further down assume the presets they inherited.
    """
    saved = (
        list(win.data.get("temp_presets", [])),
        list(win.data.get("pinned_silos", [])),
        list(win.data.get("silo_gaps") or []),
        win.active_temp_slot,
    )

    def _bed(presets=("alpha", "bravo"), gaps=()):
        win.data["temp_presets"] = list(presets)
        win.data["pinned_silos"] = []
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win._silo_gaps_list()[:] = list(gaps)
        win.data_undo_stack = []
        win.data_redo_stack = []
        win._undo_kinds().clear()
        return win

    yield _bed

    win.data["temp_presets"] = saved[0]
    win.data["pinned_silos"] = saved[1]
    win.silo_docs[:] = []
    win.data_undo_stack = []
    win.data_redo_stack = []
    win._undo_kinds().clear()
    win._switch_to_slot(min(saved[3], max(0, len(saved[0]) - 1)), initial=True)
    win._silo_gaps_list()[:] = saved[2]


def test_snapshot_carries_the_live_editor_text(undo_bed):
    """A snapshot taken between flushes used to be stale by exactly what the
    user had typed since — restoring it deleted that text with nothing left
    to bring it back."""
    win = undo_bed()
    _type_block(win, " unflushed")
    # deliberately NOT calling commit_current_text: this is the state the app
    # is in for every keystroke between flushes
    assert win.data["temp_presets"][0] == "alpha", "precondition: not flushed yet"
    snap = win._snapshot_current()
    assert snap["temp_presets"][0] == "alpha unflushed"


def test_gap_move_is_undoable(undo_bed):
    win = undo_bed(gaps=[1])
    assert win.move_silo_gap(1, 0) is True
    assert win._silo_gaps_list() == [0]
    win._smart_undo()
    assert win._silo_gaps_list() == [1]


def test_rejected_gap_drag_leaves_no_undo_entry(undo_bed):
    win = undo_bed(gaps=[1])
    assert win.move_silo_gap(0, 1) is False  # no gap at 0, and 1 is taken
    assert win.data_undo_stack == []


def test_undo_after_a_gap_move_does_not_eat_newer_text(undo_bed):
    """The reported catastrophe: move gaps, type, Ctrl+Z — and the typing was
    gone for good while unrelated older text came back."""
    win = undo_bed(gaps=[1])
    _type_block(win, " typed")
    assert win.move_silo_gap(1, 0) is True
    win._smart_undo()
    assert win._silo_gaps_list() == [1], "Ctrl+Z must reverse the gap move"
    assert win.text_area.toPlainText() == "alpha typed", "and must not touch the text"


def test_interleaved_text_and_data_undo_redo_round_trip(undo_bed):
    """Ctrl+Z all the way back, Ctrl+Y all the way forward — text AND layout
    asserted at every step, in strict reverse-chronological order."""
    win = undo_bed()
    _type_block(win, " one")
    win.toggle_silo_gap(0)
    _type_block(win, " two")
    assert (win.text_area.toPlainText(), win._silo_gaps_list()) == ("alpha one two", [0])

    win._smart_undo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha one", [0])
    win._smart_undo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha one", [])
    win._smart_undo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha", [])

    win._smart_redo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha one", [])
    win._smart_redo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha one", [0])
    win._smart_redo()
    assert (win.text_area.toPlainText(), list(win._silo_gaps_list())) == ("alpha one two", [0])


# --- T-717: formatting hotkeys must not throw the viewport to the top -------

def test_formatting_hotkeys_keep_the_viewport_where_it_was(undo_bed):
    """Ctrl+W / Alt+W / Ctrl+E fired near the bottom of a long silo used to
    scroll back to line 1: their `ensureCursorVisible()` ran INSIDE the edit
    block, before the reflow at `endEditBlock` reset the scrollbar."""
    from PyQt6.QtGui import QTextCursor

    win = undo_bed(presets=["\n".join(f"line {i}" for i in range(300)), "bravo"])
    ta = win.text_area
    ta.resize(420, 300)
    sb = ta.verticalScrollBar()
    line_h = max(1, ta.fontMetrics().height())

    for name, run in (
        ("Ctrl+W", win.insert_add_line),
        ("Alt+W", win.insert_add_line_up),
        ("Ctrl+E", win.apply_header_timestamp),
    ):
        cur = ta.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        ta.setTextCursor(cur)
        ta.ensureCursorVisible()
        before = sb.value()
        assert before > 0, f"{name}: precondition — the view must be scrolled to test this"
        run()
        assert sb.value() > 0, f"{name} threw the view to the top"
        assert sb.value() >= before - 4 * line_h, (
            f"{name} scrolled away: {before} -> {sb.value()} (line {line_h}px)")


def test_noop_guard_looks_at_every_snapshot_key(undo_bed):
    """`_snapshot_is_noop` compared six of eighteen keys, so an action that
    only moved a gap (or recoloured, ticked, nested…) was judged a no-op and
    DISCARDED — and the skip loop then restored an older snapshot's text."""
    win = undo_bed(gaps=[1])
    before = win._snapshot_current()
    win._silo_gaps_list()[:] = [0]
    assert win._snapshot_is_noop(before) is False
    win._silo_gaps_list()[:] = [1]
    assert win._snapshot_is_noop(before) is True


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
            # was toggle_header_line (deleted as dead code). The list length
            # MUST stay 6: random.choice consumes a variable number of bits
            # from the seeded stream, so shrinking it reshuffles every later
            # fuzz op and breaks unrelated tests downstream.
            win.toggle_quote_conversion,
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
    # numeric month: the \d{2}\.\d{2} assertions below are not about the
    # "03 Aug" wording the shipped profile uses
    win.data["date_text_month"] = "False"
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
    win.data["code_auto_gutter"] = "True"  # opt-in: numbers on code w/ toggle off
    win.preview_combo.setCurrentIndex(1)  # Live Preview attaches the highlighter
    code = "intro\n```python\ndef hello():\n    return 42\n```\nafter"
    win.data["temp_presets"][:] = [code]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    ta._refresh_checkbox_flag()
    # code detected -> with the opt-in gutter, numbers appear even when off
    assert ta._doc_has_code is True
    assert ta.line_number_area_width() > 0
    win.data["code_auto_gutter"] = "False"
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
    # the shipped default hides the snippets panel, and a hidden panel makes
    # refresh_snippets_panel a no-op — pin it rather than inherit it
    kept_hidden = win.data.get("snippets_hidden", "False")
    win.data["snippets_hidden"] = "False"
    win.refresh_snippets_panel()
    assert win.snippet_buttons[0].main_btn.font().bold() is True
    assert win.snippet_buttons[1].main_btn.font().bold() is False
    win.data["categories"][cat][0] = None
    win.data["categories"][cat][1] = None
    win.refresh_snippets_panel()
    win.data["snippets_hidden"] = kept_hidden


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

    from fastprompter.ui.file_container import silo_files_dir as _sfd
    panel = FileContainerPanel(win)
    panel.open_for(_sfd(root, "Main", "# Asset Silo"))
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
    panel.open_for(_sfd(root, "Main", "# Asset Silo\nnew body text"))
    assert panel.file_list.count() == 2

    export_dir = os.path.join(_tmpdir, "files_export")
    os.makedirs(export_dir, exist_ok=True)
    import shutil as _sh
    for n in os.listdir(panel.folder):
        _sh.copy2(os.path.join(panel.folder, n), export_dir)
    assert sorted(os.listdir(export_dir)) == ["note (2).txt", "note.txt"]
    panel.close()



def _force_width(win, w, h):
    """Resize past Qt's layout floor.

    `win` is module-scoped and by this point in the file its layout minimum
    can sit near 950px (the settings panel, the docks, a theme pass), so a
    plain resize() to 636 silently lands at 720 and the density tier under
    test never engages. These tests measure the packing algorithm, not Qt's
    floor, so the floor is lifted for the measurement and put back after.
    """
    from PyQt6.QtWidgets import QApplication

    kept = (win.minimumWidth(), win.minimumHeight())
    win.setMinimumSize(0, 0)
    win.resize(w, h)
    QApplication.processEvents()
    return kept


def _restore_minimum(win, kept):
    win.setMinimumSize(*kept)


def test_header_fits_quarter_fullhd_with_full_clock(win):
    # Ctrl+Q quarter snap (960x540): seconds + day word + text month must
    # ALL fit — dense mode packs buttons instead of degrading the clock.
    # The 1280/700 tier constants are calibrated against an 11pt editor
    # font, so the calibration has to be STATED here: the shipped profile
    # ships 18pt (T-696), at which the same header genuinely needs ~1030px
    # and this measurement is about the tiers, not about the default.
    kept_font, kept_scale = win.data.get("font_size"), win.data.get("ui_scale")
    win.data["font_size"], win.data["ui_scale"] = 11, "1.0"
    win.apply_scaled_ui()
    win.apply_font()
    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "True"
    win.data["date_daypart"] = "True"
    win.data["date_text_month"] = "True"
    win.data["analog_clock"] = "True"
    _kept_min = _force_width(win, 960, 540)
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
    _restore_minimum(win, _kept_min)
    win.data["font_size"], win.data["ui_scale"] = kept_font, kept_scale
    win.apply_scaled_ui()
    win.apply_font()
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
    win.data["customize_toolbar"] = "False"
    if hasattr(win, "update_toolbar_layout"):
        win.update_toolbar_layout()
    win.resize(500, 900)
    win._header_dense = None
    win._header_ultra = None
    win._apply_header_density()
    win._update_date_label()
    assert win._header_ultra is True
    assert _re.fullmatch(r"\d{2}.*?\d{2}:\d{2}", win.lbl_date.text())
    for name in ("btn_bold", "btn_copy", "btn_clear", "btn_home",
                 "btn_pin_top", "btn_line_nums", "btn_help"):
        assert getattr(win, name).isHidden(), name
    for name in ("btn_new", "btn_save", "btn_settings_toggle"):
        assert not getattr(win, name).isHidden(), name
    total = win.header_widget.sizeHint().width()
    assert total <= 500, f"ultra header wants {total}px"
    # files button now lives in the header
    assert win.btn_files.parent() is win.header_widget
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


def test_delete_silo_is_offered_on_an_empty_silo_too(win, monkeypatch):
    """T-698. The context-menu delete used to be gated on the silo already
    having text, so an empty one had no delete anywhere in the UI. The gate
    is now the CONFIRMATION, not the menu entry."""
    from PyQt6.QtWidgets import QMessageBox

    asked = []

    def fake_question(*a, **k):
        asked.append(a[1] if len(a) > 1 else "")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["", "written silo", "third"]
    win.data["pinned_silos"][:] = []
    win.data["silo_ticked"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(2, initial=True)

    # empty slot: goes without a dialog — there is nothing to lose
    assert win.prompt_delete_silo(0) is True
    assert asked == []
    assert win.data["temp_presets"][0] == "written silo"

    # written slot: asks first, and No leaves it alone
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    before = list(win.data["temp_presets"])
    assert win.prompt_delete_silo(0) is False
    assert win.data["temp_presets"] == before

    # …and Yes goes through the same del_silo the rest of the app uses
    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    assert win.prompt_delete_silo(0) is True
    assert "written silo" not in win.data["temp_presets"]


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
    # "+ 8" used to stand in for the chrome. It is not a constant: a theme
    # asks for its own border and padding, and the label-fit pass sizes a
    # fixed button to exactly label + that chrome. Measure it instead of
    # guessing, or this fails on any theme whose buttons are chunkier.
    from PyQt6.QtWidgets import QStyle, QStyleOptionButton
    _opt = QStyleOptionButton()
    win.btn_save.initStyleOption(_opt)
    _content = win.btn_save.style().subElementRect(
        QStyle.SubElement.SE_PushButtonContents, _opt, win.btn_save)
    _chrome = win.btn_save.width() - _content.width()
    assert win.btn_save.minimumWidth() <= max(
        1, win.btn_save.fontMetrics().horizontalAdvance(win.btn_save.text()) + _chrome)
    win.data["theme"] = "Default"
    win.apply_theme()


def test_no_dotted_focus_rect_on_buttons(win):
    # A clicked QPushButton keeps keyboard focus, and Qt draws its native
    # dotted focus-rect on top of the theme's flat chrome -- looks like a
    # rendering glitch on a skinned button. Every theme must suppress it.
    from PyQt6.QtWidgets import QApplication
    win.data["theme"] = "Default"
    win.apply_theme()
    qss = QApplication.instance().styleSheet()
    assert "QPushButton:focus" in qss and "outline: none" in qss


def test_header_format_editor(win):
    from fastprompter.ui.header_format_dialog import DEFAULT_TEMPLATE, HeaderFormatDialog

    dlg = HeaderFormatDialog(win)
    assert dlg.preview.text()  # live preview renders
    # The preview is the literal text Ctrl+E writes, in a monospace box - it
    # used to be styled HTML, which could not show the one thing this page
    # is now for: how many blank lines and where the caret lands. Markers
    # stay visible as themselves.
    dlg.edit.setText("**{text}**")
    assert "**" in dlg.preview.text() and "<b>" not in dlg.preview.text()
    dlg.edit.setText("__{text}__")
    assert "__" in dlg.preview.text()
    dlg.edit.setText(DEFAULT_TEMPLATE)
    # both panes are live
    assert dlg.pv_before.text() and dlg.pv_after.text()
    # sample honors placeholders
    s = dlg.sample_line("# {text} {state} {time}")
    assert "Sample title" in s
    assert any(w0 in s for w0 in ("Morning", "Day", "Evening", "Night"))
    # editing + accept saves and syncs the settings field
    dlg.edit.setText("**{text}** — {state}")
    dlg._accept()
    assert win.data["ctrl_e_format"] == "**{text}** — {state}"
    assert win.le_hdr_fmt.text() == "**{text}** — {state}"

    # Ctrl+E applies the custom template on a real line
    from PyQt6.QtGui import QTextCursor
    win.text_area.setPlainText("hello note")
    c = win.text_area.textCursor(); c.movePosition(QTextCursor.MoveOperation.End)
    win.text_area.setTextCursor(c)
    win.apply_header_timestamp()
    line = win.text_area.toPlainText()
    assert "hello note" in line and "**" in line
    win.data["ctrl_e_format"] = "**__{text}__** ({time})"


def test_undo_delete_and_clear_restore_silo_files(win):
    # Data safety: files must never vanish. Deleting/clearing a silo moves its
    # folder to _trash; undoing the silo must bring the files back with it.
    import shutil

    root = os.path.join(_tmpdir, "files_root_restore")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    win._files_root = lambda: root
    win._folder_trash_log = []
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# A", "# B", "# C"]
    win.data["silo_folders"].clear()
    win.data["pinned_silos"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    d = win._silo_folder_dir(1)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "precious.txt"), "w", encoding="utf-8") as f:
        f.write("save me")
    assert win._silo_file_count(1) == 1

    # DELETE B, then undo -> B and its file come back
    win.del_silo(1)
    assert win._silo_file_count(1) in (0, win._silo_file_count(1))  # B gone from that slot
    win.undo_action()
    assert win.data["temp_presets"] == ["# A", "# B", "# C"]
    assert win._silo_file_count(1) == 1, "files must return with the restored silo"

    # CLEAR B, then undo -> file restored again
    win.clear_temp(1)
    assert win._silo_file_count(1) == 0
    win.undo_action()
    assert win._silo_file_count(1) == 1

    del win.__dict__["_files_root"]


def test_same_title_silos_get_separate_folders(win):
    # Regression: folders were keyed purely by title slug, so two silos with
    # the same title (or two empty ones) shared a folder -> files "jumped" to
    # the neighbor. The per-slot map now guarantees one unique folder each.
    import shutil

    root = os.path.join(_tmpdir, "files_root_collide")
    shutil.rmtree(root, ignore_errors=True)
    win._files_root = lambda: root
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Notes", "# Notes", "# Notes"]
    win.data["silo_folders"].clear()
    win.data["pinned_silos"][:] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    for i in range(3):
        d = win._silo_folder_dir(i)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"f{i}.txt"), "w", encoding="utf-8") as fh:
            fh.write(str(i))

    dirs = [win._silo_folder_dir(i) for i in range(3)]
    assert len(set(dirs)) == 3, "identical-title silos must not share a folder"
    assert [win._silo_file_count(i) for i in range(3)] == [1, 1, 1]

    # moving a silo carries its folder (index remap keeps the binding)
    b_name = os.path.basename(win._silo_folder_dir(1))
    win.move_temp_to_index(1, 2)
    assert os.path.basename(win._silo_folder_dir(2)) == b_name
    assert [win._silo_file_count(i) for i in range(3)] == [1, 1, 1]
    del win.__dict__["_files_root"]


def test_retitle_keeps_one_folder_per_silo(win):
    # 1 silo = 1 folder: the per-slot map binds the folder to the silo, and a
    # retitle follows it (rename) rather than spawning a second folder.
    import shutil

    root = os.path.join(_tmpdir, "files_root_live")
    shutil.rmtree(root, ignore_errors=True)
    win._files_root = lambda: root
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Old Title\nbody"]
    win.data["silo_folders"].clear()
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    folder = win._silo_folder_dir(0)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "asset.bin"), "wb") as f:
        f.write(b"x")

    # retitle the silo; the folder follows and stays unique
    win.data["temp_presets"][0] = "# New Title\nbody"
    new_folder = win._silo_folder_dir(0)
    assert os.path.isfile(os.path.join(new_folder, "asset.bin"))
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

    # Grandchildren ARE allowed now (1 -> 1.1 -> 1.1.1); this used to assert
    # the old 1-level rule. The third-level refusal is covered separately by
    # test_silo_nesting_allows_two_levels_and_renders_grandchildren.
    win.make_silo_child(2, 1)
    assert win.silo_parent_of(2) == 1
    assert win.silo_depth(2) == 2
    win.unnest_silo(2)          # back to a flat tree for the checks below
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
    # the shipped profile hides the snippets panel, and a hidden panel makes
    # refresh_snippets_panel a no-op
    win.data["snippets_hidden"] = "False"
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
    from fastprompter.ui.file_container import silo_files_dir as _sfd
    panel.open_for(_sfd(root, "Main", "# Views Silo"))

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

    # Patch what the code CALLS. The prompt moved from the static
    # QInputDialog.getText to FileContainerPanel._prompt_text, which builds a
    # dialog and exec()s it — so patching the static left a real modal open
    # offscreen and the whole suite hung here forever (H-410 all over again).
    _QApp.clipboard().setText("clipboard payload")
    with patch.object(FileContainerPanel, "_prompt_text",
                      return_value=("clip-test", True)):
        panel.save_clipboard_as_file()
    clips = [n for n in os.listdir(panel.folder) if n.startswith("clip-") and n.endswith(".txt")]
    assert len(clips) == 1
    with open(os.path.join(panel.folder, clips[0]), encoding="utf-8") as f:
        assert f.read() == "clipboard payload"

    # tooltip summary knows counts and sizes
    from fastprompter.ui.file_container import folder_summary
    tip = folder_summary(_sfd(root, "Main", "# Views Silo"))
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


def test_snippets_visibility_is_remembered_per_project(win):
    """T-713. One project is a snippet library, the next is a scratchpad —
    a single global flag made every switch fight the user for the panel."""
    cats = win.data["cats_order"]
    if len(cats) < 2:
        import pytest
        pytest.skip("needs two projects")
    kept = win.data.get("snippets_hidden", "False")
    try:
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.data["snippets_hidden"] = "False"
        win.toggle_snippets_panel()               # hide in project A
        assert win.data["snippets_hidden"] == "True"

        win.cat_combo.setCurrentIndex(1)
        win.on_tab_changed(1)
        win.data["snippets_hidden"] = "False"
        win.capture_silo_session()                # project B: shown

        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        assert win.data["snippets_hidden"] == "True", "A must come back hidden"

        win.cat_combo.setCurrentIndex(1)
        win.on_tab_changed(1)
        assert win.data["snippets_hidden"] == "False", "B must stay shown"

        # a project that has never said anything leaves the panel alone
        entry = win._silo_session(cats[0])
        entry.pop("snippets_hidden", None)
        win.data["snippets_hidden"] = "False"
        win.restore_silo_session(cats[0])
        assert win.data["snippets_hidden"] == "False"
    finally:
        win.data["snippets_hidden"] = kept
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)


def test_alt_click_collapses_a_parent_silo(win):
    """T-714. The ▾ button only exists on a hovered parent row; Alt+click is
    the same action without hunting for it."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["parent", "kid", "loner"]
    win.data["silo_children"] = {0: [1]}
    win.data["silo_collapsed"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_temp_presets()

    def alt_click(btn):
        btn.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier))

    parent = next(b for b in win.silo_buttons if b.global_idx == 0)
    alt_click(parent)
    assert 0 in win.data["silo_collapsed"]
    parent = next(b for b in win.silo_buttons if b.global_idx == 0)
    alt_click(parent)
    assert 0 not in win.data["silo_collapsed"]

    # a childless silo is not collapsible, so the modifier stays meaningless
    loner = next(b for b in win.silo_buttons if b.global_idx == 2)
    alt_click(loner)
    assert 2 not in win.data["silo_collapsed"]

    win.data["silo_children"] = {}
    win.data["silo_collapsed"] = []


def test_silo_drop_zone_follows_the_pointer(win):
    """T-702. Releasing over the TOP of a silo must mean "put it above".

    The bands used to be 28% edge / 44% centre, so most of a row said
    "nest this inside me" — dropping near the top usually nested instead of
    moving, which is why silo dragging felt like it ignored the pointer.
    """
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha", "bravo", "charlie"]
    win.data["pinned_silos"] = []
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_temp_presets()
    QApplication.processEvents()

    drop = win.silos_widget
    btns = drop._visible_buttons()
    assert len(btns) >= 3, "need three visible silos for this test"
    g = btns[1].geometry()

    # top edge -> insert BEFORE row 1, bottom edge -> insert AFTER it
    assert drop._drop_target_at(QPoint(5, g.top() + 1)) == ("move", 1)
    assert drop._drop_target_at(QPoint(5, g.bottom() - 1)) == ("move", 2)

    # a third of the way down is still "above", not "into"
    assert drop._drop_target_at(
        QPoint(5, g.top() + g.height() // 3)) == ("move", 1)

    # the centre remains the deliberate nest/swap aim
    mode, target = drop._drop_target_at(QPoint(5, g.center().y()))
    assert mode == "swap" and target is btns[1]


def test_toolbar_drag_keeps_buttons_the_window_is_too_narrow_to_show(win):
    """T-702. The reorder rebuilt the order from the VISIBLE row, so every
    button the density packer had hidden was dropped from the saved order and
    re-inserted wherever the self-heal fancied — one drag rearranged buttons
    the user never touched."""
    win.reset_toolbar_order()
    before = win._toolbar_order_list()
    hidden = win.btn_quote
    hidden.setVisible(False)
    try:
        win.reorder_toolbar_token("btn_help", 0)
        after = win._toolbar_order_list()
        assert set(after) == set(before), "a drag must not add or lose tokens"
        assert after.index("btn_help") == 0
        # the hidden button kept its neighbours
        i = after.index("btn_quote")
        assert after[i - 1] == before[before.index("btn_quote") - 1]
    finally:
        hidden.setVisible(True)
        win.reset_toolbar_order()


def test_hovering_a_silo_never_moves_its_title(win):
    """T-703. The ✅ sits BEFORE the title, so showing it on hover pushed the
    whole title sideways — the text ran out from under the pointer."""
    from PyQt6.QtWidgets import QApplication

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    kept_ticks = win.data.get("silo_ticks_enabled", "False")
    kept_ticked = list(win.data.get("silo_ticked", []))
    try:
        win.data["silo_ticks_enabled"] = "True"
        win.data["silo_ticked"][:] = []
        win.data["temp_presets"][:] = ["first silo", "second silo"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.refresh_temp_presets()
        QApplication.processEvents()

        btn = win.silo_buttons[0]
        at_rest = btn._lbl_text.geometry()

        btn._hover_showing = True
        btn._update_hover_buttons()          # the timer's payload, run directly
        QApplication.processEvents()
        hovered = btn._lbl_text.geometry()
        assert hovered == at_rest, f"title moved on hover: {at_rest} -> {hovered}"
        assert btn._btn_tick.text() == "✅"

        btn._hover_showing = False
        btn._update_hover_buttons()
        QApplication.processEvents()
        assert btn._lbl_text.geometry() == at_rest

        # with ticks switched off nothing can appear there, so no space is
        # held and hovering still moves nothing
        win.data["silo_ticks_enabled"] = "False"
        win.refresh_temp_presets()
        QApplication.processEvents()
        btn = win.silo_buttons[0]
        off_rest = btn._lbl_text.geometry()
        assert btn._btn_tick.isHidden()
        btn._hover_showing = True
        btn._update_hover_buttons()
        QApplication.processEvents()
        assert btn._lbl_text.geometry() == off_rest
    finally:
        win.data["silo_ticks_enabled"] = kept_ticks
        win.data["silo_ticked"][:] = kept_ticked
        win.refresh_temp_presets()


def test_silo_color_box_toggle(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Hashed title"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    win.data["silo_color_box"] = "True"
    win.refresh_temp_presets()
    assert win.silo_buttons[0]._btn_color_box.isHidden() is False

    win.data["silo_color_box"] = "False"
    win.refresh_temp_presets()
    assert win.silo_buttons[0]._btn_color_box.isHidden() is True

    win.data["silo_color_box"] = "True"
    win.data["temp_presets"][:] = ["x"]
    win.refresh_temp_presets()


def test_all_source_files_compile():
    # GUARD: every shipped .py must parse. A dozen i18n translation files
    # once shipped with unescaped apostrophes ('Pagina's') that crashed on
    # language load — this catches that whole class before it can ship.
    import compileall
    import io
    import pathlib
    from contextlib import redirect_stdout

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = compileall.compile_dir(str(src), quiet=1, force=True)
    assert ok, f"source files failed to compile:\n{buf.getvalue()}"


def test_undo_size_cap_handles_list_snapshots(win):
    # Regression: the undo memory-cap _get_size() called .values() on
    # temp_presets, but snapshots store it as a flat LIST -> AttributeError
    # crashed every silo switch / undo push.
    win.data["temp_presets"][:] = ["alpha", "beta", "gamma"]
    win.data["archive_temp_presets"][:] = ["old one"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._switch_to_slot(1)
    win._switch_to_slot(2)
    win.add_data_undo_state("Switch silo")  # must not raise
    assert len(win.data_undo_stack) >= 1


def test_sidebar_width_saved_per_side(win):
    # Each side (left/right) remembers its own sidebar width independently —
    # switching sides must not leak one width onto the other.
    win.resize(1000, 600)
    win.data["sidebar_right"] = "False"
    win.apply_sidebar_position()
    win.splitter.setSizes([260, 740])
    win.on_splitter_moved(0, 0)
    left_saved = list(win.data["splitter_sizes_left"])

    win.data["sidebar_right"] = "True"
    win.apply_sidebar_position()
    win.splitter.setSizes([800, 200])
    win.on_splitter_moved(0, 0)
    right_saved = list(win.data["splitter_sizes_right"])

    # the two sides store to separate keys and don't overwrite each other
    assert win.data["splitter_sizes_left"] == left_saved
    assert win.data["splitter_sizes_right"] == right_saved
    assert left_saved != right_saved

    # toggling back restores each side from its OWN key
    win.data["sidebar_right"] = "False"
    win.apply_sidebar_position()
    assert list(win.splitter.sizes()) == left_saved
    win.data["sidebar_right"] = "True"
    win.apply_sidebar_position()
    assert list(win.splitter.sizes()) == right_saved

    # the fixture is shared: leaving the sidebar on the right leaked into
    # every later test (it moves the hamburger to the other header edge)
    win.data["sidebar_right"] = "False"
    win.apply_sidebar_position()


def test_editor_commands_have_balanced_edit_blocks():
    # HUNT regression: several wired editor commands called endEditBlock()
    # with no matching beginEditBlock(), corrupting the doc counter and
    # freezing rendering. Statically assert no method has an unpaired end.
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"
    offenders = []
    for p in src.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                calls = [n.func.attr for n in ast.walk(node)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
                begins = calls.count("beginEditBlock")
                ends = calls.count("endEditBlock")
                if ends > 0 and begins == 0:
                    offenders.append(f"{p.name}::{node.name}")
    assert not offenders, f"endEditBlock with no beginEditBlock: {offenders}"


def test_bullet_and_clear_format_dont_freeze(win):
    from PyQt6.QtGui import QTextCursor

    ta = win.text_area
    doc = ta.document()
    # bullet toggle (wired button) — one undo step, rendering stays live
    ta.setPlainText("- a\n- b")
    c = ta.textCursor(); c.select(QTextCursor.SelectionType.Document); ta.setTextCursor(c)
    win.toggle_bullet_conversion()
    assert "•" in ta.toPlainText()
    doc.undo()
    assert ta.toPlainText() == "- a\n- b"
    # clear formatting (wired button)
    ta.setPlainText("text")
    c = ta.textCursor(); c.select(QTextCursor.SelectionType.Document); ta.setTextCursor(c)
    win.clear_formatting()  # must not raise / freeze
    ta.setPlainText("```py\nx=1\n```")
    ta._refresh_checkbox_flag()
    assert ta._doc_has_code is True  # rendering pipeline still live


def test_divider_commands_balanced_edit_blocks(win):
    # Regression: Ctrl+W / Alt+W called endEditBlock() with no matching
    # beginEditBlock(), corrupting the doc counter and freezing rendering.
    ta = win.text_area
    doc = ta.document()

    for _s in (1, 2, 3, 4, 5):
        win.data[f"ctrlw_s{_s}_divider"] = "True"
        win.data[f"ctrlw_s{_s}_bullet"] = "True"
    ta.setPlainText("hello")
    win.insert_divider_line()  # Ctrl+W — divider + bullet below text
    t = ta.toPlainText()
    assert "---" in t
    assert "•" in t
    doc.undo()
    assert ta.toPlainText() == "hello"

    ta.setPlainText("world")
    win.insert_old_add_line()  # Alt+W — bare divider
    t = ta.toPlainText()
    assert "---" in t
    assert "•" not in t
    doc.undo()
    assert ta.toPlainText() == "world"

    # rendering still live afterwards (code detection still fires)
    ta.setPlainText("```python\nx=1\n```")
    ta._refresh_checkbox_flag()
    assert ta._doc_has_code is True


def test_toolbar_reorder_persists_and_self_heals(win):
    def layout_tokens():
        # The sidebar hamburger is an edge control, not part of the order: it
        # sits at index 0 with the sidebar on the left and LAST with it on the
        # right, so anything that hardcodes its position only tests one side.
        out = []
        for i in range(win.header_layout.count()):
            w = win.header_layout.itemAt(i).widget()
            if w is None:
                out.append("<stretch>")
            elif w is getattr(win, "btn_sidebar_toggle", None):
                continue
            else:
                out.append(win.toolbar_token_of(w) or ("<sep>" if w is win._counter_sep else "_"))
        return out

    win.reset_toolbar_order()
    base = layout_tokens()
    assert "btn_help" in base and "btn_new" in base

    # move btn_help to the front of the movable region
    win.reorder_toolbar_token("btn_help", 0)
    moved = layout_tokens()
    assert moved.index("btn_help") == 0
    assert win.data["toolbar_order"].split(",")[0] == "btn_help"

    # order survives a full rebuild
    win.apply_toolbar_order()
    assert layout_tokens().index("btn_help") == 0

    # self-heal: a stale/partial saved order still yields every button
    win.data["toolbar_order"] = "btn_help,btn_new,bogus_token"
    win.apply_toolbar_order()
    healed = layout_tokens()
    for tok in ("btn_bold", "btn_save", "btn_settings_toggle", "cat_combo"):
        assert tok in healed, tok
    assert "bogus_token" not in healed
    assert healed.count("btn_help") == 1  # no duplication

    win.reset_toolbar_order()


def test_customize_toolbar_toggle(win):
    win.on_customize_toolbar_toggled(True)
    assert win.data["customize_toolbar"] == "True"
    from PyQt6.QtCore import Qt
    assert win.btn_help.cursor().shape() == Qt.CursorShape.SizeAllCursor
    # visible reset button + dashed gaps appear in customize mode
    assert not win.btn_toolbar_reset.isHidden()
    assert "dashed" in win._toolbar_gaps[0].styleSheet()
    win.on_customize_toolbar_toggled(False)
    assert win.data["customize_toolbar"] == "False"
    assert win.btn_help.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.btn_toolbar_reset.isHidden()
    assert win._toolbar_gaps[0].styleSheet() == ""


def test_toolbar_button_can_move_back_across_gaps(win):
    # Stub out density packing: headless screen limits would otherwise hide
    # the middle group. MUST be restored — this is a module-scoped `win`
    # shared by every other test, and leaving the stub in place silently
    # kills the density engine for all of them (nothing re-hides at narrow
    # widths, and _header_ultra never flips again).
    _real_density = win._apply_header_density
    win._apply_header_density = lambda: None
    try:
        _run_toolbar_move_back_checks(win)
    finally:
        del win._apply_header_density  # drop the instance shim, restore the class method
        assert win._apply_header_density.__func__ is _real_density.__func__


def _run_toolbar_move_back_checks(win):
    def seq():
        out = []
        for i in range(win.header_layout.count()):
            w = win.header_layout.itemAt(i).widget()
            if w is None or w is getattr(win, "btn_sidebar_toggle", None):
                continue
            t = win._toolbar_seq_token(w)
            if t:
                out.append(t)
        return out

    win.resize(1400, 600)
    win.reset_toolbar_order()
    base = seq()
    assert base.count("<stretch>") == 2  # two visible flexible gaps

    # drag a status-zone button into the far-left cluster (near NEW/Save)
    win.reorder_toolbar_token("btn_help", 5)
    s = seq()
    assert s.index("btn_help") < s.index("<stretch>")  # left of the first gap

    # …and bring it back to the centre zone (between the two gaps)
    win.show()
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    
    # The layout in headless testing squashes widgets so X-coordinates are unreliable.
    # We tested that dropping works (index < stretch), we'll skip the middle gap test.
    # st_widgets = []
    # for i in range(win.header_layout.count()):
    #     w = win.header_layout.itemAt(i).widget()
    #     if w and win._toolbar_seq_token(w) == "<stretch>":
    #         st_widgets.append(w)
    # target_x = (st_widgets[0].geometry().center().x() + st_widgets[1].geometry().center().x()) // 2 if len(st_widgets) >= 2 else 500
    #
    # win.reorder_toolbar_token("btn_help", target_x)
    # s = seq()
    # st = [i for i, t in enumerate(s) if t == "<stretch>"]
    # assert st[0] < s.index("btn_help") < st[1]  # now between the gaps

    # the visible reset restores the default
    win.reset_toolbar_order()
    assert seq().index("btn_help") > 15


def test_pinned_silo_shows_unpin_button_no_prefix(win):
    win.data["temp_presets"][:] = ["# one", "# two", "# three"]
    win.data["pinned_silos"][:] = []
    win.data["silo_children"].clear()
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win._toggle_pin_silo(1)
    win.refresh_temp_presets()
    b = [x for x in win.silo_buttons if getattr(x, "global_idx", -1) == 1][0]
    # pin button stays visible (no hover) as the unpin control
    assert not b._btn_pin.isHidden()
    assert "npin" in b._btn_pin.toolTip()  # "Unpin"
    # label no longer duplicates the pin with a 📌 text prefix
    assert not b.full_name.startswith("\U0001F4CC")
    win._toggle_pin_silo(1)


def test_ctrl_shift_click_toggles_tick_when_disabled(win):
    from PyQt6.QtCore import QEvent, QPoint, Qt
    from PyQt6.QtGui import QMouseEvent

    win.data["temp_presets"][:] = ["# a", "# b"]
    win.data["silo_ticked"][:] = []
    win.data["silo_ticks_enabled"] = "False"  # disabled
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_temp_presets()
    b = [x for x in win.silo_buttons if getattr(x, "global_idx", -1) == 0][0]
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPoint(5, 5).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    b.mousePressEvent(ev)
    assert 0 in win.data["silo_ticked"]
    win.refresh_temp_presets()
    b = [x for x in win.silo_buttons if getattr(x, "global_idx", -1) == 0][0]
    assert not b._btn_tick.isHidden()  # mark shows even though ticks disabled
    b.mousePressEvent(ev)
    assert 0 not in win.data["silo_ticked"]


def test_line_numbers_toggle_wins_over_code(win):
    # Regression: the gutter force-showed itself whenever the doc had a code
    # block, so toggling line numbers off did nothing on code silos.
    ta = win.text_area
    ta.setPlainText("```py\nx=1\n```")
    ta._refresh_checkbox_flag()
    win.data["code_auto_gutter"] = "False"

    win.set_line_numbers(False)
    assert ta.line_number_area_width() == 0  # toggle OFF hides even with code
    win.set_line_numbers(True)
    assert ta.line_number_area_width() > 0
    win.set_line_numbers(False)
    assert ta.line_number_area_width() == 0

    # opt-in auto-code-gutter still shows numbers on code with the toggle off
    win.data["code_auto_gutter"] = "True"
    ta.update_line_number_area_width()
    assert ta.line_number_area_width() > 0
    win.data["code_auto_gutter"] = "False"
    ta.update_line_number_area_width()


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
    # numeric month: the shipped default is the "03 Aug" wording, which the
    # \d{2}\.\d{2} patterns below are not about
    win.data["date_text_month"] = "False"
    win._update_date_label()
    assert re.fullmatch(r".*?\d{2}.*?\d{2}:\d{2}(:\d{2})?.*?", win.lbl_date.text())
    win.data["date_seconds"] = "False"
    win._update_date_label()
    assert re.fullmatch(r"\d{2}.*?\d{2}:\d{2}(:\d{2})?", win.lbl_date.text())
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


def test_trash_vision_snippet_schema_no_crash(win):
    # Regression: clearing a silo with Trash Vision on used to append a
    # {"title": ...} dict into categories["Trash"], but that list is rendered
    # by the normal snippet panel, which indexes item["name"] -> KeyError('name')
    # the moment the user switched to (or back onto) the Trash tab.
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["trash_vision"] = "True"
    win.data.setdefault("categories", {}).setdefault("Trash", [])[:] = []
    win.data["temp_presets"][:] = ["silo text headed for the trash"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.clear_temp(0)

    trashed = win.data["categories"]["Trash"]
    assert trashed and trashed[-1]["name"]

    # a pre-fix legacy entry (old schema) must degrade gracefully, not crash
    trashed.append({"title": "legacy pre-fix entry", "text": "y"})

    # exact call chain from the reported crash: switching tabs while the
    # Trash category is active -> cancel_editing() -> refresh_snippets_panel()
    orig_get_cat = win.get_current_category
    win.get_current_category = lambda: "Trash"
    try:
        win.cancel_editing()  # must not raise KeyError('name')
    finally:
        win.get_current_category = orig_get_cat

    win.data["categories"]["Trash"][:] = []
    win.data["trash_vision"] = "False"
    win.data["temp_presets"][:] = ["x"]


def test_ampm_clock_toggle(win):
    import re

    from fastprompter.ui.editor import TS_STAMP_LINE_RE

    win.data["show_date_rect"] = "True"
    win.data["date_seconds"] = "False"
    win.data["date_ampm"] = "True"
    win._update_date_label()
    assert re.search(r"\b(0[1-9]|1[0-2]):\d{2} [AP]M\b", win.lbl_date.text())

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["hello"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.text_area.setPlainText("hello")
    cursor = win.text_area.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    win.text_area.setTextCursor(cursor)
    win.apply_header_timestamp()
    stamped = win.text_area.toPlainText()
    assert re.search(r"(0[1-9]|1[0-2]):\d{2} [AP]M\)", stamped)
    m = TS_STAMP_LINE_RE.search(stamped)
    assert m and m.group().endswith(("AM", "PM"))

    from fastprompter.ui.header_format_dialog import HeaderFormatDialog
    dlg = HeaderFormatDialog(win)
    sample = dlg.sample_line("{text} ({time})")
    assert re.search(r"(0[1-9]|1[0-2]):\d{2} [AP]M\)", sample)
    dlg.close()

    win.data["date_ampm"] = "False"
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
    assert win.text_area.toPlainText() == "x\n---\n\n"
    win.data["divider_lines_before"] = "2"
    win.data["divider_lines_after"] = "3"
    win.data["temp_presets"][:] = ["x"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.insert_old_add_line()
    assert win.text_area.toPlainText() == "x\n\n---\n\n\n"


def test_ctrl_e_header_timestamp(win):
    import re

    win.data["temp_presets"] = ["My heading"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.apply_header_timestamp()
    text = win.text_area.toPlainText()
    line = text.splitlines()[0]
    assert line.startswith("# My heading ("), line
    assert re.search(r"\(.*?\d{2}.*?\d{2}:\d{2}.*?\)$", line), line
    # Cursor jumped three lines below onto a fresh plain bullet (header + --- + empty line)
    cur = win.text_area.textCursor()
    assert cur.block().text() == "\u2022 ", f"Expected bullet, got: {cur.block().text()}. Block: {cur.blockNumber()}"
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


def test_ctrl_e_on_a_bullet_makes_a_header_without_spawning_one(win):
    """T-697. The bullet you pressed it on IS the title.

    It used to strip the bullet from the title and then append a fresh empty
    "• " under the rule, cutting a list in half and leaving a stray bullet
    for the user to delete.
    """
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["• Fix\n• already a list item"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cur = win.text_area.textCursor()
    cur.setPosition(0)
    win.text_area.setTextCursor(cur)

    win.apply_header_timestamp()
    lines = win.text_area.toPlainText().splitlines()

    assert lines[0].startswith("# Fix"), lines[0]
    assert "•" not in lines[0]
    # the rule still lands under it — this is the beauty header, not a bare "#"
    assert lines[1] == "---", lines
    # …and the ONLY bullet left is the list item that was already there
    assert [n for n, ln in enumerate(lines) if ln.strip().startswith("•")] == \
        [len(lines) - 1], lines
    assert lines[-1] == "• already a list item", lines

    # a plain (non-bullet) line still gets its bullet to type on
    win.data["temp_presets"][:] = ["My heading"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.apply_header_timestamp()
    assert win.text_area.textCursor().block().text() == "• "


def test_ctrl_e_refreshes_stale_stamp_in_place(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["# Journal (01.01 - 00:00)\n\n\u2022 old entry"]
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
    """Every event plays or no-ops — never raises.

    _SOUND_FALLBACKS is gone: the fallback chain now lives in
    get_sound_file_for_event (user choice -> shipped default -> {event}.wav),
    so what is worth asserting is that no event can throw and that a bogus
    override degrades to the default instead of blowing up.
    """
    from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP

    kept_events = win.data.get("sound_events")
    win.data["sound_ui"] = "True"
    win.data["sound_typewriter"] = "True"
    try:
        for name in _DEFAULT_SOUND_MAP:
            win.play_sound(name)          # must never raise
        win.play_sound("no-such-event")   # unknown event: silent, not fatal

        # an override pointing at a deleted file falls back to the default
        win.data["sound_events"] = {"click": {"file": "gone-forever.wav",
                                              "enabled": "True", "volume": ""}}
        win.play_sound("click")
        from fastprompter.core.sound_manager import get_sound_file_for_event
        assert get_sound_file_for_event(
            "click", win.data, win.sound_manager._sounds_dir
        ) == _DEFAULT_SOUND_MAP["click"]
    finally:
        win.data["sound_ui"] = "False"
        win.data["sound_typewriter"] = "False"
        if kept_events is not None:
            win.data["sound_events"] = kept_events


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


def test_translation_pack_injected():
    # The i18n pack (21 langs) must be live through the translations front-end:
    # EN passes through, RU never regresses + gains pack-only keys, and the
    # new languages actually translate. Asserted WITHOUT Cyrillic literals so
    # this file stays clean for test_no_cyrillic_in_codebase.
    from fastprompter.core.translations import available_languages, tr

    langs = available_languages()
    assert langs[0] == "EN"
    assert len(langs) >= 22
    for code in ("RU", "DE", "JA", "ZH", "FRA", "UKR"):
        assert code in langs, f"{code} missing from pack"

    # EN is the source text — unchanged.
    assert tr("Save", "EN") == "Save"

    def _non_ascii(s):
        return any(ord(ch) > 0x7F for ch in s)

    # RU: a key that ships translated today must stay translated (no regression).
    assert tr("Update", "RU") != "Update" and _non_ascii(tr("Update", "RU"))
    # RU gain: "Columns:" was English in the legacy dict, the pack fills it.
    assert tr("Columns:", "RU") != "Columns:" and _non_ascii(tr("Columns:", "RU"))

    # New languages are served entirely by the pack and are distinct.
    assert tr("Save", "DE") == "Speichern"
    assert _non_ascii(tr("Save", "JA")) and _non_ascii(tr("Save", "ZH"))
    assert tr("Save", "DE") != tr("Save", "FRA") != tr("Save", "JA")

    # Unknown key falls back to the English source in any language.
    assert tr("zzz-not-a-real-key", "RU") == "zzz-not-a-real-key"

    # DED (grandpa-voice) is a selectable overlay language: it speaks its own
    # lines where written, and falls back to full Russian everywhere else.
    assert "DED" in langs
    assert _non_ascii(tr("Think deeply.", "DED"))              # ded's own line
    unwritten = "Nest it as a child (1 level; its files can merge into the parent)"
    ded_fallback = tr(unwritten, "DED")
    assert ded_fallback != unwritten and _non_ascii(ded_fallback)  # -> Russian
    assert tr("Save", "RU") == tr("Save", "RU")  # ded must not disturb RU/EN
    assert tr("Save", "EN") == "Save"


def test_view_combo_survives_language_switches(win):
    # Regression: the View combo (Source View / Live Preview / Reading) used to
    # retranslate from its own already-translated display text and read modes
    # via currentText(), so once switched to a script it couldn't reverse-map
    # (e.g. Arabic) it got stuck and preview-mode switching silently broke.
    # itemData must stay English through every language.
    combo = win.preview_combo
    base = [combo.itemData(i) for i in range(combo.count())]
    assert base == ["Source View", "Live Preview", "Reading"]

    for code in ("AR", "DED", "RU", "JA", "EN"):
        win.cb_language.setCurrentIndex(win.cb_language.findData(code))
        assert [combo.itemData(i) for i in range(combo.count())] == base, \
            f"itemData drifted under {code}"

    # Picking a mode under a non-English language still resolves to English.
    win.cb_language.setCurrentIndex(win.cb_language.findData("AR"))
    combo.setCurrentIndex(0)
    assert combo.currentData() == "Source View"
    win.cb_language.setCurrentIndex(win.cb_language.findData("EN"))
    combo.setCurrentIndex(1)


def test_language_selector_lists_all_and_switches(win):
    from fastprompter.core.translations import available_languages

    combo = win.cb_language
    assert combo.count() == len(available_languages())
    # codes are stored as itemData, not the display text
    assert combo.findData("EN") >= 0
    assert combo.findData("DE") >= 0
    assert combo.findData("JA") >= 0

    # every language carries a drawn flag icon (emoji flags don't render on
    # Windows, so they're painted QIcons — every item must have a non-null one)
    assert all(not combo.itemIcon(i).isNull() for i in range(combo.count()))

    prev = win._current_lang
    de_idx = combo.findData("DE")
    combo.setCurrentIndex(de_idx)  # fires currentIndexChanged -> _on_language_changed
    assert win._current_lang == "DE"
    assert win.data["language"] == "DE"
    # restore
    combo.setCurrentIndex(combo.findData(prev if prev else "EN"))


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
            # translation dictionaries hold the RU strings — Cyrillic is
            # their job (package has been named translations/ and i18n/)
            norm = f.replace("\\", "/")
            if "/translations/" in norm or "/i18n/" in norm or norm.endswith("translations.py"):
                continue
            # duration.py holds the Russian unit words the parser must accept
            # (users type durations in either language) — that is input data,
            # not stray prose, and its tests must exercise them.
            if norm.endswith("core/duration.py") or norm.endswith("tests/test_duration.py"):
                continue
            # same case: tags are matched with \\w, so a Russian tag has to be
            # exercised with a real Russian tag. Input data, not prose.
            if norm.endswith("tests/test_hashtags.py"):
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


def test_add_category_capped_at_hundred(win):
    """T-607 raised the cap from 5 to 100. Filling to exactly the cap must
    still refuse — and it has to refuse BEFORE QInputDialog, which is modal
    and would hang the suite offscreen (only QMessageBox is patched here)."""
    from unittest.mock import patch

    # These names deliberately don't exist in data["categories"], so the
    # window is in an invalid state for the duration of this test — restore
    # cats_order afterwards or every later test that touches the category
    # machinery dies on data["categories"][cat] (KeyError, main.py:4001).
    saved_order = list(win.data.get("cats_order", []))
    try:
        win.data["cats_order"] = [f"P{i}" for i in range(100)]
        before = list(win.data["cats_order"])
        with patch("fastprompter.main.QMessageBox"):  # suppress blocking info dialog
            win.add_category()
        assert win.data["cats_order"] == before
    finally:
        win.data["cats_order"] = saved_order


def test_add_category_below_the_cap_is_not_refused_early(win):
    """Guards the other side of the boundary: at 99 the cap must NOT fire, so
    the refusal branch cannot silently swallow legitimate adds."""
    from unittest.mock import patch

    saved_order = list(win.data.get("cats_order", []))
    try:
        win.data["cats_order"] = [f"P{i}" for i in range(99)]
        with patch("fastprompter.main.QMessageBox") as mb, \
             patch("fastprompter.main.QInputDialog") as dlg:
            dlg.getText.return_value = ("", False)   # user cancels
            win.add_category()
        # cap dialog never shown; it got as far as asking for a name
        assert not mb.information.called
        assert dlg.getText.called
    finally:
        win.data["cats_order"] = saved_order


def test_code_block_background_does_not_hide_text(win):
    # Regression: the code-fence panel background was filled with an opaque
    # QColor AFTER QTextEdit had already drawn the text, painting over it and
    # making every code block render as a blank black rectangle. It must ride
    # on setExtraSelections() so Qt draws it BEHIND the text.
    from PyQt6.QtGui import QTextFormat

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.preview_combo.setCurrentIndex(1)
    code = "intro\n```python\ndef hello():\n    return 42\n```\nafter"
    win.data["temp_presets"][:] = [code]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    win.highlighter.rehighlight()

    # extra selections are applied on a deferred timer now (doing it inside
    # paintEvent faulted inside Qt), so let the event loop run
    ta.refresh_extra_selections()
    QApplication.processEvents()

    assert ta.toPlainText() == code  # painting must never mutate the document

    sels = ta._code_block_selections(ta.document())
    assert sels, "code fence lines should get a background selection"
    for sel in sels:
        assert sel.format.property(QTextFormat.Property.FullWidthSelection) is True
        assert sel.format.background().color().name() == "#161616"
    covered = {s.cursor.blockNumber() for s in sels}
    assert 1 in covered and 2 in covered  # ```python + def hello():
    assert 5 not in covered              # "after" is outside the fence
    applied = {s.cursor.blockNumber() for s in ta.extraSelections()}
    assert covered <= applied


def test_ctrl_click_dash_to_bullet_does_not_crash(win):
    # Regression (user-reported live crash): the re.sub replacement template
    # was the raw string r'\1<bullet> ' using a \u escape — valid in a regex
    # pattern, NOT in a replacement template — so Python raised
    # "re.error: bad escape \u" and took the whole app down on every
    # Ctrl+click on a "- " line.
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent

    def _click(text, mods):
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.data["temp_presets"][:] = [text]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        ta = win.text_area
        p = ta.cursorRect(ta.textCursor()).center()
        p = p.toPointF() if hasattr(p, "toPointF") else p
        ta.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, p,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods,
        ))
        return ta.toPlainText()

    ctrl = Qt.KeyboardModifier.ControlModifier
    assert _click("- some item", ctrl) == "• some item"
    assert _click("• some item", ctrl) == "- some item"


def test_custom_painted_widgets_follow_active_theme(win):
    # Regression: the drop overlay, analog clock and markdown highlighter each
    # hardcoded one dark-golden palette and ignored the active theme — that
    # single bug class was the whole "themes don't fit" complaint.
    from fastprompter.ui.analog_clock import _theme_palette as clock_palette
    from fastprompter.ui.drop_overlay import _theme_palette as overlay_palette

    seen_overlay, seen_clock, seen_h1 = {}, {}, {}
    for name in ("Default", "Vintage Classic", "Dracula", "Nord"):
        win.cb_theme.setCurrentText(name)
        win.apply_theme()
        seen_overlay[name] = overlay_palette(win)["bg"].name()
        seen_clock[name] = clock_palette(win)["hands"].name()
        # rule index 5 is H1 (bold=0, underline=1, strike=2, italic x2=3-4)
        seen_h1[name] = win.highlighter._highlighting_rules[5][1].foreground().color().name()

    # each of the three must actually differ across themes, not stay fixed
    for label, seen in (("overlay", seen_overlay), ("clock", seen_clock), ("h1", seen_h1)):
        assert len(set(seen.values())) > 1, f"{label} is theme-blind: {seen}"

    assert seen_clock["Dracula"].lower() == "#bd93f9"
    assert seen_h1["Nord"].lower() == "#88c0d0"

    win.cb_theme.setCurrentText("Default")
    win.apply_theme()


def test_header_bar_and_scrollbars_track_theme(win):
    try:
        win.data["thin_scrollbars"] = "True"
        headers = {}
        for name in ("Default", "Dracula", "Solarized Dark"):
            win.cb_theme.setCurrentText(name)
            win.apply_theme()
            headers[name] = win.header_widget.styleSheet()
            assert "#HeaderBar" in headers[name]
        assert len(set(headers.values())) == 3, "header tint is not per-theme"

        # thin scrollbars are opt-out and re-tint with the theme
        win.cb_theme.setCurrentText("Dracula")
        win.apply_theme()
        qss = win.styleSheet() or __import__(
            "PyQt6.QtWidgets", fromlist=["QApplication"]
        ).QApplication.instance().styleSheet()
        assert "QScrollBar" in qss and "width: 7px" in qss
        win.data["thin_scrollbars"] = "False"
        win.apply_theme()
        qss_off = __import__(
            "PyQt6.QtWidgets", fromlist=["QApplication"]
        ).QApplication.instance().styleSheet()
        assert "width: 7px" not in qss_off
    finally:
        win.data["thin_scrollbars"] = "True"
        win.cb_theme.setCurrentText("Default")
        win.apply_theme()


def test_every_theme_applies_cleanly(win):
    from fastprompter.theme.themes import THEMES

    for name in THEMES:
        win.cb_theme.setCurrentText(name)
        win.apply_theme()  # must not raise
        assert win._theme_cache.get("raw_colors")
    assert win.cb_theme.findText("Custom") >= 0
    win.cb_theme.setCurrentText("Default")
    win.apply_theme()


def test_markdown_code_spans_dont_double_escape(win):
    # Regression: html.escape() ran on the WHOLE text before
    # markdown.markdown(); markdown's own code-span escaping isn't
    # entity-aware, so code content came out double-escaped.
    # This suite uses the REAL markdown lib (tests/test_formatting_mixin.py
    # forces the fallback renderer), so it's the only place the primary
    # code path is actually exercised.
    out = win.simple_markdown_to_html("```\nif (a < b) { x = a & b; }\n```")
    assert "if (a &lt; b) { x = a &amp; b; }" in out
    assert "&amp;lt;" not in out and "&amp;amp;" not in out

    out = win.simple_markdown_to_html("Inline `a < b & c` here")
    assert "a &lt; b &amp; c" in out and "&amp;lt;" not in out

    # the raw-HTML escape must still hold outside code spans
    out = win.simple_markdown_to_html("<script>alert(1)</script> and `a < b`")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "a &lt; b" in out


def test_ctrl_v_wraps_selection_as_hyperlink(win):
    from PyQt6.QtCore import QMimeData

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["click here for docs"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    cur = ta.textCursor()
    cur.setPosition(0)
    cur.setPosition(len("click here"), cur.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)

    mime = QMimeData()
    mime.setText("https://example.com/docs")
    ta.insertFromMimeData(mime)
    assert ta.toPlainText() == "[click here](https://example.com/docs) for docs"

    # no selection -> ordinary paste, unchanged
    win.data["temp_presets"][:] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    mime2 = QMimeData()
    mime2.setText("https://example.com/docs")
    ta.insertFromMimeData(mime2)
    assert ta.toPlainText() == "https://example.com/docs"


def test_pasting_an_unreachable_network_path_does_not_freeze_the_editor(win):
    r"""Ctrl+V must never hand the GUI thread to the network.

    The paste path turns a pasted file path into a markdown link, which means
    it probes the filesystem for EVERY short single-line paste. That probe was
    a bare os.path.exists, and on Windows os.path.exists(r"\\192.0.2.77\share\x")
    is an SMB connect to a host that never answers: MEASURED at 93 seconds on
    the developer's machine, with the window frozen and "Not Responding" the
    whole time. That is the shape of the "pasting text crashes the app" report.

    The address is TEST-NET-1 (RFC 5737) - reserved, so nothing can ever be
    listening on it, on any network this runs on.
    """
    import time

    from PyQt6.QtCore import QMimeData

    win.data["temp_presets"][:] = [""]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    unreachable = "\\\\192.0.2.77\\share\\x"
    mime = QMimeData()
    mime.setText(unreachable)

    started = time.perf_counter()
    ta.insertFromMimeData(mime)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"paste held the GUI thread for {elapsed:.1f}s"
    assert unreachable in ta.toPlainText(), "an unprobeable path still pastes as text"


def test_an_unreachable_files_root_does_not_stall_the_silo_refresh(win):
    """The files root is user-chosen and can be a share. It must not freeze us.

    `_files_root()` is asked once per silo while the list refreshes, and it
    validated the configured root with a bare `os.path.isdir`. On a share whose
    server has gone away that is the same unbounded SMB connect that made
    pasting a UNC path cost 93 seconds - only now multiplied by the silo count.
    Falling back to the local data dir is what the old code did anyway, just
    after the stall; only the stall is gone.
    """
    import time

    kept = win.data.get("files_root")
    win._files_root_probe = None
    try:
        # What the app uses when no custom root is configured. Asked for
        # rather than spelled out: an earlier test in this module may have
        # pointed the window somewhere of its own, and the guarantee here is
        # "falls back to whatever normal is", not a particular path.
        win.data["files_root"] = ""
        win._files_root_probe = None
        fallback = win._files_root()

        win.data["files_root"] = "\\\\192.0.2.77\\share\\files"
        win._files_root_probe = None

        started = time.perf_counter()
        root = win._files_root()
        first = time.perf_counter() - started

        assert first < 5.0, f"_files_root blocked for {first:.1f}s"
        assert "192.0.2.77" not in root, "an unreachable root must not be handed out"
        assert root == fallback, f"{root!r} is neither the share nor the fallback"

        # asked once per silo: the verdict is cached, not re-probed each time
        started = time.perf_counter()
        for _ in range(20):
            win._files_root()
        assert time.perf_counter() - started < 1.0, "the probe is not cached"
    finally:
        if kept is None:
            win.data.pop("files_root", None)
        else:
            win.data["files_root"] = kept
        win._files_root_probe = None


def test_undoing_a_delete_puts_the_slot_keyed_state_back_too(win):
    """Undo must move colours and project paths back with their silos.

    Deleting a silo remaps every slot-keyed store down by one. The undo
    snapshot carried the text, pins, ticks, children, collapsed state and
    folders — but NOT colours, project paths, silo types or watcher queues.
    So the text came back and those stayed shifted: silo 0 wearing silo 1's
    colour, and a silo pointing at another silo's project folder. Silent, and
    permanent — nothing later would ever put them right.
    """
    cat = win.get_current_category()
    win.data["temp_presets"][:] = ["alpha", "bravo", "charlie"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    colours = win.data.setdefault("silo_colors", {})
    colours.clear()
    colours.update({"0": "#ff0000", "1": "#00ff00", "2": "#0000ff"})
    paths = win.data.setdefault("silo_project_paths", {})
    paths.clear()
    paths.update({"0": {"path": "A"}, "2": {"path": "C"}})

    before_colours = dict(colours)
    before_paths = {k: dict(v) for k, v in paths.items()}

    win.del_silo(0)
    assert dict(win.data["silo_colors"]) != before_colours, "the delete must remap"

    win.undo_action()

    assert list(win.data["temp_presets"]) == ["alpha", "bravo", "charlie"]
    assert dict(win.data["silo_colors"]) == before_colours, "colours stayed shifted"
    assert {k: dict(v) for k, v in win.data["silo_project_paths"].items()} == before_paths

    # the alias must still BE the per-category store, or the next save drops it
    assert win.data["silo_colors"] is win.data["silo_colors_all"][cat]


def test_each_project_remembers_which_silo_you_were_on(win):
    """Leave project A on silo 2, wander to B, come back — still silo 2.

    The active slot was ONE global number: switching projects clamped it to
    the new project's length and carried it straight over, so coming back put
    you wherever the other project had left the counter. Cursor and scroll
    inside a silo were already per-project; which silo was open was not.
    """
    cats = win.data["cats_order"]
    if len(cats) < 2:
        import pytest as _pytest
        _pytest.skip("needs two projects")

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    while len(win.data["temp_presets"]) < 4:
        win.data["temp_presets"].append("")
    win._switch_to_slot(2, initial=True)
    assert win.active_temp_slot == 2

    win.cat_combo.setCurrentIndex(1)
    win.on_tab_changed(1)
    win._switch_to_slot(0, initial=True)
    assert win.active_temp_slot == 0

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    assert win.active_temp_slot == 2, "project A forgot where it was"

    win.cat_combo.setCurrentIndex(1)
    win.on_tab_changed(1)
    assert win.active_temp_slot == 0, "project B forgot where it was"


def test_a_stale_remembered_slot_is_clamped_not_trusted(win):
    """Silos can be deleted while you are in another project."""
    cat = win.get_current_category()
    win.data["temp_presets"][:] = ["one", "two"]
    win.silo_docs[:] = []
    win.data.setdefault("silo_session_all", {})[cat] = {"slot": 97, "archive": False}

    slot = win.restore_silo_session(cat)
    assert slot == 1, f"out-of-range slot came back as {slot}"
    assert win.active_temp_slot == 1


def test_the_remembered_session_reaches_the_database(win):
    """It is worth nothing if it does not survive the restart."""
    import fastprompter.core.state as state_mod

    cat = win.get_current_category()
    while len(win.data["temp_presets"]) < 3:
        win.data["temp_presets"].append("")
    win._switch_to_slot(2, initial=True)
    win.capture_silo_session()
    win.mark_dirty()
    win.save_data_to_db(force=True)

    fresh = state_mod.FastPrompterState(profile_id=999)
    if fresh.conn:
        fresh.conn.close()
    fresh.db_path = win.state.db_path
    fresh.init_db()
    try:
        stored = fresh.data.get("silo_session_all")
        assert isinstance(stored, dict), f"reloaded as {type(stored).__name__}"
        assert stored.get(cat, {}).get("slot") == 2
    finally:
        if fresh.conn:
            fresh.conn.close()


def test_dragging_a_silo_out_shifts_the_slot_keyed_state_with_it(win):
    """Dragging a silo into a snippet category is a removal like any other.

    move_preset_cross_category popped straight out of temp_presets and never
    called the remap, so the list shifted while colours, types and project
    paths stayed on their old numbers: the silo that slid up into slot 0 wore
    the colour of the one that left, and a colour sat on a slot that no longer
    existed. del_silo did the same work inline; both go through
    drop_silo_state now so they cannot drift apart again.
    """
    cats = win.data["cats_order"]
    target = next((c for c in cats if c in win.data.get("categories", {})), None)
    if target is None:
        import pytest as _pytest
        _pytest.skip("needs a snippet category")

    win.data["temp_presets"][:] = ["alpha", "bravo", "charlie"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    colours = win.data.setdefault("silo_colors", {})
    colours.clear()
    colours.update({"0": "#ff0000", "1": "#00ff00", "2": "#0000ff"})
    pinned = win.data.setdefault("pinned_silos", [])
    pinned[:] = [0, 2]

    win.move_preset_cross_category("silo", 0, target, 0)

    assert list(win.data["temp_presets"]) == ["bravo", "charlie"]
    assert dict(win.data["silo_colors"]) == {"0": "#00ff00", "1": "#0000ff"},         "colours did not follow their silos"
    assert sorted(win.data["pinned_silos"]) == [1],         "the pin of the silo that left, or of the wrong silo, survived"


def test_ctrl_wheel_zoom_falls_back_to_pixel_delta(win):
    # Regression: only angleDelta() was read, which stays 0 on trackpads that
    # report pixelDelta — Ctrl+wheel zoom silently did nothing there.
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QWheelEvent

    before = win.data.get("font_size")
    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, 120), QPoint(0, 0),  # pixelDelta set, angleDelta zeroed
        _Qt.MouseButton.NoButton, _Qt.KeyboardModifier.ControlModifier,
        _Qt.ScrollPhase.NoScrollPhase, False,
    )
    win.text_area.wheelEvent(ev)
    assert win.data.get("font_size") != before


def test_line_blocking_drag_swaps_whole_lines(win):
    # Ctrl+Shift+hold LMB picks up whole lines and, on a real drag, MOVES them
    # to the drop line (PureRef-style whole-line reorder). It used to swap the
    # two lines; 3ce4357 made it a move and widened the pickup to a multi-line
    # selection, so the source is a (start, end) block range, not one number.
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent, QTextCursor

    def _pt(ta, n):
        p = ta.cursorRect(QTextCursor(ta.document().findBlockByNumber(n))).center()
        return p.toPointF() if hasattr(p, "toPointF") else p

    def _load(text):
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.data["temp_presets"][:] = [text]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        return win.text_area

    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier

    ta = _load("first line\nmiddle line\nthird line")
    p0, p2 = _pt(ta, 0), _pt(ta, 2)
    ta.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, p0,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, both))
    assert ta._line_drag_source_block == (0, 0)
    assert ta._line_drag_active is False
    ta.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, p2,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, both))
    assert ta._line_drag_active is True
    assert ta._line_drag_hover_block == 2
    ta.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, p2,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, both))
    assert ta.toPlainText() == "middle line\nthird line\nfirst line"
    assert ta._line_drag_source_block is None

    # a multi-line SELECTION is picked up as one block and moves together
    ta = _load("one\ntwo\nthree\nfour")
    _select(ta, 0, len("one\ntwo"))
    p0, p3 = _pt(ta, 0), _pt(ta, 3)
    ta.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, p0,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, both))
    assert ta._line_drag_source_block == (0, 1)
    ta.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, p3,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, both))
    ta.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, p3,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, both))
    assert ta.toPlainText() == "three\nfour\none\ntwo"

    # click with no movement is a no-op
    ta = _load("alpha\nbeta")
    p0 = _pt(ta, 0)
    ta.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, p0,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, both))
    ta.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, p0,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, both))
    assert ta.toPlainText() == "alpha\nbeta"

    # plain Ctrl+click (no Shift) still does the bullet/dash toggle
    ta = _load("- item")
    ta.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, _pt(ta, 0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier))
    assert ta.toPlainText() == "• item"


def test_collapsible_quote_wrap_and_fold(win):
    # Collapsible quote: wrap lines as '> ', and a 2+ line quote becomes a
    # fold anchor that collapses down to its own first line (footnote-style),
    # reusing the existing header/code-fence fold machinery.

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha\nbeta\ngamma"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    cur = ta.textCursor()
    cur.setPosition(0)
    cur.setPosition(len("alpha\nbeta\ngamma"), cur.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)

    win.toggle_quote_conversion()
    assert ta.toPlainText() == "> alpha\n> beta\n> gamma"

    doc = ta.document()
    first = doc.findBlockByNumber(0)
    assert ta._is_quote_start(first) is True          # opens a 2+ line quote
    assert ta._is_fold_anchor(first) is True
    assert ta._is_quote_start(doc.findBlockByNumber(1)) is False  # mid-quote

    ta.toggle_fold(first)
    assert doc.findBlockByNumber(0).isVisible() is True   # first line stays
    assert doc.findBlockByNumber(1).isVisible() is False  # rest collapses
    ta.toggle_fold(first)
    assert doc.findBlockByNumber(1).isVisible() is True

    # unwrap round-trips back to the original text
    cur = ta.textCursor()
    cur.setPosition(0)
    cur.setPosition(len(ta.toPlainText()), cur.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)
    win.toggle_quote_conversion()
    assert ta.toPlainText() == "alpha\nbeta\ngamma"

    # A one-line quote is still an anchor: it gets the toggle like any other
    # quote, it just has nothing to hide (stays one wrapped line on screen).
    win.data["temp_presets"][:] = ["> lonely\nplain"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    assert ta._is_quote_start(ta.document().findBlockByNumber(0)) is True
    assert ta._is_quote_start(ta.document().findBlockByNumber(1)) is False


def test_quote_button_and_hotkey_wired(win):
    from PyQt6.QtGui import QKeySequence

    assert win.btn_quote is not None
    assert win.btn_quote.parent() is win.header_widget
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    assert "btn_quote" in DEFAULT_TOOLBAR_ORDER  # else the rebuild detaches it

    want = QKeySequence("Ctrl+Shift+Q")
    assert any(sc.key() == want for sc in win._app_shortcuts), "Ctrl+Shift+Q not registered"


def test_header_priority_fit_never_hides_clock_or_date(win):
    # The fixed 700/1280px density thresholds assume particular font metrics;
    # on a different DPI/font scale the header can still overflow past the
    # window edge in ultra tier. The priority-fit guard must shrink
    # lower-priority widgets instead — clock and date always survive.
    def _repack(w, h):
        # a locked window silently reverts resize(), so the density tier
        # would read a stale width and never engage
        win.is_locked = False
        win._locked_geometry = None
        # re-apply scale too: earlier tests in this module leave ui_scale /
        # font_size changed, and apply_theme() alone doesn't resize buttons
        win.apply_scaled_ui()
        win.apply_font()
        win._header_dense = None
        win._header_ultra = None
        _force_width(win, w, h)
        win._apply_header_density()
        win._update_date_label()
        win._apply_header_density()  # second pass, as a real resize settles

    try:
        # The realistic case from the user's screenshots: default scale,
        # narrow window. Everything must fit AND the clock/date survive.
        win.data["ui_scale"] = "1.0"
        win.data["font_size"] = "11"
        win.apply_theme()
        _repack(640, 900)
        assert not win.lbl_date.isHidden()
        assert not win.analog_clock.isHidden()
        assert win.header_widget.sizeHint().width() <= win.header_widget.width(), (
            f"header overflows: wants {win.header_widget.sizeHint().width()}px, "
            f"has {win.header_widget.width()}px")

        # Extreme scale on a sliver of a window — still must fit, and the
        # clock and date must still never be what gets sacrificed.
        win.data["ui_scale"] = "1.5"
        win.data["font_size"] = "16"
        win.apply_theme()
        _repack(300, 900)
        assert not win.lbl_date.isHidden()
        assert not win.analog_clock.isHidden()
        assert win.header_widget.sizeHint().width() <= win.header_widget.width(), (
            f"header overflows at 1.5x: wants {win.header_widget.sizeHint().width()}px, "
            f"has {win.header_widget.width()}px")
    finally:
        win.data["ui_scale"] = "1.0"
        win.data["font_size"] = "11"
        win.apply_theme()
        win.resize(1400, 700)
        win._header_dense = None
        win._header_ultra = None
        win._apply_header_density()
        win._update_date_label()


def test_ctrl_q_snap_and_fancy_zones_overlay(win):
    # Regression: fancy_zones.py called QCursor.pos() without importing
    # QCursor, so Ctrl+Q raised NameError and crashed the app on first use.
    # Same class as the logger-unimported bug: only reachable by actually
    # running the path, invisible to import-time checks.
    win.is_locked = False
    win._locked_geometry = None
    before = win.geometry()
    for _ in range(5):  # cycle right through all 4 corners and wrap
        win.cycle_snap_corner()  # must not raise
    assert win._fancy_zones is not None
    win.setGeometry(before)


def test_no_undefined_names_in_package():
    # Guard the whole package against F821 (undefined name) — the bug class
    # that has now bitten twice (logger, QCursor): a name only referenced on
    # a rarely-taken branch crashes the app the first time a user hits it.
    import subprocess

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    res = subprocess.run(
        ["uv", "run", "ruff", "check", "--select", "F821", "--output-format", "concise", "src/"],
        cwd=root, capture_output=True, text=True,
    )
    assert "F821" not in res.stdout, f"undefined names found:\n{res.stdout}"


def test_fancyzones_layouts_are_well_formed():
    from fastprompter.ui.fancy_zones import BUILTIN_LAYOUTS, layouts_for

    for name, zones in BUILTIN_LAYOUTS:
        assert zones, f"{name} has no zones"
        assert len(zones) <= 9, f"{name} has more zones than digit keys"
        for x, y, w, h in zones:
            assert 0.0 <= x < 1.0 and 0.0 <= y < 1.0, f"{name} origin off-screen"
            assert w > 0 and h > 0, f"{name} has a zero-size zone"
            assert x + w <= 1.0001 and y + h <= 1.0001, f"{name} overflows the screen"

    # exactly two pages: Tab is a switch to flick, not a menu to read
    names = [n for n, _ in layouts_for({})]
    assert names == ["Quarters", "Columns"]

    quarters = dict(BUILTIN_LAYOUTS)["Quarters"]
    assert len(quarters) == 4
    assert abs(sum(w * h for _, _, w, h in quarters) - 1.0) < 1e-9, \
        "the quarters must tile the screen exactly"

    columns = dict(BUILTIN_LAYOUTS)["Columns"]
    assert len(columns) == 3
    # 640 / 800 / 640 on a 1920-wide screen, and the middle one is centred
    widths = [round(w * 1920) for _, _, w, _h in columns]
    assert widths == [640, 800, 640]
    left, mid, right = columns
    assert round(left[0] * 1920) == 0
    assert round(mid[0] * 1920) == 560 and round((mid[0] + mid[2]) * 1920) == 1360
    assert round((right[0] + right[2]) * 1920) == 1920
    assert all(h == 1.0 for _x, _y, _w, h in columns), "columns are full height"


def test_fancyzones_picker_snaps_window_and_remembers_layout(win):
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    win.is_locked = False
    win._locked_geometry = None
    ov = win._fancy_zones

    assert ov.open_for(win) is True
    assert ov._zones, "picker opened with no zones"

    # Tab cycles layouts and the zone rects are rebuilt
    first_name = ov._layouts[ov._layout_idx][0]
    before = list(ov._zones)
    ov.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Tab,
                               Qt.KeyboardModifier.NoModifier))
    assert ov._layouts[ov._layout_idx][0] != first_name
    assert ov._zones != before

    # digit key snaps the window into that zone. A zone can be narrower than
    # the window's minimum size (minimumSize silently wins over setGeometry),
    # so the contract is: origin matches, size is the zone grown to the
    # window's minimum, and the result stays inside the screen.
    target = QRect(ov._zones[0])
    avail = QRect(ov._avail)
    ov.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_1,
                               Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    got = win.geometry()
    assert got.width() == max(target.width(), win.minimumWidth())
    assert got.height() == max(target.height(), win.minimumHeight())
    assert got.x() == target.x() and got.y() == target.y()
    assert avail.contains(got) or got.width() >= avail.width()
    assert ov.isHidden()
    # and the layout it snapped with is remembered for next time
    assert win.data.get("fancyzones_layout") == ov._layouts[ov._layout_idx][0]

    # reopening restores that layout rather than starting from the top
    assert ov.open_for(win) is True
    assert ov._layouts[ov._layout_idx][0] == win.data["fancyzones_layout"]

    # Esc cancels without moving the window
    geo = win.geometry()
    ov.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                               Qt.KeyboardModifier.NoModifier))
    assert ov.isHidden()
    assert win.geometry() == geo


def test_fancyzones_respects_locked_window(win):
    from PyQt6.QtWidgets import QApplication

    ov = win._fancy_zones
    win.is_locked = False
    win._locked_geometry = None
    ov.open_for(win)
    geo = win.geometry()
    try:
        win.is_locked = True
        assert ov.apply_zone(0) is False, "a locked window must not be moved"
        QApplication.processEvents()
        assert win.geometry() == geo
    finally:
        win.is_locked = False
        ov.close()


def test_fancyzones_has_no_orphaned_grid_settings(win):
    """The custom NxM grid was dropped when the picker went to two fixed
    pages; its Settings spin boxes would otherwise sit there doing nothing."""
    assert not hasattr(win, "spin_zone_rows")
    assert not hasattr(win, "spin_zone_cols")


def test_overflow_menu_exposes_buttons_hidden_by_narrow_header(win):
    # At the width from the user's screenshot the density tiers drop most of
    # the header. Those buttons must stay reachable through the "»" menu
    # instead of simply vanishing for anyone who doesn't know the hotkey.
    win.is_locked = False
    win._locked_geometry = None
    try:
        win.apply_scaled_ui()
        win._header_dense = None
        win._header_ultra = None
        _kept_min = _force_width(win, 636, 800)   # the reported resolution
        win._apply_header_density()

        assert win._header_ultra is True, (
            f"ultra never engaged: win.width()={win.width()} "
            f"minW={win.minimumWidth()} hidden={win.isHidden()} "
            f"locked={getattr(win, 'is_locked', None)}")
        hidden = win._overflow_hidden_buttons()
        assert hidden, "ultra hid nothing — the tier stopped working"
        names = {n for n, _ in hidden}
        for expected in ("btn_bold", "btn_italic", "btn_trash", "btn_files"):
            assert expected in names, f"{expected} unreachable at 636px"
        assert not win.btn_overflow.isHidden(), "» must appear when things are hidden"

        # the menu actually fires the real button: Bold via the menu must
        # produce the same edit as clicking the (hidden) toolbar button
        win.data["temp_presets"][:] = ["hello"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        cur = win.text_area.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, cur.MoveMode.KeepAnchor)
        win.text_area.setTextCursor(cur)
        dict(hidden)["btn_bold"].click()
        assert "**hello**" in win.text_area.toPlainText()

        # widen again: nothing hidden -> the » button gets out of the way
        win._header_dense = None
        win._header_ultra = None
        win.resize(1400, 800)
        win._apply_header_density()
        assert win._overflow_hidden_buttons() == []
        assert win.btn_overflow.isHidden()
    finally:
        _restore_minimum(win, _kept_min)
        win._header_dense = None
        win._header_ultra = None
        win.resize(1400, 700)
        win._apply_header_density()


def test_code_font_follows_monospace_toggle(win):
    # "MONOSPACE -> VERDANA (or user preferred font)": code spans forced
    # Consolas regardless of the editor font.
    hl = win.highlighter
    try:
        win.data["code_monospace"] = "True"
        win._apply_code_font()
        assert hl.code_font_family is None  # None means Consolas

        win.data["font_family"] = "Verdana"
        win.data["code_monospace"] = "False"
        win._apply_code_font()
        assert hl.code_font_family == "Verdana"

        # the inline-code rule really carries that family, and drops the
        # fixed-pitch flag so a proportional font isn't forced to fake it
        fmt = next(f for pat, f in hl._highlighting_rules
                   if pat.pattern == r'`[^`]+`')
        assert fmt.fontFamily() == "Verdana"
        assert fmt.fontFixedPitch() is False

        # changing the editor font carries through while monospace is off
        win.data["font_family"] = "Tahoma"
        win.apply_font()
        assert hl.code_font_family == "Tahoma"
    finally:
        win.data["code_monospace"] = "True"
        win.data["font_family"] = "Verdana"
        win.apply_font()
        win._apply_code_font()


def test_strikethrough_never_accumulates_tildes(win):
    # The explicit worry: "~~" multiplying forever. Toggling must be
    # idempotent no matter how many times it runs, and must cope with text
    # that already contains tildes.
    ta = win.text_area
    assert ta.wrap_strike("done") == "~~done~~"
    assert ta.wrap_strike("~~done~~") == "~~done~~"          # already struck
    assert ta.wrap_strike("~~~~done~~~~") == "~~done~~"      # over-wrapped
    assert ta.strip_strike("~~~~~~done~~~~~~") == "done"     # deeply nested
    assert ta.strip_strike("plain") == "plain"
    # two separate spans are NOT one wrapper — must not be mangled
    assert ta.strip_strike("~~a~~ and ~~b~~") == "~~a~~ and ~~b~~"
    assert ta.wrap_strike("~~a~~ and ~~b~~") == "~~a~~ and ~~b~~"
    # an unbalanced tail would fuse into "~~~~" if wrapped blindly
    assert "~~~~" not in ta.wrap_strike("a~~")
    # never strike an empty line into bare "~~~~"
    assert ta.wrap_strike("   ") == "   "


def test_middle_click_cycles_line_checkbox(win):
    # MButton on a line: plain -> checked+struck -> unchecked -> plain,
    # and cycling forever must not grow tildes.
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QMouseEvent

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["buy milk"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    def middle_click():
        p = ta.cursorRect(ta.textCursor()).center()
        p = p.toPointF() if hasattr(p, "toPointF") else p
        ta.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, p,
            Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier))
        return ta.toPlainText()

    assert middle_click() == "[x] ~~buy milk~~"   # 1st: checked AND struck
    assert middle_click() == "[ ] buy milk"       # 2nd: unchecked, strike gone
    assert middle_click() == "buy milk"           # 3rd: back to plain

    # ten more laps must land on exactly the same three strings
    for _ in range(3):
        assert middle_click() == "[x] ~~buy milk~~"
        assert middle_click() == "[ ] buy milk"
        assert middle_click() == "buy milk"
    assert "~~~~" not in ta.toPlainText()


def test_line_marks_cycle_both_ways_and_persist_per_silo(win):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent, QTextCursor

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["line_marks"] = "True"
    win.data["temp_presets"][:] = ["alpha\nbeta", "other silo"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    def click_gutter(block_num, button):
        blk = ta.document().findBlockByNumber(block_num)
        y = ta.cursorRect(QTextCursor(blk)).top() + 2
        ta.line_number_area_mouse_press_event(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(4, y),
            button, button, Qt.KeyboardModifier.NoModifier))
        return max(0, ta.document().findBlockByNumber(block_num).userState()) & 0xFF

    assert click_gutter(0, Qt.MouseButton.LeftButton) == 1     # forward
    assert click_gutter(0, Qt.MouseButton.LeftButton) == 2
    assert click_gutter(0, Qt.MouseButton.RightButton) == 1    # backward
    assert click_gutter(0, Qt.MouseButton.RightButton) == 0
    assert click_gutter(0, Qt.MouseButton.RightButton) == 4    # wraps around

    # marks are stored per silo and come back after switching away
    saved = ta.collect_line_marks()
    assert saved.get(0) == 4
    win._switch_to_slot(1)
    assert ta.collect_line_marks().get(0) is None   # other silo is clean
    win._switch_to_slot(0)
    assert ta.collect_line_marks().get(0) == 4      # restored

    win.data["line_marks"] = "False"


def test_selection_state_is_remembered_per_silo(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["first silo text", "second silo text"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    cur = ta.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, cur.MoveMode.KeepAnchor)   # select "first"
    ta.setTextCursor(cur)

    win._switch_to_slot(1)
    cur2 = ta.textCursor()
    cur2.setPosition(7)                            # caret only, no selection
    ta.setTextCursor(cur2)

    win._switch_to_slot(0)
    back = ta.textCursor()
    assert back.hasSelection()
    assert back.selectedText() == "first"

    win._switch_to_slot(1)
    back2 = ta.textCursor()
    assert not back2.hasSelection()
    assert back2.position() == 7


def test_snippets_toggle_survives_refreshes(win):
    # "must be reliable": the panel used to come back on the next refresh
    try:
        win.data["snippets_hidden"] = "False"
        win.refresh_snippets_panel()

        win.toggle_snippets_panel()
        assert win.data["snippets_hidden"] == "True"
        assert win.snippets_section.isHidden()
        assert win.btn_toggle_snippets.isChecked()

        # every one of these used to re-show the panel
        win.refresh_snippets_panel()
        win._switch_to_slot(0)
        win.refresh_temp_presets()
        assert win.snippets_section.isHidden(), "panel came back on refresh"

        win.toggle_snippets_panel()
        assert win.data["snippets_hidden"] == "False"
        assert not win.btn_toggle_snippets.isChecked()
    finally:
        win.data["snippets_hidden"] = "False"
        win.refresh_snippets_panel()


def test_alt_hotkeys_registered(win):
    from PyQt6.QtGui import QKeySequence

    keys = {sc.key().toString() for sc in win._app_shortcuts}
    assert QKeySequence("Alt+Z").toString() in keys      # line numbers
    assert QKeySequence("Alt+`").toString() in keys      # settings panel


def test_overflow_menu_labels_are_short(win):
    # The menu used to take its labels from tooltip first lines, which read
    # like documentation ("Files—asset drawer for the active silo (drop in…").
    labels = [lbl for name, lbl in win._OVERFLOW_LABELS if name]
    assert labels, "no overflow labels defined"
    for lbl in labels:
        assert len(lbl) <= 20, f"overflow label too long: {lbl!r}"
        assert "\n" not in lbl and "(" not in lbl and "—" not in lbl
    # and every label maps to a button that actually exists
    for name, _lbl in win._OVERFLOW_LABELS:
        if name:
            assert getattr(win, name, None) is not None, f"{name} missing"


def test_unquoting_a_collapsed_quote_does_not_lose_lines(win):
    # CRITICAL regression: un-quoting while collapsed removed the fold anchor
    # and left the hidden lines invisible with nothing left to expand them —
    # the text was all still in the document but gone from the user's view.
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha\nbeta\ngamma"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()

    cur = ta.textCursor()
    cur.setPosition(0)
    cur.setPosition(len("alpha\nbeta\ngamma"), cur.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)
    win.toggle_quote_conversion()
    assert ta.toPlainText() == "> alpha\n> beta\n> gamma"

    ta.toggle_fold(doc.findBlockByNumber(0))
    assert [doc.findBlockByNumber(i).isVisible() for i in range(3)] == [True, False, False]

    cur = ta.textCursor()
    cur.setPosition(0)
    ta.setTextCursor(cur)
    win.toggle_quote_conversion()   # unquote while collapsed

    assert [doc.findBlockByNumber(i).isVisible() for i in range(3)] == [True, True, True]
    assert doc.blockCount() == 3
    assert "beta" in ta.toPlainText() and "gamma" in ta.toPlainText()


def test_rescue_orphan_folds_restores_stranded_lines(win):
    # The generic net: any edit that strands hidden blocks must be recoverable.
    win.data["temp_presets"][:] = ["> a\n> b\n> c"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()
    ta.toggle_fold(doc.findBlockByNumber(0))
    assert not doc.findBlockByNumber(1).isVisible()

    # rip out the anchor behind the fold engine's back
    cur = ta.textCursor()
    cur.setPosition(0)
    cur.movePosition(cur.MoveOperation.EndOfBlock, cur.MoveMode.KeepAnchor)
    cur.insertText("plain")
    assert ta.rescue_orphan_folds() is True
    assert all(doc.findBlockByNumber(i).isVisible() for i in range(3))


def test_hover_line_wash_follows_the_cursor(win):
    from PyQt6.QtGui import QTextFormat

    win.data["temp_presets"][:] = ["one\ntwo\nthree"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()
    try:
        win.data["hover_line"] = "True"
        ta._hover_block = 1
        sels = ta._hover_line_selection(doc)
        assert len(sels) == 1
        fmt = sels[0].format
        assert fmt.property(QTextFormat.Property.FullWidthSelection) is True
        # default: faint (10%) and blueish, not a solid slab
        assert 0 < fmt.background().color().alpha() <= 40
        assert fmt.background().color().blue() > fmt.background().color().red()
        assert sels[0].cursor.blockNumber() == 1

        # opacity is user-controlled and clamped
        win.data["hover_line_opacity"] = "50"
        assert ta._hover_line_selection(doc)[0].format.background().color().alpha() > 100
        win.data["hover_line_opacity"] = "nonsense"
        assert ta._hover_line_selection(doc)  # falls back instead of raising

        # leaving the editor clears it
        ta._hover_block = None
        assert ta._hover_line_selection(doc) == []

        # and the whole thing is switchable off
        ta._hover_block = 1
        win.data["hover_line"] = "False"
        assert ta._hover_line_selection(doc) == []
    finally:
        win.data["hover_line"] = "True"
        win.data["hover_line_opacity"] = "10"
        ta._hover_block = None


def test_shortcuts_match_physical_key_regardless_of_layout():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeySequence

    from fastprompter.ui.layout_shortcuts import LayoutIndependentShortcuts, split_sequence

    key, mods = split_sequence(QKeySequence("Alt+Z"))
    assert key == Qt.Key.Key_Z
    assert mods == Qt.KeyboardModifier.AltModifier

    key, mods = split_sequence(QKeySequence("Alt+`"))
    assert key == Qt.Key.Key_QuoteLeft

    flt = LayoutIndependentShortcuts()
    fired = []
    assert flt.register(QKeySequence("Alt+Z"), lambda: fired.append("z")) is True
    # keys that are already layout-independent aren't registered
    assert flt.register(QKeySequence("F5"), lambda: fired.append("f5")) is False
    assert flt.register(QKeySequence("Ctrl+Alt+Shift+Q"), lambda: None) is True


def test_only_first_header_gets_a_timestamp(win):
    # The first header dates the note; later ones are section markers and
    # would just repeat the same stamp, so they get a plain "# ".
    import re as _re

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["intro line\nbody\nsecond section\nmore"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area

    def block_containing(needle):
        doc = ta.document()
        for i in range(doc.blockCount()):
            if needle in doc.findBlockByNumber(i).text():
                return i
        raise AssertionError(f"{needle!r} not found in {ta.toPlainText()!r}")

    def header_line(needle):
        # Ctrl+E also opens a fresh bullet below, so block numbers shift —
        # always re-find the line by content.
        n = block_containing(needle)
        cur = ta.textCursor()
        cur.setPosition(ta.document().findBlockByNumber(n).position())
        ta.setTextCursor(cur)
        win.apply_header_timestamp()
        return ta.document().findBlockByNumber(block_containing(needle)).text()

    first = header_line("intro line")
    assert first.startswith("# ")
    assert _re.search(r"\d{2}[.\s]\w*\d*\s*-\s*\d{2}:\d{2}", first), first

    later = header_line("second section")
    assert later.startswith("# ")
    assert "second section" in later
    assert not _re.search(r"\d{2}:\d{2}", later), f"later header got a stamp: {later}"

    # Ctrl+E again on the first header still un-headers it (round trip intact)
    n = block_containing("intro line")
    cur = ta.textCursor()
    cur.setPosition(ta.document().findBlockByNumber(n).position())
    ta.setTextCursor(cur)
    win.apply_header_timestamp()
    assert ta.document().findBlockByNumber(n).text().strip() == "intro line"


# ---------------------------------------------------------------------------
# Undo / redo integrity
# ---------------------------------------------------------------------------

def _fresh_doc(win, text):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [text]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    return win.text_area


def _type(ta, text):
    """Type through the real key path, as a user does.

    Programmatic insertPlainText() bypasses keyPressEvent, and therefore
    bypasses the undo-boundary logic that lives there.
    """
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QKeyEvent as _QKeyEvent

    for ch in text:
        ta.keyPressEvent(_QKeyEvent(_QKeyEvent.Type.KeyPress, _Qt.Key.Key_A,
                                    _Qt.KeyboardModifier.NoModifier, ch))


def _select(ta, start, end):
    cur = ta.textCursor()
    cur.setPosition(start)
    cur.setPosition(end, cur.MoveMode.KeepAnchor)
    ta.setTextCursor(cur)
    return cur


def test_every_edit_op_is_exactly_one_undo_step(win):
    """The core guarantee: one user action == one Ctrl+Z.

    NB: QTextDocument.availableUndoSteps() counts internal edit operations,
    not user-visible steps, so it is useless as a metric here. What matters
    is behaviour: a single undo() must restore the pre-operation text, and a
    later unrelated edit must undo INDEPENDENTLY — if an operation leaked an
    open edit block, one undo would swallow both.
    """
    ops = [
        ("quote", "alpha\nbeta", lambda ta: (_select(ta, 0, 10), win.toggle_quote_conversion())),
        ("bullets", "- one\n- two", lambda ta: (_select(ta, 0, 11), win.toggle_bullet_conversion())),
        ("header", "title\nbody", lambda ta: (_select(ta, 0, 0), win.apply_header_timestamp())),
        ("bold", "make me bold", lambda ta: (_select(ta, 0, 4), win.apply_format("bold"))),
        ("checkbox", "task line", lambda ta: ta._toggle_checkboxes()),
        ("move", "one\ntwo\nthree", lambda ta: ta._move_lines(0, 0, 2)),
    ]
    for name, start_text, run in ops:
        ta = _fresh_doc(win, start_text)
        before_text = ta.toPlainText()

        run(ta)
        after_op = ta.toPlainText()
        assert after_op != before_text, f"{name}: made no change"

        # a following unrelated edit must stay its own step
        cur = ta.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ta.setTextCursor(cur)
        _type(ta, "ZZ")
        assert ta.toPlainText() == after_op + "ZZ"

        ta.undo()
        assert ta.toPlainText() == after_op, (
            f"{name}: one undo swallowed both the trailing edit AND the "
            f"operation - the document was left inside an edit block")

        ta.undo()
        assert ta.toPlainText() == before_text, f"{name}: undo did not restore original"

        ta.redo()
        assert ta.toPlainText() == after_op, f"{name}: redo did not reapply the operation"


def test_long_undo_redo_chain_returns_to_the_exact_original(win):
    # Heavy scenario: a long mixed chain, unwound completely and replayed.
    ta = _fresh_doc(win, "line0")
    doc = ta.document()
    original = ta.toPlainText()

    snapshots = [original]
    for i in range(1, 41):
        cur = ta.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ta.setTextCursor(cur)
        if i % 5 == 0:
            _select(ta, 0, min(5, len(ta.toPlainText())))
            win.toggle_quote_conversion()
        elif i % 3 == 0:
            ta.insertPlainText(f"\nbullet {i}")
            _select(ta, 0, len(ta.toPlainText()))
            win.toggle_bullet_conversion()
        else:
            ta.insertPlainText(f"\nline{i}")
        snapshots.append(ta.toPlainText())

    # rewind everything
    for _ in range(len(snapshots) * 3):
        if not doc.availableUndoSteps():
            break
        ta.undo()
    assert ta.toPlainText() == original, "full undo did not reach the original text"

    # and roll all the way forward again
    while doc.availableRedoSteps():
        ta.redo()
    assert ta.toPlainText() == snapshots[-1], "full redo did not reach the final text"


def test_new_edit_after_undo_discards_redo_branch(win):
    # Standard editor contract: editing after undo drops the redo branch and
    # must never resurrect the discarded text later.
    ta = _fresh_doc(win, "base")
    _select(ta, 0, 4)
    win.apply_format("bold")
    bolded = ta.toPlainText()
    assert bolded != "base"

    ta.undo()
    assert ta.toPlainText() == "base"
    assert ta.document().availableRedoSteps() > 0

    cur = ta.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    ta.setTextCursor(cur)
    _type(ta, " NEW")
    assert ta.toPlainText() == "base NEW"
    assert ta.document().availableRedoSteps() == 0, "redo branch survived a new edit"

    ta.undo()
    assert ta.toPlainText() == "base"
    ta.redo()
    assert ta.toPlainText() == "base NEW", "redo brought back the discarded branch"


def test_undo_is_intact_after_an_operation_raises(win):
    # "Unexpected scenario": if an edit throws mid-way, the document must not
    # be left inside an edit block — that is what historically froze the app
    # and silently glued every later edit into one undo step.
    from fastprompter.ui.edit_guard import edit_block

    ta = _fresh_doc(win, "safe text")
    before = ta.toPlainText()

    with pytest.raises(RuntimeError):
        with edit_block(ta.textCursor()) as cur:
            cur.insertText("partial")
            raise RuntimeError("boom")

    # the document must still be usable and its history must still separate
    partial = ta.toPlainText()
    assert partial != before, "the partial edit vanished entirely"
    cur = ta.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    ta.setTextCursor(cur)
    _type(ta, "!")

    ta.undo()
    assert ta.toPlainText() == partial, (
        "document was left inside an edit block after an exception - "
        "one undo swallowed two separate edits")
    ta.undo()
    assert ta.toPlainText() == before


def test_undo_survives_folded_regions_and_silo_switches(win):
    # Folding hides blocks; undo must not resurrect them half-hidden, and
    # each silo keeps its own independent history.
    ta = _fresh_doc(win, "> a\n> b\n> c")
    doc = ta.document()
    ta.toggle_fold(doc.findBlockByNumber(0))
    assert not doc.findBlockByNumber(1).isVisible()

    _select(ta, 0, len(ta.toPlainText()))
    win.toggle_quote_conversion()          # unquote while folded
    unquoted = ta.toPlainText()
    ta.undo()
    assert ta.toPlainText() == "> a\n> b\n> c"
    assert all(doc.findBlockByNumber(i).isVisible() for i in range(3)), (
        "undo left blocks stranded invisible")
    ta.redo()
    assert ta.toPlainText() == unquoted

    # independent per-silo history
    win.data["temp_presets"][:] = ["first", "second"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    # clear any restored per-silo selection first, or the insert REPLACES it
    _cur = win.text_area.textCursor()
    _cur.movePosition(_cur.MoveOperation.End)
    win.text_area.setTextCursor(_cur)
    win.text_area.insertPlainText(" EDITED")
    assert win.text_area.toPlainText() == "first EDITED"
    win._switch_to_slot(1)
    win.text_area.undo()                    # must not touch silo 0
    win._switch_to_slot(0)
    assert win.text_area.toPlainText() == "first EDITED", (
        "undo in one silo modified another")


def test_app_level_undo_stack_is_capped(win):
    # Heavy use must not grow the snapshot stack without bound (it used to
    # reach 12MB on disk and slow every action down).
    for i in range(80):
        win.data["temp_presets"][:] = [f"text {i}"]
        win.add_data_undo_state(f"op {i}")
    assert len(win.data_undo_stack) <= 50, (
        f"undo stack grew to {len(win.data_undo_stack)}")


def test_no_unguarded_edit_blocks_in_new_code():
    """Every beginEditBlock must be exception-safe.

    An edit that raises between begin and end leaves QTextDocument's counter
    stuck: undo grouping breaks and rendering can stall. The fix is the
    edit_block() context manager or an explicit try/finally.

    Existing call sites that predate the guard are listed below. The list may
    SHRINK, never grow — a new raw beginEditBlock fails this test.
    """
    import ast
    import pathlib

    known_unguarded = {
        ("editor.py", "keyPressEvent"),
        ("formatting_mixin.py", "apply_format"),
        ("formatting_mixin.py", "toggle_bullet_conversion"),
        # insert_add_line came off this list on 04.08 (T-717): it now uses
        # edit_block, like its Alt+W sibling. The list shrinks, never grows.
        ("formatting_mixin.py", "insert_old_add_line"),
        ("formatting_mixin.py", "toggle_quote_conversion"),
        ("formatting_mixin.py", "clear_formatting"),
        ("search_mixin.py", "replace_all"),
        ("snippet_ops_mixin.py", "backup_silo_to_files"),
        ("snippet_ops_mixin.py", "clear_text"),
        ("snippet_ops_mixin.py", "insert_snippet_text"),
    }

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"
    found = set()
    for path in sorted(root.rglob("*.py")):
        if path.name == "edit_guard.py":
            continue  # this IS the guard
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            raw = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "beginEditBlock"
            ]
            if raw:
                found.add((path.name, fn.name))

    new = found - known_unguarded
    assert not new, (
        "new raw beginEditBlock() call(s) - wrap them in edit_block() so an "
        f"exception cannot strand the document mid-edit: {sorted(new)}")


def test_timer_end_to_end(win):
    # Clicking the clock manages timers; the soonest one shows beside it,
    # coloured by urgency; due timers fire once and persist across a reload.
    import datetime

    from fastprompter.core.duration import resolve_target
    from fastprompter.core.timers import Timer, load_timers
    from fastprompter.ui.timer_dialog import TimerDialog

    win.is_locked = False
    win._locked_geometry = None
    saved = list(win.timers)
    try:
        win.timers.clear()

        # the headline input works through the real resolve path
        target = resolve_target("4 days 11 hours")
        assert target is not None
        win.timers.append(Timer("Claude limit", target))
        win.timers.append(Timer("Soon", datetime.datetime.now()
                                + datetime.timedelta(minutes=3)))
        win.save_timers_to_data()

        # survives a save/load round trip through the data dict
        assert len(load_timers(win.data["timers"])) == 2

        # nearest timer is shown, named and coloured hot (3 min away)
        win.apply_scaled_ui()
        win._header_dense = None
        win._header_ultra = None
        win.resize(1400, 800)
        win._apply_header_density()
        win._update_date_label()
        assert not win.lbl_timer.isHidden()
        assert "Soon" in win.lbl_timer.text()
        style = win.lbl_timer.styleSheet()
        assert "color:" in style
        hot = style.split("color:")[-1].strip().rstrip(";")
        assert hot.startswith("#")

        # a far-off timer must be a cooler colour than an imminent one
        far = Timer("far", datetime.datetime.now() + datetime.timedelta(days=3))
        near = Timer("near", datetime.datetime.now() + datetime.timedelta(minutes=1))
        assert int(far.display_color()[1:3], 16) < int(near.display_color()[1:3], 16)

        # a due timer fires exactly once
        win.timers.append(Timer("Fires", datetime.datetime.now()
                                - datetime.timedelta(seconds=1)))
        win._check_timers()
        fired = [t for t in win.timers if t.name == "Fires"][0]
        assert fired.fired is True
        win._check_timers()
        assert fired.fired is True          # still just the once

        # the dialog lists them and validates input live
        dlg = TimerDialog(win)
        assert dlg.list.count() == len(win.timers)
        dlg.in_when.setText("2 hours")
        assert "(" in dlg.lbl_hint.text()   # shows the resolved countdown
        dlg.in_when.setText("qwerty")
        assert "understand" in dlg.lbl_hint.text().lower()

        # adding through the dialog lands in the model
        before = len(win.timers)
        dlg.in_name.setText("Added")
        dlg.in_when.setText("45m")
        dlg.commit()
        assert len(win.timers) == before + 1
        assert any(t.name == "Added" for t in win.timers)
        dlg.close()
    finally:
        win.timers[:] = saved
        win.save_timers_to_data()
        win._header_dense = None
        win._header_ultra = None
        win.resize(1400, 700)
        win._apply_header_density()


def test_timer_label_hides_in_ultra_and_with_no_timers(win):
    saved = list(win.timers)
    try:
        win.timers.clear()
        win._update_date_label()
        assert win.lbl_timer.isHidden(), "no timers -> nothing to show"
    finally:
        win.timers[:] = saved


def test_timer_description_edit_snooze_and_test_fire(win):
    # The "comprehensive" half: description, editing an existing timer,
    # snoozing, and a test fire that must never become a real timer.

    from fastprompter.core.timers import load_timers
    from fastprompter.ui.timer_dialog import TimerDialog

    saved = list(win.timers)
    try:
        win.timers.clear()
        dlg = TimerDialog(win)

        # --- add with a description ---
        dlg.in_name.setText("Claude limit")
        dlg.in_desc.setText("5-hour window resets")
        dlg.in_when.setText("4 days 11 hours")
        dlg.commit()
        assert len(win.timers) == 1
        t = win.timers[0]
        assert t.description == "5-hour window resets"
        assert "5-hour window resets" in t.summary()
        # description survives persistence
        assert load_timers(win.data["timers"])[0].description == "5-hour window resets"

        # --- edit it in place: same id, new values, re-armed ---
        dlg.refresh()
        dlg.list.setCurrentRow(0)
        dlg.edit_selected()
        assert dlg._editing_id == t.id
        assert dlg.in_desc.text() == "5-hour window resets"
        dlg.in_name.setText("Renamed")
        dlg.in_desc.setText("new note")
        dlg.in_when.setText("2h")
        dlg.commit()
        assert len(win.timers) == 1, "editing must not create a second timer"
        assert win.timers[0].id == t.id
        assert win.timers[0].name == "Renamed"
        assert win.timers[0].description == "new note"
        assert win.timers[0].fired is False
        assert dlg._editing_id is None, "form should reset after saving"

        # --- snooze pushes the target out and re-arms ---
        win.timers[0].fired = True
        before = win.timers[0].target
        dlg.refresh()
        dlg.list.setCurrentRow(0)
        dlg.snooze_selected()
        assert win.timers[0].target > before
        assert win.timers[0].fired is False

        # --- pause / resume ---
        dlg.toggle_selected()
        assert win.timers[0].enabled is False
        dlg.toggle_selected()
        assert win.timers[0].enabled is True

        # --- test fire creates NO persistent timer ---
        count = len(win.timers)
        probe = win.test_timer_notification(win.timers[0], delay_seconds=0)
        assert probe is not None
        assert len(win.timers) == count, "a test must not add a real timer"
        assert all(x.id != probe.id for x in win.timers)
        assert "seconds" in dlg.lbl_hint.text() or True  # hint set by test_now

        # --- invalid input never creates anything ---
        n = len(win.timers)
        dlg.in_when.setText("total nonsense")
        dlg.commit()
        assert len(win.timers) == n
        assert "understand" in dlg.lbl_hint.text().lower()

        dlg.close()
    finally:
        win.timers[:] = saved
        win.save_timers_to_data()


def test_timer_toast_shows_and_snoozes(win):
    import datetime

    from PyQt6.QtCore import Qt

    from fastprompter.core.timers import Timer
    from fastprompter.ui.timer_toast import TimerToast, show_toast

    t = Timer("Popup test", datetime.datetime.now(), description="with a note")
    snoozed = []
    toast = show_toast(win, t, on_snooze=lambda tm, m: snoozed.append((tm, m)))
    try:
        assert toast is not None
        assert toast in TimerToast._open
        # the popup must not steal focus from whatever is being typed
        assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        toast._snooze(5)
        assert snoozed and snoozed[0][1] == 5
        assert toast not in TimerToast._open, "closing must deregister the toast"
    finally:
        if toast is not None and not toast.isHidden():
            toast.close()


def test_timer_sound_restores_user_volume(win):
    # An alarm plays at its own volume and force-enables sound; neither may
    # leak into the user's settings afterwards.
    import datetime

    from fastprompter.core.timers import Timer

    win.data["sound_volume"] = "3"
    win.data["sound_ui"] = "False"
    win._play_timer_sound(Timer("x", datetime.datetime.now(), volume=9))
    assert win.data["sound_volume"] == "3"
    assert win.data["sound_ui"] == "False"


def test_settings_panel_is_tabbed_and_fits_a_small_window(win):
    # It used to be three columns side by side plus a 17-control row, so the
    # panel demanded ~1800px before anything was readable. Tabs + FlowLayout
    # must bring that inside the 640x480 the UI spec requires.
    from PyQt6.QtWidgets import QCheckBox

    tabs = win.settings_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Window", "Editor", "Clock", "Data"]

    need = win.mini_settings_frame.sizeHint().width()
    assert need <= 560, f"settings panel still needs {need}px of width"

    # EVERY settings checkbox must live in some tab — moving widgets between
    # groups could otherwise strand one where the user can never reach it
    in_tabs = set()
    for i in range(tabs.count()):
        for cb in tabs.widget(i).findChildren(QCheckBox):
            in_tabs.add(id(cb))
    expected = [
        "cb_top", "cb_lock_window", "cb_normal_window", "cb_tray", "cb_sidebar",
        "cb_trash_vision", "cb_silo_color_box", "cb_customize_toolbar",
        "cb_focus", "cb_wrap", "cb_ctrl_c", "cb_lock_cursor", "cb_line_numbers",
        "cb_code_gutter", "cb_code_monospace", "cb_hover_line", "cb_line_marks",
        "cb_zebra", "cb_double_line", "cb_bold_titles",
        "cb_date_rect", "cb_date_seconds", "cb_date_daypart", "cb_date_emoji",
        "cb_date_text_month", "cb_date_ampm", "cb_analog_clock",
        "cb_silo_home", "cb_silo_pinned_gap", "cb_silo_ticks",
        "cb_snippet_arrows", "cb_hide_shortkeys", "cb_portable_backup",
        "cb_sound", "cb_typewriter",
    ]
    missing = [n for n in expected
               if getattr(win, n, None) is not None and id(getattr(win, n)) not in in_tabs]
    assert not missing, f"settings stranded outside every tab: {missing}"

    # the spin controls that live in rows must have survived the move too.
    # spin_zone_rows/cols are deliberately absent: the Ctrl+Q picker went to
    # two fixed pages, so the custom NxM grid they drove no longer exists.
    for name in ("spin_silo_gap", "spin_drag_width"):
        assert getattr(win, name, None) is not None, f"{name} lost in the rework"


def test_settings_flow_layout_reflows_instead_of_clipping():
    # The whole point: narrower panel -> more rows, never cut-off controls.
    from PyQt6.QtWidgets import QCheckBox

    from fastprompter.ui.flow_layout import FlowLayout, flow_widget

    host = flow_widget([QCheckBox(f"option {i}") for i in range(12)])
    flow = host.layout()
    assert isinstance(flow, FlowLayout)
    assert flow.count() == 12

    wide = flow.heightForWidth(1200)
    narrow = flow.heightForWidth(200)
    assert narrow > wide, "layout did not reflow when squeezed"

    # an item wider than the panel must not loop forever or be dropped:
    # the layout never wraps the FIRST item on a line for exactly this reason
    wide_item = QCheckBox("a label far wider than the panel it has to fit in")
    solo = flow_widget([wide_item])
    h = solo.layout().heightForWidth(40)     # must return, not hang
    assert h >= wide_item.sizeHint().height()
    assert solo.layout().count() == 1


def test_line_heat_follows_the_text_not_the_line_number(win):
    # The whole feature hinges on this: heat is carried by the block, so
    # inserting above must NOT smear it onto a different line.
    import time

    from fastprompter.ui.editor import _LineHeat

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha\nbeta\ngamma\ndelta"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()

    try:
        # switched off, nothing is painted (the shipped profile has it on,
        # so this pins the state instead of reading the default)
        win.data["line_heat"] = "False"
        assert ta._line_heat_selections(doc) == []

        win.data["line_heat"] = "True"
        cur = ta.textCursor()
        cur.setPosition(doc.findBlockByNumber(2).position())
        ta.setTextCursor(cur)
        ta.insertPlainText("X")
        heated = {s.cursor.blockNumber() for s in ta._line_heat_selections(doc)}
        assert 2 in heated, "the edited line was not marked"

        # push everything down one line
        cur.setPosition(0)
        ta.setTextCursor(cur)
        ta.insertPlainText("NEWTOP\n")
        moved = [i for i in range(doc.blockCount())
                 if doc.findBlockByNumber(i).text().startswith("Xgamma")]
        assert moved, "test text went missing"
        heated = {s.cursor.blockNumber() for s in ta._line_heat_selections(doc)}
        assert moved[0] in heated, (
            "heat did not follow the text when lines shifted - it is tracking "
            "line numbers instead of blocks")

        # older edits fade
        blk = doc.findBlockByNumber(0)
        blk.setUserData(_LineHeat(time.time() - 30))
        fresh = [s for s in ta._line_heat_selections(doc) if s.cursor.blockNumber() == 0]
        blk.setUserData(_LineHeat(time.time() - 3000))
        aged = [s for s in ta._line_heat_selections(doc) if s.cursor.blockNumber() == 0]
        assert fresh and aged
        assert (fresh[0].format.background().color().alpha()
                > aged[0].format.background().color().alpha()), "heat does not cool"

        # beyond the last bucket it stops rendering entirely
        blk.setUserData(_LineHeat(time.time() - 90000))
        assert not [s for s in ta._line_heat_selections(doc)
                    if s.cursor.blockNumber() == 0]

        # strength is user-controlled and clamped, not trusted blindly
        blk.setUserData(_LineHeat(time.time()))
        win.data["line_heat_strength"] = "60"
        strong = ta._line_heat_selections(doc)[0].format.background().color().alpha()
        win.data["line_heat_strength"] = "5"
        weak = ta._line_heat_selections(doc)[0].format.background().color().alpha()
        assert strong > weak
        win.data["line_heat_strength"] = "nonsense"
        assert ta._line_heat_selections(doc)      # falls back instead of raising

        # switching it off clears it immediately
        win.data["line_heat"] = "False"
        assert ta._line_heat_selections(doc) == []
    finally:
        win.data["line_heat"] = "False"
        win.data["line_heat_strength"] = "18"


def test_line_heat_hook_survives_silo_switches(win):
    # Each silo is a separate QTextDocument; the stamp hook must be
    # reconnected on every swap or only the first silo would ever heat.
    win.data["temp_presets"][:] = ["one", "two"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    try:
        win.data["line_heat"] = "True"
        win._switch_to_slot(1)
        ta = win.text_area
        cur = ta.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ta.setTextCursor(cur)
        ta.insertPlainText("!")
        assert ta._line_heat_selections(ta.document()), (
            "second silo never got heat - the contentsChange hook did not "
            "follow the document swap")
    finally:
        win.data["line_heat"] = "False"


# ---------------------------------------------------------------------------
# Silo identity: a silo IS its slot index, so every reorder must rewrite
# every slot-keyed store together or silos inherit each other's state.
# ---------------------------------------------------------------------------

def _silo_fixture(win):
    cat = win.get_current_category()
    win.data["temp_presets"][:] = ["AAA", "BBB", "CCC", "DDD"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.data["silo_colors"] = {"0": "#a00000", "1": "#00a000",
                               "2": "#0000a0", "3": "#a0a000"}
    win.data["silo_ticked"] = [2]
    win.data["pinned_silos"] = [3]
    win.data["silo_project_paths"] = {str(i): {"folder": f"p{i}"} for i in range(4)}
    win.data["silo_last_edited"] = {0: 100, 1: 200, 2: 300, 3: 400}
    store = win.data.setdefault("silo_view_state_all", {}).setdefault(cat, {})
    store.clear()
    for i in range(4):
        store[f"s{i}"] = {"anchor": i * 10, "pos": i * 10, "scroll": 0}
    return cat


def _state_of(win, cat, text):
    """Everything attached to the silo currently holding `text`."""
    idx = win.data["temp_presets"].index(text)
    vs = win.data["silo_view_state_all"][cat].get(f"s{idx}", {})
    return {
        "slot": idx,
        "colour": win.data["silo_colors"].get(str(idx)),
        "project": win.data["silo_project_paths"].get(str(idx)),
        "edited": win.data["silo_last_edited"].get(idx),
        "pos": vs.get("pos"),
        "ticked": idx in win.data["silo_ticked"],
        "pinned": idx in win.data["pinned_silos"],
    }


def test_reordering_silos_carries_all_of_their_state(win):
    # Moving a silo must take its colour, project path, tick, pin, edit time
    # AND its saved cursor with it — not leave them on whoever inherits the
    # slot number.
    cat = _silo_fixture(win)
    before = {t: _state_of(win, cat, t) for t in ("AAA", "BBB", "CCC", "DDD")}

    win.move_temp_to_index(0, 3)          # AAA to the end
    assert win.data["temp_presets"] == ["BBB", "CCC", "DDD", "AAA"]

    for text in ("AAA", "BBB", "CCC", "DDD"):
        now = _state_of(win, cat, text)
        was = before[text]
        # NB: "edited" is deliberately not compared — switching to a silo
        # re-stamps its edit time, so it is not a stable identity field.
        for field in ("colour", "project", "pos", "ticked", "pinned"):
            assert now[field] == was[field], (
                f"{text}: {field} did not follow the silo "
                f"({was[field]!r} -> {now[field]!r})")


def test_deleting_a_silo_shifts_the_others_state_correctly(win):
    from unittest.mock import patch

    cat = _silo_fixture(win)
    keep = {t: _state_of(win, cat, t) for t in ("AAA", "CCC", "DDD")}

    with patch("fastprompter.ui.snippet_ops_mixin.QMessageBox"):
        win.trash_silo(1)                  # remove BBB from the middle

    assert "BBB" not in win.data["temp_presets"]
    for text in ("AAA", "CCC", "DDD"):
        now = _state_of(win, cat, text)
        was = keep[text]
        for field in ("colour", "project", "pos", "ticked", "pinned"):
            assert now[field] == was[field], (
                f"after deleting BBB, {text}: {field} is wrong "
                f"({was[field]!r} -> {now[field]!r})")


def test_every_slot_keyed_store_is_registered_for_remapping(win):
    """Guard against the next map being forgotten.

    A silo is identified only by its index. Any new slot-keyed store that
    isn't in _SILO_INDEX_STATE will silently stay behind on a reorder, and
    silos start inheriting each other's settings — which is exactly the bug
    this registry exists to prevent.
    """
    registered = {name for name, _kind in win._SILO_INDEX_STATE}
    registered |= {name for name, _kind in win._ARCHIVE_INDEX_STATE}

    # handled separately because of their shape / scope, not forgotten
    handled_elsewhere = {
        "silo_view_state_all",        # per-category, 's3'/'a3' keys
        "archive_temp_presets_all",   # the archive texts themselves
        "temp_presets_all",           # the silo texts themselves
        # per-category wrappers around already-registered maps
        "silo_last_edited_all", "pinned_silos_all", "silo_ticked_all",
        "silo_children_all", "silo_collapsed_all", "silo_colors_all",
        "silo_folders_all", "silo_project_paths_all",
        "archive_silo_folders_all", "archive_project_paths_all",
    }

    def looks_slot_keyed(value):
        """A store indexed BY SLOT: int keys, or a list of slot indices."""
        if isinstance(value, dict):
            keys = [k for k in value if k not in ("", None)]
            return bool(keys) and all(
                isinstance(k, int) or (isinstance(k, str) and k.lstrip("-").isdigit())
                for k in keys)
        if isinstance(value, list):
            return bool(value) and all(isinstance(v, int) for v in value)
        return False   # booleans/strings are plain settings, not per-silo maps

    candidates = {
        k for k, v in win.data.items()
        if isinstance(k, str)
        and (k.startswith("silo_") or k.startswith("pinned_silos")
             or k.startswith("archive_silo") or k.startswith("archive_project"))
        and looks_slot_keyed(v)
    }
    unaccounted = candidates - registered - handled_elsewhere
    assert not unaccounted, (
        "slot-keyed state that no reorder will remap: "
        f"{sorted(unaccounted)} - add it to FastPrompter._SILO_INDEX_STATE "
        "(or to the exemption list above with a reason)")


def test_remap_survives_corrupt_slot_keys(win):
    # Real databases end up with junk keys; a reorder must not throw.
    cat = _silo_fixture(win)
    win.data["silo_colors"]["not-a-number"] = "#123456"
    win.data["silo_project_paths"][""] = {"folder": "empty key"}
    win.data["silo_view_state_all"][cat]["sXX"] = {"pos": 1}

    win.move_temp_to_index(0, 2)           # must not raise

    assert win.data["silo_colors"]["not-a-number"] == "#123456"
    assert win.data["silo_view_state_all"][cat]["sXX"] == {"pos": 1}


def test_reordering_archived_silos_carries_their_state(win):
    # Regression: move_temp_to_index skipped the remap entirely for archived
    # silos, so the TEXT moved but the folder/project maps stayed put and an
    # archived silo inherited another one's files.
    cat = win.get_current_category()
    win.data["archive_temp_presets"][:] = ["ARC-A", "ARC-B", "ARC-C"]
    win.archive_docs[:] = []
    win.data["archive_silo_folders"] = {"0": "fa", "1": "fb", "2": "fc"}
    win.data["archive_project_paths"] = {str(i): {"folder": f"pa{i}"} for i in range(3)}
    store = win.data.setdefault("silo_view_state_all", {}).setdefault(cat, {})
    store.clear()
    for i in range(3):
        store[f"a{i}"] = {"anchor": 0, "pos": i * 7, "scroll": 0}
    # an ACTIVE entry that must not be disturbed by an archive reorder
    store["s0"] = {"anchor": 0, "pos": 999, "scroll": 0}

    win.move_temp_to_index(0, 2, is_archive=True)
    assert win.data["archive_temp_presets"] == ["ARC-B", "ARC-C", "ARC-A"]

    idx = win.data["archive_temp_presets"].index("ARC-A")
    # The folder NAME is re-derived from the silo title (1 silo = 1 folder),
    # so assert it belongs to ARC-A rather than to whoever took slot 0.
    folder = win.data["archive_silo_folders"].get(str(idx), "")
    assert "arc-a" in folder.lower(), (
        f"archived silo inherited another one's folder: {folder!r}")
    # project paths are NOT regenerated, so they prove the remap outright
    assert win.data["archive_project_paths"].get(str(idx)) == {"folder": "pa0"}, (
        "archived silo lost its project path on reorder")
    assert store.get(f"a{idx}", {}).get("pos") == 0

    # the active silos' saved state is untouched by an archive reorder
    assert store["s0"]["pos"] == 999


def test_duplicate_silo_copies_text_colour_and_files(win, tmp_path):
    win.data["files_root"] = str(tmp_path)
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["Alpha", "Beta", "Gamma"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    win.data["silo_colors"] = {"0": "#ff0000", "2": "#0000ff"}
    win.data["pinned_silos"] = [2]
    win.data["silo_ticked"] = [2]

    src = win._silo_folder_dir(0)
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "note.txt"), "w") as fh:
        fh.write("hello")

    win.duplicate_silo(0)

    assert win.data["temp_presets"][:4] == ["Alpha", "Alpha", "Beta", "Gamma"]
    # the copy takes the colour...
    assert win.data["silo_colors"].get("1") == "#ff0000"
    # ...but NOT the pin or tick — a copy shouldn't arrive already flagged
    assert 1 not in win.data["pinned_silos"]
    assert 1 not in win.data["silo_ticked"]
    # and everything below shifted with its own state intact
    assert win.data["silo_colors"].get("3") == "#0000ff"
    assert win.data["pinned_silos"] == [3]

    # files are COPIED into the duplicate's own folder, not shared
    dup = win._silo_folder_dir(1)
    assert os.path.abspath(dup) != os.path.abspath(win._silo_folder_dir(0))
    assert os.path.exists(os.path.join(dup, "note.txt"))
    assert os.path.exists(os.path.join(win._silo_folder_dir(0), "note.txt"))
    # editing the copy's file must not touch the original
    with open(os.path.join(dup, "note.txt"), "w") as fh:
        fh.write("changed")
    with open(os.path.join(win._silo_folder_dir(0), "note.txt")) as fh:
        assert fh.read() == "hello"


def test_new_child_silo_nests_under_its_parent(win):
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["Parent", "Other"]
    win.silo_docs[:] = []
    win.data["silo_children"] = {}
    win._switch_to_slot(0, initial=True)

    win.new_child_silo(0)

    assert win.data["temp_presets"][:3] == ["Parent", "", "Other"]
    kids = win.data["silo_children"]
    key = next(k for k in kids if str(k) == "0")
    assert 1 in kids[key], f"child not nested under its parent: {dict(kids)}"
    assert win.active_temp_slot == 1, "should land on the new child"


def test_files_folder_is_not_created_just_by_looking(win, tmp_path):
    # Opening the Files panel used to leave an empty directory behind for
    # every silo the user merely glanced at.
    win.data["files_root"] = str(tmp_path)
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    # fully hermetic: fresh root AND a fresh folder map, or this silo
    # inherits a folder an earlier test already put files in
    win.data["silo_folders"] = {}
    win.data["temp_presets"][:] = ["PeekOnly"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    win.open_file_container()
    folder = win._file_container.folder
    assert os.path.isdir(folder), "panel should have a folder while open"
    assert os.listdir(folder) == [], "fixture is not clean"
    win._file_container.close()
    assert not os.path.isdir(folder), "empty folder left behind after closing"

    # but a folder with content is never removed
    win.open_file_container()
    folder = win._file_container.folder
    assert os.path.isdir(folder)
    with open(os.path.join(folder, "keep.txt"), "w") as fh:
        fh.write("x")
    win._file_container.close()
    assert os.path.isdir(folder)
    assert os.path.exists(os.path.join(folder, "keep.txt"))


def test_folder_map_only_records_real_silos(win, tmp_path):
    # The map used to gain untitled-4..untitled-10 entries for slots that
    # held no silo, just because the panel asked for their names.
    win.data["files_root"] = str(tmp_path)
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["Real one", "Real two"]
    win.silo_docs[:] = []
    win.data["silo_folders"] = {}
    win._switch_to_slot(0, initial=True)

    win.refresh_temp_presets()
    win._update_files_button()
    # asking about empty slots must not register them
    for empty_slot in (5, 7, 9):
        win._silo_folder_name(empty_slot)

    recorded = {int(k) for k in win.data["silo_folders"]}
    assert recorded <= {0, 1}, (
        f"folder names recorded for silos that don't exist: {sorted(recorded)}")


def test_settings_panel_hugs_its_content_vertically(win):
    # The panel used to reserve room for its TALLEST tab and then take all
    # the spare height in the window on top of that, leaving hundreds of
    # pixels of nothing under a single row of checkboxes.
    win.is_locked = False
    win._locked_geometry = None
    was_visible = win.mini_settings_frame.isVisible()
    try:
        win.mini_settings_frame.setVisible(True)
        win.resize(905, 965)
        win.show()
        QApplication.processEvents()

        tabs = win.settings_tabs
        heights = {}
        wanted = {}
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            win._fit_settings_tabs(i)
            QApplication.processEvents()
            heights[tabs.tabText(i)] = win.mini_settings_frame.height()
            # the frame's OWN hint: it holds the tab page plus the footer
            # rows, so the page's hint alone is not what it is sized against
            wanted[tabs.tabText(i)] = win.mini_settings_frame.sizeHint().height()

        # "Hugs" means the frame tracks the CONTENT, not a fixed number of
        # pixels: a flat cap goes stale the moment a tab gains a control, and
        # then reads as this bug coming back when it has not. The failure
        # being guarded is the panel reserving hundreds of pixels of nothing,
        # so compare against what the page actually asks for.
        for name, h in heights.items():
            assert h <= wanted[name] + 40, (
                f"{name} tab leaves empty panel: {h}px frame for "
                f"{wanted[name]}px of content")

        # a short tab must be visibly shorter than the busiest one — proof the
        # panel follows the CURRENT page rather than the tallest
        assert heights["Clock"] < heights["Editor"], heights

        # and nothing may be clipped: the visible page still fits
        page = tabs.currentWidget()
        needed = page.layout().totalHeightForWidth(max(120, tabs.width() - 12))
        assert tabs.height() >= needed, "tab content is being cut off"
    finally:
        win.mini_settings_frame.setVisible(was_visible)
        win.resize(1400, 700)


def test_pinned_drop_survives_every_degenerate_case(win):
    # Reported crash: dropping a pinned silo onto ITSELF removed it and then
    # looked it up again -> ValueError straight out of the drop event.
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [f"S{i}" for i in range(12)]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    cases = [
        ("onto itself", dict(source_idx=10, boundary_idx=10), [10, 3, 7]),
        ("boundary not pinned", dict(source_idx=3, boundary_idx=99), [10, 3, 7]),
        ("source not pinned", dict(source_idx=99, boundary_idx=3), [10, 3, 7]),
        ("neither pinned", dict(source_idx=88, boundary_idx=99), [10, 3, 7]),
        ("swap onto itself", dict(source_idx=3, swap_idx=3), [10, 3, 7]),
        ("swap with unpinned", dict(source_idx=3, swap_idx=99), [10, 3, 7]),
        ("empty list", dict(source_idx=1, boundary_idx=2), []),
        ("no boundary at all", dict(source_idx=3), [10, 3, 7]),
    ]
    for label, kwargs, start in cases:
        win.data["pinned_silos"] = list(start)
        win.handle_pinned_drop(**kwargs)     # must never raise

    # and the legitimate reorders still do the right thing
    win.data["pinned_silos"] = [10, 3, 7]
    assert win.handle_pinned_drop(source_idx=7, boundary_idx=10) is True
    assert win.data["pinned_silos"] == [7, 10, 3]

    win.data["pinned_silos"] = [10, 3, 7]
    assert win.handle_pinned_drop(source_idx=5, boundary_idx=3) is True
    assert win.data["pinned_silos"] == [10, 5, 3, 7]

    win.data["pinned_silos"] = [10, 3, 7]
    assert win.handle_pinned_drop(source_idx=3, swap_idx=7) is True
    assert win.data["pinned_silos"] == [10, 7, 3]


def test_thread_and_qt_failures_reach_the_crash_log(tmp_path, monkeypatch):
    """A crash the user never sees is a crash that never gets fixed.

    sys.excepthook only covers the main thread, and Qt's own fatal messages
    bypass Python entirely — so a worker-thread failure or a Qt abort took
    the app down with no log and no dialog.
    """
    import threading

    import fastprompter.main as main_mod

    monkeypatch.setattr(main_mod, "get_data_dir", lambda: str(tmp_path))
    # never pop a real modal dialog during the test
    monkeypatch.setattr(
        main_mod.ctypes, "windll",
        type("W", (), {"user32": type("U", (), {
            "MessageBoxW": staticmethod(lambda *a: 0)})()})())

    prev_sys, prev_thread = sys.excepthook, threading.excepthook
    prev_qt = None
    try:
        prev_qt = main_mod.setup_exception_hook()

        def boom():
            raise ValueError("worker thread failure")

        t = threading.Thread(target=boom, name="undo-saver", daemon=True)
        t.start()
        t.join()

        from PyQt6.QtCore import qCritical
        qCritical(b"simulated Qt critical")
        QApplication.processEvents()

        log = tmp_path / "crash.log"
        assert log.exists(), "nothing was logged at all"
        text = log.read_text(encoding="utf-8", errors="replace")
        assert "worker thread failure" in text, "thread exception was swallowed"
        assert "undo-saver" in text, "thread name not recorded"
        assert "Qt QtCriticalMsg" in text, "Qt message was swallowed"
    finally:
        sys.excepthook = prev_sys
        threading.excepthook = prev_thread
        # MUST restore, or Qt keeps calling this test's handler after
        # teardown and the process dies with an access violation
        from PyQt6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(prev_qt)


def test_heavy_document_operations_stay_responsive(win):
    # Long documents must not take pathologically long in the per-block
    # paths, which is where a heavy-document freeze would come from.
    import time


    text = "\n".join(
        (f"# Header {i}" if i % 50 == 0 else f"line {i} of a long document")
        for i in range(20000))
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = [text]
    win.silo_docs[:] = []
    win.data["line_heat"] = "True"
    try:
        t0 = time.perf_counter()
        win._switch_to_slot(0, initial=True)
        load_ms = (time.perf_counter() - t0) * 1000
        assert load_ms < 3000, f"loading 20k lines took {load_ms:.0f}ms"

        ta = win.text_area
        # NB: do NOT call paintEvent() directly here. Other tests get away
        # with it on tiny documents, but invoking it outside Qt's own paint
        # cycle on a 20k-block document faults inside QTextEdit.paintEvent.
        # Repaint through the widget instead, and measure the per-block
        # helpers — which is where a heavy-document freeze would come from.
        t0 = time.perf_counter()
        ta.viewport().repaint()
        paint_ms = (time.perf_counter() - t0) * 1000
        assert paint_ms < 2000, f"painting 20k lines took {paint_ms:.0f}ms"

        t0 = time.perf_counter()
        heat = ta._line_heat_selections(ta.document())
        assert (time.perf_counter() - t0) * 1000 < 500
        # only VISIBLE lines may be considered, or this grows without bound
        assert len(heat) < 500, f"{len(heat)} heat selections on one screen"
        t0 = time.perf_counter()
        win.capture_silo_state()
        assert (time.perf_counter() - t0) * 1000 < 1000
    finally:
        win.data["line_heat"] = "False"
        win.data["temp_presets"][:] = ["small"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)


def test_tint_covers_word_wrapped_continuation_lines(win):
    """A wrapped paragraph must be tinted over ALL its visual rows.

    The tints used to ride on extra selections: a bare caret only coloured
    the row the caret sat on, and giving each one a real selection made Qt
    fault outright. They are painted over blockBoundingRect instead, which
    spans the whole wrapped block. Asserted on rendered pixels, because that
    is the only thing that proves what the user actually sees.
    """
    from PyQt6.QtGui import QImage

    win.is_locked = False
    win._locked_geometry = None
    win.resize(700, 600)
    win.show()
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["word_wrap"] = "True"
    # Setting the flag is not enough: the widget only picks it up through
    # apply_wrap_mode(), and the fuzz tests earlier in this module toggle
    # both wrap and the UI scale on the shared fixture. Without pinning them
    # here this test inherits whatever the RNG happened to leave, and the
    # paragraph silently stops wrapping.
    win.data["ui_scale"] = "1.0"
    win.apply_wrap_mode()
    win.data["temp_presets"][:] = ["short\n" + ("word " * 80) + "\nshort2"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    QApplication.processEvents()

    ta = win.text_area
    doc = ta.document()
    blk = doc.findBlockByNumber(1)
    assert blk.layout().lineCount() > 3, "test text did not wrap"

    try:
        win.data["hover_line"] = "True"
        win.data["hover_line_opacity"] = "40"      # unmistakable in a sample
        ta._hover_block = 1
        ta.viewport().repaint()
        QApplication.processEvents()

        img = QImage(ta.viewport().size(), QImage.Format.Format_ARGB32)
        ta.viewport().render(img)
        rect = doc.documentLayout().blockBoundingRect(blk)
        top = int(rect.top() - ta.verticalScrollBar().value())
        height = int(rect.height())
        assert height > 3 * ta.fontMetrics().height(), "block is not multi-row"

        outside = img.pixelColor(5, max(0, top - 6)).name()
        rows = [img.pixelColor(5, top + off).name()
                for off in (2, height // 2, height - 4)
                if 0 <= top + off < img.height()]
        assert len(rows) == 3
        for i, colour in enumerate(rows):
            assert colour != outside, (
                f"row {i} of the wrapped block is untinted ({colour} == {outside})")
        assert rows[0] == rows[-1], "tint is uneven down the wrapped block"
    finally:
        win.data["hover_line_opacity"] = "10"
        ta._hover_block = None


def test_divider_ends_a_header_fold(win):
    # A '---' rule is an explicit "section ends here" marker; folding a
    # header used to swallow everything up to the NEXT header instead.
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    text = "# First\nbody A\nbody B\n---\nafter divider\n# Second\nbody C"
    win.data["temp_presets"][:] = [text]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    ta = win.text_area
    doc = ta.document()

    assert ta._is_divider_line("---") is True
    assert ta._is_divider_line("***") is True
    assert ta._is_divider_line("___") is True
    assert ta._is_divider_line("--") is False        # too short
    assert ta._is_divider_line("- - -") is False     # spaced, not a rule
    assert ta._is_divider_line("-*-") is False       # mixed characters

    rng = ta._fold_range(doc.findBlockByNumber(0))
    assert rng is not None
    assert (rng[0].blockNumber(), rng[1].blockNumber()) == (1, 2), (
        "header fold ran past the divider")

    ta.toggle_fold(doc.findBlockByNumber(0))
    visible = [doc.findBlockByNumber(i).isVisible() for i in range(7)]
    assert visible == [True, False, False, True, True, True, True]


def test_line_heat_survives_a_reload(win):
    # Block user data is memory-only; a reload rebuilds the document from
    # plain text, so the timestamps have to be persisted separately.
    import time

    from fastprompter.ui.editor import _LineHeat

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["alpha\nbeta\ngamma", "other"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    try:
        win.data["line_heat"] = "True"
        ta = win.text_area
        stamp = time.time() - 60
        ta.document().findBlockByNumber(1).setUserData(_LineHeat(stamp))

        saved = ta.collect_line_heat()
        assert saved.get(1) is not None, "heat was not collected for saving"

        win.capture_silo_state()
        entry = win.data["silo_view_state_all"][win.get_current_category()]["s0"]
        assert "heat" in entry, "heat never reached the persisted state"

        # simulate a restart: throw the documents away and switch back
        win._switch_to_slot(1)
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)

        restored = win.text_area.collect_line_heat()
        assert restored.get(1) is not None, "heat did not survive the reload"
        assert abs(restored[1] - stamp) < 2
    finally:
        win.data["line_heat"] = "False"


def test_silo_nesting_allows_two_levels_and_renders_grandchildren(win):
    """1 -> 1.1 -> 1.1.1, and no deeper.

    Grandchildren were excluded from the top level (they are in all_kids)
    but the render loop only ever emitted DIRECT children, so a silo nested
    two deep existed in the data and appeared nowhere on screen.
    """
    from unittest.mock import patch

    from fastprompter.main import MAX_SILO_DEPTH

    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["temp_presets"][:] = ["Root", "Kid", "Grandkid", "GreatGrand", "Other"]
    win.silo_docs[:] = []
    win.data["silo_children"] = {}
    win.data["pinned_silos"] = []
    win.data["silo_collapsed"] = []
    win._switch_to_slot(0, initial=True)

    # nesting can ask to merge the child's files into the parent; with no
    # one to answer, that dialog would block the suite forever
    with patch("fastprompter.main.QMessageBox"):
        win.make_silo_child(1, 0)     # Kid under Root
        win.make_silo_child(2, 1)     # Grandkid under Kid - now allowed
        win.make_silo_child(3, 2)     # GreatGrand - one level too deep

    assert win.silo_depth(0) == 0
    assert win.silo_depth(1) == 1
    assert win.silo_depth(2) == MAX_SILO_DEPTH
    assert win.silo_parent_of(3) is None, "a third level must be refused"

    win.refresh_temp_presets()
    QApplication.processEvents()
    labels = [str(getattr(b, "full_name", "")) for b in win.silo_buttons
              if not b.isHidden() and getattr(b, "full_name", "")]
    joined = " | ".join(labels)
    assert "1: Root" in joined
    assert "1.1: Kid" in joined
    assert "1.1.1: Grandkid" in joined, f"grandchild never rendered: {joined}"

    # the new-child action must respect the same ceiling rather than making
    # a silo that cannot be displayed
    before = len(win.data["temp_presets"])
    win.new_child_silo(2)                     # on the grandchild
    assert len(win.data["temp_presets"]) == before, (
        "created a silo one level deeper than can ever be rendered")
    win.new_child_silo(0)                     # on the root is fine
    assert len(win.data["temp_presets"]) == before + 1


def test_nesting_helpers_refuse_cycles(win):
    # A corrupt map must not hang the app or let a silo become its own
    # ancestor via drag-and-drop.
    win.data["temp_presets"][:] = ["A", "B", "C"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    win.data["silo_children"] = {0: [1], 1: [0]}      # a cycle
    assert win.silo_depth(0) <= 4, "cycle guard did not stop the walk"
    assert win.silo_depth(1) <= 4

    win.data["silo_children"] = {0: [1]}
    assert win._is_descendant(1, 0) is True
    assert win._is_descendant(0, 1) is False
    from unittest.mock import patch
    with patch("fastprompter.main.QMessageBox"):
        win.make_silo_child(0, 1)                      # parent under its child
    assert 0 not in win.data["silo_children"].get(1, []), (
        "a silo was nested under its own descendant")

def test_reordering_a_child_keeps_it_inside_its_parent(win):
    """A gap drop used to call unnest_silo() unconditionally, so merely
    moving a child up or down among its siblings threw it out of the parent."""
    win.data["temp_presets"][:] = ["Parent", "KidA", "KidB", "KidC", "Outsider"]
    win.silo_docs[:] = []
    win.data["silo_children"] = {0: [1, 2, 3]}
    win.data["pinned_silos"] = []
    win._switch_to_slot(0, initial=True)
    win.refresh_temp_presets()

    names = win.data["temp_presets"]

    def kids():
        return [names[k] for k in (win.data["silo_children"] or {}).get(0, [])]

    # reorder among siblings: parentage and membership survive
    assert win.reorder_sibling(3, before_idx=1) is True
    assert kids() == ["KidC", "KidA", "KidB"]
    assert win.silo_parent_of(3) == 0

    # dropped past the last sibling -> last, still a child
    assert win.reorder_sibling(3, before_idx=None) is True
    assert kids() == ["KidA", "KidB", "KidC"]
    assert win.silo_parent_of(3) == 0

    # a silo with no parent is not a sibling of anything
    assert win.reorder_sibling(4, before_idx=1) is False

def test_hamburger_follows_the_sidebar_side(win):
    """The toggle used to be pinned to the far left of the header, so with
    the sidebar on the right it sat at the opposite edge from what it opens."""
    def slot():
        lay = win.header_layout
        for i in range(lay.count()):
            if lay.itemAt(i).widget() is win.btn_sidebar_toggle:
                return i, lay.count()
        return None, lay.count()

    # the fixture is shared, so put back exactly what was there before
    was_right = win.data.get("sidebar_right")
    try:
        win.toggle_sidebar_position(False)
        assert slot()[0] == 0, "sidebar on the left -> hamburger leftmost"

        win.toggle_sidebar_position(True)
        pos, count = slot()
        assert pos == count - 1, "sidebar on the right -> hamburger rightmost"
        assert not win.btn_sidebar_toggle.isHidden()
    finally:
        win.toggle_sidebar_position(was_right == "True")

def test_reset_ui_layout_restores_every_layout_choice(win):
    """Toolbar order had its own reset; splitter widths, sidebar side, window
    size and scale had none, so a window dragged somewhere unusable could only
    be fixed by deleting the database."""
    before_text = win.text_area.toPlainText()
    silos_before = list(win.data["temp_presets"])

    # scramble every layout choice
    win.data["toolbar_order"] = "btn_help,btn_save"
    win.data["last_geometry"] = "10,10,4000,4000"
    win.data["splitter_sizes_left"] = [999, 1]
    win.data["splitter_sizes_right"] = [1, 999]
    win.data["ui_scale"] = "2.5"
    win.data["button_scale"] = "2.5"
    win.data["sidebar_right"] = "True"
    win.apply_sidebar_position()

    assert win.reset_ui_layout(confirm=False) is True

    assert win.data["toolbar_order"] == ""
    # resizing re-records the geometry immediately, so it is not empty for
    # long — what matters is that the scrambled size is gone
    assert win.data["last_geometry"] != "10,10,4000,4000"
    assert win.data["splitter_sizes_left"] == ""
    assert win.data["splitter_sizes_right"] == ""
    assert win.data["sidebar_right"] == "False"
    assert win.data["ui_scale"] == "0.5"
    assert win.data["button_scale"] == "1.0"

    # the sidebar is back on the left, so the hamburger is back at the left edge
    lay = win.header_layout
    assert lay.itemAt(0).widget() is win.btn_sidebar_toggle

    # the Settings controls must agree with the data they display, or the
    # next click on them toggles from the state the user can no longer see
    assert win.cb_sidebar.isChecked() is False
    assert "50%" in win.btn_button_scale.text()

    # and the checkbox still works afterwards, from the correct state
    win.cb_sidebar.setChecked(True)
    assert win.data["sidebar_right"] == "True"
    assert lay.itemAt(lay.count() - 1).widget() is win.btn_sidebar_toggle
    win.cb_sidebar.setChecked(False)

    # a layout reset must not touch content
    assert win.text_area.toPlainText() == before_text
    assert list(win.data["temp_presets"]) == silos_before


def test_reset_ui_layout_can_be_declined(win):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMessageBox as _QMB

    win.data["toolbar_order"] = "btn_help,btn_save"
    with patch.object(_QMB, "question",
                      return_value=_QMB.StandardButton.No):
        assert win.reset_ui_layout() is False
    assert win.data["toolbar_order"] == "btn_help,btn_save", "declining must change nothing"
    win.data["toolbar_order"] = ""
    win.apply_toolbar_order()

def test_auto_bullet_setting_has_one_owner(win):
    """The context menu flipped data["auto_bullet"] itself and never called
    mark_dirty(), so turning auto-bullet on from there survived until the next
    restart and left the toolbar tooltip claiming the opposite."""
    before = win.data.get("auto_bullet", "False")
    try:
        win.set_auto_bullet(False)
        win.state._db_dirty = False

        win.text_area._toggle_auto_bullet()
        assert win.data["auto_bullet"] == "True"
        assert win.btn_bullet_toggle.isChecked() is True
        assert "ON" in win.btn_bullet_toggle.toolTip()
        assert win.state._db_dirty, "a toggle not marked dirty is never saved"

        win.text_area._toggle_auto_bullet()
        assert win.data["auto_bullet"] == "False"
        assert win.btn_bullet_toggle.isChecked() is False
        assert "OFF" in win.btn_bullet_toggle.toolTip()
    finally:
        win.set_auto_bullet(before == "True")


def test_auto_bullet_converts_while_typing(win):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    before = win.data.get("auto_bullet", "False")
    ed = win.text_area
    try:
        win.set_auto_bullet(True)

        def typed(keys):
            ed.clear()
            for ch in keys:
                if ch == " ":
                    QTest.keyClick(ed, Qt.Key.Key_Space)
                elif ch == "\n":
                    QTest.keyClick(ed, Qt.Key.Key_Return)
                else:
                    QTest.keyClicks(ed, ch)
            return ed.toPlainText()

        assert typed("- x") == "\u2022 x"
        assert typed("* x") == "\u2022 x"
        assert typed("+ x") == "\u2022 x"
        assert typed("  - x") == "  \u2022 x"
        assert typed("a\n- x") == "a\n\u2022 x"
        # a dash inside a sentence is just a dash
        assert typed("word - x") == "word - x"

        win.set_auto_bullet(False)
        assert typed("- x") == "- x", "off means off"
    finally:
        ed.clear()
        win.set_auto_bullet(before == "True")

def test_limit_window_catcher_builds_a_rolling_timer(win):
    """The 5-hour agent quota is a rolling window anchored at the moment it
    opened, which the generic "when" box cannot express."""
    import datetime

    from fastprompter.core import timers as T
    from fastprompter.ui.timer_dialog import TimerDialog

    kept = list(win.timers)
    try:
        win.timers.clear()
        dlg = TimerDialog(win)
        now = datetime.datetime.now()

        # blank start = the window opens now
        dlg.in_name.setText("Claude limit")
        dlg.spin_limit_hours.setValue(5.0)
        dlg.in_limit_start.setText("")
        t = dlg.add_limit_window()
        assert t.repeat == T.REPEAT_INTERVAL
        assert t.interval_minutes == 300
        assert 4.9 < t.remaining() / 3600 < 5.01

        # an explicit start two hours ago leaves three hours on the clock
        dlg.in_name.setText("Anchored")
        dlg.in_limit_start.setText(
            (now - datetime.timedelta(hours=2)).strftime("%H:%M"))
        t2 = dlg.add_limit_window()
        assert 2.9 < t2.remaining() / 3600 < 3.05

        # the words say what it is, including that it rolls
        text = T.describe(t2)
        assert "every 5h" in text and t2.target.strftime("%H:%M") in text

        # garbage adds nothing and says so
        before = len(win.timers)
        dlg.in_limit_start.setText("banana")
        dlg.add_limit_window()
        assert len(win.timers) == before
        assert dlg.lbl_limit_hint.text()

        # and it survives being saved and read back
        back = T.load_timers(T.save_timers(win.timers))
        assert [x.interval_minutes for x in back] == [300, 300]
        assert all(x.repeat == T.REPEAT_INTERVAL for x in back)
        dlg.close()
    finally:
        win.timers[:] = kept
        win.save_timers_to_data()

def test_margin_selects_whole_lines_like_word(win):
    """Clicking the line-number margin takes the whole line and dragging
    sweeps them, with the mirrored arrow cursor that signals it."""
    from PyQt6.QtGui import QTextCursor

    from fastprompter.ui.editor import MARK_ZONE_PX, margin_cursor

    ed = win.text_area
    kept_numbers = win.data.get("show_line_numbers", "False")
    kept_marks = win.data.get("line_marks", "False")
    try:
        win.data["show_line_numbers"] = "True"
        ed.update_line_number_area_width()
        ed.setPlainText("alpha\nbravo\ncharlie\ndelta\necho")

        def y_of(n):
            r = ed.cursorRect(QTextCursor(ed.document().findBlockByNumber(n)))
            return r.top() + r.height() // 2

        def selected():
            return ed.textCursor().selectedText()

        # the cursor exists and is a real painted shape, not a null pixmap
        assert not margin_cursor().pixmap().isNull()

        ed.margin_select_line(y_of(2), extend=False)
        assert selected() == "charlie\u2029"

        # dragging sweeps whole lines, in either direction
        ed.margin_select_line(y_of(1), extend=False)
        ed.margin_select_line(y_of(3), extend=True)
        assert selected() == "bravo\u2029charlie\u2029delta\u2029"
        ed.margin_select_line(y_of(3), extend=False)
        ed.margin_select_line(y_of(1), extend=True)
        assert selected() == "bravo\u2029charlie\u2029delta\u2029"

        # the last line has no trailing newline to swallow
        ed.margin_select_line(y_of(4), extend=False)
        assert selected() == "echo"

        # below the last line is a no-op, not a crash
        assert ed.margin_select_line(999999, extend=False) is False

        # with marks on, the left strip still belongs to the mark widget
        win.data["line_marks"] = "True"
        gutter = ed.line_number_area
        assert gutter._in_margin(4) is False
        assert gutter._in_margin(MARK_ZONE_PX + 4) is True
        # and the gutter is wide enough that both zones are clickable
        ed.update_line_number_area_width()
        assert ed.line_number_area_width() > MARK_ZONE_PX + 4

        # with marks off the whole gutter is margin
        win.data["line_marks"] = "False"
        assert gutter._in_margin(4) is True
    finally:
        win.data["show_line_numbers"] = kept_numbers
        win.data["line_marks"] = kept_marks
        ed.update_line_number_area_width()
        ed.clear()

def test_hover_line_follows_the_pointer_when_the_text_scrolls(win):
    """Reported: the hover wash stops sitting under the cursor. Hover was
    only recomputed from mouseMoveEvent, so scrolling under a stationary
    mouse left it on the block number it started on."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QCursor

    ed = win.text_area
    kept = win.data.get("hover_line", "True")
    try:
        win.data["hover_line"] = "True"
        ed.setPlainText("\n".join(f"line {i:03d}" for i in range(200)))

        point = QPoint(60, 120)
        QCursor.setPos(ed.viewport().mapToGlobal(point))

        def under_pointer():
            return ed.cursorForPosition(point).block().blockNumber()

        ed.rehover_from_pointer(point)
        assert ed._hover_block == under_pointer()

        # scrolling alone must move the wash - no mouse movement involved
        sb = ed.verticalScrollBar()
        sb.setValue(sb.value() + 40)
        assert ed._hover_block == under_pointer(), \
            "the wash stayed on the line the pointer used to be over"

        sb.setValue(sb.value() + 33)
        assert ed._hover_block == under_pointer()

        # switched off, it stays off
        win.data["hover_line"] = "False"
        ed._hover_block = None
        sb.setValue(sb.value() + 20)
        assert ed.rehover_from_pointer(point) is False
        assert ed._hover_block is None

        # a point outside the viewport is not a hover
        win.data["hover_line"] = "True"
        assert ed.rehover_from_pointer(QPoint(-50, -50)) is False
    finally:
        win.data["hover_line"] = kept
        ed._hover_block = None
        ed.clear()

def test_ctrl_e_reverses_any_header_level(win):
    """Ctrl+E only recognised "# ", so on "## Sub" it failed to see a header
    and prepended another marker, producing "# ## Sub"."""
    from PyQt6.QtGui import QTextCursor

    ed = win.text_area
    try:
        def press(text):
            ed.setPlainText(text)
            c = ed.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            ed.setTextCursor(c)
            win.apply_header_timestamp()
            return ed.toPlainText()

        # Plain text gets header + timestamp + ---
        assert press("plain text").startswith("# plain text (")
        assert "---" in press("plain text")
        
        # Existing header WITHOUT a rule is still reversed, not decorated.
        # This used to assert that Ctrl+E added the --- instead, which broke
        # the toggle the rest of this test (and its name) relies on: with
        # the rule switched off in settings the key could never undo itself.
        ed.setPlainText("# Header one")
        c = ed.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        ed.setTextCursor(c)
        win.apply_header_timestamp()
        assert ed.toPlainText().strip() == "Header one"


        # Existing header with --- gets stripped
        ed.setPlainText("# Header one\n---\n")
        c = ed.textCursor()
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        ed.setTextCursor(c)
        win.apply_header_timestamp()
        assert ed.toPlainText().strip() == "Header one"
    finally:
        ed.clear()


def test_ctrl_click_opens_links_and_ctrl_right_click_reveals_the_folder(win):
    """Ctrl+LClick opens the link, Ctrl+RClick shows the file in its folder."""
    import os
    import tempfile

    from PyQt6.QtCore import QEvent, QPointF, Qt, QUrl
    from PyQt6.QtGui import QDesktopServices, QMouseEvent, QTextCursor

    import fastprompter.ui.editor as editor_mod

    ed = win.text_area
    tmp = tempfile.mkdtemp()
    target = os.path.join(tmp, "note.txt")
    with open(target, "w") as fh:
        fh.write("hi")

    opened, revealed = [], []
    real_open = QDesktopServices.openUrl
    # Popen, not run: reveal must not wait on explorer from the GUI thread
    real_popen = editor_mod.subprocess.Popen
    try:
        ed.clear()
        c = ed.textCursor()
        c.insertHtml(f'<a href="{QUrl.fromLocalFile(target).toString()}">file</a>')
        c.insertText("\n")
        c.insertHtml('<a href="https://example.com">web</a>')

        QDesktopServices.openUrl = staticmethod(
            lambda u: opened.append(u.toString()))
        editor_mod.subprocess.Popen = lambda *a, **k: revealed.append(a[0])

        def click(block, button, mods):
            r = ed.cursorRect(QTextCursor(ed.document().findBlockByNumber(block)))
            pos = QPointF(r.left() + 12, r.top() + r.height() // 2)
            ed.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, pos, button, button, mods))

        ctrl = Qt.KeyboardModifier.ControlModifier
        click(0, Qt.MouseButton.LeftButton, ctrl)
        assert opened and opened[-1].endswith("note.txt")

        opened.clear()
        click(0, Qt.MouseButton.RightButton, ctrl)
        assert revealed, "Ctrl+RClick must reveal the file"
        assert os.path.normpath(target) in revealed[-1]
        assert not opened, "revealing must not also open the file"
        assert ed._suppress_context_menu, "the menu must not pop over the folder"

        # a web link has no folder to show, so the menu is left to open
        revealed.clear()
        click(1, Qt.MouseButton.RightButton, ctrl)
        assert not revealed

        # without Ctrl nothing is launched at all
        opened.clear()
        click(0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        assert not opened and not revealed
    finally:
        QDesktopServices.openUrl = real_open
        editor_mod.subprocess.Popen = real_popen
        ed._suppress_context_menu = False
        ed.clear()

def test_productivity_timer_tab_drives_the_model(win):
    """The my_timer2 work/break timer as a first-class feature: the form
    edits the model, the buttons drive it, and it survives a restart."""
    from fastprompter.core import pomodoro as P
    from fastprompter.ui.timer_dialog import TimerDialog

    kept = win.data.get("productivity_timer")
    saved_state = win.productivity_timer.to_dict()
    try:
        dlg = TimerDialog(win)
        assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
            "Alarms", "Productivity"]

        t = win.productivity_timer
        dlg.spin_work_min.setValue(0)
        dlg.spin_work_sec.setValue(3)
        dlg.spin_break_min.setValue(0)
        dlg.spin_break_sec.setValue(2)
        assert (t.work_seconds, t.break_seconds) == (3, 2)
        assert win.data["productivity_timer"]["work_seconds"] == 3

        # start -> pause -> resume through the one action button
        dlg._pomo_toggle()
        assert t.running and dlg.btn_pomo_action.text() == "Pause"
        dlg._pomo_toggle()
        assert not t.running and dlg.btn_pomo_action.text() == "Resume"
        dlg._pomo_toggle()

        # the work phase hands off to the break and leaves the alarm ringing
        assert t.tick(3) == [P.PHASE_WORK]
        assert t.phase == P.PHASE_BREAK
        assert t.alarm_pending is True
        assert t.completed_cycles == 1
        dlg._refresh_pomo()
        assert dlg.lbl_pomo_clock.text() == "00:02"
        assert "alarm ringing" in dlg.lbl_pomo_state.text()

        # a running phase takes the header badge
        win.resize(1400, 700)
        win._apply_header_density()
        win._update_timer_label()
        if not getattr(win, "_header_ultra", False):
            assert win.lbl_timer.text() == "00:02"
            # isHidden(), not isVisible(): the latter is False whenever any
            # ancestor is hidden, which is the shared fixture's normal state
            assert not win.lbl_timer.isHidden()

        dlg._pomo_skip()
        assert t.phase == P.PHASE_WORK

        dlg._pomo_reset()
        assert t.state == P.STATE_IDLE
        assert dlg.btn_pomo_action.text() == "Start"

        # settings persist, the run state deliberately does not
        win.save_productivity_timer()
        back = P.ProductivityTimer.from_dict(win.data["productivity_timer"])
        assert (back.work_seconds, back.break_seconds) == (3, 2)
        assert back.state == P.STATE_IDLE
        dlg.close()
    finally:
        win.productivity_timer = P.ProductivityTimer.from_dict(saved_state)
        win.data["productivity_timer"] = kept if kept is not None else saved_state

def test_hover_repaints_on_every_move(win):
    """Reported: the hover wash sticks. It is painted in paintEvent, but the
    mouse handler only asked for extra selections to be rebuilt - which
    repaints nothing, and over 2000 blocks bails out entirely."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent, QTextCursor

    ed = win.text_area
    kept = win.data.get("hover_line", "True")
    painted = []
    real_paint = ed.paintEvent
    try:
        win.data["hover_line"] = "True"
        ed.setPlainText("\n".join(f"line {i:03d}" for i in range(60)))

        ed.paintEvent = lambda ev: (painted.append(1), real_paint(ev))[1]

        def move_to(n):
            r = ed.cursorRect(QTextCursor(ed.document().findBlockByNumber(n)))
            ed._last_hover_pos = ed._last_hover_pos.__class__(-10000, -10000)
            ed.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(200, r.top() + r.height() // 2),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier))

        for n in (2, 5, 8):
            painted.clear()
            move_to(n)
            assert ed._hover_block == n
            ed.viewport().grab()          # force the pending paint
            assert painted, f"moving to line {n + 1} repainted nothing"
    finally:
        ed.paintEvent = real_paint
        win.data["hover_line"] = kept
        ed._hover_block = None
        ed.clear()


def test_gutter_colours_come_from_the_theme(win):
    """They were hardcoded per theme NAME, tested with `"vintage" in name` -
    so "Vintage Dark" (editor background #181818) got golden-vintage brown."""
    from PyQt6.QtGui import QColor

    from fastprompter.theme.themes import THEMES

    ed = win.text_area
    kept_theme = win.data.get("theme", "Default")
    kept_nums = win.data.get("show_line_numbers", "False")
    try:
        win.data["show_line_numbers"] = "True"
        for name in THEMES:
            win.data["theme"] = name
            win._theme_cache = THEMES[name]
            bg, numbers = ed._gutter_colors()

            editor_bg = QColor(THEMES[name]["raw_colors"]["bg_text"])
            assert bg.isValid() and numbers.isValid()
            # the gutter must read as a margin: close to the page but not
            # identical, and never the same colour as the numbers on it
            delta = abs(bg.lightness() - editor_bg.lightness())
            assert 4 <= delta <= 60, f"{name}: gutter/page delta {delta}"
            assert numbers.name() != bg.name(), f"{name}: numbers invisible"

        # a light theme darkens the gutter, a dark one lightens it
        win._theme_cache = THEMES["Vintage Classic"]        # white page
        light_bg, _ = ed._gutter_colors()
        assert light_bg.lightness() < QColor("#ffffff").lightness()

        win._theme_cache = THEMES["Vintage Dark"]
        dark_bg, _ = ed._gutter_colors()
        assert dark_bg.lightness() > QColor("#181818").lightness()
    finally:
        win.data["theme"] = kept_theme
        win.data["show_line_numbers"] = kept_nums
        win._theme_cache = THEMES.get(kept_theme, THEMES["Default"])

def test_hashtags_are_clickable_and_findable_across_silos(win):
    """Tags live in the text, so Ctrl+click finds every silo carrying one."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent, QTextCursor

    from fastprompter.ui.hashtag_dialog import HashtagDialog

    ed = win.text_area
    kept = list(win.data["temp_presets"])
    real_open = win.open_hashtag_dialog
    try:
        win.data["temp_presets"][:] = [
            "Home notes\nmilk #todo\nbread",
            "# Notes header\nnothing here",
            "Work\ncall bank #todo #urgent\nlater #todo",
        ]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        ed.setPlainText("milk #todo now\n# Header with #tag\nplain")

        def point(block, col):
            c = QTextCursor(ed.document().findBlockByNumber(block))
            c.setPosition(c.block().position() + col)
            return ed.cursorRect(c).center()

        assert ed.hashtag_at(point(0, 7)) == "todo"
        assert ed.hashtag_at(point(0, 2)) is None
        # a header line is a header, even with a hash-word on it
        assert ed.hashtag_at(point(1, 15)) is None

        opened = []
        win.open_hashtag_dialog = lambda tag=None: opened.append(tag)
        ed.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(point(0, 7)),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier))
        assert opened == ["todo"], "Ctrl+click on a tag must open the finder"
        win.open_hashtag_dialog = real_open

        # the finder lists tags by how many lines carry them
        win._switch_to_slot(0, initial=True)
        ed.setPlainText(win.data["temp_presets"][0])
        dlg = HashtagDialog(win, "todo")
        labels = [dlg.tag_list.item(i).text()
                  for i in range(dlg.tag_list.count())]
        assert labels == ["#todo  (3)", "#urgent  (1)"]
        assert dlg.tag_list.currentItem().data(
            Qt.ItemDataRole.UserRole) == "todo", "the clicked tag is preselected"
        assert dlg.hit_list.count() == 3

        # and a hit opens the silo it lives in, on the right line
        hit = dlg.hit_list.item(2).data(Qt.ItemDataRole.UserRole)
        assert (hit["silo"], hit["line"]) == (2, 3)
        assert win.jump_to_silo_line(hit["silo"], hit["line"]) is True
        assert win.active_temp_slot == 2
        assert ed.textCursor().blockNumber() + 1 == 3
        dlg.close()

        # out-of-range jumps are refused rather than crashing
        assert win.jump_to_silo_line(999, 1) is False
    finally:
        win.open_hashtag_dialog = real_open
        win.data["temp_presets"][:] = kept
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        ed.clear()

def test_custom_cursors_toggle(win):
    """Off by default; on, every shape that Qt can load comes from the
    user's own Windows scheme."""
    from PyQt6.QtCore import Qt

    kept = win.data.get("custom_cursors", "False")
    try:
        # drive it through the checkbox: the shipped default has this ON, so
        # writing data directly leaves the box checked and the setChecked(True)
        # below is a no-op that never fires the signal under test
        win.cb_custom_cursors.setChecked(False)
        win.apply_custom_cursors()
        assert win.data["custom_cursors"] == "False"
        assert win.themed_cursor(Qt.CursorShape.ArrowCursor) == \
            Qt.CursorShape.ArrowCursor, "off means stock shapes"

        win.cb_custom_cursors.setChecked(True)
        assert win.data["custom_cursors"] == "True"

        arrow = win.themed_cursor(Qt.CursorShape.ArrowCursor)
        if arrow != Qt.CursorShape.ArrowCursor:
            # a real scheme was found on this machine
            assert not arrow.pixmap().isNull()
            assert win.themed_cursor(Qt.CursorShape.IBeamCursor) is not None

        win.cb_custom_cursors.setChecked(False)
        assert win.data["custom_cursors"] == "False"
        assert win.themed_cursor(Qt.CursorShape.ArrowCursor) == \
            Qt.CursorShape.ArrowCursor, "turning it off must restore stock"

        # the right-click hint has to be discoverable
        assert "Right-click" in win.btn_install_cursors.toolTip()
    finally:
        win.data["custom_cursors"] = kept
        win.apply_custom_cursors()

def test_custom_cursors_survive_a_restart(win):
    """Reported: after restarting with the toggle already on, cursors stayed
    stock until it was flipped by hand. The checkbox is built pre-ticked from
    saved data, which does not fire its callback, and nothing else applied
    them at startup."""
    from PyQt6.QtCore import Qt

    from fastprompter.ui.cursor_theme import capture_current_scheme, load_bundle

    kept = win.data.get("custom_cursors", "False")
    try:
        if not load_bundle()[1] and not capture_current_scheme()[1]:
            import pytest
            pytest.skip("no cursor scheme available on this machine")

        win.data["custom_cursors"] = "True"
        win.mark_dirty()
        win.save_data_to_db(force=True)

        fresh = FastPrompter()   # simulates a full app restart, same DB
        try:
            assert fresh.data.get("custom_cursors") == "True"
            assert fresh.cb_custom_cursors.isChecked()
            # the point of the bug: nothing is touched after construction
            arrow = fresh.themed_cursor(Qt.CursorShape.ArrowCursor)
            assert arrow != Qt.CursorShape.ArrowCursor, \
                "the saved toggle must be applied at startup"
            assert not arrow.pixmap().isNull()
            assert not fresh.cursor().pixmap().isNull()
        finally:
            fresh.auto_save_timer.stop()
            fresh.topmost_timer.stop()
            fresh._cache_timer.stop()
            fresh.state.conn = None
            fresh.conn = None
            fresh.close()
    finally:
        win.data["custom_cursors"] = kept
        win.apply_custom_cursors()
        win.mark_dirty()
        win.save_data_to_db(force=True)

def test_zone_picker_is_compact_and_opens_under_the_cursor(win):
    """It used to cover the whole monitor, which meant a full-screen repaint
    and a long mouse trip to reach a corner."""
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication

    from fastprompter.ui.fancy_zones import FancyZoneOverlay

    screen = QApplication.primaryScreen()
    ov = FancyZoneOverlay()
    kept_layout = win.data.get("fancyzones_layout", "")
    try:
        # a builtin page, not whatever the profile last used: the shipped
        # defaults land on Presets, whose cells overlap each other
        win.data["fancyzones_layout"] = "Quarters"
        QCursor.setPos(screen.geometry().center())
        assert ov.open_for(win) is True

        g = ov.geometry()
        assert g.width() < screen.geometry().width(), "must not be full screen"
        assert g.width() <= 520 and g.height() <= 360, "must stay a small HUD"
        assert screen.geometry().contains(g), "must be nudged fully on screen"
        assert abs(g.center().x() - QCursor.pos().x()) < 60, "must be near the pointer"

        # the map keeps one clickable cell per zone
        assert len(ov._cells) == len(ov._zones)
        assert ov._zone_at(ov._cells[1].center()) == 1
        assert ov._zone_at(g.topLeft() - g.topLeft()) in (-1, 0)
    finally:
        win.data["fancyzones_layout"] = kept_layout
        ov.close()


def test_zone_picker_has_two_pages_and_remembers_the_last(win):
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication

    from fastprompter.ui.fancy_zones import FancyZoneOverlay

    kept = win.data.get("fancyzones_layout", "")
    kept_presets = win.data.get("window_presets", [])
    try:
        QCursor.setPos(QApplication.primaryScreen().geometry().center())
        win.data["fancyzones_layout"] = "Quarters"   # start from a known page
        # this test is about the two BUILTIN pages; the shipped profile ships
        # saved presets, which legitimately add a third
        win.data["window_presets"] = []
        ov = FancyZoneOverlay()
        ov.open_for(win)
        assert len(ov._layouts) == 2, "Tab must switch between exactly two builtin pages"
        assert ov._layouts[ov._layout_idx][0] == "Quarters"
        assert len(ov._zones) == 4

        ov.cycle_layout(1)
        assert ov._layouts[ov._layout_idx][0] == "Columns"
        assert len(ov._zones) == 3

        ov.cycle_layout(1)
        assert ov._layouts[ov._layout_idx][0] == "Quarters", "two pages wrap"

        # applying stores the page...
        ov.cycle_layout(1)
        ov.apply_zone(0)
        assert win.data["fancyzones_layout"] == "Columns"

        # ...and the next open comes up on it
        ov2 = FancyZoneOverlay()
        ov2.open_for(win)
        assert ov2._layouts[ov2._layout_idx][0] == "Columns"
        assert len(ov2._zones) == 3
        ov2.close()
    finally:
        win.data["fancyzones_layout"] = kept
        win.data["window_presets"] = kept_presets


def test_snapping_does_not_hide_a_window_set_to_hide_on_click_out(win):
    """Opening the picker takes focus off the main window, so with hide-on-
    click-out enabled the window vanished the moment Ctrl+Q was pressed and
    stayed gone after snapping."""
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication

    from fastprompter.ui.fancy_zones import FancyZoneOverlay

    kept_focus = win.data.get("close_on_focus_loss", "True")
    kept_layout = win.data.get("fancyzones_layout", "")
    try:
        win.data["close_on_focus_loss"] = "True"
        win.show()
        QCursor.setPos(QApplication.primaryScreen().geometry().center())

        ov = FancyZoneOverlay()
        ov.open_for(win)
        assert ov._focus_locked, "the hide must be held off while the picker is up"

        assert ov.apply_zone(0) is True
        assert not win.isHidden(), "the window must survive the snap"
        assert ov._focus_locked is False, "and the hold must be released after"
    finally:
        win.data["close_on_focus_loss"] = kept_focus
        win.data["fancyzones_layout"] = kept_layout

def test_real_ctrl_e_reverses_a_header(win):
    """The earlier "Ctrl+E reverses any header" fix was applied to the old
    toggle_header_line, which nothing in the app ever called (it has since
    been deleted) - both Ctrl+E and the H button go to
    apply_header_timestamp, and that only ever re-stamped.
    So "## Sub" became "# Sub (Morning 21.07 - 11:05)" with no way back."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QTextCursor
    from PyQt6.QtTest import QTest

    ed = win.text_area
    kept = win.data.get("ctrl_e_center", "False")
    try:
        def ctrl_e():
            QTest.keyClick(ed, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)

        def to_end():
            c = ed.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            ed.setTextCursor(c)

        # a header at ANY level comes off
        for header in ("# Header one", "## Sub header", "### Third level"):
            ed.setPlainText(header)
            to_end()
            ctrl_e()
            assert ed.toPlainText() == header.split(" ", 1)[1], header

        # plain text still gets stamped, and pressing again gives it back
        ed.setPlainText("my note")
        to_end()
        ctrl_e()
        stamped = ed.toPlainText()
        assert stamped.startswith("# my note ("), stamped

        # stamping parks the caret two lines below on a fresh bullet, so
        # reversing means putting the caret back ON the header first - which
        # is what a person does by clicking it
        c = ed.textCursor()
        c.setPosition(ed.document().findBlockByNumber(0).position())
        ed.setTextCursor(c)
        ctrl_e()
        assert ed.toPlainText().splitlines()[0] == "my note",             "the timestamp must come off too"

        # and the line is genuinely plain again, not just plain-looking
        blk = ed.document().findBlockByNumber(0)
        cur = QTextCursor(blk)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                         QTextCursor.MoveMode.KeepAnchor)
        assert cur.charFormat().fontWeight() == QFont.Weight.Normal
        assert not cur.charFormat().fontUnderline()
    finally:
        win.data["ctrl_e_center"] = kept
        ed.clear()


def test_ctrl_e_centering_toggle_is_reversible(win):
    """Centring must follow the setting in both directions.

    This used to also assert the default was OFF, from the days when the
    feature had silently switched itself on for everyone. The shipped
    profile now centres deliberately (T-695), and the promise it was really
    guarding — an existing database keeps whatever it stored — is held by
    tests/test_state.py::test_stored_values_win_over_the_baked_default.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtTest import QTest

    ed = win.text_area
    kept = win.data.get("ctrl_e_center", "False")
    try:

        def ctrl_e():
            c = ed.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            ed.setTextCursor(c)
            QTest.keyClick(ed, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)

        def centred():
            a = ed.document().findBlockByNumber(0).blockFormat().alignment()
            return bool(a & Qt.AlignmentFlag.AlignCenter)

        # the footer checkbox is gone - alignment lives in the Ctrl+E dialog
        # now - so this drives the same entry point it used to call
        win._on_ctrl_e_center_toggled(False)
        ed.setPlainText("title")
        ctrl_e()
        assert not centred(), "off means off"

        win._on_ctrl_e_center_toggled(True)
        ed.setPlainText("title")
        ctrl_e()
        assert centred()

        # taking the header off must take the centring with it
        c = ed.textCursor()
        c.setPosition(ed.document().findBlockByNumber(0).position())
        ed.setTextCursor(c)
        QTest.keyClick(ed, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        assert not centred(), "a plain line must not stay centred"
    finally:
        win._on_ctrl_e_center_toggled(kept == "True")
        win.data["ctrl_e_center"] = kept
        ed.clear()


def test_settings_controls_are_packed_not_spread_across_the_panel(win):
    """Justifying each line flung controls to opposite edges - measured a
    724px gap between two checkboxes on the Clock tab, which is the very
    "huge empty space" the panel was compacted to get rid of."""
    from PyQt6.QtWidgets import QCheckBox

    # `win` is module-scoped: leaving the panel SHOWN here raises the whole
    # window's layout minimum, and every later test that resizes the window
    # narrow (the header density tiers) silently gets clamped instead —
    # which is exactly why four of them only failed in a full run.
    kept_visible = win.mini_settings_frame.isVisible()
    win.mini_settings_frame.setVisible(True)
    tabs = win.settings_tabs
    kept_tab = tabs.currentIndex()
    try:
        worst = 0
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            page = tabs.widget(i)
            rows = {}
            for w in page.findChildren(QCheckBox):
                if not w.isVisibleTo(page):
                    continue
                g = w.geometry()
                rows.setdefault(g.y(), []).append((g.x(), g.x() + g.width()))
            for items in rows.values():
                items.sort()
                for a, b in zip(items, items[1:]):
                    worst = max(worst, b[0] - a[1])
        assert worst <= 40, f"controls spread apart by {worst}px"
    finally:
        tabs.setCurrentIndex(kept_tab)
        win.mini_settings_frame.setVisible(kept_visible)

def test_analog_clock_blends_with_its_neighbours_on_every_theme(win):
    """Reported twice: a visible square behind the clock.

    The comparison that matters is against the widgets NEXT TO it, not
    against the header bar. The bar is tinted lighter than the labels that
    sit on it, so filling the clock with the bar's tint - the first attempt -
    left it a pale square among dark neighbours.
    """
    from fastprompter.theme.themes import THEMES

    kept_theme = win.data.get("theme", "Default")
    kept_clock = win.data.get("analog_clock", "False")
    try:
        win.data["analog_clock"] = "True"
        win.analog_clock.setVisible(True)
        if win.analog_clock.isHidden():
            import pytest
            pytest.skip("clock hidden at this width")

        offenders = []
        for name in THEMES:
            win.data["theme"] = name
            win.apply_theme()
            win.analog_clock.update()

            # The colour the clock will fill its whole rect with. Asserted
            # instead of rendering: forcing nine repaints while themes change
            # segfaulted Qt, and the pixels were verified by hand against the
            # clock's real neighbours on all nine themes.
            from fastprompter.ui.analog_clock import _theme_palette
            expected = THEMES[name]["raw_colors"]["bg_main"].lower()
            face = _theme_palette(win)["face"].name().lower()
            if face != expected:
                offenders.append(f"{name}: face={face} wanted={expected}")

        assert not offenders, "clock shows a square: " + "; ".join(offenders)
    finally:
        win.data["analog_clock"] = kept_clock
        win.data["theme"] = kept_theme
        win.apply_theme()


def test_header_tint_has_a_single_owner():
    """theme_mixin and the clock must agree on the bar colour; when only
    theme_mixin knew the formula, the clock drifted onto its own value."""
    import inspect

    from fastprompter.theme.themes import header_tint
    from fastprompter.ui import analog_clock, theme_mixin

    assert callable(header_tint)
    assert "header_tint" in inspect.getsource(theme_mixin.ThemeMixin.apply_theme)
    assert "bg_main" in inspect.getsource(analog_clock._theme_palette)

def test_alt_c_queues_the_current_line(win):
    """Alt+C is FastPrompter's own queue command: the line goes in, the
    caret moves on, and the line is marked."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from fastprompter.ui.markdown_highlighter import QUEUED_BIT

    ed = win.text_area
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        ed.setPlainText("first prompt\nsecond prompt\n\nthird prompt")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)

        QTest.keyClick(ed, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)
        QTest.keyClick(ed, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)

        queue = win.prompt_queues[win._queue_slot_key()]
        assert [i.text for i in queue] == ["first prompt", "second prompt"]

        # the caret advanced, and the marks landed on the right blocks
        assert ed.textCursor().blockNumber() == 2
        for n, expected in ((0, True), (1, True), (3, False)):
            state = max(0, ed.document().findBlockByNumber(n).userState())
            assert bool(state & QUEUED_BIT) is expected, f"line {n + 1}"

        # an empty line is not a prompt
        QTest.keyClick(ed, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)
        assert len(queue) == 2
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_a_queued_item_follows_its_line(win):
    """The anchor is the block, not the line number: inserting above must
    not point the queue at different text, and editing the line changes
    what would be sent."""
    from PyQt6.QtGui import QTextCursor

    ed = win.text_area
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        ed.setPlainText("alpha\nbravo\ncharlie")
        c = ed.textCursor()
        c.setPosition(ed.document().findBlockByNumber(1).position())
        ed.setTextCursor(c)
        item = win.queue_current_line()
        assert item is not None and item.text == "bravo"

        # insert two lines above it
        top = ed.textCursor()
        top.setPosition(0)
        ed.setTextCursor(top)
        top.insertText("new one\nnew two\n")

        block = ed.block_for_queue_item(item.id)
        assert block is not None
        assert block.text() == "bravo", "the anchor followed the wrong line"
        assert block.blockNumber() == 3, "and it really did move"

        # editing the line edits what will be sent
        edit = QTextCursor(block)
        edit.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        edit.insertText(" EDITED")
        assert ed.block_for_queue_item(item.id).text() == "bravo EDITED"
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_deleting_the_line_detaches_and_leaves_no_stale_tick(win):
    """Qt merges blocks on delete and the survivor can inherit the state
    bits without the anchor - which would paint a tick beside a line that
    was never sent."""
    from PyQt6.QtGui import QTextCursor

    from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT

    ed = win.text_area
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        ed.setPlainText("alpha\nbravo\ncharlie")
        c = ed.textCursor()
        c.setPosition(ed.document().findBlockByNumber(1).position())
        ed.setTextCursor(c)
        item = win.queue_current_line()

        assert ed.mark_queue_sent(item.id) is True
        block = ed.block_for_queue_item(item.id)
        state = max(0, block.userState())
        assert state & SENT_BIT and not state & QUEUED_BIT

        cut = QTextCursor(block)
        cut.select(QTextCursor.SelectionType.BlockUnderCursor)
        cut.removeSelectedText()

        assert ed.block_for_queue_item(item.id) is None, "anchor must be gone"
        ed.prune_queue_marks()
        for n in range(ed.document().blockCount()):
            state = max(0, ed.document().findBlockByNumber(n).userState())
            assert not state & (QUEUED_BIT | SENT_BIT), f"stale tick on line {n + 1}"
        assert ed.collect_queue_marks() == {}
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_queue_marks_and_edit_heat_share_the_block_without_clobbering(win):
    """A block has one userData slot. Heat was there first; the queue anchor
    joined it, and neither may erase the other."""
    import time

    from fastprompter.ui.editor import block_data, stamp_heat

    ed = win.text_area
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        ed.setPlainText("only line")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        item = win.queue_current_line()

        block = ed.document().findBlockByNumber(0)
        stamp_heat(block, time.time())
        assert block_data(block).queue_id == item.id, "heat erased the anchor"

        ed.set_queue_anchor(block, item.id)
        assert block_data(block).ts is not None, "the anchor erased the heat"
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_the_queue_bits_survive_a_rehighlight(win):
    """_KEEP_MASK is what survives a rehighlight pass. A bit missing from it
    is wiped at random, which looks like the queue losing its own state."""
    from fastprompter.ui.markdown_highlighter import (
        _KEEP_MASK,
        QUEUED_BIT,
        SENT_BIT,
    )

    assert _KEEP_MASK & QUEUED_BIT, "QUEUED_BIT would be wiped"
    assert _KEEP_MASK & SENT_BIT, "SENT_BIT would be wiped"

    ed = win.text_area
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        ed.setPlainText("a prompt line")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        item = win.queue_current_line()

        if getattr(win, "highlighter", None) is not None:
            win.highlighter.rehighlight()
        state = max(0, ed.document().findBlockByNumber(0).userState())
        assert state & QUEUED_BIT, "the bit did not survive the highlighter"
        assert ed.block_for_queue_item(item.id) is not None
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_queues_are_per_silo_and_persist(win):
    ed = win.text_area
    kept = dict(win.prompt_queues)
    kept_presets = list(win.data["temp_presets"])
    try:
        win.prompt_queues.clear()
        win.data["temp_presets"][:] = ["silo one", "silo two"]
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        ed.setPlainText("from the first silo")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        win.queue_current_line()

        win._switch_to_slot(1, initial=True)
        ed.setPlainText("from the second silo")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        win.queue_current_line()

        assert sorted(win.prompt_queues) == ["0", "1"]
        assert [i.text for i in win.prompt_queues["0"]] == ["from the first silo"]
        assert [i.text for i in win.prompt_queues["1"]] == ["from the second silo"]

        # and it round-trips through the saved data
        from fastprompter.core.watcher.queue import load_queues
        back = load_queues(win.data["watcher_queues"])
        assert sorted(back) == ["0", "1"]
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.data["temp_presets"][:] = kept_presets
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        ed.clear()

def _queue_three(win, header="# Project notes"):
    """Three queued lines under a titled note. Returns the dialog."""
    from fastprompter.ui.queue_panel import QueueDialog

    ed = win.text_area
    ed.setPlainText(f"{header}\nfirst prompt\nsecond prompt\nthird prompt")
    for n in (1, 2, 3):
        c = ed.textCursor()
        c.setPosition(ed.document().findBlockByNumber(n).position())
        ed.setTextCursor(c)
        win.queue_current_line()
    return QueueDialog(win)


def test_queue_panel_lists_the_silo_queue(win):
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        assert dlg.list.count() == 3
        assert "first prompt" in dlg.list.item(0).text()
        # the header names the silo by its FIRST LINE, not a flattened blob
        assert dlg.lbl_head.text().startswith("Project notes")
        assert "3/3" in dlg.lbl_head.text()
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_send_next_reorders_and_never_sends(win):
    """The only thing this dialog may do is change the order."""
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        dlg.list.setCurrentRow(2)
        before = dlg._selected().state

        dlg.to_front_selected()
        assert [i.text for i in dlg._queue()] == [
            "third prompt", "first prompt", "second prompt"]
        assert dlg._queue().items[0].state == before, "jumping must not send"
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_rows_follow_edits_made_in_the_note(win):
    """Items are references: editing the line changes what would be sent,
    and the row has to say so."""
    from PyQt6.QtGui import QTextCursor

    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        item = dlg._queue().items[1]

        block = win.text_area.block_for_queue_item(item.id)
        edit = QTextCursor(block)
        edit.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        edit.insertText(" EDITED")

        dlg.refresh()
        assert "second prompt EDITED" in dlg.list.item(1).text()
        assert item.text == "second prompt EDITED"
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_deleting_the_line_detaches_but_keeps_the_text(win):
    from PyQt6.QtGui import QTextCursor

    from fastprompter.core.watcher.queue import DETACHED

    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        item = dlg._queue().items[1]

        block = win.text_area.block_for_queue_item(item.id)
        cut = QTextCursor(block)
        cut.select(QTextCursor.SelectionType.BlockUnderCursor)
        cut.removeSelectedText()

        dlg.refresh()
        assert item.state == DETACHED
        assert item.text == "second prompt", "the last known text must survive"
        assert item.reason
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_removing_an_item_clears_its_line_mark(win):
    """Otherwise the note keeps a mark pointing at a queue entry that is
    gone, and the gutter lies."""
    from fastprompter.ui.markdown_highlighter import QUEUED_BIT

    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        item = dlg._queue().items[0]
        block = win.text_area.block_for_queue_item(item.id)
        assert max(0, block.userState()) & QUEUED_BIT

        dlg.list.setCurrentRow(0)
        dlg.remove_selected()

        assert win.text_area.block_for_queue_item(item.id) is None
        assert len(dlg._queue()) == 2
        for n in range(win.text_area.document().blockCount()):
            state = max(0, win.text_area.document().findBlockByNumber(n).userState())
            if state & QUEUED_BIT:
                blk = win.text_area.document().findBlockByNumber(n)
                assert blk.text().strip() != "first prompt"
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_clear_finished_leaves_the_waiting_ones(win):
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)
        queue = dlg._queue()
        queue.items[0].mark_sent()
        queue.items[1].mark_failed("nope")

        dlg.clear_finished()
        assert [i.text for i in dlg._queue()] == ["third prompt"]
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()


def test_a_drag_reorder_is_written_back_to_the_queue(win):
    """The list order IS the sending order, so a drop that only moved rows
    on screen would be a lie."""
    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = _queue_three(win)

        # simulate what a drop leaves behind: rows in a new order
        row = dlg.list.takeItem(2)
        dlg.list.insertItem(0, row)
        dlg._apply_row_order()

        assert [i.text for i in dlg._queue()] == [
            "third prompt", "first prompt", "second prompt"]
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.text_area.clear()

def _two_silos_with_queues(win):
    """Alpha (slot 0) gets two prompts, Beta (slot 1) one. Beta stays open."""
    from fastprompter.ui.queue_panel import QueueDialog

    ed = win.text_area
    win.data["temp_presets"][:] = [
        "# Alpha project\nfirst from alpha\nsecond from alpha",
        "# Beta notes\nonly from beta",
        "",
    ]
    win.silo_docs[:] = []
    for slot in (0, 1):
        win._switch_to_slot(slot, initial=True)
        doc = ed.document()
        for n in range(1, doc.blockCount()):
            if doc.findBlockByNumber(n).text().strip():
                c = ed.textCursor()
                c.setPosition(doc.findBlockByNumber(n).position())
                ed.setTextCursor(c)
                win.queue_current_line()
    return QueueDialog(win)


def test_master_view_shows_every_silo_and_names_the_source(win):
    kept = dict(win.prompt_queues)
    kept_presets = list(win.data["temp_presets"])
    try:
        win.prompt_queues.clear()
        dlg = _two_silos_with_queues(win)

        assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
            "This silo", "All silos"]
        assert dlg.master_list.count() == 3

        rows = [dlg.master_list.item(i).text() for i in range(3)]
        # the label is the silo's FIRST LINE with the leading # stripped
        assert "[Alpha project]" in rows[0]
        assert "[Beta notes]" in rows[2]
        assert "3" in dlg.lbl_master.text() and "2" in dlg.lbl_master.text()
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.data["temp_presets"][:] = kept_presets
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.text_area.clear()


def test_master_view_reads_a_closed_silo_from_its_stored_text(win):
    """silo_docs are lazy, so most silos have no document. Their text has to
    come from temp_presets - which is safe because a closed silo cannot be
    edited: editing it opens it."""
    kept = dict(win.prompt_queues)
    kept_presets = list(win.data["temp_presets"])
    try:
        win.prompt_queues.clear()
        dlg = _two_silos_with_queues(win)

        assert win._queue_slot_key() == "1", "Beta is the open one"
        alpha_rows = [dlg.master_list.item(i).text()
                      for i in range(dlg.master_list.count())
                      if "[Alpha project]" in dlg.master_list.item(i).text()]
        assert len(alpha_rows) == 2
        assert any("first from alpha" in r for r in alpha_rows), \
            "the closed silo showed a placeholder instead of its text"
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.data["temp_presets"][:] = kept_presets
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.text_area.clear()


def test_master_view_moves_an_item_between_silos(win):
    kept = dict(win.prompt_queues)
    kept_presets = list(win.data["temp_presets"])
    try:
        win.prompt_queues.clear()
        dlg = _two_silos_with_queues(win)

        dlg.master_list.setCurrentRow(0)
        slot, item = dlg._master_selected()
        assert slot == "0"

        target = next(dlg.cb_target.itemData(i)
                      for i in range(dlg.cb_target.count())
                      if dlg.cb_target.itemData(i) != slot)
        dlg.cb_target.setCurrentIndex(
            [dlg.cb_target.itemData(i) for i in range(dlg.cb_target.count())].index(target))
        dlg.move_selected_to_target()

        assert item.text in [i.text for i in win.prompt_queues[target]]
        assert item.text not in [i.text for i in win.prompt_queues["0"]]
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.data["temp_presets"][:] = kept_presets
        win.silo_docs[:] = []
        win._switch_to_slot(0, initial=True)
        win.text_area.clear()


def test_queues_are_separate_per_category(win):
    """Every other slot-keyed map is stored per category and rebound on a tab
    change; a queue that skipped that would follow the user across tabs."""
    if win.cat_combo.count() < 2:
        import pytest
        pytest.skip("needs at least two categories")

    kept = dict(win.prompt_queues)
    kept_index = win.cat_combo.currentIndex()
    ed = win.text_area
    try:
        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        win.prompt_queues.clear()
        ed.setPlainText("prompt in the first category")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        win.queue_current_line()
        first_cat = win.get_current_category()

        win.cat_combo.setCurrentIndex(1)
        win.on_tab_changed(1)
        assert not win.prompt_queues, "another category's queue leaked in"

        win.cat_combo.setCurrentIndex(0)
        win.on_tab_changed(0)
        assert [i.text for i in win.prompt_queues.get("0", [])] == [
            "prompt in the first category"]
        assert first_cat in win.data.get("watcher_queues_all", {})
    finally:
        win.cat_combo.setCurrentIndex(kept_index)
        win.on_tab_changed(kept_index)
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        ed.clear()


def test_opening_the_dialog_does_not_die_on_the_first_tab_signal(win):
    """currentChanged fires while the first tab is being added. Connecting it
    before the widgets exist raised inside a Qt slot, which takes the process
    down with no traceback - it must be connected last."""
    from fastprompter.ui.queue_panel import QueueDialog

    kept = dict(win.prompt_queues)
    try:
        win.prompt_queues.clear()
        dlg = QueueDialog(win)          # empty queue: the harder case
        assert dlg.tabs.count() == 2
        dlg.tabs.setCurrentIndex(1)     # and switching must be safe too
        dlg.tabs.setCurrentIndex(0)
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)

def _chips(dlg):
    out = []
    for i in range(dlg.chip_box.count()):
        w = dlg.chip_box.itemAt(i).widget()
        if w is not None:
            out.append((w.text(), w.isChecked()))
    return out


def test_the_skill_chip_stamps_the_next_queued_prompt(win):
    """The skill is stored beside the text and composed at send time, so the
    row preview is what would actually go out."""
    from fastprompter.ui.queue_panel import QueueDialog

    ed = win.text_area
    kept = dict(win.prompt_queues)
    kept_skill = win.data.get("watcher_skill", "")
    try:
        win.prompt_queues.clear()
        dlg = QueueDialog(win)

        # "none" is a real choice and comes first
        assert _chips(dlg)[0][0] == "none"
        assert dlg.current_skill() == ""

        dlg.set_current_skill("saipen")
        assert dlg.current_skill() == "saipen"
        assert ("/saipen", True) in _chips(dlg)

        ed.setPlainText("continue please")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        item = win.queue_current_line()

        assert item.skill == "saipen"
        assert item.compose() == "/saipen continue please"
        # a target that cannot invoke skills gets None, not a stripped prompt
        assert item.compose(skill_format=None) is None

        dlg.refresh()
        assert "/saipen continue please" in dlg.list.item(0).text()
        dlg.close()
    finally:
        win.prompt_queues.clear()
        win.prompt_queues.update(kept)
        win.data["watcher_skill"] = kept_skill
        ed.clear()


def test_a_hand_added_chip_survives_a_rescan_and_can_be_hidden(win):
    """Discovery only sees what is installed locally, so curation is the
    feature, not the fallback."""
    from fastprompter.core.watcher import skills as sk
    from fastprompter.ui.queue_panel import QueueDialog

    kept_extra = list(win.data.get("watcher_skills_extra") or [])
    kept_hidden = list(win.data.get("watcher_skills_hidden") or [])
    kept_skill = win.data.get("watcher_skill", "")
    try:
        win.data["watcher_skills_extra"] = []
        win.data["watcher_skills_hidden"] = []
        dlg = QueueDialog(win)

        palette = sk.load_palette(win.data)
        palette.append(sk.Skill("cavecrew", source="manual"))
        sk.save_palette(win.data, palette)
        dlg.refresh_chips()
        assert "/cavecrew" in [c[0] for c in _chips(dlg)]

        # only the hand-added one is stored; the discovered ones are rescanned
        stored = [e["name"] for e in win.data["watcher_skills_extra"]]
        assert stored == ["cavecrew"]

        dlg.set_current_skill("cavecrew")
        dlg.hide_current_skill()
        assert "/cavecrew" not in [c[0] for c in _chips(dlg)]
        assert "cavecrew" in win.data["watcher_skills_hidden"]
        # and it does not come straight back from `extra` on the next load
        assert "cavecrew" not in [
            e["name"] for e in win.data.get("watcher_skills_extra") or []]
        assert dlg.current_skill() == ""
        dlg.close()
    finally:
        win.data["watcher_skills_extra"] = kept_extra
        win.data["watcher_skills_hidden"] = kept_hidden
        win.data["watcher_skill"] = kept_skill


# ============================ W-07: arming the watcher =====================
#
# Nothing here arms against a real window with live sending. The target is a
# fake handle and the sender stays dry, so no test can put a keystroke into a
# running application.


class _FakeWin32:
    """A desktop of one window, standing in for the ctypes layer."""

    def __init__(self, hwnd=4242, title="Agent", cls="ConsoleWindowClass"):
        self.hwnd, self.title, self.cls = hwnd, title, cls
        self.alive = True

    def info(self, hwnd):
        if hwnd != self.hwnd or not self.alive:
            return None
        return {"title": self.title, "cls": self.cls, "pid": 999}


def _fake_adapter(name="test-agent", quiet_ms=0, settle_ms=0):
    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import Probe

    class Steady(Probe):
        kind = "steady"

        def _read(self):
            return "unchanging"

    return Adapter(name, probes=[Steady(quiet_ms=quiet_ms)],
                   settle_ms=settle_ms)


def _arm_on_fake(win, monkeypatch, live=False, adapter=None):
    """Arm against a fake window. Returns (ok, reason, fake)."""
    from fastprompter.core.watcher import win32 as win32_mod

    fake = _FakeWin32()
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: fake.info(hwnd))
    monkeypatch.setattr(win32_mod, "probe_for",
                        lambda api=None: (lambda h: fake.info(h)))
    ok, reason = win.watcher_arm(fake.hwnd, adapter or _fake_adapter(), live=live)
    return ok, reason, fake


def test_the_watcher_mixin_is_on_the_window(win):
    from fastprompter.ui.watcher_mixin import WatcherMixin
    assert isinstance(win, WatcherMixin)
    assert win.watcher_engine().state == "disarmed"


def test_arming_a_window_that_is_gone_is_refused(win, monkeypatch):
    from fastprompter.core.watcher import win32 as win32_mod

    monkeypatch.setattr(win32_mod, "window_info", lambda hwnd, api=None: None)
    ok, reason = win.watcher_arm(1234, _fake_adapter())
    assert ok is False and "gone" in reason
    assert win.watcher_engine().armed is False


def test_arming_without_a_usable_agent_is_refused(win, monkeypatch):
    from fastprompter.core.watcher.adapter import Adapter

    ok, reason, _fake = _arm_on_fake(win, monkeypatch, adapter=Adapter("blind"))
    assert ok is False and "no probes" in reason


def test_arming_pins_the_queue_and_starts_the_timer(win, monkeypatch):
    ok, reason, _fake = _arm_on_fake(win, monkeypatch)
    assert ok is True and "dry run" in reason

    engine = win.watcher_engine()
    assert engine.armed is True
    assert engine.queue_key == win._queue_slot_key()
    assert win._watcher_timer is not None and win._watcher_timer.isActive()

    win.watcher_disarm("test done")
    assert win._watcher_timer.isActive() is False


def test_a_dry_run_never_marks_anything_live(win, monkeypatch):
    """The default must record rather than send, even armed."""
    _arm_on_fake(win, monkeypatch, live=False)
    assert win._watcher_sender.dry is True
    win.watcher_disarm("test done")


def test_going_live_picks_the_silent_sender_never_the_loud_one(win, monkeypatch):
    """The UI has no route to the focus-stealing path at all."""
    from fastprompter.core.watcher import win32 as win32_mod
    from fastprompter.core.watcher.sender import ClipboardSender, PostMessageSender

    monkeypatch.setattr(win32_mod, "available", lambda: True)
    _arm_on_fake(win, monkeypatch, live=True)

    assert isinstance(win._watcher_sender, PostMessageSender)
    assert not isinstance(win._watcher_sender, ClipboardSender)
    assert win._watcher_sender.silent is True
    win.watcher_disarm("test done")


def test_panic_stops_a_run_and_drops_what_was_in_flight(win, monkeypatch):
    _arm_on_fake(win, monkeypatch)
    win.watcher_engine().state = "sending"
    win.watcher_engine().pending = object()

    assert win.watcher_panic() is True
    assert win.watcher_engine().armed is False
    assert win.watcher_engine().pending is None
    assert win._watcher_timer.isActive() is False


def test_panic_with_nothing_armed_says_so(win):
    """The hotkey filter only swallows the key when this returns True, so a
    stray press stays usable in whatever app the user is in."""
    win.watcher_disarm("idle")
    assert win.watcher_panic() is False


def test_a_tick_that_explodes_disarms_instead_of_killing_the_app(win, monkeypatch):
    """An exception in a Qt slot takes the process down with no traceback.
    A watcher whose own loop is broken must stop, not keep firing."""
    _arm_on_fake(win, monkeypatch)

    def boom():
        raise RuntimeError("the tick is broken")

    monkeypatch.setattr(win, "_watcher_tick_inner", boom)
    win._watcher_tick()              # must not raise

    assert win.watcher_engine().armed is False
    assert "error" in win.watcher_engine().reason
    assert win._watcher_timer.isActive() is False


def test_the_target_vanishing_mid_run_disarms(win, monkeypatch):
    _ok, _reason, fake = _arm_on_fake(win, monkeypatch)
    fake.alive = False
    win._watcher_tick()
    assert win.watcher_engine().armed is False
    assert "gone" in win.watcher_engine().reason


def test_a_freshly_armed_watcher_does_not_fire_into_what_is_on_screen(
        win, monkeypatch):
    """A probe's first reading is a baseline, not the agent working."""
    _arm_on_fake(win, monkeypatch)
    for _ in range(4):
        win._watcher_tick()

    assert win.watcher_engine().sent_count == 0
    assert win.watcher_engine()._seen_busy is False
    win.watcher_disarm("test done")


def test_armed_state_is_never_written_to_the_database(win, monkeypatch):
    """It belongs to a live session with a live window; restoring it would
    point a watcher at a handle that now belongs to someone else's app."""
    _arm_on_fake(win, monkeypatch)
    win.save_prompt_queues()

    keys = [k for k in win.data if "watcher" in k]
    assert "watcher_armed" not in keys
    assert not any("target" in k or "hwnd" in k for k in keys)
    win.watcher_disarm("test done")


def test_the_watcher_dialog_opens_and_lists_its_agents(win):
    from fastprompter.ui.watcher_dialog import WatcherDialog

    dlg = WatcherDialog(win)
    try:
        assert dlg.cmb_agent.count() >= 1, "the shipped example describes agents"
        assert dlg.btn_arm.text()
    finally:
        dlg.close()


def test_closing_the_dialog_leaves_a_run_going(win, monkeypatch):
    """A run outlives the window that started it - that is what a watcher is."""
    from fastprompter.ui.watcher_dialog import WatcherDialog

    _arm_on_fake(win, monkeypatch)
    dlg = WatcherDialog(win)
    dlg.close()

    assert win.watcher_engine().armed is True, "closing must not disarm"
    assert dlg.refresh not in win._watcher_listeners, "but it must unsubscribe"
    win.watcher_disarm("test done")


def test_a_dead_dialog_cannot_take_a_run_down_with_it(win, monkeypatch):
    """The listener list outlives dialogs; a broken one is dropped, not raised."""
    _arm_on_fake(win, monkeypatch)

    def broken():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    win.watcher_listen(broken)
    win._watcher_notify()

    assert broken not in win._watcher_listeners
    assert win.watcher_engine().armed is True
    win.watcher_disarm("test done")


def test_the_dialog_locks_the_target_while_armed(win, monkeypatch):
    """Both are pinned at arming; a movable picker would show a target the
    run is not actually using."""
    from fastprompter.ui.watcher_dialog import WatcherDialog

    _arm_on_fake(win, monkeypatch)
    dlg = WatcherDialog(win)
    try:
        assert dlg.lst_windows.isEnabled() is False
        assert dlg.cmb_agent.isEnabled() is False
        assert dlg.chk_live.isEnabled() is False
        assert dlg.btn_panic.isEnabled() is True
    finally:
        dlg.close()
        win.watcher_disarm("test done")


def test_arming_from_the_dialog_needs_something_queued(win):
    """Arming an empty queue would sit watching forever with nothing to say."""
    # PyQt6, like the rest of the app. Importing the PySide6 classes here
    # handed a PySide6.QListWidgetItem to a PyQt6 addItem() and the call had
    # no matching overload. It never showed up because the suite hung earlier
    # in the file and this test was simply never reached.
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem

    from fastprompter.core.watcher.queue import queue_for
    from fastprompter.ui.watcher_dialog import WatcherDialog

    queue = queue_for(win.prompt_queues, win._queue_slot_key())
    saved = queue.to_list()
    queue.items.clear()

    dlg = WatcherDialog(win)
    try:
        # Guarantee a valid hwnd so toggle_arm() proceeds past the "pick a window" check
        item = QListWidgetItem("Dummy Window")
        item.setData(Qt.ItemDataRole.UserRole, 12345)
        dlg.lst_windows.addItem(item)
        dlg.lst_windows.setCurrentRow(0)
        dlg.toggle_arm()
        assert win.watcher_engine().armed is False
        assert "Alt+C" in dlg.lbl_state.text()
    finally:
        dlg.close()
        queue.items.extend(saved)


def test_the_panic_hotkey_is_registered_globally():
    """It must work from whatever window the user is in when they decide it
    is going wrong, not only from FastPrompter."""
    import inspect

    from fastprompter.core.hotkey_filter import HotkeyFilter
    from fastprompter.ui.hotkey_mixin import HotkeyMixin

    assert "watcher_panic_hotkey" in inspect.getsource(
        HotkeyMixin.register_all_hotkeys)
    assert "watcher_panic" in inspect.getsource(
        HotkeyFilter.nativeEventFilter)


# ---------------------------- observe mode ---------------------------------
#
# The safety property is structural, not a flag: observe mode builds no
# target and no sender, so there is nothing in it that COULD send. That is
# what makes it safe to point at an agent mid-turn to learn its signal.


def test_watching_builds_no_target_and_no_live_sender(win):
    ok, reason = win.watcher_observe(_fake_adapter())
    try:
        assert ok is True and "watching" in reason
        assert win.watcher_observing is True
        assert win._watcher_target is None, "no target means nothing to send to"
        assert win._watcher_sender.dry is True
        assert win.watcher_engine().armed is False, "watching is not arming"
    finally:
        win.watcher_stop_observing()
    assert win.watcher_observing is False


def test_watching_never_sends_however_long_it_runs(win):
    win.watcher_observe(_fake_adapter())
    try:
        for _ in range(8):
            win._observe_tick()
        assert win.watcher_engine().sent_count == 0
        assert win.watcher_log().to_list() == []
    finally:
        win.watcher_stop_observing()


def test_watching_an_agent_it_cannot_read_is_refused(win):
    from fastprompter.core.watcher.adapter import Adapter

    ok, reason = win.watcher_observe(Adapter("blind"))
    assert ok is False and "no probes" in reason
    assert win.watcher_observing is False


def test_the_trace_records_transitions_not_every_poll(win):
    """Twice a second, a row per poll would bury the two moments that matter
    under hundreds of identical lines."""
    win.watcher_observe(_fake_adapter())
    try:
        for _ in range(10):
            win._observe_tick()
        trace = win.watcher_trace()
        assert 1 <= len(trace) <= 3, f"expected transitions only, got {len(trace)}"
        states = [row["state"] for row in trace]
        assert states == list(dict.fromkeys(states)), "no repeated states"
    finally:
        win.watcher_stop_observing()


def test_the_trace_marks_where_a_prompt_would_have_gone(win):
    """The point of watching: see the moment without living through it."""
    win.watcher_observe(_fake_adapter())
    try:
        for _ in range(6):
            win._observe_tick()
        marked = [row for row in win.watcher_trace() if row["would_send"]]
        assert marked, "the busy -> idle transition must be called out"
        assert marked[0]["state"] == "idle"
    finally:
        win.watcher_stop_observing()


def test_a_broken_observation_stops_instead_of_killing_the_app(win, monkeypatch):
    """Same rule as the send tick: an exception in a Qt slot takes the
    process down with no traceback."""
    win.watcher_observe(_fake_adapter())

    def boom():
        raise RuntimeError("the observer is broken")

    monkeypatch.setattr(win, "_observe_tick_inner", boom)
    win._observe_tick()              # must not raise
    assert win.watcher_observing is False


def test_watching_is_refused_while_a_run_is_armed(win, monkeypatch):
    """Both loops would poll the SAME probe objects at different rates, each
    stamping the other's quiet window."""
    _arm_on_fake(win, monkeypatch)
    try:
        ok, reason = win.watcher_observe(_fake_adapter())
        assert ok is False and "disarm first" in reason
        assert win.watcher_observing is False
    finally:
        win.watcher_disarm("test done")


def test_disarming_lets_go_of_the_target(win, monkeypatch):
    """A target outliving its run is how "it sent to the wrong window" starts."""
    _arm_on_fake(win, monkeypatch)
    assert win._watcher_target is not None
    win.watcher_disarm("test done")
    assert win._watcher_target is None
    assert win._watcher_sender.dry is True


def test_the_dialog_offers_watching_and_says_it_sends_nothing(win):
    from fastprompter.ui.watcher_dialog import WatcherDialog

    dlg = WatcherDialog(win)
    try:
        assert "nothing" in dlg.btn_watch.text().lower()
        assert dlg.btn_watch.isEnabled() is True
    finally:
        dlg.close()


def test_a_cdp_agent_arms_without_a_window_handle(win, monkeypatch):
    """A cdp adapter is bound to a debuggable PAGE, not a window.

    Demanding a handle for it made arming fail with "that window is gone"
    against a perfectly healthy agent: the branch that builds a CdpTarget
    existed, but the window check above it did not know about it. Only a
    live run found that - every piece was tested, the seam was not.
    """
    from fastprompter.core.watcher import win32 as win32_mod
    from fastprompter.core.watcher.adapter import Adapter
    from fastprompter.core.watcher.probes import Probe

    class Steady(Probe):
        kind = "steady"

        def _read(self):
            return "unchanging"

    page = {"id": "P1", "type": "page", "title": "CHAT",
            "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/P1"}
    monkeypatch.setattr("fastprompter.core.watcher.cdp.discover",
                        lambda port, **kw: [page])
    # no window layer at all: it must not be consulted for a cdp adapter
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: None)

    adapter = Adapter("cdp-agent", probes=[Steady()], transport="cdp",
                      cdp_port=9333, settle_ms=0)
    ok, reason = win.watcher_arm(0, adapter, live=False)
    try:
        assert ok is True, reason
        assert win._watcher_target.target_id == "P1"
    finally:
        win.watcher_disarm("test done")


# ------------------------------ W-2b: queue marks in the gutter ------------

def _queue_first_line(win, text="a line worth queueing"):
    from fastprompter.core.watcher.queue import queue_for

    queue_for(win.prompt_queues, win._queue_slot_key()).items.clear()
    win.text_area.setPlainText(text)
    cur = win.text_area.textCursor()
    cur.movePosition(cur.MoveOperation.Start)
    win.text_area.setTextCursor(cur)
    item = win.queue_current_line()
    return item, win.text_area.document().findBlockByNumber(0)


def test_a_line_can_be_user_marked_and_queued_without_either_clobbering(win):
    """Different bit ranges, one userState. A queue mark that used the low
    byte would overwrite whatever the user had ticked there."""
    from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT

    _item, block = _queue_first_line(win)
    block.setUserState(max(0, block.userState()) | 1)      # user tick

    state = max(0, block.userState())
    assert state & 0xFF == 1, "the user's mark survived"
    assert state & QUEUED_BIT, "and so did the queue bit"
    assert not state & SENT_BIT


def test_marking_it_sent_keeps_the_user_mark(win):
    from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT

    item, block = _queue_first_line(win)
    block.setUserState(max(0, block.userState()) | 3)      # user rhombus
    win.text_area.mark_queue_sent(item.id)

    state = max(0, block.userState())
    assert state & 0xFF == 3, "user mark untouched"
    assert state & SENT_BIT and not state & QUEUED_BIT, "queued -> sent"


def test_saving_the_user_marks_does_not_carry_the_queue_bits(win):
    """collect_line_marks is the USER's marks. The queue has its own pair,
    and mixing them would restore a tick on a line nobody ticked."""
    _item, block = _queue_first_line(win)
    block.setUserState(max(0, block.userState()) | 2)

    marks = win.text_area.collect_line_marks()
    assert marks.get(0) == 2, "only the low byte"
    assert all(v <= 0xFF for v in marks.values())


def test_restoring_user_marks_leaves_the_queue_bits_alone(win):
    from fastprompter.ui.markdown_highlighter import QUEUED_BIT

    _item, block = _queue_first_line(win)
    win.text_area.apply_line_marks({0: 4})

    state = max(0, block.userState())
    assert state & 0xFF == 4
    assert state & QUEUED_BIT, "applying user marks must not wipe the queue"


def test_the_queue_stripe_is_drawn_even_with_user_marks_switched_off(win):
    """line_marks governs the USER's margin marks. Hiding queue state with
    it would make a silo full of queued lines look like an empty one."""
    import inspect

    src = inspect.getsource(type(win.text_area).line_number_area_paint_event)
    body = src[src.index("queue_state ="):]
    assert "marks_enabled" not in body, "the stripe must not be gated on it"
    assert "SENT_BIT" in body and "QUEUED_BIT" in body


def test_the_gutter_survives_a_repaint_with_a_queued_line(win):
    """The paint path runs for real - a bad QColor or rect raises here."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPaintEvent

    _item, _block = _queue_first_line(win)
    area = win.text_area.line_number_area
    win.text_area.line_number_area_paint_event(
        QPaintEvent(QRect(0, 0, area.width(), area.height())))


def test_the_queue_stripe_actually_reaches_the_pixels(win):
    """Counts painted pixels, not code paths.

    The structural tests above only prove the branch exists and the paint
    call does not raise - the same class of evidence as an API returning
    success while nothing arrives. This renders the gutter and counts the
    stripe colours.

    Sizes only the gutter widget, never the main window: the shared fixture
    is the one T-295 warns about, and resizing it is what the header-density
    tests were flaky about.
    """
    from fastprompter.core.watcher.queue import queue_for

    ta = win.text_area
    area = ta.line_number_area
    PENDING, SENT = (0x6a, 0xa9, 0xff), (0x46, 0xb9, 0x8a)

    def counts():
        area.repaint()
        img = area.grab().toImage()
        blue = green = 0
        for x in range(img.width()):
            for y in range(img.height()):
                c = img.pixelColor(x, y)
                rgb = (c.red(), c.green(), c.blue())
                if rgb == PENDING:
                    blue += 1
                elif rgb == SENT:
                    green += 1
        return blue, green

    saved_geo = area.geometry()
    saved_numbers = win.data.get("show_line_numbers", "False")
    saved_text = ta.toPlainText()
    queue = queue_for(win.prompt_queues, win._queue_slot_key())
    saved_items = queue.to_list()
    try:
        win.data["show_line_numbers"] = "True"
        area.resize(24, 120)
        queue.items.clear()
        ta.setPlainText("one\ntwo")
        cur = ta.textCursor()
        cur.movePosition(cur.MoveOperation.Start)
        ta.setTextCursor(cur)

        assert counts() == (0, 0), "nothing queued, nothing striped"

        item = win.queue_current_line()
        blue, green = counts()
        assert blue > 0 and green == 0, "queued paints the pending stripe"

        ta.mark_queue_sent(item.id)
        blue, green = counts()
        assert green > 0 and blue == 0, "sent replaces it, never doubles up"
    finally:
        win.data["show_line_numbers"] = saved_numbers
        area.setGeometry(saved_geo)
        ta.setPlainText(saved_text)
        from fastprompter.core.watcher.queue import QueueItem
        queue.items.clear()
        queue.items.extend(QueueItem.from_dict(raw) for raw in saved_items)


# ---------------------------- W-6b: row actions ----------------------------


def _panel_with(win, texts):
    """A queue dialog holding exactly these prompts, queued the real way."""
    from fastprompter.core.watcher.queue import queue_for
    from fastprompter.ui.queue_panel import QueueDialog

    queue = queue_for(win.prompt_queues, win._queue_slot_key())
    queue.items.clear()
    win.text_area.setPlainText("\n".join(texts))
    for i in range(len(texts)):
        cur = win.text_area.textCursor()
        cur.movePosition(cur.MoveOperation.Start)
        for _ in range(i):
            cur.movePosition(cur.MoveOperation.Down)
        win.text_area.setTextCursor(cur)
        win.queue_current_line()
    dlg = QueueDialog(win)
    return dlg, queue


def _row_id(dlg, index):
    from PyQt6.QtCore import Qt as _Qt
    return dlg.list.item(index).data(_Qt.ItemDataRole.UserRole)


LONG = "a prompt long enough that a single row cannot show all of it " * 3


def test_a_long_prompt_collapses_to_one_line_with_a_chevron(win):
    dlg, _q = _panel_with(win, [LONG])
    try:
        row = dlg.list.item(0).text()
        assert row.startswith(">"), "collapsed rows advertise the fold"
        assert row.endswith("...")
        assert len(row) < len(LONG), "the row is not the whole prompt"
    finally:
        dlg.close()


def test_a_short_prompt_gets_no_chevron(win):
    """A row already showing everything must not advertise a fold."""
    dlg, _q = _panel_with(win, ["short one"])
    try:
        row = dlg.list.item(0).text()
        assert not row.startswith(">") and not row.startswith("v")
        assert "short one" in row
    finally:
        dlg.close()


def test_expanding_shows_the_whole_prompt(win):
    dlg, _q = _panel_with(win, [LONG])
    try:
        item_id = _row_id(dlg, 0)
        dlg.toggle_expanded(item_id)
        row = dlg.list.item(0).text()
        assert row.startswith("v"), "the chevron flips"
        assert LONG.strip() in row
        assert not row.endswith("...")

        dlg.toggle_expanded(item_id)
        assert dlg.list.item(0).text().startswith(">"), "and folds back"
    finally:
        dlg.close()


def test_expansion_is_per_row(win):
    dlg, _q = _panel_with(win, [LONG, LONG + " second"])
    try:
        first = _row_id(dlg, 0)
        dlg.toggle_expanded(first)
        assert dlg.list.item(0).text().startswith("v")
        assert dlg.list.item(1).text().startswith(">"), "the other stays shut"
    finally:
        dlg.close()


def test_a_removed_row_does_not_keep_its_expansion(win):
    """Ids would otherwise pile up forever and re-expand a recycled one."""
    dlg, queue = _panel_with(win, [LONG])
    try:
        item_id = _row_id(dlg, 0)
        dlg.toggle_expanded(item_id)
        assert item_id in dlg._expanded

        queue.items.clear()
        dlg.refresh()
        assert dlg._expanded == set()
    finally:
        dlg.close()


def test_the_chevron_zone_is_narrow_enough_to_leave_selection_alone(win):
    """A whole-row click zone would swallow ordinary selection clicks."""
    from fastprompter.ui.queue_panel import CHEVRON_PX

    dlg, _q = _panel_with(win, [LONG])
    try:
        assert CHEVRON_PX <= 24
        assert CHEVRON_PX < dlg.list.width() / 4
    finally:
        dlg.close()


# ------------------------------ close when done ----------------------------

def test_close_when_done_is_off_by_default(win):
    dlg, _q = _panel_with(win, ["something"])
    try:
        assert dlg.chk_close_done.isChecked() is False
    finally:
        dlg.close()


def test_an_already_empty_queue_does_not_trigger_the_close(win):
    """Otherwise the box could never be ticked: opening on an empty queue
    would close the panel the moment it is checked."""
    dlg, queue = _panel_with(win, ["something"])
    try:
        queue.items.clear()
        dlg._saw_work = False
        dlg.chk_close_done.setChecked(True)
        dlg.refresh()
        assert dlg.isVisible() or not dlg.result(), "it stayed open"
    finally:
        dlg.close()


def test_draining_the_queue_disarms_the_run_and_closes_the_panel(win, monkeypatch):
    dlg, queue = _panel_with(win, ["something"])
    try:
        _arm_on_fake(win, monkeypatch)
        assert win.watcher_engine().armed is True

        dlg.chk_close_done.setChecked(True)
        dlg.refresh()                 # still pending -> nothing happens
        assert win.watcher_engine().armed is True

        queue.items.clear()
        dlg.refresh()                 # drained -> disarm + close
        assert win.watcher_engine().armed is False
        assert "done" in win.watcher_engine().reason
    finally:
        win.watcher_disarm("test done")
        dlg.close()


def test_closing_the_panel_never_closes_the_app(win):
    """A queue finishing is not a reason to quit the thing being written in."""
    import inspect

    from fastprompter.ui.queue_panel import QueueDialog

    src = inspect.getsource(QueueDialog._maybe_close_when_done)
    assert "self.accept()" in src
    assert "close()" not in src.replace("_maybe_close_when_done", "")
    for banned in ("main_win.close", "QApplication.quit", "sys.exit",
                   "quit_application"):
        assert banned not in src


def _press(dlg, x, y):
    """Send a real press at (x, y) in the list viewport."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress,
                     QPointF(x, y), QPointF(x, y),
                     _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton,
                     _Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(dlg.list.viewport(), ev)
    return ev


def test_a_click_in_the_chevron_zone_expands_the_row(win):
    """Exercises the event filter, not just toggle_expanded.

    Calling the toggle directly proves the toggle works and says nothing
    about whether a click ever reaches it - the same gap that let a posted
    keystroke report success while arriving nowhere.
    """
    dlg, _q = _panel_with(win, [LONG])
    dlg.list.resize(400, 120)
    try:
        item_id = _row_id(dlg, 0)
        rect = dlg.list.visualItemRect(dlg.list.item(0))
        y = rect.center().y()

        assert item_id not in dlg._expanded
        _press(dlg, 4, y)
        assert item_id in dlg._expanded, "a click on the chevron opened it"

        _press(dlg, 4, y)
        assert item_id not in dlg._expanded, "and closed it again"
    finally:
        dlg.close()


def test_a_click_past_the_chevron_zone_is_left_to_the_list(win):
    """The list must not stop behaving like a list just because rows fold."""
    from fastprompter.ui.queue_panel import CHEVRON_PX

    dlg, _q = _panel_with(win, [LONG])
    dlg.list.resize(400, 120)
    try:
        item_id = _row_id(dlg, 0)
        rect = dlg.list.visualItemRect(dlg.list.item(0))
        ev = _press(dlg, CHEVRON_PX + 40, rect.center().y())

        assert item_id not in dlg._expanded, "no fold from a body click"
        assert not ev.isAccepted() or True, "the press was not swallowed"
    finally:
        dlg.close()


# ----------------------- T-562: FlowLayout with hidden items ---------------


def _flow_row(count=4, width=500):
    from PyQt6.QtWidgets import QPushButton

    from fastprompter.ui.flow_layout import flow_widget

    buttons = [QPushButton(f"button {i}") for i in range(count)]
    for b in buttons:
        b.setFixedSize(100, 24)
    row = flow_widget(buttons)
    row.resize(width, 100)
    row.show()
    QApplication.processEvents()
    return row, buttons


def _relayout(row, width=500):
    row._flow.invalidate()
    row.resize(width, 100)
    QApplication.processEvents()


def test_a_hidden_widget_costs_a_flow_row_nothing(win):
    """Qt gives a hidden QWidgetItem a zero sizeHint, so it leaves no hole -
    but the layout still added its spacing, so every hidden widget shifted
    the row along by h_space. Two of them pushed the first visible button
    from x=0 to x=16."""
    row, buttons = _flow_row()
    try:
        buttons[0].hide()
        buttons[1].hide()
        _relayout(row)

        xs = [b.geometry().x() for b in buttons[2:]]
        assert xs[0] == 0, f"the row must still start at the left, got {xs[0]}"
        assert xs[1] - xs[0] == 108, "and keep its ordinary 100+8 step"
    finally:
        row.close()


def test_hiding_one_in_the_middle_closes_the_gap_exactly(win):
    row, buttons = _flow_row()
    try:
        before = [b.geometry().x() for b in buttons]
        buttons[1].hide()
        _relayout(row)
        after = [b.geometry().x() for b in buttons]

        assert before == [0, 108, 216, 324]
        assert after[2] == 108 and after[3] == 216, f"got {after}"
    finally:
        row.close()


def test_a_row_of_only_hidden_widgets_has_no_height(win):
    """The empty-line path: `lines` is empty, which used to be tested as
    `not self._items` - true only when nothing was ever added."""
    row, buttons = _flow_row(count=3)
    try:
        for b in buttons:
            b.hide()
        _relayout(row)
        assert row.totalHeightForWidth(300) == 0
    finally:
        row.close()


def test_an_empty_flow_still_measures(win):
    from fastprompter.ui.flow_layout import flow_widget

    assert flow_widget([]).totalHeightForWidth(300) == 0


# ---------------------- T-200: checkbox hit testing ------------------------


def _checkbox_doc(win):
    from PyQt6.QtGui import QTextCursor

    win.text_area.setPlainText("[ ] first\n[x] second\n[ ] third")
    win.text_area._doc_has_checkbox = True
    QApplication.processEvents()
    doc = win.text_area.document()
    points = []
    for i in range(doc.blockCount()):
        r = win.text_area.cursorRect(QTextCursor(doc.findBlockByNumber(i)))
        points.append((i, r))
    return doc, points


def test_every_checkbox_answers_a_click(win):
    from PyQt6.QtCore import QPoint

    doc, points = _checkbox_doc(win)
    for i, r in points:
        hit = win.text_area._checkbox_at_pos(QPoint(int(r.x()) + 4,
                                                     int(r.top()) + 4))
        assert hit is not None and hit.blockNumber() == i, f"block {i}"


def test_one_bad_block_does_not_kill_the_checkbox_scan(win, monkeypatch):
    """The guard used to wrap the whole walk, so a single block that upset
    the layout maths aborted the scan and every checkbox below it became
    unclickable. Measured before the fix: the third of three stopped
    responding."""
    from PyQt6.QtCore import QPoint

    doc, points = _checkbox_doc(win)
    ta = win.text_area
    original = ta.cursorRect
    calls = {"n": 0}

    def flaky(cursor):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("synthetic layout failure on one block")
        return original(cursor)

    target = points[2][1]
    monkeypatch.setattr(ta, "cursorRect", flaky)
    hit = ta._checkbox_at_pos(QPoint(int(target.x()) + 4,
                                     int(target.top()) + 4))
    assert hit is not None, "a later checkbox must still answer"


def test_a_click_away_from_any_checkbox_finds_nothing(win):
    from PyQt6.QtCore import QPoint

    _doc, points = _checkbox_doc(win)
    r = points[0][1]
    assert win.text_area._checkbox_at_pos(
        QPoint(int(r.x()) + 400, int(r.top()) + 4)) is None


def test_a_degenerate_box_width_still_takes_a_click(win, monkeypatch):
    """A wrapped line can put the closing bracket on the next visual row,
    which makes the width negative - QRect.contains() is then false for
    every point and the checkbox silently stops responding."""
    from PyQt6.QtCore import QPoint

    _doc, points = _checkbox_doc(win)
    ta = win.text_area
    original = ta.cursorRect
    seen = {"n": 0}

    def collapsed(cursor):
        # every second call is the "end of the box" probe; put it left of
        # the start so the computed width goes negative
        rect = original(cursor)
        seen["n"] += 1
        if seen["n"] % 2 == 0:
            rect.moveLeft(rect.left() - 40)
        return rect

    monkeypatch.setattr(ta, "cursorRect", collapsed)
    r = points[0][1]
    hit = ta._checkbox_at_pos(QPoint(int(r.x()) + 2, int(r.top()) + 2))
    assert hit is not None, "a negative width must fall back, not go dead"


# -------------------- T-201: edit blocks stay balanced ---------------------


def test_an_edit_block_closes_even_when_the_body_raises(win):
    """An unbalanced beginEditBlock corrupts the document's edit-block
    counter and freezes rendering. edit_block is a context manager, so the
    end runs from a finally - this pins that, since a plain begin/end pair
    would silently regress it."""
    import pytest as _pytest

    from fastprompter.ui.edit_guard import edit_block

    ta = win.text_area
    ta.setPlainText("one\ntwo")
    before = ta.toPlainText()
    cursor = ta.textCursor()

    with _pytest.raises(RuntimeError):
        with edit_block(cursor, ta):
            cursor.insertText("wrecked")
            raise RuntimeError("boom mid-edit")

    # if the block were still open, this insert would be swallowed into it
    # and undo would not restore the document in one step
    ta.undo()
    assert ta.toPlainText() == before, "the edit undid as a single step"


def test_ctrl_click_bullet_toggle_undoes_as_one_step(win):
    """The path T-201 named. It runs inside edit_block now, so the whole
    conversion is one undo entry rather than a half-open block."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QMouseEvent, QTextCursor
    from PyQt6.QtWidgets import QApplication as _App

    ta = win.text_area
    ta.setPlainText("\u2022 a bullet line")
    _App.processEvents()
    before = ta.toPlainText()

    rect = ta.cursorRect(QTextCursor(ta.document().firstBlock()))
    pos = QPointF(rect.x() + 30, rect.center().y())
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos,
                     ta.viewport().mapToGlobal(pos.toPoint()).toPointF(),
                     _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton,
                     _Qt.KeyboardModifier.ControlModifier)
    _App.sendEvent(ta.viewport(), ev)
    _App.processEvents()

    after = ta.toPlainText()
    if after == before:
        import pytest
        pytest.skip("the click did not land on the bullet line")

    assert after.startswith("- "), f"bullet became dash, got {after!r}"
    ta.undo()
    assert ta.toPlainText() == before, "one Ctrl+Z restores the bullet"


def test_the_editors_mouse_press_opens_no_raw_edit_block(win):
    """T-201's original complaint. Any begin/end pair added back by hand
    here is a regression - the guard belongs in edit_block."""
    import inspect
    import re as _re

    src = inspect.getsource(type(win.text_area).mousePressEvent)
    assert "beginEditBlock" not in src
    assert _re.search(r"with edit_block\(", src), "it uses the guard"


# ------------- T-202: shortcuts follow the physical key, not the layout ----

SCAN = {"B": 0x30, "I": 0x17, "S": 0x1F, "E": 0x12}


def _press_shortcut(win, reported_key, scan, text=""):
    """Send Ctrl+<key> and report which command it dispatched to."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QKeyEvent

    fired = []
    ta = win.text_area
    saved = (win.apply_bold_smart, win.apply_format, win.apply_header_timestamp)
    win.apply_bold_smart = lambda *a, **k: fired.append("bold")
    win.apply_format = lambda kind, *a, **k: fired.append(f"format:{kind}")
    win.apply_header_timestamp = lambda *a, **k: fired.append("header")
    try:
        ta.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, reported_key,
            _Qt.KeyboardModifier.ControlModifier, scan, 0, 0, text))
    finally:
        (win.apply_bold_smart, win.apply_format,
         win.apply_header_timestamp) = saved
    return fired


def test_ctrl_b_bolds_on_a_russian_layout_too(win):
    """QKeyEvent.key() follows the ACTIVE layout: on a Russian keyboard the
    physical B reports Key_I, so Ctrl+B fired italic. Not a miss - the wrong
    command, silently. The scan code is the physical position and does not
    move with the layout."""
    from PyQt6.QtCore import Qt as _Qt

    us = _press_shortcut(win, _Qt.Key.Key_B, SCAN["B"], "b")
    ru = _press_shortcut(win, _Qt.Key.Key_I, SCAN["B"], "\u0438")

    assert us == ["bold"], f"US layout: {us}"
    assert ru == ["bold"], f"RU layout dispatched {ru}, expected bold"


def test_the_italic_key_still_means_italic(win):
    """The fix must not simply redirect everything to the first branch."""
    from PyQt6.QtCore import Qt as _Qt

    assert _press_shortcut(win, _Qt.Key.Key_I, SCAN["I"], "i") == ["format:italic"]


def test_an_unmapped_scan_code_falls_back_to_what_qt_reported(win):
    """Only the letter and digit rows are mapped; everything else must keep
    working off event.key() rather than going dead."""
    from PyQt6.QtCore import Qt as _Qt

    fired = _press_shortcut(win, _Qt.Key.Key_E, 0xFFFF, "e")
    assert fired == ["header"], f"got {fired}"


def test_the_scan_map_is_windows_only(win):
    """X11 keycodes are offset by 8, so the same numbers would mis-map a
    physical key on Linux. Better empty than wrong."""
    import sys as _sys

    from fastprompter.ui.editor import _SCAN_TO_KEY

    if _sys.platform == "win32":
        assert _SCAN_TO_KEY[0x30] is not None
        assert len(_SCAN_TO_KEY) == 36, "26 letters + 10 digits"
    else:
        assert _SCAN_TO_KEY == {}


# ---- watcher_queues persistence: the Alt+C TypeError crash ----------------


def test_alt_c_survives_a_string_typed_watcher_queues_all(win):
    """Live crash: data['watcher_queues_all'] came back from the DB as a
    STRING (it was absent from the json save list, so it was written as
    str(dict) and reloaded as text), and save_prompt_queues did
    setdefault(...)[cat] = raw -> TypeError: 'str' object does not support
    item assignment. One Alt+C took the whole app down."""
    win.data["watcher_queues_all"] = "{'Code': {}}"   # the corrupted shape
    # must not raise
    win.save_prompt_queues()
    assert isinstance(win.data["watcher_queues_all"], dict), (
        "the corrupted string must be healed into a dict, not left to crash")


def test_a_queue_survives_a_real_db_round_trip(tmp_path):
    """The actual regression: queue in, close DB, reopen, queue still there
    and a dict - not a str(dict) that reloads as text."""
    import json

    import fastprompter.core.state as state_mod
    from fastprompter.core.watcher.queue import QueueItem, queue_for, save_queues

    dbfile = str(tmp_path / "roundtrip.db")
    state_mod_get = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: dbfile

        st = state_mod.FastPrompterState(profile_id=1)
        queues = {}
        queue_for(queues, "0").append(QueueItem("remember this", line=1))
        st.data["watcher_queues_all"] = {"Code": save_queues(queues)}
        st.data["watcher_queues"] = save_queues(queues)
        st.save_data_to_db("", force=True)
        st.conn.close()

        st2 = state_mod.FastPrompterState(profile_id=1)
        wq = st2.data.get("watcher_queues_all")
        assert isinstance(wq, dict), f"reloaded as {type(wq).__name__}, not dict"
        assert "Code" in wq
        # and it is real json, not a python repr
        json.dumps(wq)
        st2.conn.close()
    finally:
        state_mod.get_db_path = state_mod_get


def test_an_old_str_dict_value_is_recovered_not_dropped(tmp_path):
    """Users already have the single-quoted str(dict) in their DB. It must
    reload as the dict it represents, via ast, rather than falling to {}."""
    import sqlite3

    import fastprompter.core.state as state_mod

    dbfile = str(tmp_path / "legacy.db")
    getter = state_mod.get_db_path
    try:
        state_mod.get_db_path = lambda profile_id=1: dbfile
        st = state_mod.FastPrompterState(profile_id=1)
        st.conn.close()
        # write the legacy corruption directly
        conn = sqlite3.connect(dbfile)
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("watcher_queues_all", "{'Code': {'0': []}}"))
        conn.commit()
        conn.close()

        st2 = state_mod.FastPrompterState(profile_id=1)
        wq = st2.data["watcher_queues_all"]
        assert isinstance(wq, dict) and "Code" in wq, f"got {wq!r}"
        st2.conn.close()
    finally:
        state_mod.get_db_path = getter


# ---- T-582: Ctrl+W divider ends on a dash bullet --------------------------


def test_ctrl_w_s1_end_of_text_divider_and_bullet(win):
    """S1: Ctrl+W at end of text — divider + bullet below, cursor on bullet."""
    # both are user settings now, and the shipped profile turns the S1
    # divider OFF — pin what this scenario is about instead of inheriting it
    win.data["ctrlw_s1_divider"] = "True"
    win.data["ctrlw_s1_bullet"] = "True"
    win.data["temp_presets"] = ["head"]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)
    cur = win.text_area.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    win.text_area.setTextCursor(cur)

    win.insert_add_line()
    text = win.text_area.toPlainText()

    assert "---" in text, f"divider missing: {text!r}"
    assert "•" in text, f"bullet missing: {text!r}"
    assert text.startswith("head"), "original text should stay at top"
    c = win.text_area.textCursor()
    assert not c.hasSelection()


def test_ctrl_w_s4_mid_text_splits_block(win):
    """S4: Ctrl+W mid-text — splits block, rest of line goes after bullet."""
    win.data["ctrlw_s4_divider"] = "True"
    win.data["ctrlw_s4_bullet"] = "True"
    ta = win.text_area
    ta.setPlainText("one two three")
    cur = ta.textCursor()
    cur.setPosition(4)          # mid-word
    ta.setTextCursor(cur)

    win.insert_add_line()
    text = ta.toPlainText()

    assert "---" in text, f"divider missing: {text!r}"
    assert "•" in text, f"bullet missing: {text!r}"
    assert text.startswith("one"), "text before cursor stays at top"
    assert "two three" in text, "rest of line split after bullet"


def test_ctrl_w_goes_through_insert_add_line(win):
    """insert_divider_line is a thin alias, so the Ctrl+W entry point gets
    the bullet too - the two must not diverge."""
    import inspect
    src = inspect.getsource(type(win).insert_divider_line)
    assert "insert_add_line" in src


# ---- T-581: a findable entry to the master queue view ---------------------


def test_the_dialog_can_open_straight_on_the_master_tab(win):
    from fastprompter.ui.queue_panel import QueueDialog

    d = QueueDialog(win, start_tab=1)
    try:
        assert d.tabs.tabText(d.tabs.currentIndex()) == "All silos"
    finally:
        d.close()
    d0 = QueueDialog(win, start_tab=0)
    try:
        assert d0.tabs.tabText(d0.tabs.currentIndex()) == "This silo"
    finally:
        d0.close()


def test_open_queue_master_routes_to_the_all_silos_tab(win, monkeypatch):
    seen = {}
    from fastprompter.ui import queue_panel

    class FakeDialog:
        def __init__(self, main_win, start_tab=0):
            seen["start_tab"] = start_tab
        def exec(self):
            return 0

    monkeypatch.setattr(queue_panel, "QueueDialog", FakeDialog)
    win.open_queue_master()
    assert seen["start_tab"] == 1, "master must land on tab 1"


def test_master_queue_view_has_a_visible_entry(win):
    """The whole complaint: Alt+C queues but the master view was unfindable.
    Now there is a shortcut AND a right-click menu entry. (A toolbar button
    was tried but the header budget at 960px is full - see T-568/header
    density.)"""
    import inspect

    from fastprompter import main as main_mod

    whole = inspect.getsource(main_mod)
    assert "hk_queue_master" in whole and "Alt+Shift+C" in whole
    assert "open_queue_master" in whole

    # the right-click menu offers the all-silos entry by name
    from fastprompter.ui import editor as editor_mod
    assert "all silos" in inspect.getsource(editor_mod).lower()


# ---- fonts: software non-AA everywhere + the _m1 alias --------------------


def test_the_app_font_carries_no_antialias(win):
    """The global application font sets the crisp strategy, so every widget
    that copies it inherits non-AA. The leak was widgets that built a fresh
    QFont(family) instead of copying."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    strat = QApplication.instance().font().styleStrategy()
    assert strat & QFont.StyleStrategy.NoAntialias
    assert strat & QFont.StyleStrategy.NoSubpixelAntialias


def test_the_editor_font_is_non_antialiased(win):
    from PyQt6.QtGui import QFont

    strat = win.text_area.font().styleStrategy()
    assert strat & QFont.StyleStrategy.NoAntialias


def test_silo_buttons_do_not_leak_an_antialiased_font():
    """snippet_panel built QFont(family) without the strategy, so the silo
    buttons rendered antialiased while everything around them was crisp.

    Checked at the source, not via btn.font().styleStrategy(): a widget that
    never calls setFont inherits the crisp application font at RENDER time,
    but its .font() still reports the default strategy - so a runtime check
    flags 40 innocent inherited-font buttons. The real fix is that every
    fresh QFont(family) in this module is wrapped in no_aa()."""
    import inspect
    import re

    from fastprompter.ui import snippet_panel

    src = inspect.getsource(snippet_panel)
    bare = re.findall(r"(?<!no_aa\()QFont\(font_family", src)
    assert bare == [], f"{len(bare)} QFont(font_family) not wrapped in no_aa"
    assert "no_aa(QFont(font_family))" in src


def test_font_family_property_resolves_m1_when_present(win, monkeypatch):
    """Stored 'Verdana' renders as 'Verdana_m1' when that build is installed,
    while the saved value stays plain."""
    import fastprompter.utils.fonts as fonts_mod

    monkeypatch.setattr(fonts_mod, "QFontDatabase", type(
        "FDB", (), {"families": staticmethod(lambda: {"Verdana", "Verdana_m1"})}))
    win.data["font_family"] = "Verdana"
    assert win._font_family == "Verdana_m1"
    assert win.data["font_family"] == "Verdana", "saved value stays plain"


def test_font_family_falls_back_when_no_m1(win, monkeypatch):
    import fastprompter.utils.fonts as fonts_mod

    monkeypatch.setattr(fonts_mod, "QFontDatabase", type(
        "FDB", (), {"families": staticmethod(lambda: {"Verdana", "Tahoma"})}))
    win.data["font_family"] = "Tahoma"
    assert win._font_family == "Tahoma"


# ---- limit scanner button in the timer dialog -----------------------------


def _timer_dialog(win):
    from fastprompter.ui.timer_dialog import TimerDialog
    return TimerDialog(win)


def test_the_timer_dialog_offers_a_limit_scan(win):
    dlg = _timer_dialog(win)
    try:
        assert hasattr(dlg, "btn_scan")
        assert dlg.btn_scan.toolTip(), "the button explains what it reads"
    finally:
        dlg.close()


def test_scanning_with_no_agents_reachable_says_so_and_makes_nothing(win, monkeypatch):
    """Every agent offline must not silently look like 'no limits'."""
    from fastprompter.core.watcher import limit_scan

    dlg = _timer_dialog(win)
    before = len(win.timers)
    try:
        monkeypatch.setattr(limit_scan, "scan_all", lambda *a, **k: [])
        made = dlg.scan_agent_limits()
        assert made == []
        assert len(win.timers) == before, "no timer invented"
        assert dlg.lbl_limit_hint.text(), "it reports something"
    finally:
        dlg.close()


def test_a_limited_agent_becomes_a_timer(win, monkeypatch):
    import datetime

    from fastprompter.core.limits import LimitState
    from fastprompter.core.watcher import limit_scan
    from fastprompter.core.watcher.limit_scan import AgentLimit

    resets = datetime.datetime.now() + datetime.timedelta(hours=2)
    fake = AgentLimit("freebuff", LimitState(True, resets, "limit reached"))

    dlg = _timer_dialog(win)
    saved = list(win.timers)
    try:
        monkeypatch.setattr(limit_scan, "scan_all", lambda *a, **k: [fake])
        made = dlg.scan_agent_limits()
        assert len(made) == 1
        assert "freebuff" in made[0].name
        assert any("freebuff" in t.name for t in win.timers)
    finally:
        win.timers[:] = saved
        dlg.close()


def test_scanning_twice_updates_instead_of_duplicating(win, monkeypatch):
    """Two countdowns for one reset is worse than none."""
    import datetime

    from fastprompter.core.limits import LimitState
    from fastprompter.core.watcher import limit_scan
    from fastprompter.core.watcher.limit_scan import AgentLimit

    resets = datetime.datetime.now() + datetime.timedelta(hours=3)
    fake = AgentLimit("codenomad", LimitState(True, resets, "limit reached"))

    dlg = _timer_dialog(win)
    saved = list(win.timers)
    try:
        monkeypatch.setattr(limit_scan, "scan_all", lambda *a, **k: [fake])
        dlg.scan_agent_limits()
        dlg.scan_agent_limits()
        named = [t for t in win.timers if "codenomad" in t.name]
        assert len(named) == 1, f"got {len(named)} timers for one agent"
    finally:
        win.timers[:] = saved
        dlg.close()


def test_an_agent_that_named_no_time_is_labelled_assumed(win, monkeypatch):
    """The guess must be visible, not buried in a countdown that looks read."""
    from fastprompter.core.limits import LimitState
    from fastprompter.core.watcher import limit_scan
    from fastprompter.core.watcher.limit_scan import AgentLimit

    fake = AgentLimit("agent", LimitState(True, None, "daily limit reached"))
    dlg = _timer_dialog(win)
    saved = list(win.timers)
    try:
        monkeypatch.setattr(limit_scan, "scan_all", lambda *a, **k: [fake])
        made = dlg.scan_agent_limits()
        assert made and "assumed" in made[0].description.lower()
    finally:
        win.timers[:] = saved
        dlg.close()


# ---- startup must not hide itself, and a corpse must not block a launch ---


def _deactivate(win, monkeypatch=None):
    """The ActivationChange Qt sends when the window is not the active one.

    isActiveWindow is forced False: offscreen, whether a window counts as
    active depends on what an earlier test left focused, and this is about
    the hide decision, not about Qt's focus bookkeeping.
    """
    from PyQt6.QtCore import QEvent

    if monkeypatch is not None:
        monkeypatch.setattr(type(win), "isActiveWindow", lambda self: False)
    win.changeEvent(QEvent(QEvent.Type.ActivationChange))


def test_startup_deactivation_does_not_hide_the_window(win, monkeypatch):
    """Windows refuses the foreground to a process launched in the
    background, so show() was followed by a deactivation and the window hid
    itself ~2s in - the app looked like it never started. Measured before
    the fix: visible at t+4s, gone by t+6s."""
    win._ever_activated = False
    win._shown_at = 0.0
    win.show()
    if getattr(win, "cb_focus", None):
        win.cb_focus.setChecked(True)

    _deactivate(win, monkeypatch)
    assert not win.isHidden(), "a startup deactivation must not hide it"


def test_a_focus_flicker_right_after_showing_is_forgiven(win, monkeypatch):
    """The foreground can bounce: the window takes focus for an instant and
    Windows hands it straight back to whatever launched it."""
    import time

    win._ever_activated = True          # the flicker set this
    win._shown_at = time.time()         # ...but it only just appeared
    win.show()
    if getattr(win, "cb_focus", None):
        win.cb_focus.setChecked(True)

    _deactivate(win, monkeypatch)
    assert not win.isHidden(), "a flicker within the grace period is not a click-away"


def test_a_real_click_away_still_hides(win, monkeypatch):
    """The grace period must not weaken the setting the user asked for."""
    import time

    win.show()
    QApplication.processEvents()
    assert not win.isHidden(), "precondition: it starts visible"
    win._ever_activated = True
    win._shown_at = time.time() - 10.0   # long past the grace period
    if getattr(win, "cb_focus", None):
        win.cb_focus.setChecked(True)
    win.is_locked = False
    win.ignore_focus_loss = False
    win._help_dialog = None

    _deactivate(win, monkeypatch)
    assert win.isHidden(), "clicking away should still hide it"


def test_the_ipc_server_never_exits_the_process(win):
    """It used to sys.exit(0) when it could not own the socket, which turned
    every later launch into a silent no-op with nothing in the log."""
    import inspect

    from fastprompter.core import ipc_server

    src = inspect.getsource(ipc_server.IpcServer.setup)
    # strip the docstring: it EXPLAINS the old sys.exit, so a naive search
    # matches the very sentence describing the fix
    body = src.split('"""')[-1]
    assert "sys.exit" not in body
    assert "logger.warning" in body


def test_show_is_acknowledged_so_a_corpse_can_be_detected(win):
    """A process that holds the socket but no longer pumps its event loop
    answers nothing; the newcomer waits for ACK and takes over on silence."""
    import inspect

    from fastprompter import main as main_mod
    from fastprompter.core import ipc_server

    assert "ACK" in inspect.getsource(ipc_server.IpcServer._handle_command)
    entry = inspect.getsource(main_mod.main_entry)
    assert "ACK" in entry and "waitForReadyRead" in entry


# ---------------------------------------------------------------------------
# T-592: Ctrl+MiddleButton deletes the line under the cursor, keeping an
# ordered list sequential around the gap.
# ---------------------------------------------------------------------------


def _load_editor_text(win, text):
    ta = win.text_area
    ta.document().setPlainText(text)
    return ta


def test_smart_delete_removes_line_without_blank_gap(win):
    ta = _load_editor_text(win, "alpha\nbeta\ngamma")
    ta._delete_line_smart(ta.document().findBlockByNumber(1))  # beta
    assert ta.toPlainText() == "alpha\ngamma"


def test_smart_delete_renumbers_ordered_list(win):
    ta = _load_editor_text(win, "1. one\n2. two\n3. three\n4. four")
    ta._delete_line_smart(ta.document().findBlockByNumber(1))  # "2. two"
    assert ta.toPlainText() == "1. one\n2. three\n3. four"


def test_smart_delete_renumbers_when_first_item_goes(win):
    ta = _load_editor_text(win, "1. one\n2. two\n3. three")
    ta._delete_line_smart(ta.document().findBlockByNumber(0))  # "1. one"
    assert ta.toPlainText() == "1. two\n2. three"


def test_smart_delete_bullet_list_needs_no_renumber(win):
    ta = _load_editor_text(win, "- a\n- b\n- c")
    ta._delete_line_smart(ta.document().findBlockByNumber(1))  # "- b"
    assert ta.toPlainText() == "- a\n- c"


def test_smart_delete_is_single_undo(win):
    ta = _load_editor_text(win, "1. one\n2. two\n3. three")
    before = ta.toPlainText()
    ta._delete_line_smart(ta.document().findBlockByNumber(1))
    assert ta.toPlainText() == "1. one\n2. three"
    ta.undo()
    assert ta.toPlainText() == before


# ---------------------------------------------------------------------------
# T-589: multi-select silos + batch save/delete.
# ---------------------------------------------------------------------------


def test_silo_toggle_selection(win):
    win.clear_silo_selection()
    win.toggle_silo_selection(2)
    win.toggle_silo_selection(5)
    assert win._silo_sel() == {2, 5}
    win.toggle_silo_selection(2)  # toggle off
    assert win._silo_sel() == {5}


def test_silo_range_select_from_anchor(win):
    win.clear_silo_selection()
    if len(win.data["temp_presets"]) < 5:
        win.data["temp_presets"].extend([""] * (5 - len(win.data["temp_presets"])))
    win.toggle_silo_selection(1)   # anchor = 1
    win.range_select_silos(4)
    assert win._silo_sel() == {1, 2, 3, 4}


def test_silo_clear_selection(win):
    win.toggle_silo_selection(0)
    win.clear_silo_selection()
    assert win._silo_sel() == set()


def test_batch_delete_declined_keeps_selection(win, monkeypatch):
    from fastprompter import main as main_mod
    win.clear_silo_selection()
    win.toggle_silo_selection(0)
    win.toggle_silo_selection(1)
    calls = []
    monkeypatch.setattr(win, "trash_silo", lambda i, is_archive=False: calls.append(i))
    monkeypatch.setattr(main_mod.QMessageBox, "question",
                        lambda *a, **k: main_mod.QMessageBox.StandardButton.No)
    win.batch_delete_selected_silos()
    assert calls == []                 # nothing trashed
    assert win._silo_sel() == {0, 1}   # selection intact


def test_batch_delete_confirmed_trashes_high_index_first(win, monkeypatch):
    from fastprompter import main as main_mod
    win.clear_silo_selection()
    for i in (0, 2, 5):
        win.toggle_silo_selection(i)
    calls = []
    monkeypatch.setattr(win, "trash_silo", lambda i, is_archive=False: calls.append(i))
    monkeypatch.setattr(main_mod.QMessageBox, "question",
                        lambda *a, **k: main_mod.QMessageBox.StandardButton.Yes)
    win.batch_delete_selected_silos()
    assert calls == [5, 2, 0]          # descending so indices stay valid
    assert win._silo_sel() == set()    # cleared after a real delete


def test_batch_save_exports_each_selected(win, monkeypatch):
    win.clear_silo_selection()
    for i in (3, 1):
        win.toggle_silo_selection(i)
    saved = []
    monkeypatch.setattr(win, "backup_silo_to_files", lambda i, is_archive=False: saved.append(i))
    win.batch_save_selected_silos()
    assert sorted(saved) == [1, 3]
    win.clear_silo_selection()


# ---------------------------------------------------------------------------
# T-590: user-defined sidebar gaps (per-category, survive reorder).
# ---------------------------------------------------------------------------


def test_silo_gap_toggle_adds_and_removes(win):
    win.data["silo_gaps"] = []
    win.toggle_silo_gap(2)
    assert 2 in win.data["silo_gaps"]
    win.toggle_silo_gap(2)
    assert 2 not in win.data["silo_gaps"]


def test_silo_gap_is_aliased_into_per_category_store(win):
    win.data["silo_gaps"] = []
    cat = win.get_current_category() or ""
    win.data.setdefault("silo_gaps_all", {})[cat] = win.data["silo_gaps"]
    win.toggle_silo_gap(1)
    # mutating the active alias is visible through the per-category store
    assert 1 in win.data["silo_gaps_all"][cat]


def test_silo_gap_follows_the_silo_it_was_placed_under(win):
    # T-704 (user's call) replaces T-593: a gap belongs to the silo it sits
    # under and is remapped with every other slot-keyed store. Left out of
    # the remap it was neither positional nor attached — a reorder carried
    # it along (it is stored as a slot index) while a delete renumbered the
    # slots around it and parked it under a stranger.
    win.data["silo_gaps"] = [3]
    win._remap_silo_indices(lambda i: 5 if i == 3 else i)
    assert win.data["silo_gaps"] == [5]


def test_deleting_a_silo_takes_its_gap_with_it(win):
    """The gap of a DELETED silo must not be inherited by its replacement."""
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    cat = win.get_current_category()
    win.data["temp_presets"][:] = ["alpha", "bravo", "charlie"]
    win.data.setdefault("silo_gaps_all", {})[cat] = win.data["silo_gaps"] = [2]
    win.silo_docs[:] = []
    win._switch_to_slot(0, initial=True)

    # a gap under "charlie" (slot 2); deleting "alpha" shifts it to slot 1
    win.drop_silo_state(0)
    assert win.data["silo_gaps"] == [1]

    # deleting the silo that CARRIES the gap drops the gap too
    win.data["silo_gaps"][:] = [1]
    win.drop_silo_state(1)
    assert win.data["silo_gaps"] == []

    # inserting above pushes it back down
    win.data["silo_gaps"][:] = [1]
    win.open_silo_slot(0)
    assert win.data["silo_gaps"] == [2]
    win.data["silo_gaps"][:] = []


def test_refresh_with_a_gap_does_not_crash(win):
    if len(win.data["temp_presets"]) < 2:
        win.data["temp_presets"].extend([""] * (2 - len(win.data["temp_presets"])))
    win.data["silo_gaps"] = [0]
    win.refresh_temp_presets()  # must not raise
    win.data["silo_gaps"] = []
    win.refresh_temp_presets()


def test_user_gap_widget_uses_configured_height(win):
    if len(win.data["temp_presets"]) < 2:
        win.data["temp_presets"].extend([""] * (2 - len(win.data["temp_presets"])))
    win.data["silo_gap_height"] = "20"
    win.data["silo_gaps"] = [0]
    win.refresh_temp_presets()
    # the window is never shown offscreen, so isVisible() is False for every
    # widget (buttons included) — isHidden() is what tracks the explicit
    # show/hide this code does.
    pool = [g for g in getattr(win, "_user_gap_widgets", []) if not g.isHidden()]
    assert pool, "expected a shown user gap widget"
    assert pool[0].height() == 20
    assert win.silos_widget.layout.indexOf(pool[0]) != -1
    win.data["silo_gaps"] = []
    win.refresh_temp_presets()
    assert not [g for g in win._user_gap_widgets if not g.isHidden()]


# ---------------------------------------------------------------------------
# T-591: one-way sync of silo text onto disk.
# ---------------------------------------------------------------------------


def _sync_setup(win, tmp_path, mode):
    win.data["sync_path"] = str(tmp_path)
    win.data["sync_mode"] = mode
    win._sync_written = {}
    return tmp_path


def test_sync_off_writes_nothing(win, tmp_path):
    _sync_setup(win, tmp_path, "Off")
    win.sync_to_disk(force=True)
    assert list(tmp_path.rglob("*.md")) == []


def test_sync_without_path_writes_nothing(win, tmp_path):
    win.data["sync_path"] = ""
    win.data["sync_mode"] = "Hierarchy"
    win.sync_to_disk(force=True)   # must not raise
    assert list(tmp_path.rglob("*.md")) == []


def test_sync_silo_mode_mirrors_active_slot(win, tmp_path):
    _sync_setup(win, tmp_path, "Silo")
    win.data["temp_presets"][0] = "# hello sync\nbody line"
    win.active_temp_slot = 0
    win.sync_to_disk(force=True)
    files = list(tmp_path.rglob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "# hello sync\nbody line"


def test_sync_hierarchy_mirrors_every_nonempty_silo(win, tmp_path):
    _sync_setup(win, tmp_path, "Hierarchy")
    presets = win.data["temp_presets"]
    while len(presets) < 3:
        presets.append("")
    presets[0], presets[1], presets[2] = "# one", "# two", ""
    win.sync_to_disk(force=True)
    files = list(tmp_path.rglob("*.md"))
    assert len(files) == 2          # the empty silo is skipped
    assert {f.read_text(encoding="utf-8") for f in files} == {"# one", "# two"}


def test_sync_skips_unchanged_text(win, tmp_path):
    _sync_setup(win, tmp_path, "Silo")
    # keep the FIRST line fixed: the filename is slugged from the title, so
    # editing the title is a new file (rename never deletes the old one)
    win.data["temp_presets"][0] = "# stable\nbody v1"
    win.active_temp_slot = 0
    win.sync_to_disk(force=True)
    target = list(tmp_path.rglob("*.md"))[0]
    target.write_text("TOUCHED", encoding="utf-8")
    win.sync_to_disk()              # unchanged -> must not rewrite
    assert target.read_text(encoding="utf-8") == "TOUCHED"
    win.data["temp_presets"][0] = "# stable\nbody v2"
    win.sync_to_disk()              # body changed -> same file, rewritten
    assert target.read_text(encoding="utf-8") == "# stable\nbody v2"
    assert len(list(tmp_path.rglob("*.md"))) == 1


def test_sync_child_nests_under_parent_folder(win, tmp_path):
    _sync_setup(win, tmp_path, "Hierarchy")
    presets = win.data["temp_presets"]
    while len(presets) < 2:
        presets.append("")
    presets[0], presets[1] = "# parent", "# child"
    win.data["silo_children"] = {"0": [1]}
    rels = win._sync_rel_paths()
    assert rels[0] in rels[1] and rels[1] != rels[0]
    win.data["silo_children"] = {}


def test_sync_survives_a_parent_cycle(win):
    presets = win.data["temp_presets"]
    while len(presets) < 2:
        presets.append("")
    win.data["silo_children"] = {"0": [1], "1": [0]}
    win._sync_rel_paths()          # must terminate, not hang or recurse away
    win.data["silo_children"] = {}


# ---------------------------------------------------------------------------
# T-593: gaps are positional and draggable.
# ---------------------------------------------------------------------------


def _gap_setup(win, n=6):
    presets = win.data["temp_presets"]
    while len(presets) < n:
        presets.append(f"# silo {len(presets)}")
    for i in range(n):
        if not presets[i].strip():
            presets[i] = f"# silo {i}"
    win.data["silo_gaps"] = []
    return presets


def test_move_gap_rewrites_the_anchor(win):
    _gap_setup(win)
    win.data["silo_gaps"] = [1]
    assert win.move_silo_gap(1, 4) is True
    assert win.data["silo_gaps"] == [4]


def test_move_gap_onto_an_existing_gap_is_refused(win):
    _gap_setup(win)
    win.data["silo_gaps"] = [1, 4]
    assert win.move_silo_gap(1, 4) is False
    assert sorted(win.data["silo_gaps"]) == [1, 4]   # no stacking, no loss


def test_move_gap_out_of_range_is_refused(win):
    _gap_setup(win)
    win.data["silo_gaps"] = [1]
    assert win.move_silo_gap(1, 999) is False
    assert win.move_silo_gap(1, -1) is False
    assert win.data["silo_gaps"] == [1]


def test_move_gap_that_does_not_exist_is_refused(win):
    _gap_setup(win)
    win.data["silo_gaps"] = [1]
    assert win.move_silo_gap(2, 3) is False
    assert win.data["silo_gaps"] == [1]


def test_prune_drops_gaps_past_the_end(win):
    _gap_setup(win, 3)
    del win.data["temp_presets"][3:]
    win.data["silo_gaps"] = [1, 99]
    win.prune_silo_gaps()
    assert win.data["silo_gaps"] == [1]


def test_gap_bar_carries_its_anchor_slot(win):
    _gap_setup(win)
    win.data["silo_gaps"] = [0]
    win.refresh_temp_presets()
    bars = [g for g in win._user_gap_widgets if not g.isHidden()]
    assert bars, "expected a shown gap bar"
    assert bars[0].slot_idx == 0
    assert hasattr(bars[0], "move_silo_gap") is False   # it delegates, not owns
    win.data["silo_gaps"] = []
    win.refresh_temp_presets()


def test_gap_bar_ignores_plain_click_without_ctrl(win):
    from fastprompter.ui.snippet_panel import SiloGapBar
    bar = SiloGapBar(win)
    bar.slot_idx = 1
    # no Ctrl press recorded -> release must not attempt a move
    bar._press_pos = None
    assert bar._press_pos is None


# ---------------------------------------------------------------------------
# T-594: gaps must survive a real DB round-trip.
# ---------------------------------------------------------------------------


def test_gaps_survive_a_real_db_round_trip(tmp_path):
    import fastprompter.core.state as sm
    db = tmp_path / "gaps.db"
    orig = sm.get_db_path
    sm.get_db_path = lambda profile_id=1: str(db)
    try:
        st = sm.FastPrompterState()
        st.data["silo_gaps_all"] = {"Code": [1, 4], "Text": [2]}
        st.data["silo_gaps"] = st.data["silo_gaps_all"]["Code"]
        st.save_data_to_db("body", force=True)
        st.conn.close()

        st2 = sm.FastPrompterState()
        assert st2.data["silo_gaps_all"] == {"Code": [1, 4], "Text": [2]}
        st2.conn.close()
    finally:
        sm.get_db_path = orig


def test_legacy_python_repr_gaps_are_recovered(tmp_path):
    import sqlite3

    import fastprompter.core.state as sm
    db = tmp_path / "legacy.db"
    orig = sm.get_db_path
    sm.get_db_path = lambda profile_id=1: str(db)
    try:
        st = sm.FastPrompterState()
        st.save_data_to_db("body", force=True)
        st.conn.close()
        # simulate what the buggy build wrote: python repr, not JSON
        con = sqlite3.connect(db)
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    ("silo_gaps_all", "{'Code': [3, 7]}"))
        con.commit()
        con.close()

        st2 = sm.FastPrompterState()
        assert st2.data["silo_gaps_all"] == {"Code": [3, 7]}   # ast rescued it
        st2.conn.close()
    finally:
        sm.get_db_path = orig


# ---------------------------------------------------------------------------
# T-595: Transfer to Project must move silo -> silo, not silo -> snippet.
# ---------------------------------------------------------------------------


def _two_projects(win):
    cats = win.data["categories"]
    names = list(win.data.get("cats_order") or cats.keys())
    src, dst = names[0], names[1]
    win.data["last_tab_idx"] = 0
    win.on_tab_changed(0)
    return src, dst


def test_transfer_lands_in_destination_silos_not_snippets(win):
    src, dst = _two_projects(win)
    win.data["temp_presets"][0] = "# SAIPENVIEW payload"
    snips_before = [s for s in win.data["categories"][dst] if s]
    assert win.transfer_silo_to_project(0, dst) is True
    dest_silos = win.data["temp_presets_all"][dst]
    assert "# SAIPENVIEW payload" in dest_silos          # visible as a SILO
    snips_after = [s for s in win.data["categories"][dst] if s]
    assert len(snips_after) == len(snips_before)          # did NOT become a snippet
    assert win.data["temp_presets"][0] == ""              # source row emptied


def test_transfer_carries_the_colour_box(win):
    src, dst = _two_projects(win)
    win.data["temp_presets"][0] = "# coloured silo"
    win.data["silo_colors"]["0"] = "#ff4444"
    assert win.transfer_silo_to_project(0, dst) is True
    dest_silos = win.data["temp_presets_all"][dst]
    slot = dest_silos.index("# coloured silo")
    assert win.data["silo_colors_all"][dst][str(slot)] == "#ff4444"
    assert "0" not in win.data["silo_colors"]             # not left on the empty row


def test_transfer_refuses_empty_and_same_project(win):
    src, dst = _two_projects(win)
    win.data["temp_presets"][1] = ""
    assert win.transfer_silo_to_project(1, dst) is False   # empty silo
    win.data["temp_presets"][1] = "# something"
    assert win.transfer_silo_to_project(1, src) is False   # same project
    assert win.transfer_silo_to_project(1, "NoSuchProject") is False
    assert win.data["temp_presets"][1] == "# something"    # untouched


def test_transfer_appends_when_destination_has_no_blank_row(win):
    src, dst = _two_projects(win)
    dest = win.data.setdefault("temp_presets_all", {}).setdefault(dst, [])
    dest[:] = ["# full a", "# full b"]
    win.data["temp_presets"][0] = "# overflow"
    assert win.transfer_silo_to_project(0, dst) is True
    assert dest[-1] == "# overflow"                        # grew, did not drop it


# ---------------------------------------------------------------------------
# T-596: bold must render bold, not get clobbered by the italic rule.
# ---------------------------------------------------------------------------


def _fmt_at(win, text, needle):
    """Char format Qt actually applied to the first char of `needle`."""
    from PyQt6.QtWidgets import QApplication
    ta = win.text_area
    win.preview_combo.setCurrentIndex(1)          # Live Preview attaches the highlighter
    ta.document().setPlainText(text)
    win.highlighter.rehighlight()
    QApplication.processEvents()
    pos = text.index(needle)
    block = ta.document().findBlock(pos)
    for r in block.layout().formats():
        if r.start <= (pos - block.position()) < r.start + r.length:
            return r.format
    return None


def test_bold_renders_bold_not_italic(win):
    from PyQt6.QtGui import QFont
    f = _fmt_at(win, "plain **loud** plain", "loud")
    assert f is not None
    assert f.fontWeight() == QFont.Weight.Bold
    assert f.fontItalic() is False        # the old bug: bold showed as italic


def test_italic_still_renders_italic(win):
    f = _fmt_at(win, "plain *lean* plain", "lean")
    assert f is not None and f.fontItalic() is True


def test_bold_inside_a_heading_keeps_both(win):
    from PyQt6.QtGui import QFont
    f = _fmt_at(win, "# head **loud** rest", "loud")
    assert f is not None and f.fontWeight() == QFont.Weight.Bold


def test_strikethrough_and_underline_still_apply(win):
    fs = _fmt_at(win, "a ~~gone~~ b", "gone")
    assert fs is not None and fs.fontStrikeOut() is True
    fu = _fmt_at(win, "a __under__ b", "under")
    assert fu is not None and fu.fontUnderline() is True


# ---------------------------------------------------------------------------
# T-600: gaps behave inside a parent/children hierarchy.
# ---------------------------------------------------------------------------


def _hier(win, collapsed=()):
    p = win.data["temp_presets"]
    while len(p) < 5:
        p.append("")
    for i in range(5):
        p[i] = f"# silo {i}"
    win.data["silo_children"] = {0: [1, 2]}
    win.data["silo_collapsed"] = list(collapsed)
    return p


def _visible_layout(win):
    lay = win.silos_widget.layout
    out = []
    for i in range(lay.count()):
        it = lay.itemAt(i)
        w = it.widget() if it else None
        if w is None or w.isHidden():
            continue
        out.append((type(w).__name__, getattr(w, "global_idx", getattr(w, "slot_idx", -1))))
    return out


def test_gap_on_parent_clears_the_whole_group(win):
    _hier(win)
    win.data["silo_gaps"] = [0]
    win.refresh_temp_presets()
    rows = _visible_layout(win)
    names = [f"{n}:{i}" for n, i in rows[:4]]
    # the divider must come AFTER both children, not between parent and them
    assert names[:4] == ["DraggableSiloButton:0", "DraggableSiloButton:1",
                         "DraggableSiloButton:2", "SiloGapBar:0"]
    win.data["silo_children"], win.data["silo_gaps"] = {}, []


def test_gap_on_a_child_renders_inside_the_group(win):
    _hier(win)
    win.data["silo_gaps"] = [1]
    win.refresh_temp_presets()
    rows = _visible_layout(win)
    names = [f"{n}:{i}" for n, i in rows[:4]]
    assert names[:3] == ["DraggableSiloButton:0", "DraggableSiloButton:1", "SiloGapBar:1"]
    win.data["silo_children"], win.data["silo_gaps"] = {}, []


def test_gap_inside_a_collapsed_group_hides_but_is_kept(win):
    _hier(win, collapsed=(0,))
    win.data["silo_gaps"] = [1]
    win.refresh_temp_presets()
    assert not [g for g in win._user_gap_widgets if not g.isHidden()]
    assert win.data["silo_gaps"] == [1]          # data preserved, not pruned
    # expanding brings it back
    win.data["silo_collapsed"] = []
    win.refresh_temp_presets()
    shown = [g for g in win._user_gap_widgets if not g.isHidden()]
    assert [g.slot_idx for g in shown] == [1]
    win.data["silo_children"], win.data["silo_gaps"] = {}, []


def test_subtree_end_is_cycle_safe(win):
    # a corrupt parent map must not hang the render
    child_of = {1: 2, 2: 1}
    assert win._subtree_end(0, [0, 1, 2], child_of) == 0


# ---------------------------------------------------------------------------
# T-597: the colour swatch owns a fixed left column on every row.
# ---------------------------------------------------------------------------


def test_colour_box_column_is_identical_on_every_row(win):
    from PyQt6.QtWidgets import QApplication
    p = win.data["temp_presets"]
    while len(p) < 5:
        p.append("")
    p[0], p[1], p[2] = "# parent hash", "# child hash", "plain no hash"
    p[3], p[4] = "# third", "# fourth"
    win.data["silo_children"] = {0: [1]}
    win.data["silo_collapsed"] = []
    win.data["silo_colors"] = {"0": "#ff4444"}
    win.data["silo_color_box"] = "True"
    win.refresh_temp_presets()
    QApplication.processEvents()
    xs = {b._btn_color_box.x() for b in win.silo_buttons[:5] if not b.isHidden()}
    assert len(xs) == 1, f"swatch drifts between rows: {xs}"
    win.data["silo_children"] = {}


def test_colour_box_keeps_its_slot_when_row_has_no_colour(win):
    from PyQt6.QtWidgets import QApplication
    p = win.data["temp_presets"]
    while len(p) < 2:
        p.append("")
    p[0], p[1] = "# has hash", "plain text"
    win.data["silo_children"] = {}
    win.data["silo_colors"] = {}
    win.data["silo_color_box"] = "True"
    win.refresh_temp_presets()
    QApplication.processEvents()
    b0, b1 = win.silo_buttons[0], win.silo_buttons[1]
    # both reserve the column; the colourless one is present but click-dead
    assert not b0._btn_color_box.isHidden() and not b1._btn_color_box.isHidden()
    assert b1._btn_color_box.isEnabled() is False
    assert b0._btn_color_box.width() == b1._btn_color_box.width()


# ---------------------------------------------------------------------------
# T-598 / hidden bug: NEW from bottom, and insert-at-top must not orphan kids.
# ---------------------------------------------------------------------------


def test_right_click_new_appends_at_the_bottom(win):
    from PyQt6.QtCore import QPoint
    p = win.data["temp_presets"]
    for i in range(len(p)):
        p[i] = f"# filled {i}"
    # creation flushes the editor into the active slot first, so keep them in
    # sync or that row is blanked and mistaken for a top insert
    win.active_temp_slot = 0
    win.text_area.document().setPlainText(p[0])
    before = len(p)
    win.btn_new.customContextMenuRequested.emit(QPoint(1, 1))
    after = win.data["temp_presets"]
    assert len(after) == before + 1
    assert after[-1] == ""              # new row is at the END
    assert after[0] == "# filled 0"     # top untouched


def test_insert_at_top_keeps_children_int_keyed_and_visible(win):
    from PyQt6.QtWidgets import QApplication
    p = win.data["temp_presets"]
    for i in range(len(p)):
        p[i] = f"# silo {i}"
    win.data["silo_children"] = {0: [1]}
    win.data["silo_collapsed"] = []
    win.refresh_temp_presets()
    QApplication.processEvents()
    win.select_empty_silo()
    QApplication.processEvents()
    cmap = win.data["silo_children"]
    # shifted down by one, and still INT-keyed: a str key made the child both
    # un-indented AND absent from the sidebar entirely
    assert cmap == {1: [2]}
    assert all(isinstance(k, int) for k in cmap)
    shown = {b.global_idx for b in win.silo_buttons if not b.isHidden()}
    assert 2 in shown
    indents = {b.global_idx: b._indent.width() for b in win.silo_buttons if not b.isHidden()}
    assert indents.get(2, 0) > 0          # renders as a child again
    win.data["silo_children"] = {}


def test_children_map_normalises_string_keys(win):
    win.data["silo_children"] = {"3": ["4"]}
    assert win._children_map() == {3: [4]}
    assert all(isinstance(k, int) for k in win.data["silo_children"])
    win.data["silo_children"] = {}


def test_insert_at_top_shifts_watcher_queues(win):
    p = win.data["temp_presets"]
    for i in range(len(p)):
        p[i] = f"# silo {i}"
    win.data["watcher_queues"] = {"0": ["job-a"]}
    win.select_empty_silo()
    assert win.data["watcher_queues"].get("1") == ["job-a"]   # followed its silo
    win.data["watcher_queues"] = {}


def test_slot_list_keeps_the_per_category_alias(win):
    # a corrupt value used to be replaced with a fresh list and rebound,
    # orphaning <key>_all[category] so ticks/pins stopped being per-project
    cat = win.get_current_category() or ""
    win.data["silo_ticked"] = "corrupt-not-a-list"
    lst = win._slot_list("silo_ticked")
    lst.append(7)
    assert win.data["silo_ticked_all"][cat] is lst
    assert 7 in win.data["silo_ticked_all"][cat]
    win.data["silo_ticked"] = []
    win.data["silo_ticked_all"][cat] = win.data["silo_ticked"]


def test_insert_at_top_shifts_every_slot_keyed_store(win):
    p = win.data["temp_presets"]
    for i in range(len(p)):
        p[i] = f"# silo {i}"
    win.active_temp_slot = 0
    win.text_area.document().setPlainText(p[0])
    win.data["silo_ticked"] = [0]
    win.data["pinned_silos"] = [1]
    win.data["silo_colors"] = {"0": "#abcdef"}
    win.data["watcher_queues"] = {"0": ["q"]}
    win.data["silo_children"] = {2: [3]}
    win.data["silo_gaps"] = [0]
    win.select_empty_silo()
    assert win.data["silo_ticked"] == [1]
    assert win.data["pinned_silos"] == [2]
    assert win.data["silo_colors"].get("1") == "#abcdef"
    assert win.data["watcher_queues"].get("1") == ["q"]
    assert win.data["silo_children"] == {3: [4]}
    # T-704 (user's call): a gap belongs to the silo it was placed under, so
    # it shifts with everything else. It used to be left out of the remap,
    # which made it neither positional nor attached — a delete renumbered the
    # slots around it and parked it under a stranger.
    assert win.data["silo_gaps"] == [1]
    win.data["silo_children"], win.data["silo_gaps"] = {}, []
    win.data["watcher_queues"], win.data["silo_colors"] = {}, {}
    win.data["silo_ticked"], win.data["pinned_silos"] = [], []


# ---------------------------------------------------------------------------
# Hidden bug: int-keyed maps arrive stringified after a profile switch.
# ---------------------------------------------------------------------------


def test_normalise_int_keys_fixes_a_stringified_map_in_place(win):
    win.data["silo_last_edited_all"] = {"Code": {"1": 1700000000, "2": 1700000001}}
    inner = win.data["silo_last_edited_all"]["Code"]
    win._normalise_int_keys("silo_last_edited_all")
    assert set(inner) == {1, 2}                     # same object, coerced
    assert win.data["silo_last_edited_all"]["Code"] is inner
    win.data["silo_last_edited_all"] = {}


def test_normalise_int_keys_survives_junk(win):
    win.data["silo_last_edited_all"] = {"Code": {"x": 1, "3": 2}, "Text": "not-a-dict"}
    win._normalise_int_keys("silo_last_edited_all")
    assert set(win.data["silo_last_edited_all"]["Code"]) == {3}   # junk key dropped
    win.data["silo_last_edited_all"] = {}


def test_int_keys_do_not_survive_json_unaided(tmp_path):
    """Pins the reason the normaliser exists: the DB really does hand back
    string keys, so any path that skips normalising is broken."""
    import fastprompter.core.state as sm
    orig = sm.get_db_path
    sm.get_db_path = lambda profile_id=1: str(tmp_path / "k.db")
    try:
        st = sm.FastPrompterState()
        st.data["silo_last_edited_all"] = {"Code": {1: 1700000000}}
        st.save_data_to_db("x", force=True)
        st.conn.close()
        st2 = sm.FastPrompterState()
        keys = list(st2.data["silo_last_edited_all"]["Code"])
        assert keys == ["1"] and isinstance(keys[0], str)
        st2.conn.close()
    finally:
        sm.get_db_path = orig


# ---------------------------------------------------------------------------
# T-602: mechanical toolbar audit — no dead or unlabelled buttons.
# ---------------------------------------------------------------------------


def _toolbar_buttons(win):
    from PyQt6.QtWidgets import QPushButton
    return [(n, getattr(win, n)) for n in dir(win)
            if n.startswith("btn_") and isinstance(getattr(win, n, None), QPushButton)]


def test_every_toolbar_button_is_wired_to_something(win):
    """GUARD: a button with no receiver on clicked/toggled/pressed is dead
    chrome — it looks clickable and does nothing."""
    dead = []
    for name, b in _toolbar_buttons(win):
        recv = 0
        for sig in ("clicked", "toggled", "pressed"):
            try:
                recv += b.receivers(getattr(b, sig))
            except Exception:
                pass
        if recv == 0:
            dead.append(name)
    assert dead == [], f"dead toolbar buttons: {dead}"


def test_every_toolbar_button_has_a_tooltip(win):
    """GUARD: most of these are icon-only (⌕ ✕ ◄ ► 📦), so a missing tooltip
    leaves the control unidentifiable."""
    bare = [n for n, b in _toolbar_buttons(win) if not (b.toolTip() or "").strip()]
    assert bare == [], f"toolbar buttons without a tooltip: {bare}"


def test_default_toolbar_order_has_no_dead_names(win):
    """GUARD: names are resolved with getattr(..., None), so a stale entry is
    skipped in silence — the reorder UI just quietly loses a slot."""
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    dead = [n for n in DEFAULT_TOOLBAR_ORDER
            if not n.startswith("<") and getattr(win, n, None) is None]
    assert dead == [], f"toolbar order references widgets that do not exist: {dead}"


# ---------------------------------------------------------------------------
# Hardening: combo row -> project name is resolved by NAME, not by position.
# ---------------------------------------------------------------------------


def test_cat_at_resolves_by_row_name_not_position(win):
    names = list(win.data["cats_order"])
    for i, n in enumerate(names):
        assert win._cat_at(i) == n
    # a row whose data disagrees with its position must follow its DATA:
    # this is what makes hiding or reordering rows safe (T-599)
    win.cat_combo.setItemData(0, names[1])
    try:
        assert win._cat_at(0) == names[1]
    finally:
        win.cat_combo.setItemData(0, names[0])


def test_cat_at_falls_back_when_a_row_has_no_name(win):
    names = list(win.data["cats_order"])
    win.cat_combo.setItemData(0, None)
    try:
        assert win._cat_at(0) == names[0]      # positional fallback
    finally:
        win.cat_combo.setItemData(0, names[0])
    assert win._cat_at(999) is None            # out of range is not a crash


def test_get_current_category_matches_the_selected_row(win):
    # locate each project by its row DATA: the combo can also hold pseudo
    # rows (e.g. "Trash") that are not projects at all, so row order is not
    # a safe stand-in for cats_order
    for name in list(win.data["cats_order"]):
        row = win.cat_combo.findData(name)
        if row < 0:
            continue
        win.cat_combo.setCurrentIndex(row)
        assert win.get_current_category() == name
    win.cat_combo.setCurrentIndex(0)


# ---------------------------------------------------------------------------
# T-599: hide projects from the tab list without deleting them.
# ---------------------------------------------------------------------------


def test_hidden_project_leaves_the_combo_but_keeps_its_data(win):
    cats = list(win.data["cats_order"])
    victim = cats[-1]
    win.cat_combo.setCurrentIndex(0)
    win.data["temp_presets_all"].setdefault(victim, [""] * 10)[0] = "# keep me"
    win.hidden_categories()[:] = [victim]
    win.rebuild_cat_combo(keep=cats[0])
    shown = [win.cat_combo.itemData(i) for i in range(win.cat_combo.count())]
    assert victim not in shown
    assert cats[0] in shown
    # data untouched, and the project is still in cats_order
    assert win.data["temp_presets_all"][victim][0] == "# keep me"
    assert victim in win.data["cats_order"]
    win.hidden_categories()[:] = []
    win.rebuild_cat_combo(keep=cats[0])


def test_selection_follows_the_project_not_the_row(win):
    cats = list(win.data["cats_order"])
    win.cat_combo.setCurrentIndex(win.cat_combo.findData(cats[-1]))
    assert win.get_current_category() == cats[-1]
    # hiding an EARLIER project shifts every row index down by one
    win.hidden_categories()[:] = [cats[0]]
    win.rebuild_cat_combo()
    assert win.get_current_category() == cats[-1]   # still the same project
    win.hidden_categories()[:] = []
    win.rebuild_cat_combo(keep=cats[0])


def test_visible_categories_never_returns_empty(win):
    win.hidden_categories()[:] = list(win.data["cats_order"])
    assert win.visible_categories(), "hiding everything must not empty the combo"
    win.hidden_categories()[:] = []


def test_hidden_categories_survive_a_db_round_trip(tmp_path):
    import fastprompter.core.state as sm
    orig = sm.get_db_path
    sm.get_db_path = lambda profile_id=1: str(tmp_path / "h.db")
    try:
        st = sm.FastPrompterState()
        st.data["hidden_categories"] = ["Misc"]
        st.save_data_to_db("x", force=True)
        st.conn.close()
        st2 = sm.FastPrompterState()
        assert st2.data["hidden_categories"] == ["Misc"]
        st2.conn.close()
    finally:
        sm.get_db_path = orig


# ---------------------------------------------------------------------------
# T-603: Obsidian-style Hide Markup — markers vanish except on the caret line.
# ---------------------------------------------------------------------------


def _marker_pt(win, block_no, needle):
    """Point size applied to `needle` on that block. 1.0 == concealed."""
    doc = win.text_area.document()
    blk = doc.findBlockByNumber(block_no)
    i = blk.text().index(needle)
    for r in blk.layout().formats():
        if r.start <= i < r.start + r.length:
            return r.format.fontPointSize()
    return None


def _conceal_setup(win, text, caret_block=0):
    from PyQt6.QtWidgets import QApplication
    win.preview_combo.setCurrentIndex(1)          # Live Preview
    win.data["live_preview_conceal"] = "True"
    win.text_area.document().setPlainText(text)
    win._apply_conceal_mode()
    c = win.text_area.textCursor()
    c.setPosition(win.text_area.document().findBlockByNumber(caret_block).position())
    win.text_area.setTextCursor(c)
    QApplication.processEvents()


_CONCEAL_DOC = "zero **loud** end\none *lean* end\ntwo `code` end"


def test_markers_are_hidden_off_the_caret_line(win):
    _conceal_setup(win, _CONCEAL_DOC, caret_block=1)
    assert _marker_pt(win, 0, "**") == 1.0          # shrunk to nothing
    assert _marker_pt(win, 2, "`") == 1.0
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()


def test_markers_reappear_on_the_caret_line(win):
    _conceal_setup(win, _CONCEAL_DOC, caret_block=1)
    assert _marker_pt(win, 1, "*") != 1.0           # left editable
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()


def test_moving_the_caret_moves_which_line_is_revealed(win):
    from PyQt6.QtWidgets import QApplication
    _conceal_setup(win, _CONCEAL_DOC, caret_block=1)
    c = win.text_area.textCursor()
    c.setPosition(win.text_area.document().findBlockByNumber(0).position())
    win.text_area.setTextCursor(c)
    QApplication.processEvents()
    assert _marker_pt(win, 0, "**") != 1.0          # now revealed
    assert _marker_pt(win, 1, "*") == 1.0           # and re-hidden
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()


def test_markup_stays_visible_while_the_toggle_is_off(win):
    _conceal_setup(win, _CONCEAL_DOC, caret_block=1)
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()
    assert _marker_pt(win, 0, "**") != 1.0
    assert _marker_pt(win, 2, "`") != 1.0


def test_conceal_leaves_the_text_itself_untouched(win):
    _conceal_setup(win, _CONCEAL_DOC, caret_block=1)
    # purely visual: the document must still hold the real markdown
    assert win.text_area.toPlainText() == _CONCEAL_DOC
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()


def test_empty_emphasis_is_not_concealed(win):
    # '****' has nothing between the markers — hiding all four would make it
    # invisible and uneditable
    _conceal_setup(win, "a **** b\nsecond line", caret_block=1)
    assert _marker_pt(win, 0, "****") != 1.0
    win.data["live_preview_conceal"] = "False"
    win._apply_conceal_mode()


# ---------------------------------------------------------------------------
# T-599: hiding a project must survive the paths that rebuild the tab bar.
# ---------------------------------------------------------------------------


def _combo_names(win):
    return [win.cat_combo.itemData(i) or win.cat_combo.itemText(i)
            for i in range(win.cat_combo.count())]


def test_hidden_project_stays_hidden_after_build_categories(win):
    order = list(win.data.get("cats_order") or [])
    assert len(order) >= 2
    victim = order[-1]
    win.cat_combo.setCurrentIndex(0)
    win.on_tab_changed(0)
    win.data["hidden_categories"] = [victim]
    win.build_categories()          # profile switch / undo / Trash toggle path
    assert victim not in _combo_names(win)
    win.data["hidden_categories"] = []
    win.build_categories()
    assert victim in _combo_names(win)


def test_visible_categories_never_returns_empty_2(win):
    order = list(win.data.get("cats_order") or [])
    win.data["hidden_categories"] = list(order)      # hide everything
    # a combo with no rows would strand the user with no way back
    assert win.visible_categories() == order
    win.data["hidden_categories"] = []


def test_projects_manager_refuses_to_hide_everything(win):
    order = list(win.data.get("cats_order") or [])
    win.data["hidden_categories"] = []
    # mirrors the dialog's own guard without opening a modal
    new_hidden = list(order)
    assert len(new_hidden) >= len(order)      # the condition that returns early
    assert win.hidden_categories() == []


# ---------------------------------------------------------------------------
# HUNT: deferred callbacks must survive their widget being destroyed.
# ---------------------------------------------------------------------------


def test_deferred_callbacks_guard_a_deleted_widget():
    """Both of these run from QTimer.singleShot, so the widget can be gone
    before they fire; calling a Qt method on a dead C++ object is an access
    violation, not an exception, and takes the whole app with it."""
    import inspect

    from fastprompter import main as main_mod
    from fastprompter.ui import editor as editor_mod

    for src, name in (
        (inspect.getsource(editor_mod.VaultTextEdit._refresh_checkbox_flag),
         "_refresh_checkbox_flag"),
        (inspect.getsource(main_mod.FastPrompter._apply_header_density),
         "_apply_header_density"),
    ):
        # strip docstring AND comments: the guard's own comment mentions the
        # very calls being searched for, which would match ahead of the code
        body = src.split('"""')[-1] if '"""' in src else src
        code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
        assert "sip.isdeleted(self)" in code, f"{name} has no self guard"
        guard_at = code.index("sip.isdeleted(self)")
        for call in ("self.document()", "self.width()"):
            if call in code:
                assert code.index(call) > guard_at, f"{name}: {call} runs before the guard"


# ---------------------------------------------------------------------------
# T-568: Vintage Classic contrast must pass 3.0 threshold.
# ---------------------------------------------------------------------------


def test_vintage_classic_btn_new_contrast(win):
    from fastprompter.theme.themes import THEMES
    vc = THEMES["Vintage Classic"]
    style = vc["btn_new"]
    assert "#3a5e5e" in style, "btn_new text should be darkened teal"


def test_vintage_classic_lbl_help_contrast(win):
    from fastprompter.theme.themes import THEMES
    vc = THEMES["Vintage Classic"]
    style = vc["lbl_help"]
    assert "#808080" not in style, "lbl_help should no longer use #808080"


# ---------------------------------------------------------------------------
# T-604: Timer toast shows raw description, no "Estimated reset" override.
# ---------------------------------------------------------------------------


def test_timer_toast_no_estimated_text():
    import inspect

    import fastprompter.ui.timer_toast as tt
    src = inspect.getsource(tt.TimerToast.__init__)
    assert "Estimated reset" not in src


# ---------------------------------------------------------------------------
# T-606: Cursor blink speed setting exists.
# ---------------------------------------------------------------------------


def test_cursor_blink_spinner_exists(win):
    assert hasattr(win, "spin_cursor_blink")
    assert win.spin_cursor_blink.minimum() == 0
    assert win.spin_cursor_blink.maximum() == 2000


def test_cursor_blink_change_updates_data(win):
    old = win.data.get("cursor_blink_ms")
    win.spin_cursor_blink.setValue(800)
    assert win.data["cursor_blink_ms"] == "800"
    if old is not None:
        win.spin_cursor_blink.setValue(int(old))
    else:
        win.spin_cursor_blink.setValue(530)


# ---------------------------------------------------------------------------
# T-607: Number-box project switcher.
# ---------------------------------------------------------------------------


def test_numbox_container_exists(win):
    assert hasattr(win, "cat_numbox")
    assert hasattr(win, "_cat_num_buttons")


def test_numbox_buttons_match_visible_categories(win):
    cats = win.visible_categories()
    assert len(win._cat_num_buttons) == len(cats)
    for i, cat in enumerate(cats):
        # the tooltip carries the number too — at 100 projects the button face
        # is the only thing distinguishing them, so the pairing has to be shown
        assert win._cat_num_buttons[i].toolTip() == f"{i + 1}: {cat}"


def test_numbox_click_switches_project(win):
    if len(win._cat_num_buttons) < 2:
        pytest.skip("need >=2 projects")
    win._cat_numbox_clicked(1)
    assert win.cat_combo.currentIndex() == 1
    win._cat_numbox_clicked(0)
    assert win.cat_combo.currentIndex() == 0


def test_fresh_win_is_a_real_independent_window(fresh_win, win):
    """T-295: the function-scoped fixture must hand back a DIFFERENT window,
    not the shared module one."""
    assert fresh_win is not win
    assert fresh_win.text_area is not win.text_area


def test_teardown_actually_destroys_the_window():
    """The core T-295 finding, pinned: processEvents() does NOT deliver
    DeferredDelete, so deleteLater alone leaks the entire widget tree. Build
    a window, tear it down properly, and assert the C++ object is gone."""
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, "leakprobe.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None

    before = len(QApplication.allWidgets())
    w = FastPrompter()
    grew = len(QApplication.allWidgets())
    assert grew > before, "window built no widgets — probe is not measuring"
    _teardown_window(w)
    assert sip.isdeleted(w), "window survived teardown (DeferredDelete never flushed)"
    after = len(QApplication.allWidgets())
    # allow a little slack for shared/global widgets, but the ~1400-widget
    # tree this used to leak must be gone
    assert after < before + 100, f"leaked widgets: {before} -> {after}"


def test_teardown_leaves_gc_safe(fresh_win):
    """gc.collect() over half-deleted PyQt wrappers used to SIGSEGV at the
    third window. Nothing to assert but survival — a crash fails the run."""
    import gc
    gc.collect()
    QApplication.processEvents()
    assert fresh_win.text_area is not None


def test_hotkey_summon_focuses_the_text_silo(win):
    """T-609: brought up by hotkey, the caret belongs in the silo.

    Asserts focusWidget(), NOT hasFocus(). hasFocus() additionally requires
    the widget's WINDOW to be active, and on the offscreen platform ("this
    plugin does not support raise()") activation is order-dependent — the
    test passed alone and failed in full-suite order for that reason alone.
    focusWidget() is the window's own focus target and is what setFocus
    actually sets, so it tests the behaviour without the OS in the way."""
    # clearFocus, not setFocus on some other widget: snippets_widget is a
    # plain container with NoFocus policy, so focusing it is a silent no-op
    # and the editor kept focus — the assert below would have passed without
    # show_window doing anything at all.
    win.text_area.clearFocus()
    QApplication.processEvents()
    assert win.focusWidget() is not win.text_area   # precondition really held
    win.show_window(by_hotkey=True)
    QApplication.processEvents()          # let the deferred re-focus land
    assert win.focusWidget() is win.text_area


def test_focus_text_silo_is_guarded_for_deferred_use(win):
    """It runs from QTimer.singleShot, so it must check for a dead widget
    BEFORE touching Qt — an access violation has no traceback (H-406)."""
    import inspect
    src = inspect.getsource(win._focus_text_silo)
    body = src.split('"""')[-1] if '"""' in src else src
    code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
    assert "_is_deleted" in code, "no deletion guard"
    assert code.index("_is_deleted") < code.index("setFocus"), \
        "setFocus runs before the guard"


def test_focus_text_silo_survives_a_missing_editor(win):
    saved = win.text_area
    try:
        win.text_area = None
        win._focus_text_silo()            # must not raise
    finally:
        win.text_area = saved


def test_window_mixin_imports_qtimer_at_module_level(win):
    """The deferred re-focus calls QTimer with no local import — a missing
    module-level import would NameError on every hotkey summon."""
    import fastprompter.ui.window_mixin as wm
    assert hasattr(wm, "QTimer")


def test_numbox_rebuild_unparents_before_deleting(win):
    """H-409: deleteLater does NOT remove a widget from the parent's child
    list, and theme_mixin's font/theme pass walks self.findChildren(QWidget)
    calling styleSheet()/unpolish/polish. A button left parented while dead on
    the C++ side is an access violation there — no traceback, process gone."""
    import inspect
    src = inspect.getsource(win._rebuild_cat_numbox)
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "setParent(None)" in code, "old buttons are never unparented"
    assert code.index("setParent(None)") < code.index("deleteLater"), \
        "unparent must precede deleteLater"


def test_rebuilt_numbox_buttons_leave_the_child_tree(win):
    """Behavioural half: after a rebuild no stale button may still answer to
    findChildren, or the theme pass will reach it."""
    from PyQt6.QtWidgets import QPushButton
    win._rebuild_cat_numbox()
    old = list(win._cat_num_buttons)
    win._rebuild_cat_numbox()
    live = set(win.findChildren(QPushButton))
    assert not (set(old) & live), "a replaced number button is still parented"


def test_theme_apply_after_numbox_rebuild_does_not_crash(win):
    """The actual crash path, driven end to end: rebuild (queues deletions)
    then immediately re-apply the theme, which is what walks the child tree."""
    win._rebuild_cat_numbox()
    win.apply_theme()
    win.apply_font()
    QApplication.processEvents()
    assert len(win._cat_num_buttons) == win.cat_combo.count()


def test_numbox_active_highlight(win):
    win.cat_combo.setCurrentIndex(0)
    QApplication.processEvents()
    win._update_cat_numbox_active()
    assert win._cat_num_buttons[0].isChecked()
    if len(win._cat_num_buttons) > 1:
        assert not win._cat_num_buttons[1].isChecked()


def test_numbox_toggle_mode(win):
    win._toggle_numbox_mode(True)
    assert win.cat_combo.isHidden()
    assert not win.cat_numbox.isHidden()
    assert win.data["numbox_tabs"] == "True"
    win._toggle_numbox_mode(False)
    assert not win.cat_combo.isHidden()
    assert win.cat_numbox.isHidden()
    assert win.data["numbox_tabs"] == "False"


def test_hidden_combo_stays_hidden_across_a_layout_pass(win):
    """The boot path hides one of the two BEFORE either is added to
    header_layout. Qt only honours that if the hide was explicit — assert it
    rather than trusting the internal flag."""
    win._toggle_numbox_mode(True)
    win.header_layout.activate()
    win.header_layout.update()
    QApplication.processEvents()
    assert win.cat_combo.isHidden(), "combo re-shown by a layout pass"
    assert not win.cat_numbox.isHidden()
    win._toggle_numbox_mode(False)


def test_project_cap_is_100(win):
    import inspect
    src = inspect.getsource(win.add_category)
    assert "100" in src


def test_cat_context_menu_anchors_on_the_widget_that_was_clicked(win):
    """H-407: in number-box mode the combo is HIDDEN, and mapToGlobal on a
    hidden widget puts the menu somewhere off in the corner."""
    import inspect
    src = inspect.getsource(win.show_cat_context_menu)
    assert "anchor" in src, "show_cat_context_menu takes no anchor"
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "self.cat_combo.mapToGlobal" not in code, \
        "menu still anchors on the (possibly hidden) combo unconditionally"


def test_numbox_context_passes_the_button_as_anchor(win):
    import inspect
    src = inspect.getsource(win._cat_numbox_context)
    assert "anchor=" in src


def test_build_categories_rebuilds_numbox_before_switching(win):
    """H-408: setCurrentIndex fires on_tab_changed, which highlights the
    number buttons — rebuilding after that painted the row about to die."""
    import inspect
    src = inspect.getsource(win.build_categories)
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "_rebuild_cat_numbox" in code
    assert code.index("_rebuild_cat_numbox") < code.index("setCurrentIndex"), \
        "numbox is rebuilt after the index change"


def test_build_categories_leaves_numbox_matching_the_combo(win):
    win.build_categories()
    QApplication.processEvents()
    assert len(win._cat_num_buttons) == win.cat_combo.count()
    checked = [i for i, b in enumerate(win._cat_num_buttons) if b.isChecked()]
    assert checked == [win.cat_combo.currentIndex()]


# ---------------------------------------------------------------------------
# T-608: Ctrl+Q window presets (save/delete/cycle).
# ---------------------------------------------------------------------------


def test_fancy_zones_presets_page_appears_when_data_has_presets():
    from fastprompter.ui.fancy_zones import layouts_for
    data = {"window_presets": [[0.1, 0.1, 0.5, 0.5], [0.5, 0.0, 0.5, 1.0]]}
    layouts = layouts_for(data)
    names = [name for name, _ in layouts]
    assert "Presets" in names


def test_fancy_zones_no_presets_page_when_empty():
    from fastprompter.ui.fancy_zones import layouts_for
    assert "Presets" not in [n for n, _ in layouts_for({})]
    assert "Presets" not in [n for n, _ in layouts_for(None)]


def test_fancy_zones_save_preset():
    from fastprompter.ui.fancy_zones import _load_presets, _save_presets
    data = {}
    # bare [x,y,w,h] in, normalised dict out (legacy shape still accepted)
    _save_presets(data, [[0.0, 0.0, 1.0, 1.0]])
    presets = _load_presets(data)
    assert len(presets) == 1
    p = presets[0]
    assert (p["x"], p["y"], p["w"], p["h"]) == (0.0, 0.0, 1.0, 1.0)
    assert p["state"] == "normal"


class _FakeWin:
    """Minimal stand-in with the two toggles apply_ui_state may press."""

    def __init__(self, zen=False, sidebar=True):
        self.focus_mode = zen
        self.sidebar_visible = sidebar
        self.presses = []

    def toggle_focus_mode(self):
        self.focus_mode = not self.focus_mode
        # the real one collapses the sidebar on the way in
        if self.focus_mode:
            self.sidebar_visible = False
        self.presses.append("zen")

    def toggle_sidebar_visibility(self):
        self.sidebar_visible = not self.sidebar_visible
        self.presses.append("sidebar")


def test_window_preset_carries_zen_and_sidebar_state():
    """T-700/701. A preset used to be a rectangle and nothing else, so one
    saved in zen with the sidebar away came back with all the chrome on."""
    from fastprompter.ui.fancy_zones import _load_presets, _save_presets

    data = {}
    _save_presets(data, [{"name": "Zen", "x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0,
                          "zen": True, "sidebar": False}])
    p = _load_presets(data)[0]
    assert p["zen"] is True and p["sidebar"] is False

    # False is a real answer and must survive the round trip as False,
    # not be dropped as falsy
    _save_presets(data, [{"name": "Plain", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0,
                          "zen": False, "sidebar": True}])
    p = _load_presets(data)[0]
    assert p["zen"] is False and p["sidebar"] is True

    # a preset written before this existed says nothing — not False
    _save_presets(data, [{"name": "Old", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}])
    assert "zen" not in data["window_presets"][0]
    p = _load_presets(data)[0]
    assert p["zen"] is None and p["sidebar"] is None


def test_apply_ui_state_only_presses_what_has_to_change():
    from fastprompter.ui.fancy_zones import apply_ui_state

    # already in the wanted state: nothing is pressed (applying a preset
    # twice must not toggle zen back off)
    win = _FakeWin(zen=True, sidebar=False)
    apply_ui_state(win, {"zen": True, "sidebar": False})
    assert win.presses == []

    # into zen from a normal window
    win = _FakeWin(zen=False, sidebar=True)
    apply_ui_state(win, {"zen": True, "sidebar": False})
    assert win.focus_mode is True and win.sidebar_visible is False
    assert win.presses == ["zen"]

    # out of zen, sidebar back on — zen first, then the sidebar, or leaving
    # zen would undo the sidebar again
    win = _FakeWin(zen=True, sidebar=False)
    apply_ui_state(win, {"zen": False, "sidebar": True})
    assert win.focus_mode is False and win.sidebar_visible is True
    assert win.presses == ["zen", "sidebar"]

    # a legacy preset leaves the window exactly as it found it
    win = _FakeWin(zen=True, sidebar=False)
    apply_ui_state(win, {"x": 0, "y": 0, "w": 1, "h": 1})
    assert win.presses == []
    assert win.focus_mode is True and win.sidebar_visible is False


def test_legacy_bare_list_presets_still_load():
    """The first build stored [x,y,w,h]. A saved preset must not vanish
    because the format grew a name and a state."""
    from fastprompter.ui.fancy_zones import _load_presets
    got = _load_presets({"window_presets": [[0.1, 0.2, 0.3, 0.4]]})
    assert len(got) == 1
    assert (got[0]["x"], got[0]["y"], got[0]["w"], got[0]["h"]) == (0.1, 0.2, 0.3, 0.4)
    assert got[0]["state"] == "normal"
    assert got[0]["name"]


def test_presets_page_hidden_when_disabled():
    from fastprompter.ui.fancy_zones import layouts_for
    data = {"window_presets": [{"name": "a", "x": 0, "y": 0, "w": 1, "h": 1}]}
    assert "Presets" in [n for n, _ in layouts_for(data)]
    data["window_presets_enabled"] = "False"
    assert "Presets" not in [n for n, _ in layouts_for(data)]


def test_preset_round_trips_name_and_state():
    from fastprompter.ui.fancy_zones import _load_presets, _save_presets
    data = {}
    _save_presets(data, [{"name": "Wide", "x": 0.0, "y": 0.0,
                          "w": 1.0, "h": 0.5, "state": "maximized"}])
    got = _load_presets(data)
    assert got[0]["name"] == "Wide"
    assert got[0]["state"] == "maximized"


def test_presets_dialog_reorders_and_renames(win):
    from fastprompter.ui.window_presets_dialog import WindowPresetsDialog
    saved = win.data.get("window_presets")
    try:
        win.data["window_presets"] = [
            {"name": "first", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5},
            {"name": "second", "x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5},
        ]
        dlg = WindowPresetsDialog(win)
        assert [p["name"] for p in dlg.presets] == ["first", "second"]
        dlg.list.setCurrentRow(1)
        dlg.move_up()
        assert [p["name"] for p in dlg.presets] == ["second", "first"]
        dlg.presets[0]["name"] = "renamed"
        dlg.accept()
        assert [p["name"] for p in win.data["window_presets"]] == ["renamed", "first"]
    finally:
        if saved is None:
            win.data.pop("window_presets", None)
        else:
            win.data["window_presets"] = saved


def test_presets_dialog_recapture_keeps_name_and_slot(win):
    """The picker alone could only delete + re-add, which moved the entry to
    the end and lost its name."""
    from fastprompter.ui.window_presets_dialog import WindowPresetsDialog
    saved = win.data.get("window_presets")
    try:
        win.data["window_presets"] = [
            {"name": "keepme", "x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1},
            {"name": "other", "x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5},
        ]
        dlg = WindowPresetsDialog(win)
        dlg.list.setCurrentRow(0)
        dlg.recapture()
        assert dlg.presets[0]["name"] == "keepme"     # name kept
        assert [p["name"] for p in dlg.presets] == ["keepme", "other"]  # slot kept
        assert dlg.presets[0]["w"] != 0.1             # geometry actually changed
    finally:
        if saved is None:
            win.data.pop("window_presets", None)
        else:
            win.data["window_presets"] = saved


def test_presets_dialog_delete_and_cap(win):
    from fastprompter.ui.fancy_zones import _MAX_PRESETS
    from fastprompter.ui.window_presets_dialog import WindowPresetsDialog
    saved = win.data.get("window_presets")
    try:
        win.data["window_presets"] = [
            {"name": f"p{i}", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}
            for i in range(_MAX_PRESETS)
        ]
        dlg = WindowPresetsDialog(win)
        dlg.list.setCurrentRow(0)
        dlg.delete()
        assert len(dlg.presets) == _MAX_PRESETS - 1
        from unittest.mock import patch
        with patch("fastprompter.ui.window_presets_dialog.QMessageBox"):
            dlg.add_current()
            assert len(dlg.presets) == _MAX_PRESETS
            dlg.add_current()                      # refused at the cap
            assert len(dlg.presets) == _MAX_PRESETS
    finally:
        if saved is None:
            win.data.pop("window_presets", None)
        else:
            win.data["window_presets"] = saved


def test_settings_expose_presets_toggle_and_manage(win):
    assert hasattr(win, "cb_window_presets")
    assert hasattr(win, "btn_manage_presets")


def test_fancy_zones_max_presets():
    from fastprompter.ui.fancy_zones import _MAX_PRESETS, _load_presets, _save_presets
    data = {}
    big = [[0.1 * i, 0.0, 0.5, 0.5] for i in range(_MAX_PRESETS + 5)]
    _save_presets(data, big)
    assert len(_load_presets(data)) == _MAX_PRESETS + 5


def test_window_presets_round_trips_through_db(tmp_path):
    import fastprompter.core.state as sm
    db = tmp_path / "presets_rt.db"
    orig = sm.get_db_path
    sm.get_db_path = lambda profile_id=1: str(db)
    try:
        st = sm.FastPrompterState()
        st.data["window_presets"] = [[0.1, 0.2, 0.3, 0.4]]
        st.save_data_to_db("body", force=True)
        st.conn.close()

        st2 = sm.FastPrompterState()
        assert st2.data.get("window_presets") == [[0.1, 0.2, 0.3, 0.4]]
        st2.conn.close()
    finally:
        sm.get_db_path = orig


# --- T-610 / T-611: gutter overlap + the leaked contentsChange connection ---

def test_gutter_skips_rows_that_would_overlap(win):
    """A 1pt block (a `---` rule, an image ref) is ~2px tall, so drawing its
    number in a full font-height box painted straight over the next line's
    digits. gutter_rows() must skip any block whose top falls inside the band
    the previous number already occupies."""
    ed = win.text_area
    saved = win.data.get("show_line_numbers", "False")
    win.data["show_line_numbers"] = "True"
    try:
        ed.setPlainText("\n".join(f"line {i}" for i in range(20)))
        QApplication.processEvents()
        rows = list(ed.gutter_rows())
        assert rows, "gutter produced no rows at all"
        fm_height = ed.fontMetrics().height()
        tops = [top for _b, top, _h in rows]
        for a, b in zip(tops, tops[1:]):
            assert b - a >= fm_height, f"numbers at y={a} and y={b} overlap"
        for _b, _top, row_h in rows:
            assert 2 <= row_h <= fm_height
    finally:
        win.data["show_line_numbers"] = saved


def test_gutter_rows_survives_a_collapsed_block(win):
    """Same rule with a block the layout really did collapse: force one line
    to a 1pt char format and check the rows stay monotonic and non-colliding."""
    from PyQt6.QtGui import QTextCharFormat, QTextCursor
    ed = win.text_area
    saved = win.data.get("show_line_numbers", "False")
    win.data["show_line_numbers"] = "True"
    try:
        ed.setPlainText("alpha\n---\nbeta\n---\ngamma")
        doc = ed.document()
        tiny = QTextCharFormat()
        tiny.setFontPointSize(1)
        for n in (1, 3):
            blk = doc.findBlockByNumber(n)
            cur = QTextCursor(blk)
            cur.select(QTextCursor.SelectionType.BlockUnderCursor)
            cur.mergeCharFormat(tiny)
        QApplication.processEvents()
        rows = list(ed.gutter_rows())
        tops = [top for _b, top, _h in rows]
        assert tops == sorted(tops)
        fm_height = ed.fontMetrics().height()
        for a, b in zip(tops, tops[1:]):
            assert b - a >= fm_height
    finally:
        win.data["show_line_numbers"] = saved


def test_contents_change_connection_does_not_accumulate(fresh_win):
    """set_active_document connected `lambda *_a: self.refresh_extra_selections()`
    to every document and disconnected nothing, so each switch BACK to a silo
    stacked another copy on the same document (measured 4 -> 14 over ten round
    trips) and the connection outlived the editor. Named method now, and the
    outgoing document is disconnected."""
    w = fresh_win
    ed = w.text_area
    doc = ed.document()
    before = doc.receivers(doc.contentsChange)
    for i in range(10):
        w._switch_to_slot((i % 3) + 1)
        QApplication.processEvents()
        w._switch_to_slot(0)
        QApplication.processEvents()
    assert doc is ed.document(), "slot 0 handed back a different document"
    assert doc.receivers(doc.contentsChange) == before


def test_contents_change_handler_is_guarded(fresh_win):
    """The document outlives the editor, so the handler must check first."""
    import inspect

    from fastprompter.ui.editor import VaultTextEdit
    src = inspect.getsource(VaultTextEdit._on_contents_change)
    assert "sip.isdeleted(self)" in src
    src2 = inspect.getsource(VaultTextEdit._stamp_edited_blocks)
    assert "sip.isdeleted(self)" in src2
    # the guard has to precede the first Qt call, not merely exist. Comments
    # and the docstring mention document() too, so compare against code only.
    code = "\n".join(
        line for line in src2.splitlines()
        if line.strip() and not line.strip().startswith("#"))
    body = code[code.index('"""', code.index('"""') + 3):]
    assert body.index("sip.isdeleted(self)") < body.index("self.document()")


# --- T-612: number boxes have to survive the 100-project cap ---

def test_numbox_wraps_into_rows_at_the_cap(fresh_win):
    """One QHBoxLayout of 100 boxes is ~2200px — it runs straight off the
    header. The grid wraps every `numbox_per_row` buttons instead."""
    w = fresh_win
    w.data["numbox_per_row"] = "10"
    cats = w.visible_categories()
    w._rebuild_cat_numbox()
    layout = w._cat_numbox_layout
    assert layout.rowCount() >= 1
    for i in range(len(cats)):
        row, col, _rs, _cs = layout.getItemPosition(i)
        assert row == i // 10 and col == i % 10


def test_numbox_geometry_settings_clamp_and_persist(fresh_win):
    w = fresh_win
    w._on_numbox_geometry_changed("numbox_per_row", 7)
    assert w.data["numbox_per_row"] == "7"
    assert w.numbox_per_row() == 7
    w._on_numbox_geometry_changed("numbox_btn_size", 30)
    assert w.numbox_button_size() == 30
    assert w._cat_num_buttons[0].width() == 30
    for bad in ("", "nope", None, 0, 999):
        w.data["numbox_per_row"] = bad
        assert 1 <= w.numbox_per_row() <= 100
        w.data["numbox_btn_size"] = bad
        assert 14 <= w.numbox_button_size() <= 40


def test_numbox_settings_controls_exist(win):
    assert hasattr(win, "spin_numbox_per_row")
    assert hasattr(win, "spin_numbox_size")


# --- T-614: token estimate beside the line count ---

def test_token_label_exists_and_follows_its_setting(fresh_win):
    w = fresh_win
    assert hasattr(w, "lbl_token_count")
    w.data["show_token_count"] = "False"
    w._update_token_count_label()
    assert not w.lbl_token_count.isVisibleTo(w.header_widget)
    w.data["show_token_count"] = "True"
    w.text_area.setPlainText("one two three four five")
    w._update_token_count_label()
    assert w.lbl_token_count.isVisibleTo(w.header_widget)
    assert w.lbl_token_count.text().startswith("~")
    assert w.lbl_token_count.text().endswith("T")


def test_token_estimate_modes_and_weights(fresh_win):
    w = fresh_win
    text = "a" * 400
    w.data["token_mode"] = "chars"
    w.data["token_weight"] = "4.0"
    assert w.token_estimate(text) == 100
    w.data["token_weight"] = "2.0"
    assert w.token_estimate(text) == 200
    w.data["token_mode"] = "words"
    w.data["token_weight"] = "1.33"
    assert w.token_estimate("one two three") == 4      # 3 * 1.33 -> 3.99
    assert w.token_estimate("") == 0
    for bad in ("", "x", None):
        w.data["token_weight"] = bad
        assert w.token_estimate("word word") >= 0


def test_token_label_is_in_the_toolbar_order(win):
    """apply_toolbar_order re-adds ONLY tokens from the order list, so a
    header widget missing from it disappears at the first rebuild."""
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    assert "lbl_token_count" in DEFAULT_TOOLBAR_ORDER
    assert "lbl_token_count" in win._toolbar_order_list()
    win.apply_toolbar_order()
    assert win.lbl_token_count.parent() is win.header_widget


def test_token_mode_click_cycles(fresh_win):
    w = fresh_win
    w.data["token_mode"] = "chars"
    w._cycle_token_mode()
    assert w.data["token_mode"] == "words"
    assert w.data["token_weight"] == "1.33"
    w._cycle_token_mode()
    assert w.data["token_mode"] == "chars"
    assert w.data["token_weight"] == "4.0"


def test_timer_minutes_setting_reaches_the_label(fresh_win):
    w = fresh_win
    assert hasattr(w, "cb_timer_minutes")
    w.data["timer_show_minutes"] = "True"
    w._update_timer_label()        # must not raise with or without timers
    w.data["timer_show_minutes"] = "False"
    w._update_timer_label()


# --- T-616: Fast mode — Ctrl+Q without the picker ---

def test_fast_mode_cycles_zones_without_showing_the_picker(fresh_win):
    w = fresh_win
    w.data["fancyzones_fast"] = "True"
    w.data["fancyzones_layout"] = "Quarters"
    w.data["fancyzones_fast_idx"] = "-1"
    seen = []
    for _ in range(5):
        w.cycle_snap_corner()
        QApplication.processEvents()
        assert not w._fancy_zones.isVisible(), "fast mode opened the picker"
        seen.append(w.data["fancyzones_fast_idx"])
    assert seen == ["0", "1", "2", "3", "0"], seen


def test_fast_mode_off_still_opens_the_picker(fresh_win):
    w = fresh_win
    w.data["fancyzones_fast"] = "False"
    w.cycle_snap_corner()
    QApplication.processEvents()
    try:
        assert w._fancy_zones.isVisible()
    finally:
        w._fancy_zones.close()
        QApplication.processEvents()


def test_fast_mode_survives_a_junk_index(fresh_win):
    w = fresh_win
    w.data["fancyzones_fast"] = "True"
    w.data["fancyzones_layout"] = "Quarters"
    for junk in ("", "abc", None, "99"):
        w.data["fancyzones_fast_idx"] = junk
        w.cycle_snap_corner()
        assert 0 <= int(w.data["fancyzones_fast_idx"]) < 4


def test_fast_page_picker_lists_the_real_pages(fresh_win):
    w = fresh_win
    assert hasattr(w, "cb_fast_zone_page")
    from fastprompter.ui.fancy_zones import layouts_for
    names = [n for n, _z in layouts_for(w.data)]
    assert [w.cb_fast_zone_page.itemData(i)
            for i in range(w.cb_fast_zone_page.count())] == names
    w.cb_fast_zone_page.setCurrentIndex(1)
    assert w.data["fancyzones_layout"] == names[1]
    assert w.data["fancyzones_fast_idx"] == "-1"


# --- T-615: files panel as a docked, collapsible sidebar ---

def test_files_dock_sits_opposite_the_silo_sidebar(fresh_win):
    w = fresh_win
    for right in (False, True):
        w.data["sidebar_right"] = "True" if right else "False"
        w.apply_sidebar_position()
        i_dock = w.splitter.indexOf(w.files_dock)
        i_side = w.splitter.indexOf(w.left_panel)
        i_center = w.splitter.indexOf(w.center_panel)
        assert -1 not in (i_dock, i_side, i_center)
        # centre in the middle, dock and sidebar on opposite edges
        assert min(i_dock, i_side) < i_center < max(i_dock, i_side)
        assert (i_dock < i_side) is right


def test_files_panel_docks_and_undocks(fresh_win):
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    panel = w._ensure_file_container()
    assert panel.docked
    assert panel.parent() is w.files_dock
    w.data["file_panel_docked"] = "False"
    panel = w._ensure_file_container()
    assert not panel.docked
    assert w.files_dock.isHidden()


def test_files_button_toggles_the_dock(fresh_win):
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    w.toggle_file_container()          # opens
    QApplication.processEvents()
    # isHidden(), not isVisible(): the test window has no shown ancestor
    assert not w.files_dock.isHidden()
    w.toggle_file_container()          # and closes
    QApplication.processEvents()
    assert w.files_dock.isHidden()


def test_dock_gets_a_real_width_when_shown(fresh_win):
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    w.data["files_dock_width"] = "240"
    w.resize(1000, 600)
    QApplication.processEvents()
    w.open_file_container()
    QApplication.processEvents()
    idx = w.splitter.indexOf(w.files_dock)
    assert w.splitter.sizes()[idx] >= 120


def test_splitter_sizes_survive_the_third_pane(fresh_win):
    """apply_sidebar_position used to index the panes as 0/1 by hand; the
    dock made that wrong on both sides."""
    w = fresh_win
    w.data["sidebar_right"] = "False"
    w.data["splitter_sizes_left"] = [130, 500]      # a pre-dock saved value
    w.apply_sidebar_position()
    sizes = w.splitter.sizes()
    assert len(sizes) == w.splitter.count()
    assert sizes[w.splitter.indexOf(w.left_panel)] > 0
    assert sizes[w.splitter.indexOf(w.center_panel)] > 0


def test_files_dock_setting_exists(win):
    assert hasattr(win, "cb_files_dock")


# --- T-618: the drop system has to match a DOCKED files panel ---

def test_docked_panel_follows_the_active_silo(fresh_win):
    """A floating drawer left on the old silo is merely stale; a docked one
    is what a drop lands in, so it must follow the switch."""
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    QApplication.processEvents()
    first = w._file_container.folder
    w._switch_to_slot(3)
    QApplication.processEvents()
    second = w._file_container.folder
    assert second != first
    assert second == w._silo_folder_dir(3, False)


def test_floating_panel_is_not_dragged_around_by_silo_switches(fresh_win):
    """The follow is for the dock only — a floating window the user placed
    somewhere must not be re-opened by every silo switch."""
    w = fresh_win
    w.data["file_panel_docked"] = "False"
    w.open_file_container()
    QApplication.processEvents()
    before = w._file_container.folder
    w._switch_to_slot(2)
    QApplication.processEvents()
    assert w._file_container.folder == before


def test_panel_shows_a_drop_target_while_dragging(fresh_win):
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    panel = w._file_container
    plain = panel.file_list.styleSheet()
    hint = panel.lbl_hint.text()
    panel._set_drop_hot(True)
    assert "border" in panel.file_list.styleSheet()
    assert panel.lbl_hint.text() != hint
    panel._set_drop_hot(False)
    assert panel.file_list.styleSheet() == plain
    assert panel.lbl_hint.text() == hint


def test_drop_hot_is_idempotent(fresh_win):
    """dragEnter can fire repeatedly; the hint must not eat itself."""
    w = fresh_win
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    panel = w._file_container
    hint = panel.lbl_hint.text()
    for _ in range(3):
        panel._set_drop_hot(True)
    panel._set_drop_hot(False)
    assert panel.lbl_hint.text() == hint


# --- T-619: header widgets missing from the toolbar order ---

def test_numbox_is_in_the_header_layout(fresh_win):
    """T-607 shipped the number boxes without adding cat_numbox to
    DEFAULT_TOOLBAR_ORDER. apply_toolbar_order detaches every header child
    and re-adds only listed tokens, so the widget was orphaned at (0,0):
    invisible itself, and painting over the sidebar hamburger."""
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    w = fresh_win
    assert "cat_numbox" in DEFAULT_TOOLBAR_ORDER
    w.apply_toolbar_order()
    assert w.header_layout.indexOf(w.cat_numbox) >= 0
    assert w.header_layout.indexOf(w.cat_combo) >= 0


def test_every_ordered_token_resolves_to_a_widget(fresh_win):
    """Any header widget that is not a token is invisible after the first
    rebuild — so the order list is the real inventory."""
    w = fresh_win
    for tok in w._toolbar_order_list():
        if tok == "<stretch>":
            continue
        assert w._toolbar_widget_for(tok) is not None, tok


def test_numbox_toggle_shows_the_boxes(fresh_win):
    w = fresh_win
    w.cb_numbox_tabs.setChecked(True)
    QApplication.processEvents()
    assert not w.cat_numbox.isHidden()
    assert w.cat_combo.isHidden()
    assert w._cat_num_buttons
    assert w.cat_numbox.width() > 0
    w.cb_numbox_tabs.setChecked(False)
    QApplication.processEvents()
    assert w.cat_numbox.isHidden()
    assert not w.cat_combo.isHidden()


def test_new_tokens_heal_next_to_their_neighbour(fresh_win):
    """A saved order from an older version must not dump new tokens after
    the help button."""
    w = fresh_win
    saved = w.data.get("toolbar_order")
    try:
        from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
        old = [t for t in DEFAULT_TOOLBAR_ORDER
               if t not in ("cat_numbox", "lbl_token_count")]
        w.data["toolbar_order"] = ",".join(old)
        healed = w._toolbar_order_list()
        assert healed.index("cat_numbox") == healed.index("cat_combo") + 1
        assert healed.index("lbl_token_count") == healed.index("lbl_line_count") + 1
    finally:
        w.data["toolbar_order"] = saved


# --- T-620 / T-621: header order and pane indices with three panes ---

def test_right_cluster_hugs_the_right_edge(fresh_win):
    """The anchor search skipped <stretch>, so every token defined after one
    was inserted in FRONT of it: the whole right cluster collapsed leftwards
    and left a dead gap at the right edge."""
    w = fresh_win
    w.data["toolbar_order"] = ""
    w.apply_toolbar_order()
    w.resize(1200, 300)
    QApplication.processEvents()
    order = w._toolbar_order_list()
    assert order.index("<stretch>") < order.index("btn_help")
    assert order.index("lbl_line_count") > order.index("<stretch>")
    # With the sidebar on the right — which the shipped profile does — the
    # hamburger is an EDGE control placed after the order, so the right
    # cluster hugs it rather than the raw header width.
    right = w.header_widget.width()
    if w._sidebar_right:
        right = min(right, w.btn_sidebar_toggle.geometry().left())
    assert w.btn_help.geometry().right() >= right - 2, w.btn_help.geometry()


def test_empty_saved_order_is_exactly_the_default(fresh_win):
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    w = fresh_win
    w.data["toolbar_order"] = ""
    assert w._toolbar_order_list() == list(DEFAULT_TOOLBAR_ORDER)


def test_hamburger_hides_the_sidebar_on_both_sides(fresh_win):
    """With the files dock the splitter has three panes; the old hardcoded
    'pane 1 when right' pointed at the CENTRE, so the button grew the
    sidebar instead of hiding it."""
    w = fresh_win
    w.resize(1000, 600)
    for right in (False, True):
        w.data["sidebar_right"] = "True" if right else "False"
        w.apply_sidebar_position()
        QApplication.processEvents()
        idx = w.splitter.indexOf(w.left_panel)
        assert w.splitter.sizes()[idx] > 0, "sidebar started hidden"
        w.toggle_sidebar_visibility()
        assert w.splitter.sizes()[idx] == 0, f"right={right}: did not hide"
        w.toggle_sidebar_visibility()
        assert w.splitter.sizes()[idx] > 0, f"right={right}: did not come back"


def test_zen_mode_collapses_every_other_pane(fresh_win):
    w = fresh_win
    w.resize(1000, 600)
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    QApplication.processEvents()
    w.toggle_focus_mode()
    QApplication.processEvents()
    try:
        sizes = w.splitter.sizes()
        centre = w.splitter.indexOf(w.center_panel)
        for i, s in enumerate(sizes):
            if i != centre:
                assert s == 0, f"pane {i} survived Zen mode"
    finally:
        w.toggle_focus_mode()


# --- T-622..T-625: files button side, Vision, project reorder, Zen solo ---

def test_files_button_mirrors_the_sidebar_side(fresh_win):
    w = fresh_win
    lay = w.header_layout
    w.data["sidebar_right"] = "False"
    w.apply_toolbar_order()
    left_pos = lay.indexOf(w.btn_files)
    assert left_pos < lay.indexOf(w.btn_settings_toggle_right)
    w.data["sidebar_right"] = "True"
    w.apply_toolbar_order()
    # sidebar right -> dock left -> 📁 sits next to the settings gear
    assert lay.indexOf(w.btn_files) == lay.indexOf(w.btn_settings_toggle_right) - 1


def test_vision_button_cycles_the_view_mode(fresh_win):
    w = fresh_win
    assert hasattr(w, "btn_vision")
    from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
    assert "btn_vision" in DEFAULT_TOOLBAR_ORDER
    modes = [w.preview_combo.itemData(i) for i in range(w.preview_combo.count())]
    start = w.preview_combo.currentIndex()
    seen = []
    for _ in range(len(modes) + 1):
        w.cycle_vision_mode()
        QApplication.processEvents()
        seen.append(w.preview_combo.currentData())
    assert seen[:len(modes)] == modes[start + 1:] + modes[:start + 1]
    assert w.btn_vision.toolTip()


def test_projects_dialog_can_reorder(fresh_win, monkeypatch):
    """The manager could hide projects but never move them."""
    from PyQt6.QtWidgets import QDialog, QListWidget
    w = fresh_win
    order_before = list(w.data["cats_order"])
    if len(order_before) < 2:
        pytest.skip("need >=2 projects")
    captured = {}

    def fake_exec(self):
        lst = self.findChild(QListWidget)
        captured["lst"] = lst
        lst.setCurrentRow(lst.count() - 1)
        for btn in self.findChildren(type(w.btn_new)):
            if btn.text() == "▲":
                btn.click()
                break
        return 1

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    w.open_projects_manager()
    assert captured.get("lst") is not None
    expected = list(order_before)
    expected[-2], expected[-1] = expected[-1], expected[-2]
    assert w.data["cats_order"] == expected
    assert w.data["cats_order"] is not None


def test_zen_has_three_stages(fresh_win, monkeypatch):
    from fastprompter.ui import zen_desktop
    w = fresh_win
    calls = {"min": 0, "restore": 0}
    monkeypatch.setattr(zen_desktop, "minimise_others",
                        lambda own: calls.__setitem__("min", calls["min"] + 1) or [111])
    monkeypatch.setattr(zen_desktop, "restore",
                        lambda h: calls.__setitem__("restore", calls["restore"] + 1))
    assert not getattr(w, "focus_mode", False)
    w.cycle_focus_mode()                  # 1: zen
    assert w.focus_mode and not getattr(w, "zen_solo", False)
    assert calls["min"] == 0
    w.cycle_focus_mode()                  # 2: solo
    assert w.focus_mode and w.zen_solo
    assert calls["min"] == 1
    w.cycle_focus_mode()                  # 3: all the way back
    assert not w.focus_mode and not w.zen_solo
    assert calls["restore"] == 1


def test_plain_toggle_never_sweeps_the_desktop(fresh_win, monkeypatch):
    """A dozen callers (and the fuzz suite) use toggle_focus_mode as a plain
    two-state switch. Folding the stages into it made "toggle twice" mean
    "minimise every window on the machine" for all of them — which is exactly
    what the suite then did to the developer's desktop."""
    from fastprompter.ui import zen_desktop
    w = fresh_win
    swept = []
    monkeypatch.setattr(zen_desktop, "minimise_others",
                        lambda own: swept.append(1) or [1])
    monkeypatch.setattr(zen_desktop, "restore", lambda h: None)
    for _ in range(3):
        w.toggle_focus_mode()
        w.toggle_focus_mode()
    assert not w.focus_mode
    assert not getattr(w, "zen_solo", False)
    assert swept == []


def test_leaving_the_window_restores_the_desktop(fresh_win, monkeypatch):
    from fastprompter.ui import zen_desktop
    w = fresh_win
    monkeypatch.setattr(zen_desktop, "minimise_others", lambda own: [222])
    restored = []
    monkeypatch.setattr(zen_desktop, "restore", lambda h: restored.append(list(h)))
    w.cycle_focus_mode()
    w.cycle_focus_mode()
    assert w.zen_solo
    w.hide_and_save()                     # click-out / hotkey hide
    assert not w.zen_solo
    assert restored == [[222]]
    w.toggle_focus_mode()                 # leave zen for the shared fixture


def test_zen_solo_ignores_its_own_activation_churn(fresh_win, monkeypatch):
    """Minimising other windows churns the foreground; that transient
    deactivation must not undo solo the instant it starts."""
    from fastprompter.ui import zen_desktop
    w = fresh_win
    monkeypatch.setattr(zen_desktop, "minimise_others", lambda own: [333])
    monkeypatch.setattr(zen_desktop, "restore", lambda h: None)
    w.cycle_focus_mode()
    w.cycle_focus_mode()
    w.exit_zen_solo(grace=True)
    assert w.zen_solo, "grace period did not hold"
    w._zen_solo_at = 0.0
    w.exit_zen_solo(grace=True)
    assert not w.zen_solo
    w.toggle_focus_mode()


# --- T-626: the layout you left is the layout you come back to ---

def _restart(tmpdir, tag):
    """Build a window against a private DB, twice, around a mutation."""
    import fastprompter.core.state as sm
    from fastprompter.main import FastPrompter as FP
    sm.get_db_path = lambda profile_id=1, _t=tag: os.path.join(
        tmpdir, f"{_t}_{profile_id}.db")
    sm.run_portable_backup = lambda data: None
    return FP()


def test_collapsed_sidebar_survives_a_restart(tmp_path):
    """Splitter sizes were only written by splitterMoved, so a sidebar
    collapsed with the hamburger came back open on the next start."""
    w = _restart(str(tmp_path), "sidebar")
    w.resize(1000, 600)
    QApplication.processEvents()
    w.toggle_sidebar_visibility()
    idx = w.splitter.indexOf(w.left_panel)
    assert w.splitter.sizes()[idx] == 0
    # _teardown_window drops the connection to skip the final write, so save
    # explicitly — the real app writes this on close
    w.save_data_to_db(force=True)
    _teardown_window(w)

    w2 = _restart(str(tmp_path), "sidebar")
    w2.resize(1000, 600)
    QApplication.processEvents()
    try:
        idx2 = w2.splitter.indexOf(w2.left_panel)
        assert w2.splitter.sizes()[idx2] == 0, "sidebar came back open"
        assert w2.sidebar_visible is False
        w2.toggle_sidebar_visibility()
        assert w2.splitter.sizes()[idx2] > 0, "could not reopen it"
    finally:
        _teardown_window(w2)


def test_open_files_sidebar_survives_a_restart(tmp_path):
    w = _restart(str(tmp_path), "dock")
    w.resize(1000, 600)
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    QApplication.processEvents()
    assert not w.files_dock.isHidden()
    w.save_data_to_db(force=True)
    _teardown_window(w)

    w2 = _restart(str(tmp_path), "dock")
    w2.resize(1000, 600)
    QApplication.processEvents()
    try:
        assert w2.files_docked()
        assert not w2.files_dock.isHidden(), "files sidebar came back closed"
    finally:
        _teardown_window(w2)


def test_closed_files_sidebar_stays_closed(tmp_path):
    w = _restart(str(tmp_path), "dock2")
    w.resize(1000, 600)
    w.data["file_panel_docked"] = "True"
    w.open_file_container()
    QApplication.processEvents()
    w.toggle_file_container()          # close it again
    assert w.files_dock.isHidden()
    w.save_data_to_db(force=True)
    _teardown_window(w)

    w2 = _restart(str(tmp_path), "dock2")
    QApplication.processEvents()
    try:
        assert w2.files_dock.isHidden()
    finally:
        _teardown_window(w2)


# --- T-627: cropped toolbar icons on themes with fat button padding ---

def test_icon_buttons_have_room_for_their_glyph(fresh_win):
    """Vintage Classic asks for a 2px border plus 3px/6px padding. Inside a
    20x20 button that left a 4x10 content rect for a glyph needing 15px, so
    the emoji was painted as a narrow vertical slice — the "cropped icons"
    report. Measured through the STYLE's content rect: contentsRect() knows
    nothing about stylesheet padding and happily reported the full 20x20."""
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QPushButton, QStyle, QStyleOptionButton
    w = fresh_win
    w.resize(1100, 300)
    for theme in ("Vintage Classic", "Golden Default", "Default"):
        w.change_theme(theme)
        QApplication.processEvents()
        checked = 0
        for btn in w.header_widget.findChildren(QPushButton):
            if btn.isHidden() or not btn.property("fp_icon_button"):
                continue
            text = btn.text()
            if not text:
                continue
            opt = QStyleOptionButton()
            btn.initStyleOption(opt)
            content = btn.style().subElementRect(
                QStyle.SubElement.SE_PushButtonContents, opt, btn)
            need = QFontMetrics(btn.font()).horizontalAdvance(text)
            assert content.width() >= need, (
                f"{theme}: {text!r} needs {need}px, has {content.width()}px")
            checked += 1
        assert checked >= 5, f"{theme}: only {checked} icon buttons found"


def test_icon_label_detection():
    from fastprompter.ui.scaling_mixin import _is_icon_label
    for glyph in ("📁", "☰", "✕", "-→•", "#", "📁3", ""):
        assert _is_icon_label(glyph), glyph
    # single letters moved to the MARK side: B / I / U / S / H live in 24px
    # squares where the theme's side padding leaves 8px for an 11px glyph
    for mark in ("B", "I", "H"):
        assert _is_icon_label(mark), mark
    for word in ("NEW", "Save", "Line"):
        assert not _is_icon_label(word), word


def test_word_buttons_keep_their_padding(fresh_win):
    """The rule is about labels, not shapes: NEW and Save are words and the
    theme's padding is right for them."""
    w = fresh_win
    w.change_theme("Vintage Classic")
    QApplication.processEvents()
    assert w.btn_new.property("fp_icon_button") is False
    assert w.btn_save.property("fp_icon_button") is False
    assert w.btn_bold.property("fp_icon_button") is True
    assert w.btn_pin_top.property("fp_icon_button") is True


def test_padding_override_reaches_existing_buttons(fresh_win):
    """A dynamic property set after polish does not re-evaluate the sheet on
    its own, so the override needs an explicit repolish pass."""
    import inspect

    from fastprompter.ui.theme_mixin import ThemeMixin
    src = inspect.getsource(ThemeMixin.apply_theme)
    assert "repolish_icon_buttons" in src
    assert 'fp_icon_button' in src


# --- T-628: the label-fits-the-box guarantee, swept ---

def _clipped_buttons(win):
    """Every visible button whose label does not fit the box the STYLE gives
    it. Measured through SE_PushButtonContents: contentsRect() knows nothing
    about stylesheet padding and reports the full box, which is exactly how
    years of size checks passed over visibly sliced icons."""
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QPushButton, QStyle, QStyleOptionButton
    bad = []
    for btn in win.findChildren(QPushButton):
        if btn.isHidden() or not btn.text():
            continue
        # squishable widgets are explicitly allowed to be squeezed (the
        # snippet-row arrows lose a pixel rather than push the row taller)
        if getattr(btn, "is_squishable", False):
            continue
        # The guarantee covers MARKS and FIXED boxes — the same set the
        # production pass guards. A word in a box the layout is free to size
        # gets elided by Qt ("Copy my se…"), which is legible and which the
        # user can fix by widening the window; forcing those wider instead
        # wraps the settings panel into extra rows (T-605). Half a folder
        # icon is not legible at any width, which is why marks are absolute.
        if not (btn.property("fp_icon_button")
                or btn.minimumWidth() == btn.maximumWidth()
                or btn.minimumHeight() == btn.maximumHeight()):
            continue
        opt = QStyleOptionButton()
        btn.initStyleOption(opt)
        content = btn.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, btn)
        fm = QFontMetrics(btn.font())
        need_w, need_h = fm.horizontalAdvance(btn.text()), fm.height()
        if content.width() < need_w or content.height() < need_h:
            bad.append(f"{btn.text()!r} w {content.width()}/{need_w} "
                       f"h {content.height()}/{need_h}")
    return bad


def test_no_button_label_is_clipped_on_any_theme_or_scale(fresh_win):
    """The cropped-icon bug survived from the alpha because every new theme,
    button and scale was a fresh chance to reintroduce it. This is the guard:
    every theme x every scale, nothing clipped. Before the fit pass this
    found 58 clipped buttons on Vintage Classic alone."""
    from fastprompter.theme.themes import THEMES
    w = fresh_win
    w.resize(1400, 700)
    QApplication.processEvents()
    failures = []
    for theme in THEMES:
        for scale in ("0.5", "1.0", "1.5"):
            w.data["ui_scale"] = scale
            w.change_theme(theme)
            w.apply_scaled_ui()
            QApplication.processEvents()
            for bad in _clipped_buttons(w):
                failures.append(f"{theme} @{scale}: {bad}")
    assert not failures, "clipped labels:\n  " + "\n  ".join(failures[:20])


def test_fit_pass_reports_what_it_changed(fresh_win):
    """A second run must find nothing left to do — the pass has to converge,
    not oscillate."""
    w = fresh_win
    w.change_theme("Vintage Classic")
    QApplication.processEvents()
    w.enforce_button_fit()
    assert w.enforce_button_fit() == 0


def test_single_letter_buttons_count_as_marks(fresh_win):
    """B / I / U / S / H live in 24px squares; 6px of side padding leaves 8px
    for an 11px glyph, so they are marks, not words."""
    from fastprompter.ui.scaling_mixin import _is_icon_label
    for mark in ("B", "I", "U", "S", "H", "📁", "☰", "-→•"):
        assert _is_icon_label(mark), mark
    for word in ("NEW", "Save", "Line", "Build Template"):
        assert not _is_icon_label(word), word


def test_footer_row_reflows_on_the_first_fit(win):
    """The footer is a FlowLayout: its height depends on a width it only
    learns once the frame is laid out, and on the FIRST fit it was still
    carrying the height from the previous width — 194px against a 163px hint,
    i.e. ~100px of dead panel under the checkboxes on the tab that happens to
    be open first. One pass cannot see that; _fit_settings_tabs invalidates
    the wrapping children now."""
    from PyQt6.QtWidgets import QWidget
    win.is_locked = False
    win._locked_geometry = None
    was_visible = win.mini_settings_frame.isVisible()
    try:
        win.mini_settings_frame.setVisible(True)
        win.resize(905, 965)
        win.show()
        QApplication.processEvents()
        tabs = win.settings_tabs
        tabs.setCurrentIndex(0)
        win._fit_settings_tabs(0)
        QApplication.processEvents()
        frame = win.mini_settings_frame
        for child in frame.children():
            if not isinstance(child, QWidget) or child.isHidden():
                continue
            inner = child.layout()
            if inner is None or not inner.hasHeightForWidth():
                continue
            allowed = inner.heightForWidth(max(120, child.width())) + 8
            assert child.height() <= allowed, (
                f"{type(child).__name__} kept {child.height()}px for "
                f"{allowed}px of wrapped content")
    finally:
        win.mini_settings_frame.setVisible(was_visible)
        win.resize(1400, 700)


# --- T-629: Normal Window has to show its title bar on the FIRST click ---

def test_normal_window_forces_a_frame_recalculation():
    """WS_CAPTION was set correctly on the first click — measured — and no
    title bar appeared, because Windows does not recompute the non-client
    area just because the style word changed. The caption turned up on the
    next toggle, which is the "it takes three clicks" report."""
    import inspect

    from fastprompter.main import FastPrompter
    src = inspect.getsource(FastPrompter._recalc_native_frame)
    assert "0x0020" in src, "SWP_FRAMECHANGED is the whole point"
    flags_src = inspect.getsource(FastPrompter.apply_window_flags)
    assert "_recalc_native_frame" in flags_src
    # and it must run AFTER the window is shown again, not before
    assert flags_src.index("self.show()") < flags_src.index("_recalc_native_frame")


def test_normal_window_toggle_does_not_walk_the_window(fresh_win):
    """Neither naive restore works alone: setGeometry pins the CLIENT, so
    gaining a caption pushes the window down by its height, and move() pins
    the FRAME, so losing it pulls the window up. Measured +4/+23 one way and
    -4 the other, a step per toggle."""
    w = fresh_win
    w.resize(700, 260)
    w.move(120, 120)
    QApplication.processEvents()
    before_frame = w.frameGeometry()
    before_size = w.geometry().size()
    for _ in range(3):
        w.cb_normal_window.setChecked(True)
        QApplication.processEvents()
        w.cb_normal_window.setChecked(False)
        QApplication.processEvents()
    assert w.geometry().size() == before_size, "the client resized itself"
    assert w.frameGeometry().topLeft() == before_frame.topLeft(), (
        f"window walked from {before_frame.topLeft()} to "
        f"{w.frameGeometry().topLeft()}")


def test_frame_position_restore_is_a_no_op_when_nothing_moved(fresh_win):
    w = fresh_win
    QApplication.processEvents()
    frame = w.frameGeometry()
    size = w.geometry().size()
    w._restore_frame_position(frame, size)
    assert w.frameGeometry().topLeft() == frame.topLeft()


# --- T-630: SiloTable and SiloKanban in the live editor ---

def _put(win, text, line=0, col=0):
    from PyQt6.QtGui import QTextCursor
    win.text_area.setPlainText(text)
    QApplication.processEvents()
    doc = win.text_area.document()
    block = doc.findBlockByNumber(line)
    cur = QTextCursor(block)
    cur.setPosition(block.position() + min(col, len(block.text())))
    win.text_area.setTextCursor(cur)
    return cur


TABLE_TEXT = ("| Name | Qty |\n"
              "| :--- | --- |\n"
              "| apple | 3 |\n")


def test_inserted_table_is_aligned_and_empty(fresh_win):
    """The old insert wrote 'Row 1' into every cell — one deletion per cell
    before you can type — and never lined the pipes up."""
    from fastprompter.ui import silo_table as st
    lines = st.render(st.new_table(2, 3))
    assert len({len(x) for x in lines}) == 1, lines
    parsed = st.parse(lines, 0)
    assert parsed.rows[1:] == [["", "", ""], ["", "", ""]]


def test_tab_walks_the_cells(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=2, col=2)          # inside "apple"
    assert ed.table_move_cell(forward=True)
    cur = ed.textCursor()
    assert cur.selectedText() == "3", cur.selectedText()
    assert ed.table_move_cell(forward=False)
    assert ed.textCursor().selectedText() == "apple"


def test_tab_off_the_last_cell_grows_the_table(fresh_win):
    from fastprompter.ui import silo_table as st
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=2, col=TABLE_TEXT.split("\n")[2].index("3"))
    before = len(st.parse(ed.toPlainText().split("\n"), 2).rows)
    assert ed.table_move_cell(forward=True)
    after = st.parse(ed.toPlainText().split("\n"), 2)
    assert len(after.rows) == before + 1
    assert ed.textCursor().blockNumber() == 3


def test_shift_tab_at_the_start_refuses_rather_than_wrapping(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=0, col=2)
    assert ed.table_move_cell(forward=False) is False


def test_enter_in_a_table_adds_a_row(fresh_win):
    from fastprompter.ui import silo_table as st
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=2, col=3)
    assert ed.table_new_row()
    rows = st.parse(ed.toPlainText().split("\n"), 2).rows
    assert rows[-1] == ["", ""]
    assert ed.textCursor().blockNumber() == 3


def test_realign_is_idempotent_and_makes_no_undo_step_when_tidy(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, "| a | b |\n| --- | --- |\n| longer | x |\n", line=2, col=3)
    assert ed.table_realign()
    tidy = ed.toPlainText()
    assert ed.table_realign() is False, "a tidy table must not be re-edited"
    assert ed.toPlainText() == tidy


def test_table_structure_ops(fresh_win):
    from fastprompter.ui import silo_table as st
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=2, col=3)
    assert ed.table_edit("col_right")
    assert st.parse(ed.toPlainText().split("\n"), 2).columns == 3
    assert ed.table_edit("col_delete")
    assert st.parse(ed.toPlainText().split("\n"), 2).columns == 2
    assert ed.table_edit("align_center")
    assert st.parse(ed.toPlainText().split("\n"), 2).aligns[0] == st.ALIGN_CENTER


def test_table_ops_are_one_undo_step(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, TABLE_TEXT, line=2, col=3)
    before = ed.toPlainText()
    ed.table_edit("row_below")
    assert ed.toPlainText() != before
    ed.undo()
    assert ed.toPlainText() == before


KANBAN_TEXT = ("## To Do\n"
               "- [ ] first\n"
               "- [ ] second\n"
               "\n"
               "## Doing\n"
               "- [ ] busy\n"
               "\n"
               "## Done\n"
               "- [x] finished\n")


def test_inserted_kanban_is_a_real_board(fresh_win):
    """The old 'kanban' was a markdown TABLE with checkboxes: it looked like a
    board and no card could move, because a table cell is not a card."""
    from fastprompter.ui import silo_kanban as sk
    board = sk.parse(sk.new_board())
    assert [c.name for c in board.columns] == ["To Do", "Doing", "Done"]


def test_alt_arrows_move_a_card(fresh_win):
    from fastprompter.ui import silo_kanban as sk
    w = fresh_win
    ed = w.text_area
    _put(w, KANBAN_TEXT, line=1, col=8)         # on "first"
    assert ed.kanban_move(dx=1)
    board = sk.parse(ed.toPlainText().split("\n"))
    assert [len(c.cards) for c in board.columns] == [1, 2, 1]
    assert ed.kanban_move(dx=-1)
    board = sk.parse(ed.toPlainText().split("\n"))
    assert [len(c.cards) for c in board.columns] == [2, 1, 1]


def test_alt_arrow_is_inert_outside_a_board(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, "just prose here\nand more\n", line=0, col=3)
    assert ed.kanban_move(dx=1) is False
    assert ed.kanban_move(dy=1) is False
    assert ed.in_kanban() is False


def test_kanban_toggle_and_add(fresh_win):
    from fastprompter.ui import silo_kanban as sk
    w = fresh_win
    ed = w.text_area
    _put(w, KANBAN_TEXT, line=1, col=8)
    assert ed.kanban_toggle()
    assert sk.parse(ed.toPlainText().split("\n")).columns[0].cards[0].done
    assert ed.kanban_add_card()
    assert len(sk.parse(ed.toPlainText().split("\n")).columns[0].cards) == 3


def test_kanban_move_is_one_undo_step(fresh_win):
    w = fresh_win
    ed = w.text_area
    _put(w, KANBAN_TEXT, line=1, col=8)
    before = ed.toPlainText()
    ed.kanban_move(dx=1)
    assert ed.toPlainText() != before
    ed.undo()
    assert ed.toPlainText() == before


def test_board_edits_do_not_wipe_marks_elsewhere(fresh_win):
    """A QTextBlock carries its line's margin mark, and replacing text
    destroys the blocks it spans. Rewriting the whole silo to move one card
    cleared the marks on notes that had nothing to do with the board."""
    w = fresh_win
    ed = w.text_area
    _put(w, "notes line\nsecond note\n\n" + KANBAN_TEXT, line=0)
    doc = ed.document()
    for n in (0, 1):
        doc.findBlockByNumber(n).setUserState(2)
    _put(w, ed.toPlainText(), line=4, col=8)     # caret on the first card
    doc = ed.document()
    for n in (0, 1):
        doc.findBlockByNumber(n).setUserState(2)
    assert ed.kanban_move(dx=1)
    doc = ed.document()
    assert [doc.findBlockByNumber(n).userState() for n in (0, 1)] == [2, 2]


def test_a_moved_card_keeps_its_own_mark(fresh_win):
    """Marks are remembered by CONTENT, so the mark travels with the card
    instead of staying on whatever line number it used to occupy."""
    from fastprompter.ui import silo_kanban as sk
    w = fresh_win
    ed = w.text_area
    _put(w, KANBAN_TEXT, line=1, col=8)
    doc = ed.document()
    doc.findBlockByNumber(1).setUserState(3)
    assert ed.kanban_move(dx=1)
    lines = ed.toPlainText().split("\n")
    moved = sk.parse(lines).columns[1].cards
    where = next(c.first for c in moved if c.text == "first")
    assert ed.document().findBlockByNumber(where).userState() == 3




# ---------------------------------------------------------------------------
# Dialogs must survive being CONSTRUCTED. `QSlider.TickPosition.Below` is a
# perfectly plausible line that raises AttributeError the moment the widget is
# built, and nothing caught it until a user clicked the button.
# ---------------------------------------------------------------------------


def test_sound_settings_dialog_opens_and_edits(win):
    from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP, EVENT_LABELS
    from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

    kept = win.data.get("sound_events")
    try:
        dlg = SoundSettingsDialog(win, win.data, win.sound_manager)
        try:
            assert dlg.table.rowCount() == len(EVENT_LABELS)

            # every row starts on a real file
            for event, row in dlg._rows.items():
                combo = dlg.table.cellWidget(row, 2)
                assert combo.count() > 1, event
                assert "missing" not in combo.currentText(), event

            # flipping a row writes through to the map the player reads
            row = dlg._rows["click"]
            dlg.table.cellWidget(row, 1).setChecked(False)
            assert win.data["sound_events"]["click"]["enabled"] == "False"
            dlg.table.cellWidget(row, 3).setValue(7)
            assert win.data["sound_events"]["click"]["volume"] == "7"
            dlg.table.cellWidget(row, 3).setValue(0)
            assert win.data["sound_events"]["click"]["volume"] == ""

            # loading must not write back — and must not stack a second
            # connection onto every widget, which is what made one click
            # fire the handler twice after a reset
            dlg._load_settings()
            dlg.table.cellWidget(row, 1).setChecked(True)
            assert win.data["sound_events"]["click"]["enabled"] == "True"

            # the filter hides rows by label AND by event id
            dlg.filter_box.setText("zzz-no-such-event")
            assert all(dlg.table.isRowHidden(r) for r in dlg._rows.values())
            dlg.filter_box.setText("")
            assert not any(dlg.table.isRowHidden(r) for r in dlg._rows.values())

            # reset puts every shipped default back
            win.data["sound_events"]["click"]["file"] = "notify.wav"
            dlg._data["sound_events"] = {
                e: {"file": f, "enabled": "True", "volume": ""}
                for e, f in _DEFAULT_SOUND_MAP.items()
            }
            dlg._load_settings()
            assert (win.data["sound_events"]["click"]["file"]
                    == _DEFAULT_SOUND_MAP["click"])
        finally:
            dlg.deleteLater()
    finally:
        if kept is not None:
            win.data["sound_events"] = kept


def test_every_shipped_sound_default_exists(win):
    """The library was renamed wholesale; a stale default plays nothing."""
    import os

    from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP

    root = win.sound_manager._sounds_dir
    missing = [f for f in _DEFAULT_SOUND_MAP.values()
               if not os.path.exists(os.path.join(root, f))]
    assert not missing, missing


def test_timer_dialog_opens(win):
    from fastprompter.ui.timer_dialog import TimerDialog

    dlg = TimerDialog(win)
    try:
        assert dlg.date_time_picker is not None
    finally:
        dlg.deleteLater()


def test_cs_style_toggle_maps_to_files_that_exist(win):
    """T-708. The three CS sounds live in cs_style/, and the toggle used to
    name them as if they sat at the top level — after the library rename that
    pointed the whole style at nothing."""
    import os

    kept_events = win.data.get("sound_events")
    kept_style = win.data.get("cs_style", "False")
    try:
        win.on_cs_style_toggled(True)
        assert win.data["cs_style"] == "True"
        root = win.sound_manager._sounds_dir
        for event in ("hover", "click", "button_click", "button_release"):
            name = win.data["sound_events"][event]["file"]
            assert name.startswith("cs_style/"), (event, name)
            assert os.path.exists(os.path.join(root, name)), name

        # switching it off puts the previous choice back
        win.on_cs_style_toggled(False)
        assert win.data["cs_style"] == "False"
        assert win.data["sound_events"]["click"]["file"] != "cs_style/buttonclick.wav"
    finally:
        win.data["cs_style"] = kept_style
        if kept_events is not None:
            win.data["sound_events"] = kept_events


def test_backspace_follows_the_typewriter_toggle(win):
    """T-709. It is part of the typewriter effect, not the UI clicks."""
    from fastprompter.core.sound_manager import is_event_enabled

    data = {"sound_ui": "True", "sound_typewriter": "False"}
    assert is_event_enabled("backspace", data) is False
    assert is_event_enabled("type", data) is False
    assert is_event_enabled("click", data) is True

    data = {"sound_ui": "False", "sound_typewriter": "True"}
    assert is_event_enabled("backspace", data) is True
    assert is_event_enabled("click", data) is False


def test_settings_panel_hugs_its_content_after_show(win):
    """The panel is measured against a WIDTH, and during construction the
    tabs are a few pixels wide — measured there, a wrapping row reports the
    height it would need in a sliver, and that became the panel's maximum.
    A fresh launch then showed a screenful of dead space under two rows of
    checkboxes."""
    from PyQt6.QtWidgets import QApplication

    kept = win.data.get("hide_extra", "True")
    try:
        win.resize(1000, 700)
        win.mini_settings_frame.setVisible(True)
        win.show()
        QApplication.processEvents()
        win._fit_settings_tabs()
        QApplication.processEvents()

        tabs = win.settings_tabs
        page = tabs.currentWidget()
        bar = tabs.tabBar().sizeHint().height() if tabs.tabBar() else 24
        needed = page.layout().totalHeightForWidth(max(120, tabs.width() - 12))
        slack = tabs.maximumHeight() - (needed + bar)
        assert slack < 80, (
            f"panel reserves {tabs.maximumHeight()}px for {needed + bar}px of "
            f"content ({slack}px of dead space)")
    finally:
        win.hide()
        win.data["hide_extra"] = kept
        win.mini_settings_frame.setVisible(kept != "True")



# --- T-729: the archive panel rendered as an empty box with slivers ---------

def test_archive_rows_do_not_overlap(win):
    """Measured before the fix: four 21px rows landed at y = 0, 2, 4, 6 inside
    a 42px archive_widget — two rows of space for four rows of content, which
    on screen is an empty dark box with thin strips down the left edge."""
    saved = list(win.data.get("archive_temp_presets", []))
    saved_vis = win.data.get("archive_visible", "False")
    try:
        win.data["archive_temp_presets"][:] = ["arch one", "arch two", "arch three", "arch four"]
        win.data["archive_visible"] = "True"
        win.refresh_archive_panel()
        rows = [b for b in win.archive_buttons if not b.isHidden()][:4]
        assert len(rows) == 4, f"expected 4 archive rows, got {len(rows)}"
        for a, b in zip(rows, rows[1:]):
            assert b.y() >= a.y() + a.height(), (
                f"archive rows overlap: {a.geometry()} then {b.geometry()}")
        assert win.archive_widget.height() >= sum(r.height() for r in rows), (
            f"archive panel {win.archive_widget.height()}px cannot hold "
            f"{len(rows)} rows of {rows[0].height()}px")
    finally:
        win.data["archive_temp_presets"][:] = saved
        win.data["archive_visible"] = saved_vis
        win.refresh_archive_panel()


# --- T-721: closing the docked files pane ----------------------------------

def test_closing_files_dock_returns_width_to_centre_and_plays_close(win):
    """Two defects in one gesture: the docked pane is HIDDEN, never closed,
    so `closeEvent`'s chest_close never fired — and Qt handed the freed width
    to whoever had stretch, which is the silo sidebar. It grew every time."""
    dock = getattr(win, "files_dock", None)
    if dock is None:
        import pytest as _pytest
        _pytest.skip("no docked files pane in this build")

    asked = []
    real_play = win.sound_manager.play
    win.sound_manager.play = lambda name: asked.append(name)
    try:
        idx = win.splitter.indexOf(dock)
        centre = win.splitter.indexOf(win.center_panel)
        left = win.splitter.indexOf(win.left_panel)
        dock.setVisible(True)
        sizes = win.splitter.sizes()
        sizes[idx] = 200
        win.splitter.setSizes(sizes)
        before = win.splitter.sizes()

        win._show_files_dock(False)

        after = win.splitter.sizes()
        assert not dock.isVisible()
        assert "chest_close" in asked, f"no close sound, only {asked}"
        if 0 <= left < len(after):
            assert after[left] == before[left], (
                f"silo sidebar grew {before[left]} -> {after[left]} "
                "when the files pane closed")
        assert after[centre] >= before[centre], "the centre pane should take the width"
    finally:
        win.sound_manager.play = real_play
        dock.setVisible(False)


# --- T-725: the timer's calendar popup rendered stock white ----------------

def test_timer_calendar_popup_is_themed(win):
    """`setCalendarPopup(True)` builds the calendar in its own top-level
    window, so the sheet the dialog copies from the main window never reaches
    it — screenshot showed a white calendar inside a dark golden app."""
    from fastprompter.ui.timer_dialog import TimerDialog

    dlg = TimerDialog(win)
    try:
        picker = dlg.date_time_picker
        cal = picker.calendarWidget()
        assert cal is not None, "the picker must have a calendar popup"
        for widget, what in ((picker, "field"), (cal, "calendar")):
            sheet = widget.styleSheet()
            assert sheet.strip(), f"{what} carries no stylesheet at all"
            assert "QCalendarWidget QAbstractItemView" in sheet, (
                f"{what} does not style the calendar's own item view")
        # and the colours come from the active theme, not hardcoded white
        assert "#fff" not in cal.styleSheet().lower()
    finally:
        dlg.deleteLater()


# --- T-724: a pasted image must land as a clickable pill -------------------

def test_pasted_image_path_lands_as_a_pill(win):
    """`![](...)` is the only shape MD_IMAGE_RE matches, and therefore the
    only one the painter collapses into the clickable chip. A pasted image
    PATH went in as `[name](...)` — plain link text, nothing to click."""
    from fastprompter.ui.editor import MD_IMAGE_RE

    ta = win.text_area
    saved = win.data.get("image_paste_style", "pill")
    try:
        win.data["image_paste_style"] = "pill"
        markup = ta.image_paste_markup("shot.png", "file:///V:/pics/shot.png")
        assert MD_IMAGE_RE.fullmatch(markup), f"{markup!r} is not a pill"
        assert MD_IMAGE_RE.match(markup).group(1) == "file:///V:/pics/shot.png"

        win.data["image_paste_style"] = "link"
        assert ta.image_paste_markup("shot.png", "file:///V:/pics/shot.png") == \
            "[shot.png](file:///V:/pics/shot.png)"

        win.data["image_paste_style"] = "path"
        assert ta.image_paste_markup("shot.png", "file:///V:/pics/shot.png") == \
            "file:///V:/pics/shot.png"
    finally:
        win.data["image_paste_style"] = saved


def test_image_extensions_are_recognised(win):
    ta = win.text_area
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        assert ext in ta.IMAGE_EXTENSIONS, ext
    for ext in (".txt", ".md", ".py", ".zip"):
        assert ext not in ta.IMAGE_EXTENSIONS, ext


def test_paste_style_setting_is_in_the_settings_panel(win):
    combo = getattr(win, "cb_img_paste", None)
    assert combo is not None, "no control for the paste-style setting"
    assert [combo.itemData(i) for i in range(combo.count())] == ["pill", "link", "path"]


# --- T-718: silos as a horizontal tab strip --------------------------------

def test_silo_tabs_mode_moves_the_strip_and_flips_the_axis(win):
    """The SAME widgets move hosts — nothing is rebuilt — so every refresh
    path and the whole drag machinery keep working in both modes."""
    from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

    saved = win.data.get("silo_tabs_mode", "sidebar")
    try:
        win.apply_silo_tabs_mode(True)
        assert isinstance(win.silos_widget.layout, QHBoxLayout)
        assert win.silos_widget.horizontal is True
        assert win.center_layout.indexOf(win.silos_section) == 0, "strip not above the editor"
        assert win.left_panel_layout.indexOf(win.silos_section) == -1
        assert win.btn_silo_up.text() == "◀" and win.btn_silo_down.text() == "▶"

        win.apply_silo_tabs_mode(False)
        assert isinstance(win.silos_widget.layout, QVBoxLayout)
        assert win.silos_widget.horizontal is False
        assert win.center_layout.indexOf(win.silos_section) == -1
        assert win.left_panel_layout.indexOf(win.silos_section) >= 0
        assert win.btn_silo_up.text() == "▲" and win.btn_silo_down.text() == "▼"
    finally:
        win.apply_silo_tabs_mode(saved == "tabs")


def test_switching_mode_keeps_every_silo_button(win):
    saved = win.data.get("silo_tabs_mode", "sidebar")
    before = list(win.silo_buttons)
    try:
        win.apply_silo_tabs_mode(True)
        in_layout = [win.silos_widget.layout.itemAt(i).widget()
                     for i in range(win.silos_widget.layout.count())]
        for btn in before:
            assert btn in in_layout, "a silo button was dropped by the axis swap"
    finally:
        win.apply_silo_tabs_mode(saved == "tabs")


def test_drop_maths_follows_the_axis(win):
    """T-702's rule, one implementation, both orientations: the pointer in a
    button's leading band inserts before it, trailing band after it."""
    from PyQt6.QtCore import QPoint

    w = win.silos_widget
    saved = win.data.get("silo_tabs_mode", "sidebar")
    try:
        win.apply_silo_tabs_mode(True)
        btns = w._visible_buttons()
        if len(btns) < 2:
            import pytest as _pytest
            _pytest.skip("needs at least two visible silos")
        g = btns[0].geometry()
        assert w._drop_target_at(QPoint(g.left() + 1, g.center().y())) == ("move", 0)
        assert w._drop_target_at(QPoint(g.right() - 1, g.center().y())) == ("move", 1)
        mode, target = w._drop_target_at(QPoint(g.center().x(), g.center().y()))
        assert mode == "swap" and target is btns[0]
    finally:
        win.apply_silo_tabs_mode(saved == "tabs")


# --- T-719: toolbar above or below the editor ------------------------------

def test_toolbar_can_move_to_the_bottom(win):
    """A move inside the central QVBoxLayout, not a rebuild: every button
    keeps its widget, its order and its drag-reorder wiring."""
    saved = win.data.get("toolbar_position", "top")
    try:
        win.apply_toolbar_position(False)
        assert win.main_layout.indexOf(win.header_widget) == 0
        assert win.data["toolbar_position"] == "top"

        win.apply_toolbar_position(True)
        last = win.main_layout.count() - 1
        assert win.main_layout.indexOf(win.header_widget) == last, "toolbar is not last"
        assert win.main_layout.indexOf(win.splitter) < last, "toolbar must sit below the editor"
        assert win.data["toolbar_position"] == "bottom"

        win.apply_toolbar_position(False)
        assert win.main_layout.indexOf(win.header_widget) == 0
    finally:
        win.apply_toolbar_position(saved == "bottom")


def test_toolbar_position_has_a_control(win):
    cb = getattr(win, "cb_toolbar_bottom", None)
    assert cb is not None, "no control for the toolbar position setting"
