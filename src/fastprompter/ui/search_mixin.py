"""Search mixin for FastPrompter — find/replace text functionality.

Extracted from main.py Phase 2b of the modularization plan.
Provides SearchMixin class for use as a mixin with FastPrompter QMainWindow.
"""

from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QMessageBox

from fastprompter.core.translations import tr


class SearchMixin:
    """Mixin providing find/replace UI and logic.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.search_frame, self.replace_input, self.search_input,
        self.text_area, self.btn_replace, self.btn_replace_all
    """

    def show_find(self):
        """Show the find search bar."""
        self.search_frame.show()
        self.replace_input.hide()
        self.btn_replace.hide()
        self.btn_replace_all.hide()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def show_replace(self):
        """Show the find/replace search bar."""
        self.search_frame.show()
        self.replace_input.show()
        self.btn_replace.show()
        self.btn_replace_all.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def close_search(self):
        """Hide the search frame and return focus to text area."""
        self.search_frame.hide()
        self.text_area.setFocus()

    def find_next(self):
        """Find the next occurrence of search text."""
        self.find_text(backward=False)

    def find_prev(self):
        """Find the previous occurrence of search text."""
        self.find_text(backward=True)

    def find_text(self, backward=False):
        """Find text in the text area, wrapping around if needed."""
        text = self.search_input.text()
        if not text:
            return
        options = QTextDocument.FindFlag(0)
        if backward:
            options |= QTextDocument.FindFlag.FindBackward

        found = self.text_area.find(text, options)

        if not found:
            doc = self.text_area.document()
            search_cursor = QTextCursor(doc)
            search_cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            found_cursor = doc.find(text, search_cursor, options)
            if not found_cursor.isNull():
                self.text_area.setTextCursor(found_cursor)

    def replace_text(self):
        """Replace the current selection with replace text, then find next."""
        cursor = self.text_area.textCursor()
        if cursor.hasSelection() and cursor.selectedText().replace('\u2029', '\n') == self.search_input.text():
            cursor.insertText(self.replace_input.text())
        self.find_next()

    def replace_all(self):
        """Replace all occurrences of search text with replace text.

        Uses one document cursor so the search position always advances
        past each replacement — this is both correct (the text_area's own
        cursor was never moved by the old copy-cursor version) and safe
        when the replacement contains the search term (which otherwise
        re-matched forever).
        """
        search_str = self.search_input.text()
        if not search_str:
            return
        replace_str = self.replace_input.text()
        doc = self.text_area.document()
        edit_cursor = self.text_area.textCursor()
        edit_cursor.beginEditBlock()
        count = 0
        find_cur = QTextCursor(doc)
        while True:
            find_cur = doc.find(search_str, find_cur)
            if find_cur.isNull():
                break
            find_cur.insertText(replace_str)
            # find_cur now sits at the end of the inserted text, so the
            # next search starts after it — no re-match, guaranteed progress
            count += 1
        edit_cursor.endEditBlock()
        lang = getattr(self, '_current_lang', 'EN')
        QMessageBox.information(self, tr("Replace All", lang), tr("Replaced {} occurrences.", lang).format(count))

    def on_search_toggle(self, checked):
        """Toggle the sidebar search bar visibility."""
        self.search_bar.setVisible(checked)
        self.data["search_visible"] = str(checked)
        self.mark_dirty()
        if checked:
            self.search_bar.setFocus()
        else:
            self.search_bar.clear()
