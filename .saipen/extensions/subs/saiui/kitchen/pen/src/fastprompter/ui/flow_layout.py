"""A layout that wraps its children like text.

Qt's grid layouts keep a fixed column count, so a settings panel built from
one is only readable at the width it was designed for — squeeze the window
and the right-hand column is simply cut off. This reflows instead: as many
items per row as actually fit, down to a single column on a very narrow
panel, so nothing ever becomes unreachable.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=2,
                 stretch_items=False):
        super().__init__(parent)
        self._items = []
        self._stretch = stretch_items
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

        # Group items into lines (first pass)
        lines = []
        i = 0
        while i < len(items):
            x = left
            line_h = 0
            line_start = i
            while i < len(items):
                hint = items[i].sizeHint()
                w, h = hint.width(), hint.height()
                if line_h > 0 and x + w > right:
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
                w, h = item.sizeHint().width(), item.sizeHint().height()
                w += spare
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


class FlowWidget(QWidget):
    """QWidget wrapping a FlowLayout, with a totalHeightForWidth helper.

    Exposes totalHeightForWidth so _fit_settings_tabs can measure the
    exact height at the actual tab width instead of relying on
    QLayout.totalHeightForWidth — which may not exist in PyQt6.
    """
    def __init__(self, items, margin=0, h_spacing=8, v_spacing=2,
                 stretch_items=False):
        super().__init__()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._flow = FlowLayout(self, margin=margin,
                                 h_spacing=h_spacing, v_spacing=v_spacing,
                                 stretch_items=stretch_items)
        for item in items:
            if isinstance(item, QLayout):
                sub = QWidget()
                sub.setLayout(item)
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


def flow_widget(items, margin=0, h_spacing=8, v_spacing=2, stretch_items=False):
    """Wrap widgets/layouts in a FlowWidget using a FlowLayout."""
    return FlowWidget(items, margin=margin, h_spacing=h_spacing,
                      v_spacing=v_spacing, stretch_items=stretch_items)
