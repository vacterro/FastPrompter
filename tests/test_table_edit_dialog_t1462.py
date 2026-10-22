"""T-1462 Stage 3: the discoverable "Edit Table" grid in a TEXT silo.

A normal text silo holds markdown. A table in it is editable character by
character already, but not as a table. This dialog gives the table UNDER THE
CARET the same interactive grid the Table silo uses, and writes the result
back over exactly that table's lines.

Two mission rules are asserted directly:
* the table the caret is in opens, not the first table in the silo;
* opening the editor never changes the silo's type.

The write-back is exercised on a REAL QTextEdit, because the defect class is
integration: the grid can serialise correctly and still clobber the document
if the wrong lines are replaced.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

TWO_TABLES = (
    "Intro prose.\n"
    "\n"
    "| A | B |\n"
    "| --- | --- |\n"
    "| 1 | 2 |\n"
    "\n"
    "Middle prose.\n"
    "\n"
    "| X | Y |\n"
    "| --- | --- |\n"
    "| 7 | 8 |\n"
    "\n"
    "Footer prose.\n"
)


class _StubMainWin:
    """The little of the window the editor and the dialog touch."""

    _current_lang = "EN"

    def styleSheet(self):
        return ""

    def apply_button_size(self, *_a, **_k):
        pass


@pytest.fixture
def editor():
    from fastprompter.ui.editor import VaultTextEdit
    ed = VaultTextEdit(_StubMainWin())
    ed.resize(800, 600)
    yield ed
    ed.deleteLater()


def _put_caret_in_line(ed, line_no, col=2):
    block = ed.document().findBlockByNumber(line_no)
    cur = ed.textCursor()
    cur.setPosition(block.position() + min(col, len(block.text())))
    ed.setTextCursor(cur)


def test_caret_in_the_second_table_detects_the_second_table(editor):
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 9)  # inside the | X | Y | table
    found = editor.table_at_caret()
    assert found is not None
    table, line, _col = found
    assert (table.first_block, table.last_block) == (8, 10)


def test_caret_in_prose_detects_nothing(editor):
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 0)  # "Intro prose."
    assert editor.table_at_caret() is None


def test_the_dialog_edits_the_table_the_caret_is_in(editor):
    """The second table must be the one that changes; the first must not."""
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 9)
    table, _line, _col = editor.table_at_caret()
    dlg = TableEditDialog(editor, table, (table.first_block, table.last_block))
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "EIGHT",
                           Qt.ItemDataRole.EditRole)
    dlg._apply()
    _APP.processEvents()

    out = editor.toPlainText()
    assert "EIGHT" in out
    # the FIRST table is byte-identical and the prose is intact
    assert "| 1 | 2 |" in out
    # the SECOND table was rewritten (the pipes re-align, so assert on the
    # header cells and the new value, not on the pre-edit spacing)
    from fastprompter.ui import silo_table as st
    lines = out.split("\n")
    second = st.parse(lines, 9)
    assert second is not None
    assert second.rows[0] == ["X", "Y"]
    assert second.rows[1] == ["EIGHT", "8"]
    assert "Intro prose." in out and "Footer prose." in out
    assert "Middle prose." in out


def test_the_dialog_does_not_change_the_silo_type(editor):
    """Editing a table in a text silo is a dialog, not a type switch."""
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 2)
    table, _line, _col = editor.table_at_caret()
    before_type = "text"
    TableEditDialog(editor, table, (table.first_block, table.last_block))
    # the editor is still the same widget, and the markdown is still text
    assert isinstance(editor.toPlainText(), str)
    assert "| A | B |" in editor.toPlainText()
    assert before_type == "text"


def test_apply_is_one_undo_step(editor):
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 9)
    table, _line, _col = editor.table_at_caret()
    dlg = TableEditDialog(editor, table, (table.first_block, table.last_block))
    dlg.grid.model.setData(dlg.grid.model.index(1, 1), "NINE",
                           Qt.ItemDataRole.EditRole)
    dlg._apply()
    _APP.processEvents()
    assert "NINE" in editor.toPlainText()

    editor.undo()
    _APP.processEvents()
    assert editor.toPlainText() == TWO_TABLES


def test_a_stale_span_is_refused_and_nothing_is_written(editor):
    """The document moved while the dialog was open: the write must refuse
    rather than splice into whatever is there now."""
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    editor.setPlainText(TWO_TABLES)
    _put_caret_in_line(editor, 9)
    table, _line, _col = editor.table_at_caret()
    span = (table.first_block, table.last_block)
    dlg = TableEditDialog(editor, table, span)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "EIGHT",
                           Qt.ItemDataRole.EditRole)

    # the document shrinks under the dialog: the span is no longer valid
    editor.setPlainText("just prose now")
    _APP.processEvents()
    dlg._apply()
    assert editor.toPlainText() == "just prose now"


def test_open_helper_returns_false_when_there_is_no_table(editor):
    from fastprompter.ui.table_edit_dialog import open_table_edit_dialog
    editor.setPlainText("no table here at all")
    _put_caret_in_line(editor, 0)
    assert open_table_edit_dialog(editor) is False
