"""Tests for T-1468: TableGridWidget settings host ownership, visual default
propagation in TableEditDialog, and the Reset Table Layout UX contract (Option A).
"""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QTextEdit, QWidget

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.ui import silo_table as st
from fastprompter.ui.table_edit_dialog import TableEditDialog, open_table_edit_dialog
from fastprompter.ui.table_grid import TableGridWidget, is_settings_host

_APP = QApplication.instance() or QApplication([])


class _MockSettingsHost(QWidget):
    """A realistic settings host mimicking FastPrompter main window."""

    def __init__(self, **settings):
        super().__init__()
        self.data = dict(settings)
        self.dirty_calls = []
        self._current_lang = "EN"

    def mark_dirty(self, kind="all"):
        self.dirty_calls.append(kind)

    def styleSheet(self):
        return ""

    def _default_table_layout(self):
        return st.parse_default_layout(self.data.get("table_default_layout"))


class _MockEditor(QTextEdit):
    """An editor stub hosting a document and caret tracking."""

    def __init__(self, main_win=None):
        super().__init__()
        self.main_win = main_win

    def table_at_caret(self):
        line = self.textCursor().blockNumber()
        lines = self.toPlainText().split("\n")
        table = st.parse(lines, line)
        if table is None:
            return None
        col = st.cell_index(lines[line], self.textCursor().positionInBlock())
        return table, line, col


def _make_template(cols=4, rows=5, width=160, height=35, word_wrap=True):
    return {
        "version": 1,
        "columns": cols,
        "visible_rows": rows,
        "col_widths": [width] * cols,
        "row_heights": [height] * rows,
        "manual_cols": list(range(cols)),
        "manual_rows": list(range(rows)),
        "word_wrap": word_wrap,
    }


# ============================================================================
# STAGE 1: SETTINGS HOST OWNERSHIP & CONTRACT
# ============================================================================

def test_is_settings_host_validation():
    assert not is_settings_host(None)
    assert not is_settings_host(QWidget())
    assert not is_settings_host(object())

    class BadData:
        data = "not a dict"
        def mark_dirty(self, kind): pass

    class BadDirty:
        data = {}
        mark_dirty = "not callable"

    class GoodHost:
        data = {}
        def mark_dirty(self, kind="all"): pass

    assert not is_settings_host(BadData())
    assert not is_settings_host(BadDirty())
    assert is_settings_host(GoodHost())
    assert is_settings_host(_MockSettingsHost())


def test_table_grid_unbound_settings_host_raises_runtime_error():
    """When TableGridWidget has no settings host, settings ops raise RuntimeError."""
    grid = TableGridWidget()
    assert grid.get_settings_host() is None

    with pytest.raises(RuntimeError, match="requires a settings host"):
        grid.save_as_default_layout()

    with pytest.raises(RuntimeError, match="requires a settings host"):
        grid.apply_default_layout()

    with pytest.raises(RuntimeError, match="requires a settings host"):
        grid.restore_factory_layout()


def test_table_grid_binds_explicit_settings_host():
    """Explicit settings_host is used even when parent is a non-host widget."""
    parent_widget = QWidget()
    host = _MockSettingsHost()
    grid = TableGridWidget(parent=parent_widget, settings_host=host)

    assert grid.get_settings_host() is host
    assert grid.parent() is parent_widget

    # Save layout through explicit host
    grid.load_markdown("| A | B | C | D |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |\n| 5 | 6 | 7 | 8 |\n")
    grid.save_as_default_layout()
    assert "settings" in host.dirty_calls
    stored = json.loads(host.data["table_default_layout"])
    assert stored["columns"] == 4
    assert stored["visible_rows"] == 3


def test_table_edit_dialog_passes_settings_host_to_grid():
    """TableEditDialog wires editor.main_win to its TableGridWidget as settings_host."""
    host = _MockSettingsHost()
    editor = _MockEditor(main_win=host)

    tpl = _make_template(3, 4, width=180)
    host.data["table_default_layout"] = json.dumps(tpl)

    table_md = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n"
    editor.setPlainText(table_md)
    table = st.parse(table_md.split("\n"), 0)

    dlg = TableEditDialog(editor, table, (0, 2))
    assert dlg.settings_host is host
    assert dlg.grid.get_settings_host() is host

    # Right-click operations must not crash with AttributeError
    dlg.grid.save_as_default_layout()
    assert "settings" in host.dirty_calls

    dlg.grid.restore_factory_layout()
    assert host.data["table_default_layout"] == DEFAULT_PROFILE.get("table_default_layout", "")


# ============================================================================
# STAGE 2: VISUAL DEFAULTS PROPAGATION TO INSERTED TABLES
# ============================================================================

def test_newly_inserted_table_in_dialog_receives_saved_default_layout():
    """An empty table opened in TableEditDialog inherits saved widths and word-wrap."""
    tpl = _make_template(cols=3, rows=3, width=222, height=44, word_wrap=True)
    host = _MockSettingsHost(table_default_layout=json.dumps(tpl))
    editor = _MockEditor(main_win=host)

    # Empty table as produced by _insert_table
    new_tbl = st.default_table(tpl)
    md_lines = st.render(new_tbl)
    editor.setPlainText("\n".join(md_lines))

    table = st.parse(md_lines, 0)
    dlg = TableEditDialog(editor, table, (0, len(md_lines) - 1))

    # Grid columns must have the saved 222 width
    assert dlg.grid.view.horizontalHeader().sectionSize(0) == 222
    assert dlg.grid.view.horizontalHeader().sectionSize(1) == 222
    assert dlg.grid.view.horizontalHeader().sectionSize(2) == 222
    assert dlg.grid.view.wordWrap() is True


def test_existing_populated_table_in_dialog_does_not_override_layout():
    """A populated table opened in TableEditDialog keeps content-fit sizing, not template."""
    tpl = _make_template(cols=3, rows=3, width=350, word_wrap=True)
    host = _MockSettingsHost(table_default_layout=json.dumps(tpl))
    editor = _MockEditor(main_win=host)

    populated_md = (
        "| City | Pop | Country |\n"
        "| --- | --- | --- |\n"
        "| Tokyo | 14M | Japan |\n"
    )
    editor.setPlainText(populated_md)
    table = st.parse(populated_md.split("\n"), 0)

    dlg = TableEditDialog(editor, table, (0, 2))
    # Populated table must not take the 350px template width
    assert dlg.grid.view.horizontalHeader().sectionSize(0) != 350


# ============================================================================
# STAGE 3: RESET-LAYOUT UX CONTRACT (OPTION A)
# ============================================================================

def test_reset_layout_matching_shape_applies_successfully():
    """Matching column count applies default layout cleanly."""
    tpl = _make_template(cols=3, rows=3, width=195)
    host = _MockSettingsHost(table_default_layout=json.dumps(tpl))
    grid = TableGridWidget(settings_host=host)

    # Load 3-column table
    grid.load_markdown("| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n")
    assert grid.apply_default_layout() is True
    assert grid.view.horizontalHeader().sectionSize(0) == 195
    assert grid._last_apply_error is None


def test_reset_layout_shape_mismatch_returns_false_and_records_reason(monkeypatch):
    """Mismatched column count returns False, sets error state, and warns via dialog."""
    tpl = _make_template(cols=4, rows=3, width=195)
    host = _MockSettingsHost(table_default_layout=json.dumps(tpl))
    grid = TableGridWidget(settings_host=host)

    # 3-column table vs 4-column template
    grid.load_markdown("| A | B | C |\n|---|---|---|\n| 1 | Important Data | 3 |\n")

    assert grid.apply_default_layout() is False
    assert grid._last_apply_error == ("shape_mismatch", 3, 4)

    # Ensure cell data was NOT deleted or mutated
    assert grid.model.data(grid.model.index(1, 1), Qt.ItemDataRole.DisplayRole) == "Important Data"

    # Verify _report_layout_mismatch shows informative QMessageBox
    dialog_shown = []
    def fake_info(parent, title, msg, buttons):
        dialog_shown.append((title, msg))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    grid._report_layout_mismatch()

    assert len(dialog_shown) == 1
    title, msg = dialog_shown[0]
    assert "3 column(s)" in msg
    assert "4 column(s)" in msg


def test_reset_layout_no_template_returns_false_and_records_reason(monkeypatch):
    """Missing template returns False and informs the user."""
    host = _MockSettingsHost()  # no table_default_layout
    grid = TableGridWidget(settings_host=host)
    grid.load_markdown("| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n")

    assert grid.apply_default_layout() is False
    assert grid._last_apply_error == "no_template"

    dialog_shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda p, t, m, b: dialog_shown.append((t, m)))
    grid._report_layout_mismatch()

    assert len(dialog_shown) == 1
    _, msg = dialog_shown[0]
    assert "Save Current Table Layout as Default" in msg


def test_open_table_edit_dialog_passes_main_win_settings_host(monkeypatch):
    """open_table_edit_dialog extracts main_win and passes it to TableEditDialog."""
    host = _MockSettingsHost()
    editor = _MockEditor(main_win=host)

    md = "| Col1 | Col2 |\n| --- | --- |\n| a | b |\n"
    editor.setPlainText(md)
    cur = editor.textCursor()
    cur.setPosition(2)
    editor.setTextCursor(cur)

    opened = []
    def fake_exec(self):
        opened.append(self)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TableEditDialog, "exec", fake_exec)
    res = open_table_edit_dialog(editor)

    assert res is True
    assert len(opened) == 1
    assert opened[0].settings_host is host


def test_menu_apply_default_user_declines(monkeypatch):
    """When user answers No to confirmation, apply_default_layout is not executed."""
    host = _MockSettingsHost()
    grid = TableGridWidget(settings_host=host)
    grid.load_markdown("| A | B |\n|---|---|\n| 1 | 2 |\n")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    called = []
    monkeypatch.setattr(grid, "apply_default_layout", lambda: called.append(True))

    grid._menu_apply_default()
    assert len(called) == 0


def test_menu_apply_default_user_confirms_mismatch_shows_dialog(monkeypatch):
    """When user confirms Yes and layout fails, informative mismatch dialog is shown."""
    tpl = _make_template(cols=4, rows=3, width=195)
    host = _MockSettingsHost(table_default_layout=json.dumps(tpl))
    grid = TableGridWidget(settings_host=host)
    grid.load_markdown("| A | B |\n|---|---|\n| 1 | 2 |\n")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    info_shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: info_shown.append(a))

    grid._menu_apply_default()
    assert len(info_shown) == 1
    assert "2 column(s)" in info_shown[0][2]
    assert "4 column(s)" in info_shown[0][2]

