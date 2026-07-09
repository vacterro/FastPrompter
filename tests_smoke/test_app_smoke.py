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
