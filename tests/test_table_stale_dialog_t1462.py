"""T-1462 Stage 2: a stale table dialog cannot overwrite newer content.

The defect boundary: `TableEditDialog` captured a line span but never the
table CONTENT. `replace_region` rejects out-of-range coordinates, but a
SAME-LENGTH concurrent modification stays inside the span arithmetic — so a
dialog left open while the table was edited (or the table was replaced by one
with the same number of lines) would overwrite the newer bytes with its own
stale copy.

These tests drive a real `QTextEdit` and the real dialog. The oracle is the
live document's bytes: a refused Apply must change nothing.
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

ONE_TABLE = (
    "Header prose.\n"
    "\n"
    "| A | B |\n"
    "| --- | --- |\n"
    "| 1 | 2 |\n"
    "\n"
    "Footer prose.\n"
)


class _StubMainWin:
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


def _caret(ed, line_no, col=2):
    block = ed.document().findBlockByNumber(line_no)
    cur = ed.textCursor()
    cur.setPosition(block.position() + min(col, len(block.text())))
    ed.setTextCursor(cur)


def _open(ed, line_no):
    from fastprompter.ui.table_edit_dialog import TableEditDialog
    _caret(ed, line_no)
    table, _line, _col = ed.table_at_caret()
    span = (table.first_block, table.last_block)
    return TableEditDialog(ed, table, span)


# --------------------------------------------------- capture + verify units

def test_capture_and_verify_round_trip():
    from fastprompter.ui import table_edit_target as t
    own = t.capture_ownership(ONE_TABLE, (2, 4))
    assert own is not None
    assert t.verify_ownership(ONE_TABLE, own) is True


def test_a_same_length_content_change_breaks_verification():
    """The exact hole the span arithmetic left open."""
    from fastprompter.ui import table_edit_target as t
    own = t.capture_ownership(ONE_TABLE, (2, 4))
    stale = ONE_TABLE.replace("| 1 | 2 |", "| 9 | 8 |")  # same length
    assert len(stale) == len(ONE_TABLE)
    assert t.verify_ownership(stale, own) is False


def test_a_moved_table_breaks_verification():
    from fastprompter.ui import table_edit_target as t
    own = t.capture_ownership(ONE_TABLE, (2, 4))
    shifted = "extra line\n" + ONE_TABLE
    assert t.verify_ownership(shifted, own) is False


def test_unrelated_prose_change_above_keeps_the_table_verifiable():
    """A prose edit outside the table must NOT block a valid Apply."""
    from fastprompter.ui import table_edit_target as t
    own = t.capture_ownership(ONE_TABLE, (2, 4))
    changed = ONE_TABLE.replace("Header prose.", "Different header prose.")
    # the table lines are still at the same span and identical
    assert t.verify_ownership(changed, own) is True


def test_a_replaced_document_breaks_verification():
    from fastprompter.ui import table_edit_target as t
    own = t.capture_ownership(ONE_TABLE, (2, 4))
    assert t.verify_ownership("completely different\n\ntext\n", own) is False


# --------------------------------------------------- end-to-end Apply cases

def test_apply_refuses_when_the_table_changed_to_the_same_length(editor):
    """Case A: equal-length concurrent modification. Nothing may be written."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "STALE",
                           Qt.ItemDataRole.EditRole)

    # a same-length edit lands on the live document under the dialog
    stale_live = ONE_TABLE.replace("| 1 | 2 |", "| 5 | 6 |")
    assert len(stale_live) == len(ONE_TABLE)
    editor.setPlainText(stale_live)
    _APP.processEvents()
    before = editor.toPlainText()

    dlg._apply()
    _APP.processEvents()
    assert editor.toPlainText() == before, "stale Apply must not change bytes"
    assert "STALE" not in editor.toPlainText()
    assert dlg.result() != dlg.DialogCode.Accepted


def test_apply_refuses_when_the_header_changed(editor):
    """Case B: the header was edited while the dialog was open."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 1), "NEW",
                           Qt.ItemDataRole.EditRole)

    editor.setPlainText(ONE_TABLE.replace("| A | B |", "| C | D |"))
    _APP.processEvents()
    before = editor.toPlainText()
    dlg._apply()
    _APP.processEvents()
    assert editor.toPlainText() == before


def test_apply_refuses_when_the_table_moved(editor):
    """Case C: the table moved to another region."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "NEW",
                           Qt.ItemDataRole.EditRole)
    editor.setPlainText("new first line\n\n" + ONE_TABLE)
    _APP.processEvents()
    before = editor.toPlainText()
    dlg._apply()
    _APP.processEvents()
    assert editor.toPlainText() == before


def test_apply_refuses_a_delete_and_recreate_of_a_similar_table(editor):
    """Case D: a different table with the same shape occupies the span."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "NEW",
                           Qt.ItemDataRole.EditRole)
    other = ONE_TABLE.replace("| A | B |", "| Z | W |")
    editor.setPlainText(other)
    _APP.processEvents()
    before = editor.toPlainText()
    dlg._apply()
    _APP.processEvents()
    assert editor.toPlainText() == before


def test_apply_succeeds_when_only_surrounding_prose_changed(editor):
    """Case F: the target table is unchanged, so a valid Apply lands."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "APPLIED",
                           Qt.ItemDataRole.EditRole)
    edited = ONE_TABLE.replace("Footer prose.", "Different footer prose.")
    editor.setPlainText(edited)
    _APP.processEvents()
    dlg._apply()
    _APP.processEvents()
    out = editor.toPlainText()
    assert "APPLIED" in out
    assert "Different footer prose." in out


def test_apply_refuses_when_the_document_identity_changed(editor):
    """Case G: the whole document was replaced by an unrelated one."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "NEW",
                           Qt.ItemDataRole.EditRole)
    editor.setPlainText("unrelated\n\nprose\n\nwith no table at all\n")
    _APP.processEvents()
    before = editor.toPlainText()
    dlg._apply()
    _APP.processEvents()
    assert editor.toPlainText() == before


def test_a_valid_apply_is_one_coherent_undo_transaction(editor):
    """Case I: a valid Apply lands as ONE undo step."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "ONE",
                           Qt.ItemDataRole.EditRole)
    dlg.grid.model.setData(dlg.grid.model.index(1, 1), "TWO",
                           Qt.ItemDataRole.EditRole)
    dlg._apply()
    _APP.processEvents()
    assert "ONE" in editor.toPlainText() and "TWO" in editor.toPlainText()
    editor.undo()
    _APP.processEvents()
    assert editor.toPlainText() == ONE_TABLE


def test_a_refused_apply_keeps_the_dialog_and_its_edits(editor):
    """The user's uncommitted grid state survives a refusal."""
    editor.setPlainText(ONE_TABLE)
    dlg = _open(editor, 3)
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "KEPT",
                           Qt.ItemDataRole.EditRole)
    editor.setPlainText(ONE_TABLE.replace("| 1 | 2 |", "| 3 | 4 |"))
    _APP.processEvents()
    dlg._apply()
    _APP.processEvents()
    # the dialog was not accepted and the grid still holds the edit
    assert dlg.result() != dlg.DialogCode.Accepted
    assert dlg.grid.model.rows[1][0] == "KEPT"


def test_two_tables_editing_the_first_leaves_the_second_untouched(editor):
    """Case E: edit the first table; the second stays byte-identical."""
    editor.setPlainText(TWO_TABLES)
    dlg = _open(editor, 3)  # inside the FIRST table
    dlg.grid.model.setData(dlg.grid.model.index(1, 0), "FIRST",
                           Qt.ItemDataRole.EditRole)
    dlg._apply()
    _APP.processEvents()
    out = editor.toPlainText()
    assert "FIRST" in out
    assert "| X | Y |" in out
    assert out.count("| X | Y |") == 1
