"""A layout that wraps its children like text.

Qt's grid layouts keep a fixed column count, so a settings panel built from
one is only readable at the width it was designed for — squeeze the window
and the right-hand column is simply cut off. This reflows instead: as many
items per row as actually fit, down to a single column on a very narrow
panel, so nothing ever becomes unreachable.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=2):
        super().__init__(parent)
        self._items = []
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

        x, y = left, top
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            # wrap when this item would overflow — but never wrap the first
            # item on a line, or a too-wide item would loop forever
            if line_height > 0 and x + w > right:
                x = left
                y += line_height + self._v_space
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._h_space
            line_height = max(line_height, h)
        return y + line_height - rect.y() + margins.bottom()


def flow_widget(items, margin=0, h_spacing=8, v_spacing=2):
    """Wrap widgets/layouts in a QWidget using a FlowLayout."""
    from PyQt6.QtWidgets import QWidget

    host = QWidget()
    host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    layout = FlowLayout(host, margin=margin, h_spacing=h_spacing, v_spacing=v_spacing)
    for item in items:
        if isinstance(item, QLayout):
            sub = QWidget()
            sub.setLayout(item)
            layout.addWidget(sub)
        else:
            layout.addWidget(item)
    return host
