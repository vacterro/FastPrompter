"""Timer manager — create, edit and test limit-reset countdowns.

Opened by clicking the clock in the top bar. The common case ("remind me in
4 days 11 hours") stays one row: name, when, Add. Description, repeat,
sound, volume and colour sit underneath for when they're wanted, and a
Test button fires a throwaway copy in 5s so nobody has to wait four days to
find out their alarm was silent.
"""

from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.duration import PRESETS, format_remaining, resolve_target
from fastprompter.core.timers import (
    COLOR_STATIC,
    COLOR_TEMPERATURE,
    REPEAT_CHOICES,
    REPEAT_INTERVAL,
    describe,
    limit_window,
    Timer,
)
from fastprompter.core import pomodoro
from fastprompter.core.translations import tr

_SOUNDS = ("tick", "click", "new", "save", "delete", "clear", "silo", "snippet")
_TEST_DELAY_S = 5


class TimerDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self._editing_id = None

        self.setWindowTitle(tr("Timers", self.lang))
        self.setMinimumWidth(460)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs)

        alarms_page = QWidget()
        root = QVBoxLayout(alarms_page)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)
        self.tabs.addTab(alarms_page, tr("Alarms", self.lang))

        # ---- existing timers ----
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(130)
        self.list.setToolTip(tr(
            "Double-click a timer to edit it.\nColour shows how close it is.",
            self.lang))
        self.list.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        root.addWidget(self.list, 1)

        # ---- what and when ----
        row = QHBoxLayout()
        row.setSpacing(4)
        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText(tr("Name (e.g. Claude limit)", self.lang))
        self.in_name.setToolTip(tr("What is resetting", self.lang))
        row.addWidget(self.in_name, 2)

        self.in_when = QLineEdit()
        self.in_when.setPlaceholderText(tr("4 days 11 hours / 18:30", self.lang))
        self.in_when.setToolTip(tr(
            "A delay: 4 days 11 hours, 4d 11h, 90m, 1h30, 1.5h\n"
            "or a clock time: 18:30, tomorrow 9:00\n"
            "Russian works too. Press Enter to add.", self.lang))
        self.in_when.returnPressed.connect(self.commit)
        row.addWidget(self.in_when, 2)

        self.cb_preset = QComboBox()
        self.cb_preset.setToolTip(tr("Ready-made delays", self.lang))
        self.cb_preset.addItem(tr("Preset", self.lang), "")
        for label, value in PRESETS:
            self.cb_preset.addItem(label, value)
        self.cb_preset.currentIndexChanged.connect(self._preset_picked)
        row.addWidget(self.cb_preset, 1)
        root.addLayout(row)

        # ---- the 5-hour limit catcher ----
        # An agent quota is a rolling window, not a one-off alarm: it opened
        # at some moment and comes back every N hours from THAT moment. The
        # generic "when" box can express the first reset but not the roll,
        # and getting the anchor right by hand is exactly the fiddly part.
        limit = QHBoxLayout()
        limit.setSpacing(4)

        self.lbl_limit = QLabel(tr("Limit window:", self.lang))
        limit.addWidget(self.lbl_limit)

        self.spin_limit_hours = QDoubleSpinBox()
        self.spin_limit_hours.setRange(0.25, 72.0)
        self.spin_limit_hours.setSingleStep(0.5)
        self.spin_limit_hours.setDecimals(2)
        self.spin_limit_hours.setValue(5.0)
        self.spin_limit_hours.setSuffix(tr(" h", self.lang))
        self.spin_limit_hours.setToolTip(tr(
            "How long the window lasts. 5 hours is the usual agent quota.",
            self.lang))
        limit.addWidget(self.spin_limit_hours)

        self.in_limit_start = QLineEdit()
        self.in_limit_start.setPlaceholderText(tr("started (blank = now)", self.lang))
        self.in_limit_start.setToolTip(tr(
            "When the window OPENED, e.g. 09:20 - the countdown is that\n"
            "moment plus the hours on the left. Leave empty to start now.\n"
            "A start already in the past rolls forward to the next reset.",
            self.lang))
        self.in_limit_start.returnPressed.connect(self.add_limit_window)
        limit.addWidget(self.in_limit_start, 1)

        self.btn_limit = QPushButton(tr("Catch limit", self.lang))
        self.btn_limit.setToolTip(tr(
            "Add a repeating timer for a rolling usage window.\n"
            "It re-arms itself every period, so it keeps telling you\n"
            "when the NEXT reset lands - even after days offline.",
            self.lang))
        self.btn_limit.clicked.connect(self.add_limit_window)
        limit.addWidget(self.btn_limit)
        root.addLayout(limit)

        self.lbl_limit_hint = QLabel("")
        self.lbl_limit_hint.setWordWrap(True)
        root.addWidget(self.lbl_limit_hint)
        self.in_limit_start.textChanged.connect(self._preview_limit)
        self.spin_limit_hours.valueChanged.connect(
            lambda _v: self._preview_limit(self.in_limit_start.text()))

        # ---- description ----
        self.in_desc = QLineEdit()
        self.in_desc.setPlaceholderText(tr("Description (optional)", self.lang))
        self.in_desc.setToolTip(tr(
            "Shown in the notification popup when it fires", self.lang))
        self.in_desc.returnPressed.connect(self.commit)
        root.addWidget(self.in_desc)

        # ---- options ----
        opts = QHBoxLayout()
        opts.setSpacing(4)

        self.cb_repeat = QComboBox()
        self.cb_repeat.setToolTip(tr("How often it repeats", self.lang))
        for r in REPEAT_CHOICES:
            self.cb_repeat.addItem(tr(r.capitalize(), self.lang), r)
        opts.addWidget(self.cb_repeat)

        self.cb_sound = QComboBox()
        self.cb_sound.setToolTip(tr("Alarm sound", self.lang))
        for s in _SOUNDS:
            self.cb_sound.addItem(s)
        opts.addWidget(self.cb_sound)

        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 10)
        self.spin_vol.setValue(5)
        self.spin_vol.setToolTip(tr("Alarm volume (0-10)", self.lang))
        opts.addWidget(self.spin_vol)

        self.cb_temp = QCheckBox(tr("Heat colour", self.lang))
        self.cb_temp.setChecked(True)
        self.cb_temp.setToolTip(tr(
            "Colour warms from blue to red as the deadline nears.\n"
            "Off: always the same colour.", self.lang))
        opts.addWidget(self.cb_temp)

        self.btn_test = QPushButton(tr("Test", self.lang))
        self.btn_test.setToolTip(tr(
            "Fire these settings in 5 seconds so you can check the sound\n"
            "and the popup. Nothing is saved.", self.lang))
        self.btn_test.clicked.connect(self.test_now)
        opts.addWidget(self.btn_test)

        opts.addStretch(1)
        self.btn_commit = QPushButton(tr("Add", self.lang))
        self.btn_commit.clicked.connect(self.commit)
        opts.addWidget(self.btn_commit)
        root.addLayout(opts)

        # ---- live feedback ----
        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)
        self.in_when.textChanged.connect(self._preview)

        # ---- row actions ----
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.btn_edit = QPushButton(tr("Edit", self.lang))
        self.btn_edit.clicked.connect(self.edit_selected)
        actions.addWidget(self.btn_edit)

        self.btn_toggle = QPushButton(tr("Pause", self.lang))
        self.btn_toggle.setToolTip(tr("Pause or resume the selected timer", self.lang))
        self.btn_toggle.clicked.connect(self.toggle_selected)
        actions.addWidget(self.btn_toggle)

        self.btn_snooze = QPushButton(tr("+10m", self.lang))
        self.btn_snooze.setToolTip(tr("Push the selected timer back 10 minutes", self.lang))
        self.btn_snooze.clicked.connect(self.snooze_selected)
        actions.addWidget(self.btn_snooze)

        self.btn_remove = QPushButton(tr("Remove", self.lang))
        self.btn_remove.clicked.connect(self.remove_selected)
        actions.addWidget(self.btn_remove)

        actions.addStretch(1)
        self.btn_cancel_edit = QPushButton(tr("New", self.lang))
        self.btn_cancel_edit.setToolTip(tr("Clear the form", self.lang))
        self.btn_cancel_edit.clicked.connect(self.clear_form)
        actions.addWidget(self.btn_cancel_edit)

        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        actions.addWidget(btn_close)
        root.addLayout(actions)

        self._build_productivity_tab()

        # keep the countdown column honest while the dialog is open
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh)
        self._tick.start(1000)

        self.refresh()

    # ------------------------------------------------------------------
    def _build_productivity_tab(self):
        """Work/break timer, the my_timer2 model as a first-class feature.

        Separate from the alarms tab because it is a different kind of
        thing: alarms are deadlines that arrive on their own, this is a
        stopwatch the user drives and can pause for as long as they like.
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.lbl_pomo_clock = QLabel("")
        self.lbl_pomo_clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pomo_clock.setStyleSheet("font-size: 26px; font-weight: bold;")
        lay.addWidget(self.lbl_pomo_clock)

        self.lbl_pomo_state = QLabel("")
        self.lbl_pomo_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_pomo_state)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.addWidget(QLabel(tr("Work", self.lang)), 0, 0)
        self.spin_work_min = QSpinBox()
        self.spin_work_min.setRange(0, 600)
        self.spin_work_min.setSuffix(tr(" min", self.lang))
        grid.addWidget(self.spin_work_min, 0, 1)
        self.spin_work_sec = QSpinBox()
        self.spin_work_sec.setRange(0, 59)
        self.spin_work_sec.setSuffix(tr(" sec", self.lang))
        grid.addWidget(self.spin_work_sec, 0, 2)

        grid.addWidget(QLabel(tr("Break", self.lang)), 1, 0)
        self.spin_break_min = QSpinBox()
        self.spin_break_min.setRange(0, 600)
        self.spin_break_min.setSuffix(tr(" min", self.lang))
        grid.addWidget(self.spin_break_min, 1, 1)
        self.spin_break_sec = QSpinBox()
        self.spin_break_sec.setRange(0, 59)
        self.spin_break_sec.setSuffix(tr(" sec", self.lang))
        grid.addWidget(self.spin_break_sec, 1, 2)
        lay.addLayout(grid)

        for spin in (self.spin_work_min, self.spin_work_sec,
                     self.spin_break_min, self.spin_break_sec):
            spin.valueChanged.connect(lambda _v: self._pomo_durations_changed())

        opts = QHBoxLayout()
        opts.setSpacing(4)
        self.cb_pomo_breaks = QCheckBox(tr("Take breaks", self.lang))
        self.cb_pomo_breaks.setToolTip(tr(
            "Off: the timer stops when the work phase ends\n"
            "instead of starting a break.", self.lang))
        self.cb_pomo_breaks.toggled.connect(self._pomo_options_changed)
        opts.addWidget(self.cb_pomo_breaks)

        self.cb_pomo_repeat = QCheckBox(tr("Keep ringing", self.lang))
        self.cb_pomo_repeat.setToolTip(tr(
            "The alarm keeps sounding until you acknowledge it,\n"
            "so it still catches you if you left the desk.", self.lang))
        self.cb_pomo_repeat.toggled.connect(self._pomo_options_changed)
        opts.addWidget(self.cb_pomo_repeat)
        opts.addStretch(1)
        lay.addLayout(opts)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.btn_pomo_action = QPushButton(tr("Start", self.lang))
        self.btn_pomo_action.clicked.connect(self._pomo_toggle)
        buttons.addWidget(self.btn_pomo_action)

        self.btn_pomo_skip = QPushButton(tr("Skip phase", self.lang))
        self.btn_pomo_skip.setToolTip(tr(
            "Jump straight to the other phase", self.lang))
        self.btn_pomo_skip.clicked.connect(self._pomo_skip)
        buttons.addWidget(self.btn_pomo_skip)

        self.btn_pomo_reset = QPushButton(tr("Reset", self.lang))
        self.btn_pomo_reset.clicked.connect(self._pomo_reset)
        buttons.addWidget(self.btn_pomo_reset)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        lay.addStretch(1)

        self.tabs.addTab(page, tr("Productivity", self.lang))
        self._load_pomo_into_form()

    def _pomo(self):
        return self.main_win.productivity_timer

    def _load_pomo_into_form(self):
        """Fill the form from the model without echoing back into it."""
        t = self._pomo()
        widgets = (self.spin_work_min, self.spin_work_sec,
                   self.spin_break_min, self.spin_break_sec,
                   self.cb_pomo_breaks, self.cb_pomo_repeat)
        for w in widgets:
            w.blockSignals(True)
        self.spin_work_min.setValue(t.work_seconds // 60)
        self.spin_work_sec.setValue(t.work_seconds % 60)
        self.spin_break_min.setValue(t.break_seconds // 60)
        self.spin_break_sec.setValue(t.break_seconds % 60)
        self.cb_pomo_breaks.setChecked(t.breaks_enabled)
        self.cb_pomo_repeat.setChecked(t.repeat_alarm)
        for w in widgets:
            w.blockSignals(False)
        self._refresh_pomo()

    def _pomo_durations_changed(self):
        self._pomo().apply_durations(
            work_seconds=self.spin_work_min.value() * 60 + self.spin_work_sec.value(),
            break_seconds=self.spin_break_min.value() * 60 + self.spin_break_sec.value(),
        )
        self.main_win.save_productivity_timer()
        self._refresh_pomo()

    def _pomo_options_changed(self, _checked=False):
        t = self._pomo()
        t.breaks_enabled = self.cb_pomo_breaks.isChecked()
        t.repeat_alarm = self.cb_pomo_repeat.isChecked()
        self.main_win.save_productivity_timer()
        self._refresh_pomo()

    def _pomo_toggle(self):
        self._pomo().toggle()
        self.main_win.on_productivity_changed()
        self._refresh_pomo()

    def _pomo_skip(self):
        self._pomo().skip_phase()
        self.main_win.on_productivity_changed()
        self._refresh_pomo()

    def _pomo_reset(self):
        self._pomo().reset()
        self.main_win.on_productivity_changed()
        self._refresh_pomo()

    def _refresh_pomo(self):
        t = self._pomo()
        self.lbl_pomo_clock.setText(pomodoro.format_clock(t.remaining))
        self.lbl_pomo_state.setText(t.describe())
        self.btn_pomo_action.setText(
            tr("Pause", self.lang) if t.running
            else tr("Start", self.lang) if t.state == pomodoro.STATE_IDLE
            else tr("Resume", self.lang))
        colour = "#e0a03c" if t.phase == pomodoro.PHASE_BREAK else "#6aa9ff"
        if t.alarm_pending:
            colour = "#e05555"
        self.lbl_pomo_clock.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {colour};")

    # ------------------------------------------------------------------
    def _preset_picked(self, idx):
        value = self.cb_preset.itemData(idx)
        if value:
            self.in_when.setText(value)

    def _preview(self, text):
        """Say what will happen before the user commits to it."""
        if not text.strip():
            self.lbl_hint.setText("")
            return
        target = resolve_target(text)
        if target is None:
            self.lbl_hint.setText(tr("Not a time I understand", self.lang))
            return
        rem = (target - datetime.datetime.now()).total_seconds()
        self.lbl_hint.setText(
            f"{target.strftime('%d.%m %H:%M')}   ({format_remaining(rem)})")

    def _form_timer(self, target=None):
        """Build a Timer from the current form values."""
        return Timer(
            name=self.in_name.text().strip() or tr("Timer", self.lang),
            description=self.in_desc.text().strip(),
            target=target or datetime.datetime.now(),
            repeat=self.cb_repeat.currentData(),
            sound=self.cb_sound.currentText(),
            volume=self.spin_vol.value(),
            color_mode=COLOR_TEMPERATURE if self.cb_temp.isChecked() else COLOR_STATIC,
            interval_minutes=self._interval_minutes(),
        )

    def _interval_minutes(self):
        return max(1, int(round(self.spin_limit_hours.value() * 60)))

    def _limit_anchor(self):
        """Resolve the 'started at' box. Returns (anchor, ok)."""
        text = self.in_limit_start.text().strip()
        if not text:
            return datetime.datetime.now(), True
        anchor = resolve_target(text, prefer_past=True)
        return anchor, anchor is not None

    def _preview_limit(self, _text=None):
        """Spell out the next reset before the user commits to it."""
        anchor, ok = self._limit_anchor()
        if not ok:
            self.lbl_limit_hint.setText(tr("Not a time I understand", self.lang))
            return
        preview = limit_window(
            self.in_name.text().strip() or tr("Limit", self.lang),
            hours=self.spin_limit_hours.value(), anchor=anchor)
        self.lbl_limit_hint.setText(describe(preview))

    def add_limit_window(self):
        anchor, ok = self._limit_anchor()
        if not ok:
            self.lbl_limit_hint.setText(tr("Not a time I understand", self.lang))
            self.in_limit_start.setFocus()
            return
        timer = limit_window(
            self.in_name.text().strip() or tr("Limit", self.lang),
            hours=self.spin_limit_hours.value(),
            anchor=anchor,
            description=self.in_desc.text().strip(),
            sound=self.cb_sound.currentText(),
            volume=self.spin_vol.value(),
            color_mode=COLOR_TEMPERATURE if self.cb_temp.isChecked() else COLOR_STATIC,
        )
        self.main_win.timers.append(timer)
        self.main_win.save_timers_to_data()
        self.clear_form()
        self.refresh()
        self.lbl_limit_hint.setText(describe(timer))
        return timer

    def test_now(self):
        """Fire a throwaway copy in 5s — sound and popup, nothing saved."""
        self.main_win.test_timer_notification(self._form_timer(), _TEST_DELAY_S)
        self.lbl_hint.setText(
            tr("Test fires in {} seconds", self.lang).format(_TEST_DELAY_S))

    def commit(self):
        """Add a new timer, or save the one being edited."""
        text = self.in_when.text().strip()
        target = resolve_target(text)
        if target is None:
            self.lbl_hint.setText(tr("Not a time I understand", self.lang))
            self.in_when.setFocus()
            return

        if self._editing_id:
            existing = next((t for t in self.main_win.timers
                             if t.id == self._editing_id), None)
            if existing is not None:
                form = self._form_timer(target)
                existing.name = form.name
                existing.description = form.description
                existing.target = target
                existing.repeat = form.repeat
                existing.sound = form.sound
                existing.volume = form.volume
                existing.color_mode = form.color_mode
                existing.interval_minutes = form.interval_minutes
                existing.fired = False        # re-arm after an edit
        else:
            self.main_win.timers.append(self._form_timer(target))

        self.main_win.save_timers_to_data()
        self.clear_form()
        self.refresh()

    def clear_form(self):
        self._editing_id = None
        self.in_name.clear()
        self.in_desc.clear()
        self.in_when.clear()
        self.lbl_hint.setText("")
        self.btn_commit.setText(tr("Add", self.lang))
        self.in_name.setFocus()

    def _selected(self):
        item = self.list.currentItem()
        if item is None:
            return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return next((t for t in self.main_win.timers if t.id == tid), None)

    def edit_selected(self):
        t = self._selected()
        if t is None:
            return
        self._editing_id = t.id
        self.in_name.setText(t.name)
        self.in_desc.setText(t.description)
        self.in_when.setText(t.target.strftime("%H:%M"))
        idx = self.cb_repeat.findData(t.repeat)
        if idx >= 0:
            self.cb_repeat.setCurrentIndex(idx)
        s_idx = self.cb_sound.findText(t.sound)
        if s_idx >= 0:
            self.cb_sound.setCurrentIndex(s_idx)
        self.spin_vol.setValue(t.volume)
        self.cb_temp.setChecked(t.color_mode == COLOR_TEMPERATURE)
        self.btn_commit.setText(tr("Save", self.lang))
        self.lbl_hint.setText(
            tr("Editing '{}' - change the time and press Save", self.lang).format(t.name))

    def toggle_selected(self):
        t = self._selected()
        if t is None:
            return
        t.enabled = not t.enabled
        if t.enabled:
            t.fired = False
        self.main_win.save_timers_to_data()
        self.refresh()

    def snooze_selected(self):
        t = self._selected()
        if t is None:
            return
        t.snooze(10)
        self.main_win.save_timers_to_data()
        self.refresh()

    def remove_selected(self):
        t = self._selected()
        if t is None:
            return
        if self._editing_id == t.id:
            self.clear_form()
        self.main_win.timers = [x for x in self.main_win.timers if x.id != t.id]
        self.main_win.save_timers_to_data()
        self.refresh()

    def _update_buttons(self):
        t = self._selected()
        has = t is not None
        for b in (self.btn_edit, self.btn_toggle, self.btn_snooze, self.btn_remove):
            b.setEnabled(has)
        if has:
            self.btn_toggle.setText(
                tr("Resume", self.lang) if not t.enabled else tr("Pause", self.lang))

    def refresh(self):
        if hasattr(self, "lbl_pomo_clock"):
            self._refresh_pomo()
        from PyQt6.QtGui import QColor

        keep = self.list.currentItem()
        keep_id = keep.data(Qt.ItemDataRole.UserRole) if keep else None

        self.list.blockSignals(True)
        self.list.clear()
        now = datetime.datetime.now()
        for t in sorted(self.main_win.timers, key=lambda x: x.target):
            rem = t.remaining(now)
            when = t.target.strftime("%d.%m %H:%M")
            if not t.enabled:
                tail = tr("paused", self.lang)
            elif rem <= 0:
                tail = tr("done", self.lang)
            else:
                tail = format_remaining(rem)
            repeat = "" if t.repeat == "once" else f" ({t.repeat})"
            item = QListWidgetItem(f"{t.name}{repeat}  -  {when}  -  {tail}")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            tip = [t.name]
            if t.description:
                tip.append(t.description)
            tip.append(f"{when}  ({tail})")
            tip.append(f"{tr('Sound', self.lang)}: {t.sound}  vol {t.volume}")
            item.setToolTip("\n".join(tip))
            if t.enabled:
                item.setForeground(QColor(t.display_color(now)))
            self.list.addItem(item)
            if t.id == keep_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

        if keep_id is None and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def closeEvent(self, event):
        self._tick.stop()
        super().closeEvent(event)
