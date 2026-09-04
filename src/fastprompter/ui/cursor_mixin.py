"""Custom-cursor handling for the main window (T-785 extraction).

Moved verbatim out of ``FastPrompter`` (main.py) so the monolith shrinks
and the cursor logic lives where the other UI concerns already do.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMessageBox

from fastprompter.core.translations import tr


class CursorMixin:
    def themed_cursor(self, shape):
        """The user's own cursor for a shape, or the stock shape.

        Everything that sets a cursor goes through here, so the toggle is a
        single switch rather than a hunt through every setCursor call.
        """
        if self.data.get("custom_cursors", "False") != "True":
            return shape
        cache = getattr(self, "_cursor_map", None)
        if cache is None:
            cache = self._cursor_map = self._build_cursor_map()
        return cache.get(shape, shape)

    def _build_cursor_map(self):
        from fastprompter.ui.cursor_theme import build_cursor_map
        try:
            return build_cursor_map()
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("could not read the cursor scheme")
            return {}

    def apply_custom_cursors(self):
        """Apply (or drop) the user's cursor set across the window."""
        on = self.data.get("custom_cursors", "False") == "True"
        self._cursor_map = self._build_cursor_map() if on else {}
        # the margin arrow is the set's own arrow mirrored, so it goes stale
        # the moment the set changes - or the old one is drawn forever
        from fastprompter.ui.editor import reset_margin_cursor
        reset_margin_cursor()
        arrow = self.themed_cursor(Qt.CursorShape.ArrowCursor)
        beam = self.themed_cursor(Qt.CursorShape.IBeamCursor)
        try:
            if on:
                self.setCursor(arrow)
                self.text_area.viewport().setCursor(beam)
            else:
                # unsetCursor, not setCursor(ArrowCursor): children must go
                # back to inheriting rather than being pinned to an arrow
                self.unsetCursor()
                self.text_area.viewport().setCursor(
                    Qt.CursorShape.IBeamCursor)
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("could not apply cursors")
        # The static override draws the ARROW of whichever set is active, so a
        # set change has to refresh it or the old image stays on screen.
        self.apply_static_cursor()
        return on

    # -- one static pointer image ------------------------------------------
    def static_cursor_enabled(self) -> bool:
        return self.data.get("static_cursor", "False") == "True"

    def apply_static_cursor(self):
        """Freeze the pointer image app-wide, or release it. Idempotent.

        An application OVERRIDE cursor, not a per-widget one: the shape changes
        the setting is about (I-beam over text, pointing hand over a link or a
        button, resize arrows on a splitter) are set by dozens of widgets and by
        Qt itself, and an override outranks all of them at once instead of
        needing every call site to ask permission first.
        """
        on = self.static_cursor_enabled()
        app = QApplication.instance()
        if app is None:
            return on
        applied = bool(getattr(self, "_static_cursor_applied", False))
        if on:
            arrow = self.themed_cursor(Qt.CursorShape.ArrowCursor)
            cursor = arrow if isinstance(arrow, QCursor) else QCursor(arrow)
            # changeOverrideCursor replaces OUR push; setOverrideCursor again
            # would stack a second one that no single restore could undo.
            if applied:
                app.changeOverrideCursor(cursor)
            else:
                app.setOverrideCursor(cursor)
                self._static_cursor_applied = True
        elif applied:
            app.restoreOverrideCursor()
            self._static_cursor_applied = False
        return on

    def toggle_static_cursor(self, checked):
        self.data["static_cursor"] = "True" if checked else "False"
        self.mark_dirty()
        self.apply_static_cursor()

    def toggle_custom_cursors(self, checked):
        # Turning it on with nothing copied yet would be a no-op, so grab
        # the set now: the program is meant to carry its OWN copy, not to
        # mirror whatever Windows happens to be drawing at the moment.
        if checked:
            from fastprompter.ui.cursor_theme import load_bundle
            if not load_bundle()[1] and not self.capture_cursor_set(quiet=True):
                self.cb_custom_cursors.blockSignals(True)
                self.cb_custom_cursors.setChecked(False)
                self.cb_custom_cursors.blockSignals(False)
                lang = getattr(self, "_current_lang", "EN")
                QMessageBox.information(
                    self, tr("Cursors", lang),
                    tr("No cursor files could be copied from your system.",
                       lang))
                return
        self.data["custom_cursors"] = "True" if checked else "False"
        self.mark_dirty()
        self.apply_custom_cursors()

    def capture_cursor_set(self, quiet=False):
        """Copy the live Windows cursor set into the program."""
        from fastprompter.ui.cursor_theme import capture_current_scheme
        lang = getattr(self, "_current_lang", "EN")
        name, paths = capture_current_scheme()
        if not paths:
            if not quiet:
                QMessageBox.information(
                    self, tr("Cursors", lang),
                    tr("No cursor files could be copied from your system.",
                       lang))
            return False
        self._cursor_map = None          # force a rebuild from the new copy
        if self.data.get("custom_cursors", "False") == "True":
            self.apply_custom_cursors()
        if not quiet:
            QMessageBox.information(
                self, tr("Cursors", lang),
                tr("Copied {} cursors into the program.", lang).format(len(paths))
                if "{}" in tr("Copied {} cursors into the program.", lang)
                else f"{len(paths)} cursors copied.")
        return True

    def install_cursors_to_system(self):
        """Explicit button: make this set the live Windows scheme."""
        from fastprompter.ui.cursor_theme import install_to_system, load_bundle
        lang = getattr(self, "_current_lang", "EN")
        name, paths = load_bundle()
        if not paths:
            QMessageBox.information(
                self, tr("Cursors", lang),
                tr("Copy a cursor set into the program first.", lang))
            return False
        answer = QMessageBox.question(
            self, tr("Cursors", lang),
            tr("Set this cursor scheme as the Windows default?\n"
               "It changes the cursor everywhere, not just here.", lang),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        ok = install_to_system(paths)
        if not ok:
            QMessageBox.warning(
                self, tr("Cursors", lang),
                tr("Could not write the cursor scheme.", lang))
        return ok
