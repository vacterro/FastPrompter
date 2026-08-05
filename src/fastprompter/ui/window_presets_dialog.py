"""Manage the Ctrl+Q window presets: order, names, geometry.

The picker itself can only save and delete. Everything that needs a list to
work on — reordering, renaming, re-capturing an existing entry — lives here.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr
from fastprompter.ui.fancy_zones import (
    _MAX_PRESETS,
    _captures_ui_state,
    _current_ui_state,
    _load_presets,
    _save_presets,
)


def _describe(p) -> str:
    # zen / no-sidebar are shown because they are part of what the preset
    # will DO to the window, and a list that only shows the box makes the
    # layout half of it look like a surprise.
    extra = "".join(t for t in (
        ", zen" if p.get("zen") else "",
        ", no sidebar" if p.get("sidebar") is False and not p.get("zen") else "",
    ))
    if p.get("state") == "maximized":
        return f'{p["name"]}  —  maximized{extra}'
    return (f'{p["name"]}  —  {round(p["w"] * 100)}% x {round(p["h"] * 100)}% '
            f'@ {round(p["x"] * 100)},{round(p["y"] * 100)}{extra}')


class WindowPresetsDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Window Presets (Ctrl+Q)", self.lang))
        self.setMinimumWidth(420)

        self.presets = _load_presets(getattr(main_win, "data", None))

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr(
            "Order here is the order in the Ctrl+Q picker, and the number "
            "key that applies each one.", self.lang)))

        # T-728: a preset can carry the whole app state or just the box. When
        # off, capture is geometry-only and applying it changes nothing but
        # the window's rectangle.
        self.cb_capture_state = QCheckBox(tr(
            "Capture full app state (theme, font, scale, toolbar, zen, sidebar)",
            self.lang))
        self.cb_capture_state.setChecked(
            _captures_ui_state(getattr(main_win, "data", None)))
        self.cb_capture_state.setToolTip(tr(
            "On: the preset also restores theme, font size, UI scale, toolbar "
            "position, zen and sidebar. Off: geometry only.", self.lang))
        self.cb_capture_state.toggled.connect(self._capture_state_toggled)
        lay.addWidget(self.cb_capture_state)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lay.addWidget(self.list)
        self._reload()

        row = QHBoxLayout()
        for label, slot in (
            ("▲", self.move_up),
            ("▼", self.move_down),
            (tr("Rename", self.lang), self.rename),
            (tr("Re-capture", self.lang), self.recapture),
            (tr("Delete", self.lang), self.delete),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

        add = QPushButton(tr("Add current window", self.lang))
        add.clicked.connect(self.add_current)
        lay.addWidget(add)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ---- helpers ------------------------------------------------------
    def _reload(self, keep=None):
        self.list.clear()
        for i, p in enumerate(self.presets):
            self.list.addItem(QListWidgetItem(f"{(i + 1) % 10}.  {_describe(p)}"))
        if keep is not None and 0 <= keep < self.list.count():
            self.list.setCurrentRow(keep)

    def _row(self):
        r = self.list.currentRow()
        return r if 0 <= r < len(self.presets) else -1

    def _capture(self):
        """Current window geometry as fractions of its screen's work area."""
        mw = self.main_win
        from PyQt6.QtWidgets import QApplication
        screen = (QApplication.screenAt(mw.geometry().center())
                  or QApplication.primaryScreen())
        if screen is None:
            return None
        a = screen.availableGeometry()
        if not a.isValid() or a.width() <= 0 or a.height() <= 0:
            return None
        g = mw.geometry()
        cap = {
            "x": max(0.0, (g.x() - a.x()) / a.width()),
            "y": max(0.0, (g.y() - a.y()) / a.height()),
            "w": max(0.05, g.width() / a.width()),
            "h": max(0.05, g.height() / a.height()),
            "state": "maximized" if mw.isMaximized() else "normal",
        }
        # Same app state the picker's own S=save records — this is the
        # second place a preset is born, and a preset that means different
        # things depending on which surface made it is worse than neither.
        # The checkbox decides geometry-only vs full state.
        cap.update(_current_ui_state(mw))
        return cap

    # ---- actions ------------------------------------------------------
    def _capture_state_toggled(self, checked):
        data = getattr(self.main_win, "data", None)
        if data is None:
            return
        data["window_presets_capture_state"] = "True" if checked else "False"
        if hasattr(self.main_win, "mark_dirty"):
            self.main_win.mark_dirty()

    def move_up(self):
        r = self._row()
        if r > 0:
            self.presets[r - 1], self.presets[r] = self.presets[r], self.presets[r - 1]
            self._reload(keep=r - 1)

    def move_down(self):
        r = self._row()
        if 0 <= r < len(self.presets) - 1:
            self.presets[r + 1], self.presets[r] = self.presets[r], self.presets[r + 1]
            self._reload(keep=r + 1)

    def rename(self):
        r = self._row()
        if r < 0:
            return
        name, ok = QInputDialog.getText(self, tr("Rename preset", self.lang),
                                        tr("Name:", self.lang),
                                        text=self.presets[r]["name"])
        if ok and name.strip():
            self.presets[r]["name"] = name.strip()
            self._reload(keep=r)

    def recapture(self):
        """Point an existing preset at the window's CURRENT box, keeping its
        name and its slot — the picker alone could only delete and re-add,
        which moved it to the end and lost the name."""
        r = self._row()
        if r < 0:
            return
        cap = self._capture()
        if cap is None:
            return
        cap["name"] = self.presets[r]["name"]
        self.presets[r] = cap
        self._reload(keep=r)

    def delete(self):
        r = self._row()
        if r < 0:
            return
        self.presets.pop(r)
        self._reload(keep=min(r, len(self.presets) - 1))

    def add_current(self):
        if len(self.presets) >= _MAX_PRESETS:
            QMessageBox.information(
                self, tr("Preset Limit", self.lang),
                tr("Maximum of {} presets.", self.lang).format(_MAX_PRESETS))
            return
        cap = self._capture()
        if cap is None:
            return
        cap["name"] = f"Preset {len(self.presets) + 1}"
        self.presets.append(cap)
        self._reload(keep=len(self.presets) - 1)

    def accept(self):
        _save_presets(self.main_win.data, self.presets)
        if hasattr(self.main_win, "mark_dirty"):
            self.main_win.mark_dirty()
        super().accept()
