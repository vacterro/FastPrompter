"""The table silo's visual widget.

T-1462: the grid is a QTableView over `TableCellsModel` (see `table_grid.py`),
so single-cell editing, rectangular selection, drag-to-select, column
resizing, keyboard navigation and copy/cut/paste of a range come from the Qt
framework rather than from a hand-built QGridLayout of QLineEdits.

This module stays the public face of the widget for main.py, the theme mixin
and the tests. It is a re-export so there is exactly ONE implementation of the
grid, not two that can drift.
"""

from __future__ import annotations

from fastprompter.ui.table_grid import TableGridWidget

__all__ = ["TableGridWidget"]
