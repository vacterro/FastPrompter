"""The sound panel: every event, its file, its volume, on or off (T-707).

Nothing about WHICH sound plays is hardcoded here. The event list comes from
`sound_manager.EVENT_LABELS`, the file list from whatever WAVs are actually in
`sound/`, and every change is written straight into `data["sound_events"]`,
which is the same map the player reads.
"""

from typing import Any

from PyQt6.QtCore import Qt
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

        info = QLabel(tr(
            "Every sound the app makes. Changes apply immediately; picking a "
            "sound plays it. Volume 0 means \"use the global volume\".",
            self.lang))
        info.setWordWrap(True)
        layout.addWidget(info)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText(tr("Filter events…", self.lang))
        self.filter_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_box)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("Event", self.lang), tr("On", self.lang), tr("Sound", self.lang),
            tr("Volume", self.lang), "",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        events = list(EVENT_LABELS)
        self.table.setRowCount(len(events))
        self._rows = {}
        for row, event in enumerate(events):
            item = QTableWidgetItem(tr(EVENT_LABELS[event], self.lang))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(event)
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
            vol.setToolTip(tr("0 = use the global volume", self.lang))
            vol.valueChanged.connect(lambda v, e=event: self._set_volume(e, v))
            self.table.setCellWidget(row, _COL_VOL, vol)

            play = QPushButton("▶")
            play.setFixedWidth(28)
            play.setToolTip(tr("Play this sound", self.lang))
            play.clicked.connect(lambda _c, e=event: self._preview(e))
            self.table.setCellWidget(row, _COL_PLAY, play)

            self._rows[event] = row

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_EVENT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_VOL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_PLAY, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

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
