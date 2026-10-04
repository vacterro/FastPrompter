"""A layout that wraps its children like text.

Qt's grid layouts keep a fixed column count, so a settings panel built from
one is only readable at the width it was designed for — squeeze the window
and the right-hand column is simply cut off. This reflows instead: as many
items per row as actually fit, down to a single column on a very narrow
panel, so nothing ever becomes unreachable.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLabel, QLayout, QSizePolicy, QWidget


class _AtomicLayoutWidget(QWidget):
    """Wrapper for a row layout that must remain internally reachable.

    A bare QWidget with a child QHBoxLayout can advertise a zero-ish minimum
    through QWidgetItem even though its label/editor/button row needs much
    more.  The outer flow then squeezes the settings group below that row and
    clips its right-hand controls.  A row is atomic to FlowLayout (its own
    children cannot reflow), so its minimum must be its layout's full hint.
    """

    def minimumSizeHint(self):
        layout = self.layout()
        return layout.sizeHint() if layout is not None else super().minimumSizeHint()


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=2,
                 stretch_items=False, columns=False, one_per_line=False):
        super().__init__(parent)
        self._items = []
        self._stretch = stretch_items
        self._columns = columns
        # Settings cards: every control on its own line, so a card reads as
        # a tidy column instead of a wrapped paragraph of checkboxes.
        self._one_per_line = one_per_line
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # ---- QLayout plumbing ---------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    # ---- the actual wrapping ------------------------------------------
    def _do_layout(self, rect, apply):
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        right = rect.right() - margins.right()

        # Hidden widgets are skipped outright. Qt already gives a hidden
        # QWidgetItem a zero sizeHint, so they do not leave a hole - but the
        # loop below adds h_space per item regardless, so each one still cost
        # a phantom gap. Measured: two hidden widgets pushed the first
        # visible one from x=0 to x=16 and spread the rest to match.
        items = [it for it in self._items if not it.isEmpty()]
        if self._columns:
            return self._do_columns(items, left, top, right, rect, margins,
                                    apply)

        # Group items into lines (first pass)
        full = max(1, right - left + 1)
        lines = []
        i = 0
        while i < len(items):
            x = left
            line_h = 0
            line_start = i
            while i < len(items):
                w, h = self._fit(items[i], full)
                if line_h > 0 and (self._one_per_line or x + w > right):
                    break
                x += w + self._h_space
                line_h = max(line_h, h)
                i += 1
            lines.append((line_start, i - line_start, line_h))

        # Apply geometry (second pass). Items are packed from the left and
        # NOT justified across the width: spreading them measured a 724px
        # gap between two checkboxes on the Clock tab, which is exactly the
        # "huge empty space" the settings panel was compacted to remove.
        #
        # `stretch_items` is the opposite trade, and only makes sense for
        # items that are containers: the leftover width is added TO them
        # rather than put between them, so a row of settings groups fills
        # the panel and their contents still sit left-aligned inside. Used
        # for the settings tabs, where a flow of groups otherwise stopped at
        # 449px of 956 and left a dead stripe down the right.
        y = top
        for start, count, line_h in lines:
            x = left
            spare = 0
            if self._stretch and count:
                used = sum(items[j].sizeHint().width()
                           for j in range(start, start + count))
                used += self._h_space * (count - 1)
                spare = max(0, (right - left) - used) // count
            placed = []
            for j in range(start, start + count):
                item = items[j]
                w, h = self._fit(item, full)
                w += spare
                if self._one_per_line and isinstance(item.widget(),
                                                     _AtomicLayoutWidget):
                    w = max(w, full)
                # A widened container has to re-flow its own contents, or it
                # keeps the tall narrow shape it had at hint width and the
                # extra room buys nothing. Measured on the Editor tab: 351px
                # of panel before asking, 272 after.
                if spare and item.hasHeightForWidth():
                    # NOT max(minimumSize().height(), ...): a layout with
                    # height-for-width reports its minimum height at its
                    # MINIMUM width, i.e. the tallest it can ever be, which
                    # pinned one group at 122px when 70 was the truth.
                    h = item.heightForWidth(w)
                placed.append((item, w, h))
                x += w + self._h_space
            if placed:
                line_h = max(line_h if not spare else 0, max(h for _i, _w, h in placed))
            x = left
            for item, w, h in placed:
                if apply:
                    item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
                x += w + self._h_space
            y += line_h + self._v_space

        if not lines:
            return margins.top() + margins.bottom()
        return y - self._v_space - rect.y() + margins.bottom()

    @staticmethod
    def _fit(item, max_width):
        """An item's (width, height), never wider than the whole line.

        A word-wrapping label placed at its size hint was either cut off on
        the right inside a narrower card, or wrapped into a tall narrow tower
        inside a wider one (the Problip Help text, both ways).  A paragraph
        now takes as much of the line as its one-line length asks for, and
        any item that can trade width for height gets the height that goes
        with the width it was given.
        """
        hint = item.sizeHint()
        width, height = hint.width(), hint.height()
        if not item.hasHeightForWidth():
            return width, height
        widget = item.widget()
        if isinstance(widget, QLabel) and widget.wordWrap() and widget.text():
            margins = widget.contentsMargins()
            one_line = (widget.fontMetrics().horizontalAdvance(widget.text())
                        + margins.left() + margins.right()
                        + 2 * widget.margin() + 4)
            if one_line > width:
                width = min(max_width, one_line)
                height = item.heightForWidth(width)
        if width > max_width:
            width = max_width
            height = item.heightForWidth(width)
        return width, height

    def _do_columns(self, items, left, top, right, rect, margins, apply):
        """A closed mosaic of container cards with no holes (T-1246).

        Plain row packing left every card at its own height inside a row as
        tall as its TALLEST sibling: a tall group (Problip's Sound pool) left
        blank stripes under every short neighbour.  Candidates here are the
        row packing and independent equal-width columns (1..N, a wide card
        spanning several); every candidate closes its gaps by growing each
        card down to the card below it or to the page bottom (content stays
        top-aligned inside).  The lowest page wins -- the editor owns the
        spare height -- and among near-equal heights the least blank.
        """
        if not items:
            return margins.top() + margins.bottom()
        avail = max(1, right - left + 1)
        hints = [item.sizeHint().width() for item in items]
        narrowest = max(1, min(hints))
        most = (avail + self._h_space) // (narrowest + self._h_space)
        most = max(1, min(len(items) * 2, most))
        plans = [self._plan_rows(items, hints, avail)]
        plans += [self._plan_columns(items, hints, count, avail)
                  for count in range(1, most + 1)]
        best = None
        for plan in plans:
            if plan is None:
                continue
            height, blank, _placed = plan
            if best is None or height < best[0] - 6 or (
                    height <= best[0] + 6 and blank < best[1]):
                best = plan
        height, _blank, placed = best
        if apply:
            for item, x, y, width, h in placed:
                item.setGeometry(QRect(QPoint(left + x, top + y),
                                       QSize(width, h)))
        return top + height - rect.y() + margins.bottom()

    def _plan_rows(self, items, hints, avail):
        """Row packing with every card grown to its row's height."""
        space = self._h_space
        lines, line, x = [], [], 0
        for item, hint in zip(items, hints):
            if line and x + hint > avail:
                lines.append(line)
                line, x = [], 0
            line.append((item, hint))
            x += hint + space
        if line:
            lines.append(line)
        placed, blank, y = [], 0, 0
        for line in lines:
            used = sum(hint for _item, hint in line) + space * (len(line) - 1)
            spare = max(0, avail - used) // len(line)
            cells, x = [], 0
            for position, (item, hint) in enumerate(line):
                width = hint + spare
                if position == len(line) - 1 and spare:
                    width = max(width, avail - x)   # reach the right edge
                h = (item.heightForWidth(width) if item.hasHeightForWidth()
                     else max(item.sizeHint().height(),
                              item.minimumSize().height()))
                cells.append((item, x, width, h))
                x += width + space
            line_h = max(h for *_rest, h in cells)
            for item, x, width, h in cells:
                blank += (line_h - h) * width
                placed.append((item, x, y, width, line_h))
            y += line_h + self._v_space
        return y - self._v_space, blank, placed

    def _plan_columns(self, items, hints, count, avail):
        """Place cards on ``count`` equal columns; a wide card spans several.

        Returns ``(height, blank_area, [(item, x, y, w, h), ...])`` or None
        when a card cannot fit even across every column.
        """
        space = self._h_space
        col_w = (avail - space * (count - 1)) / count
        if col_w < 1:
            return None
        bottoms = [0] * count
        placed = []
        blank = 0
        for item, hint in zip(items, hints):
            span = 1
            while span < count and span * col_w + (span - 1) * space < hint:
                span += 1
            if count > 1 and span * col_w + (span - 1) * space < hint - 1:
                return None      # too narrow here; fewer columns will do
            start = min(range(count - span + 1),
                        key=lambda c: (max(bottoms[c:c + span]), c))
            y = max(bottoms[start:start + span])
            x0 = round(start * (col_w + space))
            x1 = round((start + span) * (col_w + space) - space)
            width = max(1, x1 - x0)
            if item.hasHeightForWidth():
                # NOT max'ed with minimumSize(): that is the height at the
                # MINIMUM width, the tallest the card can ever be.
                h = item.heightForWidth(width)
            else:
                h = max(item.sizeHint().height(), item.minimumSize().height())
            for column in range(start, start + span):
                blank += (y - bottoms[column]) * col_w
                bottoms[column] = y + h + self._v_space
            placed.append([item, x0, y, width, h, start, span])
        height = max(bottoms) - self._v_space
        # the ragged bottom is blank the user sees too
        blank += sum((height + self._v_space - b) * col_w for b in bottoms)
        return height, blank, self._close_gaps(placed, height)

    def _close_gaps(self, placed, height):
        """Stretch each card down to the card below it (or the page bottom).

        What is left after the least-blank plan is absorbed INTO the cards
        (their content stays top-aligned), so the page is one closed mosaic
        of cards with no holes and no ragged bottom edge.
        """
        out = []
        for index, (item, x, y, width, h, start, span) in enumerate(placed):
            columns = range(start, start + span)
            below = [other[2] for other in placed[index + 1:]
                     if other[2] > y and any(
                         other[5] <= c < other[5] + other[6] for c in columns)]
            # a later card sits under ALL of this card's columns only if it
            # starts at the same height everywhere; stop at the nearest one.
            limit = (min(below) - self._v_space) if below else height
            out.append((item, x, y, width, max(h, limit - y)))
        return out


class FlowWidget(QWidget):
    """QWidget wrapping a FlowLayout, with a totalHeightForWidth helper.

    Exposes totalHeightForWidth so _fit_settings_tabs can measure the
    exact height at the actual tab width instead of relying on
    QLayout.totalHeightForWidth — which may not exist in PyQt6.
    """
    def __init__(self, items, margin=0, h_spacing=8, v_spacing=2,
                 stretch_items=False, one_per_line=False):
        super().__init__()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Maximum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._flow = FlowLayout(self, margin=margin,
                                 h_spacing=h_spacing, v_spacing=v_spacing,
                                 stretch_items=stretch_items,
                                 one_per_line=one_per_line)
        for item in items:
            if isinstance(item, QLayout):
                sub = _AtomicLayoutWidget()
                sub.setLayout(item)
                sub.setSizePolicy(QSizePolicy.Policy.Minimum,
                                  QSizePolicy.Policy.Fixed)
                self._flow.addWidget(sub)
            else:
                self._flow.addWidget(item)

    def totalHeightForWidth(self, width):
        """Total height this widget needs at the given outer width.

        `width` is the total width available to the widget. The
        inner FlowLayout already subtracts its own margins from the
        width inside heightForWidth, so we pass it through as-is.
        """
        return self._flow.heightForWidth(width)


def flow_widget(items, margin=0, h_spacing=8, v_spacing=2, stretch_items=False,
                one_per_line=False):
    """Wrap widgets/layouts in a FlowWidget using a FlowLayout."""
    return FlowWidget(items, margin=margin, h_spacing=h_spacing,
                      v_spacing=v_spacing, stretch_items=stretch_items,
                      one_per_line=one_per_line)
