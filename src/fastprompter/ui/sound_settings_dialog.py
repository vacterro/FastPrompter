"""The sound panel: every event, its file, its volume, on or off (T-707).

Nothing about WHICH sound plays is hardcoded here. The event list comes from
`sound_manager.EVENT_LABELS`, the file list from whatever WAVs are actually in
`sound/`, and every change is written straight into `data["sound_events"]`,
which is the same map the player reads.
"""

from typing import Any

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from fastprompter.core.sound_manager import (
    _DEFAULT_SOUND_MAP,
    EVENT_LABELS,
)
from fastprompter.core.translations import tr

_COL_EVENT, _COL_ON, _COL_FILE, _COL_VOL, _COL_PLAY = range(5)

# A small painted pictogram per event, so the table is scannable without
# reading every label. Drawn, not emoji: no font dependency, and it matches
# the painted-language-flags approach used elsewhere in the app.
_EVENT_GLYPHS: dict[str, str] = {
    "new": "plus", "save": "save", "silo": "swap", "snippet": "doc",
    "tick": "check", "untick": "check", "delete": "cross", "clear": "cross",
    "undo": "undo", "redo": "redo", "select_all": "check",
    "settings": "gear", "help": "question", "hotkey": "key",
    "bold": "bold", "italic": "italic", "underline": "underline",
    "strike": "strike", "header": "header", "divider": "line",
    "snap": "corner", "find": "magnifier", "replace": "swap",
    "focus": "lock", "export": "export", "quit": "quit",
    "archive": "folder", "snippets_toggle": "panel", "transform": "swap",
    "sidebar": "panel", "lock": "lock", "copy": "copy", "paste": "paste",
    "cut": "scissors", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
    "escape": "quit", "search": "magnifier", "backup": "save",
    "restore": "restore", "reset": "reset", "timer_start": "clock",
    "profile": "user", "watcher": "eye", "type": "key",
    "backspace": "key", "click": "cursor", "hover": "cursor",
    "button_click": "cursor", "button_release": "cursor",
    "chest_open": "folder", "chest_close": "folder", "notify": "bell",
    "error": "exclaim", "success": "check", "timer": "alarm",
}

# Unknown glyph -> the bell, so a new event still gets a picture.
_GLYPH_FALLBACK = "bell"


def _event_color(event: str, base: QColor) -> QColor:
    """A stable per-event colour so every row's icon is individually
    distinguishable, even when events share a glyph shape (tick/untick,
    click/hover, find/search ...). The hue walks a golden-angle spread from
    the theme's own base colour, so the palette stays in the theme's family
    while no two adjacent events look alike."""
    hue = base.hue()
    if hue < 0:
        hue = 40
    try:
        idx = sorted(_EVENT_GLYPHS).index(event)
    except ValueError:
        idx = 0
    rotated = (hue + int((idx * 137.5) % 360)) % 360
    return QColor.fromHsv(
        rotated, max(80, base.saturation()), max(140, base.value()))


def _event_icon(event: str, base: QColor) -> QIcon:
    """A 20x20 painted pictogram for one sound event, tinted per event."""
    color = _event_color(event, base)
    glyph = _EVENT_GLYPHS.get(event, _GLYPH_FALLBACK)
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.4)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # helpers used by several glyphs
    def line(x1, y1, x2, y2):
        p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def arrow(x1, y1, x2, y2):
        p.drawLine(int(x1), int(y1), int(x2), int(y2))
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        for da in (2.5, -2.5):
            p.drawLine(int(x2), int(y2),
                       int(x2 - 3.5 * math.cos(ang + da)),
                       int(y2 - 3.5 * math.sin(ang + da)))

    def circle(cx, cy, r):
        p.drawEllipse(QRect(int(cx - r), int(cy - r), int(2 * r), int(2 * r)))

    if glyph == "plus":
        line(10, 4, 10, 16); line(4, 10, 16, 10)
    elif glyph == "save":
        p.drawRect(QRect(3, 3, 14, 14)); p.drawRect(QRect(6, 6, 8, 6)); line(6, 15, 14, 15)
    elif glyph == "doc":
        p.drawRect(QRect(6, 3, 8, 14)); line(8, 6, 12, 6); line(8, 9, 12, 9); line(8, 12, 11, 12)
    elif glyph == "check":
        line(3, 10, 8, 15); line(8, 15, 17, 5)
    elif glyph == "cross":
        line(5, 5, 15, 15); line(15, 5, 5, 15)
    elif glyph == "undo":
        arrow(15, 5, 7, 5); p.drawArc(QRect(4, 4, 11, 11), 60 * 16, -180 * 16)
    elif glyph == "redo":
        arrow(5, 5, 13, 5); p.drawArc(QRect(5, 4, 11, 11), 120 * 16, 180 * 16)
    elif glyph == "gear":
        circle(10, 10, 4.5); p.drawEllipse(QRect(7, 7, 6, 6))
        for a in range(0, 360, 45):
            import math
            r0, r1 = 7.5, 9.5
            p.drawLine(int(10 + r0 * math.cos(math.radians(a))),
                       int(10 + r0 * math.sin(math.radians(a))),
                       int(10 + r1 * math.cos(math.radians(a))),
                       int(10 + r1 * math.sin(math.radians(a))))
    elif glyph == "question":
        p.drawText(QRect(2, 2, 16, 16), Qt.AlignmentFlag.AlignCenter, "?")
    elif glyph == "key":
        circle(6, 10, 3.5); line(9, 10, 15, 10); line(13, 10, 13, 13); line(15, 10, 15, 13)
    elif glyph == "bold":
        p.setFont(QFont("Verdana", 9, QFont.Weight.Bold))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "B")
    elif glyph == "italic":
        p.setFont(QFont("Verdana", 9, QFont.Weight.Normal))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "I")
    elif glyph == "underline":
        p.setFont(QFont("Verdana", 9, QFont.Weight.Normal))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "U")
        line(4, 17, 16, 17)
    elif glyph == "strike":
        p.setFont(QFont("Verdana", 9, QFont.Weight.Normal))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "S")
        line(3, 11, 17, 11)
    elif glyph == "header":
        line(5, 4, 5, 16); line(15, 4, 15, 16); line(5, 10, 15, 10)
    elif glyph == "line":
        line(3, 10, 17, 10)
    elif glyph == "corner":
        line(3, 3, 3, 17); line(3, 17, 17, 17)
    elif glyph == "magnifier":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16)
    elif glyph == "lock":
        p.drawRect(QRect(5, 9, 10, 8)); p.drawArc(QRect(6, 4, 8, 8), 0, 180 * 16); line(9, 13, 11, 13)
    elif glyph == "export":
        arrow(10, 3, 10, 13); line(10, 3, 6, 7); line(10, 3, 14, 7); line(3, 17, 17, 17)
    elif glyph == "quit":
        arrow(10, 3, 10, 13); line(10, 3, 6, 7); line(10, 3, 14, 7); line(3, 17, 17, 17)
        line(3, 17, 17, 17)
    elif glyph == "folder":
        path = QPainterPath()
        path.moveTo(2, 8)
        path.lineTo(18, 8)
        path.lineTo(18, 17)
        path.lineTo(2, 17)
        path.closeSubpath()
        p.drawPath(path)
        line(2, 6, 8, 6)
        line(2, 6, 2, 17)
    elif glyph == "panel":
        line(3, 6, 17, 6); line(3, 11, 17, 11); line(3, 16, 17, 16)
    elif glyph == "scissors":
        line(4, 4, 16, 16); line(16, 4, 4, 16); circle(4, 4, 2.2); circle(16, 4, 2.2)
    elif glyph == "copy":
        p.drawRect(QRect(4, 6, 10, 12)); line(7, 4, 17, 4); line(17, 4, 17, 14)
    elif glyph == "paste":
        p.drawRect(QRect(4, 6, 12, 11)); p.drawRect(QRect(8, 3, 5, 4))
    elif glyph == "zoom_in":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16); line(8, 5, 8, 11); line(5, 8, 11, 8)
    elif glyph == "zoom_out":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16); line(5, 8, 11, 8)
    elif glyph == "restore":
        circle(10, 10, 6); arrow(14, 5, 10, 5); line(10, 5, 10, 10)
    elif glyph == "reset":
        arrow(13, 13, 15, 11); p.drawArc(QRect(4, 4, 12, 12), 30 * 16, 300 * 16)
    elif glyph == "clock":
        circle(10, 10, 6.5); line(10, 6, 10, 10); line(10, 10, 14, 12)
    elif glyph == "user":
        circle(10, 6, 3); p.drawArc(QRect(4, 10, 12, 9), 0, 180 * 16)
    elif glyph == "eye":
        p.drawEllipse(QRect(2, 7, 16, 8)); circle(10, 11, 2.5)
    elif glyph == "cursor":
        p.setBrush(QColor(color))
        p.drawPolygon([QPoint(5, 3), QPoint(15, 10), QPoint(10, 11),
                       QPoint(12, 16), QPoint(8, 16), QPoint(7, 11), QPoint(5, 3)])
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif glyph == "bell":
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14); line(10, 15, 10, 17)
    elif glyph == "exclaim":
        line(10, 4, 10, 12); p.drawEllipse(QRect(8, 14, 4, 4))
    elif glyph == "alarm":
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14); line(10, 15, 10, 17)
        line(10, 6, 10, 10); line(10, 10, 13, 12)
    else:
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14)
    p.end()
    return QIcon(pm)


class SoundSettingsDialog(QDialog):
    def __init__(self, parent, data: dict[str, Any], sound_manager):
        super().__init__(parent)
        self.main_win = parent
        self._data = data
        self._sound_manager = sound_manager
        self._available = sound_manager.get_available_sounds()
        self.lang = getattr(parent, "_current_lang", "EN")
        # Set while widgets are being filled from settings. Every handler
        # returns early on it, which is what keeps _load_settings() from
        # writing back the values it just read — and lets Reset reuse the
        # same loader instead of a second, drifting copy of it.
        self._loading = False

        self.setWindowTitle(tr("Sound Settings", self.lang))
        self.resize(720, 520)
        # Wear the app's theme. Without this the dialog is a stock-white Qt
        # window inside a dark golden app — the scrollbar and the table's
        # empty right-hand strip came out bright white.
        try:
            self.setStyleSheet(parent.styleSheet())
        except Exception:
            pass
        self._build()
        self._load_settings()

    # ---- construction -------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        info = QLabel(tr(
            "Picking a sound plays it. Volume 0 = the global volume.",
            self.lang))
        info.setWordWrap(True)
        layout.addWidget(info)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText(tr("Filter events…", self.lang))
        self.filter_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_box)

        # Icon colour follows the theme's text colour (gold on the dark
        # golden theme), so the pictograms stay visible on any theme.
        try:
            icon_color = self.palette().color(
                self.palette().ColorRole.Text)
        except Exception:
            icon_color = QColor("#d0b060")

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("Event", self.lang), tr("On", self.lang), tr("Sound", self.lang),
            tr("Volume", self.lang), "▶",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        # Give the zebra stripes a tone the theme can see: the app QSS does
        # not set AlternateBase, so without this the alternating colors are
        # both the same.
        try:
            pal = self.table.palette()
            base = pal.color(pal.ColorRole.Base)
            pal.setColor(pal.ColorRole.AlternateBase, QColor(base).lighter(106))
            self.table.setPalette(pal)
        except Exception:
            pass

        events = list(EVENT_LABELS)
        self.table.setRowCount(len(events))
        self._rows = {}
        for row, event in enumerate(events):
            item = QTableWidgetItem(tr(EVENT_LABELS[event], self.lang))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(event)
            item.setIcon(_event_icon(event, icon_color))
            self.table.setItem(row, _COL_EVENT, item)

            on = QCheckBox()
            on.toggled.connect(lambda checked, e=event: self._set_enabled(e, checked))
            self.table.setCellWidget(row, _COL_ON, on)

            combo = QComboBox()
            combo.setMaxVisibleItems(20)
            for name in self._available:
                combo.addItem(name, name)
            combo.currentIndexChanged.connect(
                lambda _idx, e=event, c=combo: self._set_file(e, c))
            self.table.setCellWidget(row, _COL_FILE, combo)

            vol = QSlider(Qt.Orientation.Horizontal)
            vol.setRange(0, 10)
            # TicksBelow — PyQt6 uses the C++ enumerator names verbatim, and
            # the wrong one is an AttributeError that only fires when this
            # dialog is opened.
            vol.setTickPosition(QSlider.TickPosition.TicksBelow)
            vol.setTickInterval(1)
            vol.setFixedWidth(150)
            vol.setToolTip(tr("0 = use the global volume", self.lang))
            vol.valueChanged.connect(lambda v, e=event: self._set_volume(e, v))
            self.table.setCellWidget(row, _COL_VOL, vol)

            play = QPushButton("▶")
            play.setFixedWidth(28)
            play.setToolTip(tr("Play this sound", self.lang))
            play.clicked.connect(lambda _c, e=event: self._preview(e))
            self.table.setCellWidget(row, _COL_PLAY, play)

            self.table.setRowHeight(row, 34)
            self._rows[event] = row

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_EVENT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_VOL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_PLAY, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        reset = QPushButton(tr("Reset to defaults", self.lang))
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        buttons.addStretch()
        close = QPushButton(tr("Close", self.lang))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    # ---- settings <-> widgets -----------------------------------------
    def _events(self):
        events = self._data.get("sound_events")
        if not isinstance(events, dict):
            events = {}
            self._data["sound_events"] = events
        return events

    def _config(self, event):
        events = self._events()
        cfg = events.get(event)
        if not isinstance(cfg, dict):
            cfg = {}
            events[event] = cfg
        return cfg

    def _load_settings(self):
        self._loading = True
        try:
            for event, row in self._rows.items():
                cfg = self._config(event)
                self.table.cellWidget(row, _COL_ON).setChecked(
                    cfg.get("enabled", "True") == "True")

                combo = self.table.cellWidget(row, _COL_FILE)
                wanted = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
                idx = combo.findData(wanted)
                if idx < 0 and wanted:
                    # a file that is no longer in the folder: keep it visible
                    # rather than silently showing something else
                    combo.addItem(f"{wanted} ({tr('missing', self.lang)})", wanted)
                    idx = combo.count() - 1
                combo.setCurrentIndex(max(0, idx))

                try:
                    vol = int(cfg.get("volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                self.table.cellWidget(row, _COL_VOL).setValue(max(0, min(10, vol)))
        finally:
            self._loading = False

    def _touch(self):
        if hasattr(self.main_win, "mark_dirty"):
            self.main_win.mark_dirty()

    def _set_enabled(self, event, checked):
        if self._loading:
            return
        self._config(event)["enabled"] = "True" if checked else "False"
        self._touch()

    def _set_file(self, event, combo):
        if self._loading:
            return
        name = combo.currentData()
        if not name:
            return
        self._config(event)["file"] = name
        self._touch()
        self._preview(event)          # picking a sound plays it

    def _set_volume(self, event, value):
        if self._loading:
            return
        self._config(event)["volume"] = "" if value == 0 else str(value)
        self._touch()

    def _preview(self, event):
        """Play what this row is set to, whatever the global toggles say.

        Straight through the manager's file player rather than `play(event)`:
        the preview must work while UI sounds are switched off, and it must
        not depend on the row's own enabled checkbox either.
        """
        cfg = self._config(event)
        name = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
        if not name:
            return
        try:
            vol = int(cfg.get("volume") or 0)
        except (TypeError, ValueError):
            vol = 0
        self._sound_manager.play_file(name, vol or None)

    def _reset(self):
        if QMessageBox.question(
                self, tr("Reset to defaults", self.lang),
                tr("Put every sound back to the shipped default?", self.lang),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._data["sound_events"] = {
            event: {"file": default, "enabled": "True", "volume": ""}
            for event, default in _DEFAULT_SOUND_MAP.items()
        }
        self._load_settings()
        self._touch()

    def _apply_filter(self, text):
        needle = (text or "").strip().lower()
        for event, row in self._rows.items():
            label = self.table.item(row, _COL_EVENT).text().lower()
            self.table.setRowHidden(
                row, bool(needle) and needle not in label and needle not in event)
