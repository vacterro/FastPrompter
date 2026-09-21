"""The rule editor uses toggle buttons, so a stray wheel cannot rewrite a rule.

A QComboBox in a table cell is a data hazard: the pointer crosses it while the
user is scrolling the list and the rule silently steps to another value. Toggle
buttons have no value to step, so the wheel can only ever scroll the table.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

from fastprompter.core.topbar_visibility import (
    RANGE_IDS,
    TOPBAR_ITEMS,
    default_topbar_visibility,
)
from fastprompter.ui.topbar_visibility_dialog import (
    RuleButtonGroup,
    TopbarVisibilityDialog,
)

_APP = QApplication.instance() or QApplication([])


class _Host(QWidget):
    """Smallest main window the dialog actually reads."""

    def __init__(self):
        super().__init__()
        self._current_lang = "EN"
        self.data = {}
        self.dirty = 0
        self.densities = 0
        self.resize(1600, 200)

    def _topbar_visibility_config(self):
        return default_topbar_visibility()

    def _topbar_effective_width(self):
        return 1600.0

    def mark_dirty(self, *_args):
        self.dirty += 1

    def _apply_header_density(self):
        self.densities += 1


def _dialog():
    host = _Host()
    dialog = TopbarVisibilityDialog(host)
    dialog._preview_timer.stop()
    return host, dialog


def _wheel(widget, notches=-3):
    return QWheelEvent(
        QPointF(widget.rect().center()),
        QPointF(widget.mapToGlobal(widget.rect().center())),
        QPoint(0, notches * 40),
        QPoint(0, notches * 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_no_rule_cell_is_a_dropdown():
    host, dialog = _dialog()
    try:
        for row in range(dialog.table.rowCount()):
            for col in range(1, len(RANGE_IDS) + 1):
                cell = dialog.table.cellWidget(row, col)
                assert isinstance(cell, RuleButtonGroup)
                assert not cell.findChildren(QComboBox)
    finally:
        dialog.close()
        host.close()


def test_scrolling_across_a_rule_cell_cannot_change_it():
    host, dialog = _dialog()
    try:
        dialog.show()
        _APP.processEvents()
        token = next(i.token for i in TOPBAR_ITEMS if i.configurable)
        group = dialog._range_boxes[(token, "wide")]
        before = group.currentData()
        for target in [group] + group._buttons:
            _APP.sendEvent(target, _wheel(target))
            _APP.processEvents()
        assert group.currentData() == before
    finally:
        dialog.close()
        host.close()


def test_clicking_a_button_is_exclusive_and_is_what_gets_saved():
    host, dialog = _dialog()
    try:
        token = next(i.token for i in TOPBAR_ITEMS
                     if i.configurable and not i.compact)
        group = dialog._range_boxes[(token, "narrow")]
        hide_index = next(i for i in range(group.count())
                          if group.itemData(i)[0] == "hide")
        group._buttons[hide_index].click()

        checked = [i for i, b in enumerate(group._buttons) if b.isChecked()]
        assert checked == [hide_index]
        assert group.currentData() == ("hide", None)

        dialog.apply_changes()
        assert host.data["topbar_visibility"]["items"][token]["narrow"] == "hide"
        assert host.dirty == 1
        assert host.densities == 1
    finally:
        dialog.close()
        host.close()


def test_locked_items_stay_unclickable():
    host, dialog = _dialog()
    try:
        locked = [i.token for i in TOPBAR_ITEMS if not i.configurable]
        assert locked, "the fixture needs at least one locked access control"
        for token in locked:
            for rid in RANGE_IDS:
                group = dialog._range_boxes[(token, rid)]
                assert not group.isEnabled()
                assert all(not b.isEnabled() for b in group._buttons)
    finally:
        dialog.close()
        host.close()
