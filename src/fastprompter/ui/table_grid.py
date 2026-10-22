"""The interactive table grid: QTableView over TableCellsModel.

This replaces the QGridLayout-of-QLineEdits grid that used to live in
`table_widget.py`. The old grid had no rectangular selection, no column
resizing, no working clipboard beyond one cell, and no way to drag a range —
every one of those had to be hand-built on Qt's widget system. QTableView +
QAbstractTableModel + QHeaderView + the default delegate provide all of it.

What is left to write is the part that is genuinely ours:
* Markdown stays canonical — the model reads `silo_table.parse` and writes
  `silo_table.render`, the SAME two functions the plain-text path uses.
* The write-back goes to exactly the region the grid owns (`_visual_span`),
  so a table in a silo with a title, notes and a second table is never
  reached past.
* Customisation is limited: one cell selection at a time, no row/column
  dragging, no formulas, no macros, no separate spreadsheet engine.

`cells[row][column]` is kept as a compatibility view over the model so
existing callers (and the tests that drive a real edit by emitting
`textEdited`) keep working without knowing a QTableView is in between.
"""

from __future__ import annotations

import itertools

from PyQt6.QtCore import QModelIndex, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.translations import tr
from fastprompter.ui.table_model import TableCellsModel

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = "left", "center", "right"

#: Process-wide, so two widgets constructed in the same tick never collide.
_IDENTITY_SEQ = itertools.count(1)


def is_settings_host(obj: object) -> bool:
    """True if obj provides settings persistence (.data dict and .mark_dirty callback)."""
    return (
        obj is not None
        and hasattr(obj, "data")
        and isinstance(getattr(obj, "data", None), dict)
        and callable(getattr(obj, "mark_dirty", None))
    )


class _CellHandle(QObject):
    """A stand-in for the old CellWidget: reads and writes one model cell.

    The editor is now a delegate over the model, so a persistent widget per
    cell is gone. Callers that still work with a "cell" get this: `.text()`
    reads the model, `setText()` writes the rows, and `.textEdited` is a real
    signal that arms the coalescing sync — which is what let the timer fire on
    a real edit and stay quiet on a programmatic set, exactly as the old
    QLineEdit did.
    """

    textEdited = pyqtSignal(str)

    def __init__(self, grid, row, column):
        super().__init__(grid)
        self._grid = grid
        self._row = row
        self._column = column

    def text(self):
        return self._grid.model.rows[self._row][self._column]

    def setText(self, text):
        # Programmatic, like QLineEdit.setText: silent. A user edit is the
        # delegate writing through setData, which the model reports.
        is_valid, reason = self._grid.model.validate_cell_value(text)
        if not is_valid:
            self._grid.model.edit_refusal = reason
            self._grid.model.paste_refusal = reason
            return False
        self._grid.model.rows[self._row][self._column] = text
        self._grid._model_changed()
        return True

    def property(self, name):
        if name == "header":
            return "true" if (self._grid.model.has_header
                             and self._row == 0) else None
        return None

    def styleSheet(self):
        return ""

    def setAlignment(self, _value):
        pass

    def setFocus(self):
        self._grid.view.setCurrentIndex(
            self._grid.model.index(self._row, self._column))


class _CellsProxy:
    """`grid.cells[row][column]` over the model's rows.

    Handles are cached so `.textEdited` is a stable signal per cell rather
    than a fresh connection on every access.
    """

    def __init__(self, grid):
        self._grid = grid
        self._cache: dict[tuple[int, int], _CellHandle] = {}

    def __len__(self):
        return len(self._grid.model.rows)

    def __iter__(self):
        for r in range(len(self._grid.model.rows)):
            yield self[r]

    def _handle(self, row, column):
        key = (row, column)
        h = self._cache.get(key)
        if h is None:
            h = _CellHandle(self._grid, row, column)
            h.textEdited.connect(self._grid._schedule_sync)
            self._cache[key] = h
        return h

    def __getitem__(self, row):
        rows = self._grid.model.rows
        if row >= len(rows):
            raise IndexError(row)
        width = self._grid.model._width()
        return [self._handle(row, c) for c in range(width)]

    def __setitem__(self, row, value):
        self._grid.model.rows[row] = list(value)
        self._grid._model_changed()


class TableGridWidget(QWidget):
    """A markdown table you can edit with a mouse.

    Signals
    -------
    changed = pyqtSignal(str)
        The whole silo, rebuilt with this grid's table in place. main.py maps
        that onto the region the grid owns.
    undoRequested = pyqtSignal()
        Ctrl+Z, when the grid is the focused editing surface.
    redoRequested = pyqtSignal()
        Ctrl+Y / Ctrl+Shift+Z, likewise.
    """

    changed = pyqtSignal(str)
    undoRequested = pyqtSignal()
    redoRequested = pyqtSignal()

    def __init__(self, parent=None, settings_host=None):
        super().__init__(parent)
        self._settings_host = settings_host
        self._last_apply_error = None
        self._visual_source = ""
        # T-1462: the whole-line span this widget owns, or None before a load.
        self._visual_span = None
        # T-1462 Stage 2: ownership is not just the line range. A region is
        # only meaningful together with WHAT table it was and WHICH revision
        # of it last reached the document: the widget adds a row, the table
        # grows by a line, and the range it still carries from load is one
        # line short of what it now owns. `_identity` says which table this
        # is, `_revision` counts writes that landed, and `note_write_back` is
        # the single place the range is re-derived after a write.
        self._identity = None
        self._revision = 0
        self._prefix: list[str] = []
        self._suffix: list[str] = []
        # T-1462 Stage 6: a section knows whether its size is AUTOMATIC (fit
        # to content, and safe to re-fit) or MANUAL (the user dragged it, and
        # no structural command may touch it again). Without the distinction,
        # one inserted row re-fitted every column and threw the user's widths
        # away — which is what made the grid feel like it lost its layout.
        self._manual_cols: set[int] = set()
        self._manual_rows: set[int] = set()
        #: True while THIS code is resizing, so a programmatic resize is not
        #: mistaken for the user dragging a section handle.
        self._sizing = False

        self.model = TableCellsModel(self)

        self.view = QTableView(self)
        self.view.setObjectName("silo_table_grid")
        self.view.setModel(self.model)
        # A table IS a grid of cells, so the grid of cells is the selection:
        # one item at a time, rectangular, dragged with the mouse.
        self.view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        self.view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.view.setCornerButtonEnabled(False)
        self.view.setShowGrid(True)
        # Resize to content, but let the user drag: a column that holds a
        # long command is a column the user must be able to widen.
        self.view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.view.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setSectionsClickable(False)
        self.view.verticalHeader().setSectionsClickable(False)
        self.view.setAlternatingRowColors(False)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        # A drag on a section handle is the ONLY manual resize: every other
        # resize in this class runs inside the `_sizing` guard.
        hh, vh = self.view.horizontalHeader(), self.view.verticalHeader()
        hh.sectionResized.connect(
            lambda i, _o, _n: self._on_section_resized(i, columns=True))
        vh.sectionResized.connect(
            lambda i, _o, _n: self._on_section_resized(i, columns=False))

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(500)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._do_serialize)

        # T-1462 Stage 6: the add controls are real buttons. A QLabel with a
        # click handler is invisible to the keyboard and to a screen reader —
        # it cannot be tabbed to and announces nothing. QPushButton gives both
        # for free, and its tooltip/accessible name is translated.
        lang = getattr(parent, "lang", None) or getattr(parent, "_current_lang", None)
        if lang is None and settings_host is not None:
            lang = getattr(settings_host, "_current_lang", None)
        if lang is None and hasattr(self, "_current_lang"):
            lang = self._current_lang
        self.btn_add_col = QPushButton("+")
        self.btn_add_col.setObjectName("table_add")
        self.btn_add_col.setToolTip(tr("Add Column", lang))
        self.btn_add_col.setAccessibleName(tr("Add Column", lang))
        self.btn_add_col.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_add_col.clicked.connect(self._add_column)

        self.btn_add_row = QPushButton(tr("+ Row", lang))
        self.btn_add_row.setObjectName("table_add")
        self.btn_add_row.setToolTip(tr("Add Row", lang))
        self.btn_add_row.setAccessibleName(tr("Add Row", lang))
        self.btn_add_row.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_add_row.clicked.connect(self._add_row)

        bar = QHBoxLayout()
        bar.setContentsMargins(4, 0, 4, 4)
        bar.setSpacing(6)
        bar.addWidget(self.btn_add_col)
        bar.addWidget(self.btn_add_row)
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addLayout(bar)

        self.model.dataChanged.connect(lambda *a: self._schedule_sync())
        for sig in ("rowsInserted", "rowsRemoved",
                    "columnsInserted", "columnsRemoved"):
            getattr(self.model, sig).connect(lambda *a: self._schedule_sync())
        # T-1462 Stage 6: the manual flags ride the same renumbering Qt applies
        # to the sections, or a deleted column would inherit the flag that
        # belonged to its neighbour.
        for sig, columns in (("columnsInserted", True), ("columnsRemoved", True),
                             ("rowsInserted", False), ("rowsRemoved", False)):
            getattr(self.model, sig).connect(
                lambda _p, first, last, c=columns, s=sig: self._remap_manual(
                    first, last - first + 1, "Inserted" in s, c))
        self.model.layoutChanged.connect(lambda *a: self._schedule_sync())

        self._cells = _CellsProxy(self)

    # ---- compat API -----------------------------------------------------
    @property
    def cells(self):
        """`cells[row][column]` over the model, the shape the old grid
        exposed. A caller should not need to know a QTableView is in between.
        """
        return self._cells

    @property
    def alignments(self):
        return [self._qt_align(a) for a in self.model.aligns]

    @staticmethod
    def _qt_align(a):
        return {
            ALIGN_CENTER: Qt.AlignmentFlag.AlignCenter,
            ALIGN_RIGHT: Qt.AlignmentFlag.AlignRight,
        }.get(a, Qt.AlignmentFlag.AlignLeft)

    # ---- load -----------------------------------------------------------
    def load_markdown(self, text, span=None, layout=None, default_layout=None,
                      restore_scroll=True):
        """Build the grid from `text`, owning the table region in it.

        The lines around the table are kept so the write-back splices them
        back exactly. Without this the silo's title became the header row:
        measured on "# Weekly report\\n\\n Notes\\n\\n| Name | Qty |..." the
        widget serialised `| # Weekly report |\\n|--- |` and the rest was
        gone.

        `layout` restores a saved per-silo presentation (T-1462 Stage 5) instead
        of autofitting. A layout whose shape no longer matches falls back to
        autofit, so a table that gained a column still sizes to content.

        `default_layout` (T-1466) applies the user's global table template to
        NEW tables (empty/default structure). Only used when `layout` is None.

        `restore_scroll` (T-1466) gates scroll position restoration. When
        False, the table opens at top-left regardless of saved scroll.
        """
        from fastprompter.ui import silo_region

        self._visual_source = text or ""
        all_lines = self._visual_source.split("\n")
        if span is None:
            span = silo_region.table_region(all_lines)
        self._prefix, region, self._suffix = silo_region.split(all_lines, span)
        # The ONLY lines this widget owns. T-1462: the write-back replaces
        # exactly these lines in the live document instead of the whole silo,
        # so a stale cached prefix/suffix can no longer consume unrelated text.
        self._visual_span = span
        # A fresh load is a NEW table identity, and revision restarts: the
        # span, the rows and the document are all consistent with each other
        # as of this moment, whatever came before.
        self._identity = next(_IDENTITY_SEQ)
        self._revision = 0
        self.model.load_markdown(text, span=span)
        # Priority: per-silo saved layout > default template > autofit
        # T-1466: default template only applies to NEW empty tables (no saved
        # per-silo layout AND all body cells empty). Existing tables with
        # content fall back to autofit, never the template.
        applied = False
        if layout is not None:
            applied = self.apply_presentation(layout, restore_scroll=restore_scroll)
        if not applied and default_layout is not None and self._is_empty_table():
            applied = self.apply_presentation(default_layout, restore_scroll=restore_scroll)
        if not applied:
            self._autofit()
        # T-1466 Stage 5: focus A2 (first body cell) on NEW empty tables.
        # No auto-edit mode, no focus stealing — just place the cursor.
        if layout is None and default_layout is not None and self._is_empty_table():
            if self.model.rowCount() > 1 and self.model.columnCount() > 0:
                idx = self.model.index(1, 0)  # row 1 = first body, col 0 = A
                self.view.setCurrentIndex(idx)
                self.view.setFocus()
        return span

    def _is_empty_table(self) -> bool:
        """True when every cell (header and body) is empty (T-1466 / T-1468).

        Used to distinguish a NEW empty table from an existing table that
        happens to have no saved presentation. The default template applies
        only to the former.
        """
        for row in range(self.model.rowCount()):
            for col in range(self.model.columnCount()):
                idx = self.model.index(row, col)
                val = self.model.data(idx, Qt.ItemDataRole.DisplayRole)
                if val and str(val).strip():
                    return False
        return True

    def apply_presentation(self, layout: dict | None, restore_scroll=True) -> bool:
        """Restore saved column widths / row heights (T-1462 Stage 5).

        Presentation is persisted separately from the Markdown: the silo's text
        is the source of truth for CONTENT, but a column the user widened is a
        layout choice that should survive a reload. The saved layout is keyed
        by the same silo identity that owns the document, so it can never be
        applied to a different table.

        Returns True when the layout was applied. A layout whose column count
        no longer matches the table is refused (the user inserted or deleted a
        column since it was saved) and the caller falls back to autofit.

        T-1466: also restores scroll position (h_scroll/v_scroll) when present
        and ``restore_scroll`` is True. The caller gates this on the
        "Remember Silo Scroll Position" toggle.
        """
        if not layout:
            return False
        cols = layout.get("cols")
        rows = layout.get("rows")
        if not isinstance(cols, list):
            # The stored template names the same arrays col_widths/row_heights.
            cols = layout.get("col_widths")
        if not isinstance(rows, list):
            rows = layout.get("row_heights")
        if not isinstance(cols, list) or not isinstance(rows, list):
            return False
        if len(cols) != self.model.columnCount():
            return False
        hh = self.view.horizontalHeader()
        vh = self.view.verticalHeader()
        self._sizing = True
        try:
            for i, w in enumerate(cols):
                if isinstance(w, (int, float)) and w > 0:
                    hh.resizeSection(i, int(w))
            for i, h in enumerate(rows):
                if isinstance(h, (int, float)) and h > 0:
                    vh.resizeSection(i, int(h))
            # T-1462 Stage 6: the manual flags come back WITH the sizes. A
            # layout saved before this distinction has no flags, and it is
            # applied exactly as it was — automatic, nothing remembered.
            self._manual_cols = {i for i in layout.get("manual_cols", [])
                                 if isinstance(i, int) and 0 <= i < len(cols)}
            self._manual_rows = {i for i in layout.get("manual_rows", [])
                                 if isinstance(i, int) and 0 <= i < len(rows)}
            # T-1466: the saved template owns the wrap preference; a per-silo
            # layout carries no word_wrap key and leaves the view alone.
            if "word_wrap" in layout:
                self.view.setWordWrap(bool(layout["word_wrap"]))
            # T-1466 Stage 6: restore scroll position (gated by toggle)
            if restore_scroll:
                h_scroll = layout.get("h_scroll")
                v_scroll = layout.get("v_scroll")
                if isinstance(h_scroll, (int, float)) and h_scroll >= 0:
                    self.view.horizontalScrollBar().setValue(int(h_scroll))
                if isinstance(v_scroll, (int, float)) and v_scroll >= 0:
                    self.view.verticalScrollBar().setValue(int(v_scroll))
        finally:
            self._sizing = False
        return True

    def capture_presentation(self) -> dict:
        """Column widths and row heights the user has set, for persistence.

        Autofit-only columns (never resized by the user) report their content
        width, which is what a fresh load would compute anyway — storing them
        is harmless and keeps the round trip lossless. The `manual_*` lists
        are the half that is lost without them: they say which of these sizes
        were deliberately chosen and must survive the next structural command.

        T-1466: scroll position is captured here too, so it survives with the
        presentation when "Remember Silo Scroll Position" is ON.
        """
        hh = self.view.horizontalHeader()
        vh = self.view.verticalHeader()
        cols = [hh.sectionSize(i) for i in range(self.model.columnCount())]
        rows = [vh.sectionSize(i) for i in range(self.model.rowCount())]
        # Scroll position — saved regardless of the toggle; the toggle only
        # controls whether restore applies it.
        h_scroll = self.view.horizontalScrollBar().value()
        v_scroll = self.view.verticalScrollBar().value()
        return {"cols": cols, "rows": rows,
                "manual_cols": sorted(self._manual_cols),
                "manual_rows": sorted(self._manual_rows),
                "h_scroll": h_scroll, "v_scroll": v_scroll}

    def get_settings_host(self):
        """Return the bound settings host, or parent if it satisfies the contract."""
        if self._settings_host is not None:
            return self._settings_host
        parent = self.parent()
        if is_settings_host(parent):
            return parent
        return None

    def set_settings_host(self, host):
        """Bind an explicit settings persistence host."""
        self._settings_host = host

    def _require_settings_host(self):
        """Validate and return settings host, raising RuntimeError on missing host."""
        host = self.get_settings_host()
        if not is_settings_host(host):
            raise RuntimeError(
                "TableGridWidget settings operation requires a settings host with "
                ".data (dict) and .mark_dirty(topic)."
            )
        return host

    def save_as_default_layout(self):
        """Save the current table layout as the user's default template (T-1466 / T-1468).

        Captures column count, visible row count, widths, heights, manual/auto
        flags, and word-wrap setting. Stores as a versioned dict in
        ``table_default_layout`` setting. Empty template only — no cell content.
        """
        import json
        host = self._require_settings_host()
        pres = self.capture_presentation()
        template = {
            "version": 1,
            "columns": self.model.columnCount(),
            "visible_rows": self.model.rowCount(),
            "col_widths": pres["cols"],
            "row_heights": pres["rows"],
            "manual_cols": pres["manual_cols"],
            "manual_rows": pres["manual_rows"],
            "word_wrap": self.view.wordWrap(),
        }
        # Store as JSON string to match DEFAULT_PROFILE format
        host.data["table_default_layout"] = json.dumps(template)
        host.mark_dirty("settings")

    def apply_default_layout(self):
        """Apply the user's default template to THIS table (T-1466 / T-1468).

        Reads ``table_default_layout`` from settings and applies it to the
        current table. Used by "Reset Table Layout to Default" action.
        """
        from fastprompter.ui import silo_table as st
        host = self._require_settings_host()
        raw = host.data.get("table_default_layout")
        if not raw:
            self._last_apply_error = "no_template"
            return False
        template = st.parse_default_layout(raw)
        if not template:
            self._last_apply_error = "invalid_template"
            return False
        if len(template.get("cols", [])) != self.model.columnCount():
            self._last_apply_error = (
                "shape_mismatch",
                self.model.columnCount(),
                template["columns"],
            )
            return False
        self._last_apply_error = None
        # apply_presentation() reads the template's own key names, so the
        # stored template IS the layout dict -- no lossy re-projection.
        return self.apply_presentation(template)

    def restore_factory_layout(self):
        """Reset the stored template to factory defaults (T-1466 / T-1468).

        Overwrites ``table_default_layout`` with the baked DEFAULT_PROFILE
        value. Does NOT resize the current table.
        """
        from fastprompter.core.default_profile import DEFAULT_PROFILE
        host = self._require_settings_host()
        factory = DEFAULT_PROFILE.get("table_default_layout", "")
        host.data["table_default_layout"] = factory
        host.mark_dirty("settings")

    def note_write_back(self, first: int, line_count: int) -> None:
        """Record that a write-back of `line_count` lines at `first` landed.

        T-1462 Stage 2: after a structural edit the widget owns a different
        number of lines than it did at load, so the caller (which owns the
        live document) tells the widget what it actually wrote. The identity
        stays: this is the SAME table, one revision later. `first` is taken
        from the caller because a table inserted above this one would shift
        the region down, and only the document knows that.
        """
        self._visual_span = (first, first + max(0, line_count) - 1)
        self._revision += 1

    def identity(self):
        """A stable per-widget token: two widgets never share one."""
        return self._identity

    def revision(self):
        return self._revision

    def _autofit(self, columns: bool = True, rows: bool = True):
        """Size to content, but never over a dimension the user set by hand.

        T-1462 Stage 6: this used to call `resizeColumnsToContents()` on every
        structural command, which re-fitted ALL sections — including the ones
        the user had dragged — so one inserted row silently undid the widths.
        Only the AUTOMATIC sections are re-fitted, and only in the axis the
        command actually changed, so a row insertion never touches a column.
        """
        hh = self.view.horizontalHeader()
        vh = self.view.verticalHeader()
        self._sizing = True
        try:
            if columns:
                for c in range(self.model.columnCount()):
                    if c not in self._manual_cols:
                        hh.resizeSection(c, self.view.sizeHintForColumn(c))
            if rows:
                for r in range(self.model.rowCount()):
                    if r not in self._manual_rows:
                        vh.resizeSection(r, self.view.sizeHintForRow(r))
        finally:
            self._sizing = False

    def autofit_all(self):
        """Explicit Auto-fit: re-fit EVERY section, manual ones included.

        The user asked for it, so their earlier widths are the thing being
        replaced rather than collateral damage.
        """
        self._manual_cols.clear()
        self._manual_rows.clear()
        self._autofit()

    def reset_size(self):
        """Explicit Reset Size: one uniform size, and the manual flags gone."""
        self._manual_cols.clear()
        self._manual_rows.clear()
        hh = self.view.horizontalHeader()
        vh = self.view.verticalHeader()
        default_w = hh.defaultSectionSize()
        default_h = vh.defaultSectionSize()
        self._sizing = True
        try:
            for c in range(self.model.columnCount()):
                hh.resizeSection(c, default_w)
            for r in range(self.model.rowCount()):
                vh.resizeSection(r, default_h)
        finally:
            self._sizing = False

    def _on_section_resized(self, section: int, columns: bool):
        """Remember a section the user resized by dragging its handle."""
        if self._sizing or section < 0:
            return
        (self._manual_cols if columns else self._manual_rows).add(section)

    def _remap_manual(self, first: int, count: int, inserted: bool,
                      columns: bool):
        """Keep the manual flags on the same columns/rows after a shape change.

        An index set cannot survive a deletion on its own: removing column 0
        would mark column 1 (the user's) manual and column 0 nothing. Sections
        are renumbered exactly as Qt renumbers them, so the flag follows the
        section it was set on.
        """
        flags = self._manual_cols if columns else self._manual_rows
        delta = count if inserted else -count
        kept = set()
        for i in flags:
            if inserted:
                kept.add(i + count if i >= first else i)
            elif i < first or i >= first + count:
                kept.add(i + delta if i >= first + count else i)
        flags.clear()
        flags.update(kept)

    def _model_changed(self):
        """Re-read the view after a programmatic change to the rows."""
        self.view.viewport().update()
        self._schedule_sync()

    # ---- serialize ------------------------------------------------------
    def serialize(self):
        """The whole silo: the text around the table, with the table rebuilt.

        Returning only the table here is what deleted the rest of the silo.
        """
        from fastprompter.ui import silo_region

        return silo_region.splice(self._prefix, self.model.table_lines(),
                                  self._suffix)

    def _table_lines(self):
        return self.model.table_lines()

    def flush(self):
        """Emit a pending cell edit NOW rather than let the 500 ms timer race
        the caller.

        A silo switch reads the outgoing document and then swaps the widget:
        an edit still parked in the timer at that moment is emitted against
        the NEXT silo's text, or lost. Navigation must flush first.
        """
        if self._sync_timer.isActive():
            self._sync_timer.stop()
            self._do_serialize()

    def discard_pending_sync(self):
        """Drop a parked cell edit WITHOUT writing it.

        Called after a document history step (Ctrl+Z / Ctrl+Y): the edit the
        timer would emit belongs to a document state that no longer exists, so
        writing it would resurrect undone content. The caller re-renders the
        widget from the live text instead.
        """
        if self._sync_timer.isActive():
            self._sync_timer.stop()

    def _schedule_sync(self):
        self._sync_timer.start()

    def _do_serialize(self):
        self.changed.emit(self.serialize())

    # ---- shape commands --------------------------------------------------
    def _current_cell(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            return 0, 0
        return idx.row(), idx.column()

    def _add_row(self):
        row = len(self.model.rows)
        if not self.model.insert_rows(row):
            self.model.insert_rows(row - 1)
        # T-1462 Stage 6: a new row says nothing about column content, so the
        # columns are left exactly as the user has them.
        self._autofit(columns=False)
        self._schedule_sync()

    def _add_column(self):
        width = self.model._width()
        if not self.model.insert_columns(width):
            self.model.insert_columns(width - 1)
        # T-1462 Stage 6: a new column needs fitting, and it fits only the
        # columns — the row heights the user set are not a function of it.
        self._autofit(rows=False)
        self._schedule_sync()

    def _pos_of(self, cell):
        """(row, column) from a model index, a (row, col) pair, or a cell."""
        if isinstance(cell, QModelIndex):
            return cell.row(), cell.column()
        if isinstance(cell, _CellHandle):
            return cell._row, cell._column
        if isinstance(cell, (tuple, list)) and len(cell) == 2:
            return int(cell[0]), int(cell[1])
        return self._current_cell()

    def insert_row(self, cell, offset):
        r, _c = self._pos_of(cell)
        if r < 0:
            return False
        target = r if offset < 0 else r + 1
        # Never insert above the header: a markdown table's first row is the
        # header, so a row above it would start a new table.
        if self.model.has_header:
            target = max(1, target)
        if not self.model.insert_rows(target):
            return False
        self.view.setCurrentIndex(self.model.index(target, 0))
        self._autofit(columns=False)
        self._schedule_sync()
        return True

    def delete_row(self, cell):
        r, _c = self._pos_of(cell)
        if r <= 0:
            return False
        if not self.model.remove_rows(r):
            return False
        self.view.setCurrentIndex(
            self.model.index(min(r, len(self.model.rows) - 1), 0))
        self._autofit(columns=False)
        self._schedule_sync()
        return True

    def insert_col(self, cell, offset):
        _r, c = self._pos_of(cell)
        if c < 0:
            return False
        target = c if offset < 0 else c + 1
        if not self.model.insert_columns(target):
            return False
        self._autofit(rows=False)
        self._schedule_sync()
        return True

    def delete_col(self, cell):
        _r, c = self._pos_of(cell)
        if c < 0:
            return False
        if not self.model.remove_columns(c):
            return False
        self._autofit(rows=False)
        self._schedule_sync()
        return True

    def swap_row_up(self, cell):
        r, c = self._pos_of(cell)
        if not self.model.move_row(r, -1):
            return False
        self.view.setCurrentIndex(self.model.index(r - 1, c))
        self._autofit(columns=False)
        self._schedule_sync()
        return True

    def swap_row_down(self, cell):
        r, c = self._pos_of(cell)
        if not self.model.move_row(r, +1):
            return False
        self.view.setCurrentIndex(self.model.index(r + 1, c))
        self._autofit(columns=False)
        self._schedule_sync()
        return True

    def swap_col_left(self, cell):
        r, c = self._pos_of(cell)
        if not self.model.move_column(c, -1):
            return False
        self.view.setCurrentIndex(self.model.index(r, c - 1))
        self._autofit(rows=False)
        self._schedule_sync()
        return True

    def swap_col_right(self, cell):
        r, c = self._pos_of(cell)
        if not self.model.move_column(c, +1):
            return False
        self.view.setCurrentIndex(self.model.index(r, c + 1))
        self._autofit(rows=False)
        self._schedule_sync()
        return True

    # ---- alignment -------------------------------------------------------
    def set_column_align(self, align):
        """Align the current column. Markdown has three states, not ten."""
        indexes = self.view.selectionModel().selectedIndexes()
        columns = {i.column() for i in indexes} or {self._current_cell()[1]}
        for c in sorted(columns):
            self.model.set_alignment(c, align)
        self._schedule_sync()

    # ---- keyboard / clipboard ---------------------------------------------
    def keyPressEvent(self, e):
        mods = e.modifiers()
        # Ctrl+Z / Ctrl+Y belong to the DOCUMENT's undo stack: the region
        # write-back is one undo step there, and a second stack in the grid
        # would desynchronise the two.
        if mods & Qt.KeyboardModifier.ControlModifier:
            k = e.key()
            # Ctrl+Shift+Z is the other redo chord; Ctrl+Z alone is undo. The
            # grid must emit the matching request, or Ctrl+Y would undo (the
            # old code sent every Ctrl chord to undoRequested).
            if k == Qt.Key.Key_Z:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.redoRequested.emit()
                else:
                    self.undoRequested.emit()
                e.accept()
                return
            if k == Qt.Key.Key_Y:
                self.redoRequested.emit()
                e.accept()
                return
            if k == Qt.Key.Key_C:
                self.copy_cells()
                e.accept()
                return
            if k == Qt.Key.Key_X:
                self.cut_cells()
                e.accept()
                return
            if k == Qt.Key.Key_V:
                self.paste_cells()
                e.accept()
                return
            if k == Qt.Key.Key_A:
                self.view.selectAll()
                e.accept()
                return
        super().keyPressEvent(e)

    def copy_cells(self):
        """Copy the rectangular bounding box of the selection as TSV.

        Ctrl+C with a selection elsewhere in the app copies some TEXT, so
        without this the app's own shortcut would eat the range first.
        """
        text = self.model.clipboard_range(
            self.view.selectionModel().selectedIndexes())
        if text:
            QGuiApplication.clipboard().setText(text)

    def cut_cells(self):
        self.copy_cells()
        for idx in self.view.selectionModel().selectedIndexes():
            self.model.setData(idx, "", Qt.ItemDataRole.EditRole)
        self._schedule_sync()

    def paste_cells(self):
        text = QGuiApplication.clipboard().text()
        if not text:
            return
        r, c = self._current_cell()
        rows, cols = self.model.paste_tsv(r, c, text)
        if not (rows and cols):
            # T-1462 Stage 4: a refused paste must not autofit — resizing to a
            # table that did not change would reward the refusal with a layout
            # jump — and must not arm the write-back timer, because there is
            # nothing new to write. Tell the user why and leave everything as
            # it was.
            self._report_paste_refusal()
            return
        self._autofit(columns=False)
        self._schedule_sync()

    def _report_paste_refusal(self):
        """Surface a refused paste where the user is looking.

        Only fires when the model actually refused (a reason is set); an empty
        clipboard or a whitespace-only one is a silent no-op, not a refusal.
        """
        reason = getattr(self.model, "paste_refusal", "")
        if not reason:
            return
        from PyQt6.QtWidgets import QToolTip
        rect = self.view.viewport().rect()
        QToolTip.showText(self.view.viewport().mapToGlobal(rect.center()),
                          reason, self.view)

    # ---- context menu ------------------------------------------------------
    def _resolved_lang(self) -> str:
        """Resolve the effective language for context menu labels and messages."""
        lang = getattr(self, "_menu_lang", None)
        if lang is not None:
            return lang
        host = self.get_settings_host()
        if host is not None:
            lang = getattr(host, "_current_lang", None)
            if lang is not None:
                return lang
        parent = self.parent()
        if parent is not None:
            lang = getattr(parent, "lang", None) or getattr(parent, "_current_lang", None)
            if lang is not None:
                return lang
        lang = getattr(self, "_current_lang", None)
        return lang or "EN"

    def _menu_label(self, key: str, shortcut: str = "") -> str:
        """One menu label through the existing translation architecture.

        The grid is not a QWidget subclass with its own ``tr`` override, so
        the language comes from the same place the add buttons use: the
        settings host or parent's language. Every label is looked up, never a literal.
        """
        lang = self._resolved_lang()
        label = tr(key, lang)
        return f"{label}\t{shortcut}" if shortcut else label

    def _menu_save_default(self):
        """Save current table layout as the user's default template."""
        self.save_as_default_layout()

    def _menu_apply_default(self):
        """Apply the user's default template to this table."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, self._menu_label("Reset Table Layout to Default"),
            self._menu_label(
                "Apply the default table layout to this table? "
                "Current column widths and row heights will be replaced."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            if not self.apply_default_layout():
                self._report_layout_mismatch()

    def _report_layout_mismatch(self):
        """Surface default layout refusal dialog to user (Option A, T-1468)."""
        from PyQt6.QtWidgets import QMessageBox

        lang = self._resolved_lang()
        err = getattr(self, "_last_apply_error", None)
        title = self._menu_label("Reset Table Layout to Default")
        if isinstance(err, tuple) and err[0] == "shape_mismatch":
            _, cur_cols, tpl_cols = err
            raw_msg = tr(
                "Cannot apply default table layout because the table shape does not match.\n\n"
                "Current table has {cur_cols} column(s), but default template has {tpl_cols} column(s).\n\n"
                "To reset layout, adjust table columns to match the template, or save this table's layout as default.",
                lang,
            )
            msg = raw_msg.format(cur_cols=cur_cols, tpl_cols=tpl_cols)
        elif err == "no_template":
            msg = tr(
                "Cannot apply default table layout because no default template is saved.\n\n"
                "Use 'Save Current Table Layout as Default' to save one.",
                lang,
            )
        else:
            msg = tr(
                "Cannot apply default table layout because the template is invalid or unavailable.",
                lang,
            )
        QMessageBox.information(self, title, msg, QMessageBox.StandardButton.Ok)

    def _menu_restore_factory(self):
        """Reset the stored template to factory defaults."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, self._menu_label("Restore Factory Table Defaults"),
            self._menu_label(
                "Reset the default table layout to factory defaults? "
                "This does NOT resize the current table."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            self.restore_factory_layout()

    def _show_context_menu(self, pos):
        # T-1457 Stage 3: every visible label goes through the translation
        # architecture, and the row/column MOVE operations the widget already
        # implements are surfaced here -- they were unreachable except by
        # keyboard, which is exactly the "inaccessible custom control" defect.
        menu = QMenu(self)
        menu.addAction(self._menu_label("Insert row above"),
                       self._menu_insert_row)
        menu.addAction(self._menu_label("Insert row below"),
                       self._menu_insert_row_below)
        menu.addAction(self._menu_label("Delete row(s)"),
                       self._menu_delete_rows)
        menu.addSeparator()
        menu.addAction(self._menu_label("Insert column left"),
                       self._menu_insert_col_left)
        menu.addAction(self._menu_label("Insert column right"),
                       self._menu_insert_col_right)
        menu.addAction(self._menu_label("Delete column"),
                       self._menu_delete_col)
        menu.addSeparator()
        menu.addAction(self._menu_label("Move row up"), self._menu_move_row_up)
        menu.addAction(self._menu_label("Move row down"),
                       self._menu_move_row_down)
        menu.addAction(self._menu_label("Move column left"),
                       self._menu_move_col_left)
        menu.addAction(self._menu_label("Move column right"),
                       self._menu_move_col_right)
        menu.addSeparator()
        menu.addAction(self._menu_label("Align left"),
                       lambda: self.set_column_align(ALIGN_LEFT))
        menu.addAction(self._menu_label("Align center"),
                       lambda: self.set_column_align(ALIGN_CENTER))
        menu.addAction(self._menu_label("Align right"),
                       lambda: self.set_column_align(ALIGN_RIGHT))
        menu.addSeparator()
        # T-1462 Stage 6: the two explicit ways OUT of "my widths stick".
        # Auto-fit re-fits everything (the columns the user dragged included);
        # Reset Size puts one uniform default back. Neither touches the text.
        menu.addAction(self._menu_label("Auto-fit"), self.autofit_all)
        menu.addAction(self._menu_label("Reset Size"), self.reset_size)
        menu.addSeparator()
        # T-1466: default table layout template actions
        menu.addAction(self._menu_label("Save Current Table Layout as Default"),
                       self._menu_save_default)
        menu.addAction(self._menu_label("Reset Table Layout to Default"),
                       self._menu_apply_default)
        menu.addAction(self._menu_label("Restore Factory Table Defaults"),
                       self._menu_restore_factory)
        menu.addSeparator()
        menu.addAction(self._menu_label("Copy", "Ctrl+C"), self.copy_cells)
        menu.addAction(self._menu_label("Cut", "Ctrl+X"), self.cut_cells)
        menu.addAction(self._menu_label("Paste", "Ctrl+V"), self.paste_cells)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _menu_move_row_up(self):
        self.swap_row_up(self._current_cell())

    def _menu_move_row_down(self):
        self.swap_row_down(self._current_cell())

    def _menu_move_col_left(self):
        self.swap_col_left(self._current_cell())

    def _menu_move_col_right(self):
        self.swap_col_right(self._current_cell())

    def _menu_insert_row(self):
        # Route through the guarded helper: with a header, "above" the header
        # is refused by the model, and the helper clamps to row 1 instead.
        self.insert_row(self._current_cell(), -1)

    def _menu_insert_row_below(self):
        self.insert_row(self._current_cell(), +1)

    def _menu_delete_rows(self):
        """Delete the selected body rows as ONE atomic batch.

        T-1462 Stage 1: the selection may include the header row, and the
        model refuses to remove row zero. Deleting the permitted body rows
        anyway would silently complete half of a rejected batch, so the whole
        operation is refused when it touches the header, and the remaining
        rows are removed as a single contiguous run — one begin/endRemoveRows,
        no partial completion.
        """
        rows = sorted({i.row()
                       for i in self.view.selectionModel().selectedIndexes()})
        if not rows:
            return
        if self.model.has_header and rows[0] < 1:
            return
        # Contiguous run from the first selected row; a gap is split into
        # runs so no unselected row is removed.
        runs: list[tuple[int, int]] = []
        start = prev = rows[0]
        for r in rows[1:]:
            if r == prev + 1:
                prev = r
                continue
            runs.append((start, prev - start + 1))
            start = prev = r
        runs.append((start, prev - start + 1))
        changed = False
        for start, count in reversed(runs):
            if self.model.remove_rows(start, count):
                changed = True
        if not changed:
            return
        self.view.setCurrentIndex(
            self.model.index(min(rows[0], len(self.model.rows) - 1), 0))
        self._autofit(rows=False)
        self._schedule_sync()

    def _menu_insert_col_left(self):
        self.insert_col(self._current_cell(), -1)

    def _menu_insert_col_right(self):
        self.insert_col(self._current_cell(), +1)

    def _menu_delete_col(self):
        _r, c = self._current_cell()
        self.model.remove_columns(c)
        self._autofit()
        self._schedule_sync()
