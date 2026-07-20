"""Timer manager — create and edit limit-reset countdowns.

Opened by clicking the clock in the top bar. The point of the layout is
that the common case ("remind me in 4 days 11 hours") is one field and one
button; everything else stays out of the way until wanted.
"""

from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from fastprompter.core.duration import PRESETS, format_remaining, resolve_target
from fastprompter.core.timers import (
    COLOR_STATIC,
    COLOR_TEMPERATURE,
    REPEAT_CHOICES,
    Timer,
)
from fastprompter.core.translations import tr

_SOUNDS = ("tick", "click", "new", "save", "delete", "clear", "silo", "snippet")


class TimerDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Timers", lang))
        self.setMinimumWidth(430)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(120)
        root.addWidget(self.list, 1)

        # --- the one-liner: what, and when ---
        row = QHBoxLayout()
        row.setSpacing(4)
        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText(tr("Name (e.g. Claude limit)", lang))
        row.addWidget(self.in_name, 2)

        self.in_when = QLineEdit()
        self.in_when.setPlaceholderText(tr("4 days 11 hours / 18:30", lang))
        self.in_when.setToolTip(tr(
            "Type a delay (4 days 11 hours, 90m, 1h30) or a clock time\n"
            "(18:30, tomorrow 9:00). Russian works too.", lang))
        self.in_when.returnPressed.connect(self.add_timer)
        row.addWidget(self.in_when, 2)

        self.cb_preset = QComboBox()
        self.cb_preset.addItem(tr("Preset…", lang), "")
        for label, value in PRESETS:
            self.cb_preset.addItem(label, value)
        self.cb_preset.currentIndexChanged.connect(self._preset_picked)
        row.addWidget(self.cb_preset, 1)
        root.addLayout(row)

        # --- options ---
        opts = QHBoxLayout()
        opts.setSpacing(4)
        self.cb_repeat = QComboBox()
        for r in REPEAT_CHOICES:
            self.cb_repeat.addItem(tr(r.capitalize(), lang), r)
        opts.addWidget(self.cb_repeat)

        self.cb_sound = QComboBox()
        for s in _SOUNDS:
            self.cb_sound.addItem(s)
        opts.addWidget(self.cb_sound)

        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 10)
        self.spin_vol.setValue(5)
        self.spin_vol.setToolTip(tr("Volume", lang))
        opts.addWidget(self.spin_vol)

        self.cb_temp = QCheckBox(tr("Heat colour", lang))
        self.cb_temp.setChecked(True)
        self.cb_temp.setToolTip(tr(
            "Colour warms as the deadline gets closer.\n"
            "Off: always the timer's own colour.", lang))
        opts.addWidget(self.cb_temp)
        opts.addStretch(1)

        self.btn_add = QPushButton(tr("Add", lang))
        self.btn_add.clicked.connect(self.add_timer)
        opts.addWidget(self.btn_add)
        root.addLayout(opts)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)
        self.in_when.textChanged.connect(self._preview)

        # --- actions on the selected timer ---
        actions = QHBoxLayout()
        actions.setSpacing(4)
        for text, slot in (
            (tr("Toggle", lang), self.toggle_selected),
            (tr("Remove", lang), self.remove_selected),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        btn_close = QPushButton(tr("Close", lang))
        btn_close.clicked.connect(self.accept)
        actions.addWidget(btn_close)
        root.addLayout(actions)

        self.refresh()

    # ------------------------------------------------------------------
    def _preset_picked(self, idx):
        value = self.cb_preset.itemData(idx)
        if value:
            self.in_when.setText(value)

    def _preview(self, text):
        """Say what will happen before the user commits to it."""
        lang = getattr(self.main_win, "_current_lang", "EN")
        if not text.strip():
            self.lbl_hint.setText("")
            return
        target = resolve_target(text)
        if target is None:
            self.lbl_hint.setText(tr("Not a time I understand", lang))
            return
        rem = (target - datetime.datetime.now()).total_seconds()
        self.lbl_hint.setText(
            f"{target.strftime('%d.%m %H:%M')}  ({format_remaining(rem)})")

    def add_timer(self):
        text = self.in_when.text().strip()
        target = resolve_target(text)
        if target is None:
            lang = getattr(self.main_win, "_current_lang", "EN")
            self.lbl_hint.setText(tr("Not a time I understand", lang))
            return
        timer = Timer(
            name=self.in_name.text().strip() or tr(
                "Timer", getattr(self.main_win, "_current_lang", "EN")),
            target=target,
            repeat=self.cb_repeat.currentData(),
            sound=self.cb_sound.currentText(),
            volume=self.spin_vol.value(),
            color_mode=COLOR_TEMPERATURE if self.cb_temp.isChecked() else COLOR_STATIC,
        )
        self.main_win.timers.append(timer)
        self.main_win.save_timers_to_data()
        self.in_name.clear()
        self.in_when.clear()
        self.lbl_hint.setText("")
        self.refresh()

    def _selected(self):
        item = self.list.currentItem()
        if item is None:
            return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return next((t for t in self.main_win.timers if t.id == tid), None)

    def toggle_selected(self):
        t = self._selected()
        if t is None:
            return
        t.enabled = not t.enabled
        if t.enabled:
            t.fired = False
        self.main_win.save_timers_to_data()
        self.refresh()

    def remove_selected(self):
        t = self._selected()
        if t is None:
            return
        self.main_win.timers = [x for x in self.main_win.timers if x.id != t.id]
        self.main_win.save_timers_to_data()
        self.refresh()

    def refresh(self):
        from PyQt6.QtGui import QColor

        lang = getattr(self.main_win, "_current_lang", "EN")
        self.list.clear()
        now = datetime.datetime.now()
        for t in sorted(self.main_win.timers, key=lambda x: x.target):
            rem = t.remaining(now)
            when = t.target.strftime("%d.%m %H:%M")
            if not t.enabled:
                tail = tr("paused", lang)
            elif rem <= 0:
                tail = tr("done", lang)
            else:
                tail = format_remaining(rem)
            repeat = "" if t.repeat == "once" else f" ({t.repeat})"
            item = QListWidgetItem(f"{t.name}{repeat} — {when} — {tail}")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            if t.enabled:
                item.setForeground(QColor(t.display_color(now)))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
