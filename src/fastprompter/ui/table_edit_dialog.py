"""Edit ONE markdown table in place, from a normal text silo.

A text silo holds markdown, and a markdown table in it can already be edited
character by character. What it cannot do is behave like a table: select a
rectangle, paste a block from Excel, resize a column, insert a row without
counting pipes. This dialog gives the table under the caret the same grid the
Table silo uses, and writes the result back over EXACTLY that table's lines.

Two rules the mission is explicit about, and which shape this module:

* The table the caret is IN is the table that opens — never the first table
  in the silo. The span comes from `table_at_caret`, so a caret in the second
  of two tables edits the second one.
* Opening the editor never changes the silo's TYPE. This is a dialog over the
  document, not a switch to the Table view; the silo stays a text silo and
  the markdown stays the source of truth.

The write-back is `table_edit_target.replace_region`, the same whole-line,
one-undo-step mechanism the Table silo uses, so a table edited here and a
table edited in the Table view land identically.

T-1462 Stage 2: the dialog captures the exact table CONTENT (and its span) at
open time and refuses an Apply when the live document no longer holds that
content — a same-length concurrent modification stays inside the span
arithmetic, so only a content check can detect it. The refusal preserves the
user's uncommitted grid state (the dialog stays open) rather than discarding it.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr
from fastprompter.ui import table_edit_target
from fastprompter.ui.table_grid import TableGridWidget


class TableEditDialog(QDialog):
    """A modal grid over one table region of a text silo."""

    def __init__(self, editor, table, span, lang="EN", settings_host=None):
        super().__init__(editor)
        self.editor = editor
        self.lang = lang
        self.span = span
        if settings_host is None:
            settings_host = getattr(editor, "main_win", None)
        self.settings_host = settings_host

        self.setWindowTitle(tr("Edit Table", lang))
        self.setStyleSheet(editor.main_win.styleSheet()
                           if hasattr(editor, "main_win") else "")
        self.setMinimumSize(560, 360)

        lines = editor.toPlainText().split("\n")
        region = lines[span[0]:span[1] + 1]
        # T-1462 Stage 2: capture the ORIGINAL table content and the document
        # identity. Apply verifies these against the live document, so a stale
        # dialog cannot overwrite a newer table that happens to have the same
        # length.
        self.ownership = table_edit_target.capture_ownership(
            editor.toPlainText(), span)
        self._document_identity = self.ownership.get("doc_rev") if self.ownership else None

        layout = QVBoxLayout(self)
        hint = QLabel(tr("Editing the table at the caret. "
                         "Ctrl+C / Ctrl+V move a rectangular range; "
                         "right-click for rows, columns and alignment.", lang))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.grid = TableGridWidget(self, settings_host=self.settings_host)
        # T-1468: obtain default table template from settings host so newly inserted
        # empty tables receive their visual defaults in modal text editing.
        default_layout = None
        if hasattr(self.settings_host, "_default_table_layout") and callable(self.settings_host._default_table_layout):
            default_layout = self.settings_host._default_table_layout()
        elif hasattr(self.settings_host, "data") and isinstance(getattr(self.settings_host, "data", None), dict):
            from fastprompter.ui import silo_table as st
            default_layout = st.parse_default_layout(self.settings_host.data.get("table_default_layout"))

        # The dialog owns the region, so the grid's own prefix/suffix are the
        # lines around the table; but the write-back is driven by `span`, not
        # by the cached splice, so an unrelated edit cannot ride along.
        self.grid.load_markdown("\n".join(region), default_layout=default_layout)

        layout.addWidget(self.grid, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_ok = QPushButton(tr("Apply", lang))
        self.btn_cancel = QPushButton(tr("Cancel", lang))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

    def _apply(self):
        """Write the table back over its own lines, as one undo step.

        A stale target is refused BEFORE any byte is written: the document
        moved under the dialog, so applying would overwrite newer content.
        The refusal is reported and the dialog stays open, preserving the
        user's uncommitted grid state.
        """
        new_lines = self.grid.model.table_lines()
        if table_edit_target.replace_region(self.editor, self.span, new_lines,
                                            ownership=self.ownership):
            self.accept()
            return
        # Distinguish a stale region (content changed) from a vanished editor.
        # Only notify a human who can actually see the dialog: a headless or
        # programmatic Apply has no user to warn, and a modal box would block.
        if self.isVisible():
            live = self.editor.toPlainText()
            if not table_edit_target.verify_ownership(live, self.ownership):
                QMessageBox.warning(
                    self,
                    tr("Table Changed", self.lang),
                    tr("The table changed while this editor was open. "
                       "Apply was refused so your newer content is not "
                       "overwritten. Close and reopen to edit the current "
                       "table.", self.lang))
        # stay open: the grid still holds the user's uncommitted edits



def open_table_edit_dialog(editor, lang=None, settings_host=None):
    """Open the grid for the table at the caret. False when there is none.

    Detection is the editor's own `table_at_caret`, so "the caret is in a
    table" means exactly what it means everywhere else in the app, and the
    span is the table that caret is in.
    """
    found = editor.table_at_caret()
    if not found:
        return False
    table, _line, _col = found
    if table is None:
        return False
    if lang is None:
        lang = getattr(getattr(editor, "main_win", None), "_current_lang", "EN")
    if settings_host is None:
        settings_host = getattr(editor, "main_win", None)
    span = (table.first_block, table.last_block)
    dlg = TableEditDialog(editor, table, span, lang, settings_host=settings_host)
    dlg.exec()
    return True


__all__ = ["TableEditDialog", "open_table_edit_dialog"]
