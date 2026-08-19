"""Timer manager — create, edit and test limit-reset countdowns.

Opened by clicking the clock in the top bar. The common case ("remind me in
4 days 11 hours") stays one row: name, when, Add. Description, repeat,
sound, volume and colour sit underneath for when they're wanted, and a
Test button fires a throwaway copy in 5s so nobody has to wait four days to
find out their alarm was silent.
"""

from __future__ import annotations

import datetime

from PyQt6.QtCore import QDate, QDateTime, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core import pomodoro
from fastprompter.core.duration import PRESETS, format_remaining, resolve_target
from fastprompter.core.timers import (
    COLOR_STATIC,
    COLOR_TEMPERATURE,
    KIND_ALARM,
    KIND_CALENDAR,
    MAX_TIMER_SOUND_RULES,
    REPEAT_CHOICES,
    REPEAT_DAILY,
    REPEAT_INTERVAL,
    REPEAT_MONTHLY,
    REPEAT_NONE,
    REPEAT_WEEKLY,
    REPEAT_YEARLY,
    SOUND_MODE_POOL,
    SOUND_MODE_SINGLE,
    Timer,
    describe,
    limit_window,
    occurrences_in_month,
    occurs_on_date,
)
from fastprompter.core.translations import tr

_SOUNDS = ("tick", "click", "new", "save", "delete", "clear", "silo", "snippet")
_TEST_DELAY_S = 5


# ---------------------------------------------------------------------------
# T-1005 / T-1006. One reusable block of "how this timer behaves" controls.
#
# Alarm and Calendar forms differ in time/repeat/name fields, but the behaviour
# knobs (show notification, show in top bar, heat/static colour, default volume,
# single vs random-pool sound) are identical truth. This widget owns them once
# so the two forms never duplicate 150 lines of sound/notify/topbar form.
# ---------------------------------------------------------------------------

class _TimerBehaviorEditor(QWidget):
    """Reusable timer-behaviour editor: notify / top-bar / colour / sound."""

    # (sound_ref, volume) the host should audition immediately
    previewRequested = pyqtSignal(str, int)

    def __init__(self, main_win, lang, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.lang = lang
        self._sound_choices = []  # [(display, ref), ...] built once per dialog

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ---- notify / top-bar toggles ----
        toggles = QHBoxLayout()
        toggles.setSpacing(4)
        self.cb_show_notif = QCheckBox(tr("Show notification", lang))
        self.cb_show_notif.setChecked(True)
        self.cb_show_topbar = QCheckBox(tr("Show in top bar", lang))
        self.cb_show_topbar.setChecked(True)
        toggles.addWidget(self.cb_show_notif)
        toggles.addWidget(self.cb_show_topbar)
        toggles.addStretch(1)
        lay.addLayout(toggles)

        # ---- colour + default volume ----
        basics = QHBoxLayout()
        basics.setSpacing(4)
        self.cb_temp = QCheckBox(tr("Heat colour", lang))
        self.cb_temp.setChecked(True)
        self.cb_temp.setToolTip(tr(
            "Colour warms from blue to red as the deadline nears.\n"
            "Off: always the same colour.", lang))
        basics.addWidget(self.cb_temp)

        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 10)
        self.spin_vol.setValue(5)
        self.spin_vol.setToolTip(tr("Alarm volume (0-10)", lang))
        basics.addWidget(QLabel(tr("Vol", lang)))
        basics.addWidget(self.spin_vol)
        basics.addStretch(1)
        lay.addLayout(basics)

        # ---- single sound vs random pool ----
        self.cb_pool = QCheckBox(tr("Random sound pool", lang))
        self.cb_pool.setToolTip(tr(
            "Play a random sound from a pool of rules, each with its own\n"
            "time window and volume. Off: the single sound above is used.", lang))
        lay.addWidget(self.cb_pool)

        self.cb_sound = QComboBox()
        self.cb_sound.setToolTip(tr(
            "Alarm sound — the named events first, then every file in the "
            "library", lang))
        self._fill_sound_choices()
        lay.addWidget(self.cb_sound)

        # ---- pool editor ----
        self.pool = QTableWidget()
        self.pool.setColumnCount(6)
        self.pool.setHorizontalHeaderLabels([
            tr("On", lang), tr("Sound", lang), tr("All day", lang),
            tr("From", lang), tr("To", lang), tr("Volume", lang),
        ])
        self.pool.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pool.horizontalHeader().setStretchLastSection(True)
        self.pool.setVisible(False)
        lay.addWidget(self.pool)

        pool_btns = QHBoxLayout()
        pool_btns.setSpacing(4)
        self.btn_pool_add = QPushButton(tr("Add sound", lang))
        self.btn_pool_add.clicked.connect(self._pool_add)
        self.btn_pool_remove = QPushButton(tr("Remove sound", lang))
        self.btn_pool_remove.clicked.connect(self._pool_remove)
        pool_btns.addWidget(self.btn_pool_add)
        pool_btns.addWidget(self.btn_pool_remove)
        pool_btns.addStretch(1)
        lay.addLayout(pool_btns)

        self.cb_pool.toggled.connect(self._on_pool_toggled)
        # preview ONLY on real user activation, never on programmatic set
        self.cb_sound.activated.connect(lambda _i: self._preview_single())

    # -- cached sound choices ------------------------------------------------
    def _fill_sound_choices(self):
        """Build the sound combo ONCE. Named events first, then every file.

        Reads the SoundManager's own cached inventory so Alarm and Calendar
        editors always derive their choices from the SAME library listing.
        """
        self.cb_sound.setMaxVisibleItems(20)
        self._sound_choices = []
        for name in _SOUNDS:
            self._sound_choices.append((name, name))
            self.cb_sound.addItem(name, name)
        try:
            files = self.main_win.sound_manager.get_available_sounds()
        except Exception:
            files = []
        if files:
            self.cb_sound.insertSeparator(self.cb_sound.count())
            for rel in files:
                self._sound_choices.append((rel, f"file:{rel}"))
                self.cb_sound.addItem(rel, f"file:{rel}")

    def select_sound(self, value):
        idx = self.cb_sound.findData(value or "tick")
        if idx < 0:
            idx = self.cb_sound.findData("tick")
        if idx >= 0:
            self.cb_sound.setCurrentIndex(idx)

    # -- pool table ----------------------------------------------------------
    def _on_pool_toggled(self, on):
        self.cb_sound.setVisible(not on)
        self.pool.setVisible(on)
        self.btn_pool_add.setVisible(on)
        self.btn_pool_remove.setVisible(on)
        self._refresh_pool_buttons()

    def _refresh_pool_buttons(self):
        at_cap = self.pool.rowCount() >= MAX_TIMER_SOUND_RULES
        self.btn_pool_add.setEnabled(not at_cap)

    def _default_rule(self):
        ref = self.cb_sound.currentData() or "tick"
        return {"sound": ref, "enabled": True, "all_day": True,
                "start_minute": 0, "end_minute": 0, "volume": None}

    def _pool_add(self):
        if self.pool.rowCount() >= MAX_TIMER_SOUND_RULES:
            return
        self._pool_append_row(self._default_rule())
        self._refresh_pool_buttons()
        self._preview_pool_row(self.pool.rowCount() - 1)

    def _pool_remove(self):
        row = self.pool.currentRow()
        if row < 0:
            return
        self.pool.removeRow(row)
        self._refresh_pool_buttons()

    def _pool_append_row(self, rule):
        r = self.pool.rowCount()
        self.pool.insertRow(r)
        self._pool_set_row(r, rule)

    def _pool_set_row(self, r, rule):
        en = QCheckBox()
        en.setChecked(bool(rule.get("enabled", True)))
        self.pool.setCellWidget(r, 0, en)

        sound = QComboBox()
        sound.setMaxVisibleItems(20)
        for disp, ref in self._sound_choices:
            sound.addItem(disp, ref)
        idx = sound.findData(rule.get("sound") or "tick")
        sound.setCurrentIndex(idx if idx >= 0 else 0)
        self.pool.setCellWidget(r, 1, sound)

        allday = QCheckBox()
        allday.setChecked(bool(rule.get("all_day", True)))
        self.pool.setCellWidget(r, 2, allday)

        frm = QTimeEdit()
        frm.setDisplayFormat("HH:mm")
        frm.setTime(_minute_to_time(rule.get("start_minute", 0)))
        self.pool.setCellWidget(r, 3, frm)

        to = QTimeEdit()
        to.setDisplayFormat("HH:mm")
        to.setTime(_minute_to_time(rule.get("end_minute", 0)))
        self.pool.setCellWidget(r, 4, to)

        vol = QSpinBox()
        vol.setRange(-1, 10)
        vol.setSpecialValueText(tr("Timer", self.lang))
        v = rule.get("volume", None)
        vol.setValue(-1 if v is None else max(-1, min(10, int(v))))
        self.pool.setCellWidget(r, 5, vol)

        # Signals capture the WIDGETS, never the table row: removing an
        # earlier row shifts every later one, so a captured row number would
        # point at the wrong sound / the wrong From-To pair after any
        # remove/add sequence.
        sound.activated.connect(
            lambda _i, s=sound, v=vol: self._preview_pool_widgets(s, v))
        allday.toggled.connect(
            lambda _c, a=allday, f=frm, t=to: self._sync_window_widgets(a, f, t))
        self._sync_window_widgets(allday, frm, to)

    def _sync_window_widgets(self, allday, frm, to):
        """Enable/disable a row's From/To edits straight from its widgets."""
        on = not allday.isChecked()
        frm.setEnabled(on)
        to.setEnabled(on)

    def _read_pool_rules(self):
        out = []
        for r in range(self.pool.rowCount()):
            en = self.pool.cellWidget(r, 0)
            sound = self.pool.cellWidget(r, 1)
            allday = self.pool.cellWidget(r, 2)
            frm = self.pool.cellWidget(r, 3)
            to = self.pool.cellWidget(r, 4)
            vol = self.pool.cellWidget(r, 5)
            ref = sound.currentData() or "tick"
            all_day = allday.isChecked()
            start = _time_to_minute(frm.time()) if not all_day else 0
            end = _time_to_minute(to.time()) if not all_day else 0
            v = vol.value()
            out.append({
                "sound": ref,
                "enabled": en.isChecked(),
                "all_day": all_day,
                "start_minute": start,
                "end_minute": end,
                "volume": None if v < 0 else v,
            })
        return out

    # -- preview (user activation only) -------------------------------------
    def _preview_single(self):
        if self.cb_pool.isChecked():
            return
        self.previewRequested.emit(self.cb_sound.currentData() or "tick",
                                   self.spin_vol.value())

    def _preview_pool_row(self, row):
        if not self.cb_pool.isChecked():
            return
        if row < 0 or row >= self.pool.rowCount():
            return
        sound = self.pool.cellWidget(row, 1)
        vol = self.pool.cellWidget(row, 5)
        self._preview_pool_widgets(sound, vol)

    def _preview_pool_widgets(self, sound, vol):
        """Preview one pool row straight from its widgets.

        Emits the EFFECTIVE volume: a rule whose volume says "inherit the
        timer default" resolves to THIS editor's volume spin, so the host
        never has to guess which editor a preview request came from.
        """
        if not self.cb_pool.isChecked():
            return
        v = vol.value()
        ref = sound.currentData() or "tick"
        self.previewRequested.emit(ref, self.spin_vol.value() if v < 0 else v)

    # -- validation --------------------------------------------------------
    def validate(self):
        """First pool-row problem as a user message, or None.

        One rule, enforced by every form that can save a timer: a
        non-all-day row whose start equals end matches nothing, ever, so it
        must not be saved as an apparently active rule.
        """
        for i in range(self.pool.rowCount()):
            allday = self.pool.cellWidget(i, 2)
            if allday.isChecked():
                continue
            frm = self.pool.cellWidget(i, 3)
            to = self.pool.cellWidget(i, 4)
            if _time_to_minute(frm.time()) == _time_to_minute(to.time()):
                return tr("Sound rule {} has an empty time range.", self.lang) \
                    .format(i + 1)
        return None

    def select_bad_row(self):
        """Highlight the first offending pool row, if any."""
        for i in range(self.pool.rowCount()):
            allday = self.pool.cellWidget(i, 2)
            if allday.isChecked():
                continue
            frm = self.pool.cellWidget(i, 3)
            to = self.pool.cellWidget(i, 4)
            if _time_to_minute(frm.time()) == _time_to_minute(to.time()):
                self.pool.setCurrentCell(i, 0)
                return True
        return False

    # -- public API used by the forms ---------------------------------------
    def load_timer(self, timer):
        self.cb_show_notif.setChecked(timer.show_notification)
        self.cb_show_topbar.setChecked(timer.show_in_top_bar)
        self.cb_temp.setChecked(timer.color_mode == COLOR_TEMPERATURE)
        self.spin_vol.setValue(timer.volume)
        self.select_sound(timer.sound)
        is_pool = timer.sound_mode == SOUND_MODE_POOL
        self.cb_pool.setChecked(is_pool)
        self.pool.setRowCount(0)
        for rule in timer.sound_rules:
            self._pool_append_row(rule)
        self._refresh_pool_buttons()

    def reset_defaults(self):
        self.cb_show_notif.setChecked(True)
        self.cb_show_topbar.setChecked(True)
        self.cb_temp.setChecked(True)
        self.spin_vol.setValue(5)
        self.select_sound("tick")
        self.cb_pool.setChecked(False)
        self.pool.setRowCount(0)
        self._refresh_pool_buttons()

    def timer_kwargs(self):
        """Validated behaviour kwargs for Timer(...) / Timer mutation."""
        if self.cb_pool.isChecked():
            return {
                "show_notification": self.cb_show_notif.isChecked(),
                "show_in_top_bar": self.cb_show_topbar.isChecked(),
                "color_mode": COLOR_TEMPERATURE if self.cb_temp.isChecked()
                else COLOR_STATIC,
                "volume": self.spin_vol.value(),
                "sound_mode": SOUND_MODE_POOL,
                "sound_rules": self._read_pool_rules(),
                "sound": self.cb_sound.currentData() or "tick",
            }
        return {
            "show_notification": self.cb_show_notif.isChecked(),
            "show_in_top_bar": self.cb_show_topbar.isChecked(),
            "color_mode": COLOR_TEMPERATURE if self.cb_temp.isChecked()
            else COLOR_STATIC,
            "volume": self.spin_vol.value(),
            "sound_mode": SOUND_MODE_SINGLE,
            "sound_rules": [],
            "sound": self.cb_sound.currentData() or "tick",
        }


def _minute_to_time(minute):
    from PyQt6.QtCore import QTime
    minute = max(0, min(1439, int(minute)))
    return QTime(minute // 60, minute % 60)


def _time_to_minute(t):
    return t.hour() * 60 + t.minute()


class TimerDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self._editing_id = None
        self._editing_original_target = None
        self._editing_original_anchor = None

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
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Name", self.lang), tr("Time", self.lang), tr("Remaining", self.lang)])
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setRootIsDecorated(False)
        self.list.setMinimumHeight(130)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(1, 100)
        self.list.setColumnWidth(2, 90)
        self.list.setToolTip(tr(
            "Double-click a timer to edit it.\nColour shows how close it is.",
            self.lang))
        self.list.itemDoubleClicked.connect(lambda *_: self.edit_selected())
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

        # ---- modern date/time picker (T-711) ----
        picker_row = QHBoxLayout()
        picker_row.setSpacing(4)
        
        self.date_time_picker = QDateTimeEdit()
        self.date_time_picker.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.date_time_picker.setCalendarPopup(True)
        self.date_time_picker.setTimeSpec(Qt.TimeSpec.LocalTime)
        self.date_time_picker.setToolTip(tr("Pick date and time (modern picker)", self.lang))
        self.date_time_picker.setDateTime(QDateTime.currentDateTime().addSecs(3600))  # Default: 1 hour from now
        self._style_calendar_popup()
        picker_row.addWidget(self.date_time_picker, 2)
        
        self.btn_pick_now = QPushButton(tr("Now", self.lang))
        self.btn_pick_now.setToolTip(tr("Set to current time", self.lang))
        self.btn_pick_now.clicked.connect(lambda: self.date_time_picker.setDateTime(QDateTime.currentDateTime()))
        picker_row.addWidget(self.btn_pick_now)
        
        self.btn_use_picker = QPushButton(tr("Use Picker", self.lang))
        self.btn_use_picker.setToolTip(tr("Use the picker date/time instead of text", self.lang))
        self.btn_use_picker.clicked.connect(self._use_picker_value)
        picker_row.addWidget(self.btn_use_picker)
        
        root.addLayout(picker_row)

        # ---- one-click quick presets (T-726) ----
        # The primary flow must be visible, not typed: a click writes a
        # concrete ISO moment into in_when, so commit() needs no typing and
        # no new parsing. Free text stays the POWER path above it.
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        self.btn_quick_10m = QPushButton("in 10m")
        self.btn_quick_10m.setToolTip("10 minutes from now")
        self.btn_quick_10m.clicked.connect(lambda: self._quick_pick("10m"))
        quick_row.addWidget(self.btn_quick_10m)

        self.btn_quick_1h = QPushButton("in 1h")
        self.btn_quick_1h.setToolTip("1 hour from now")
        self.btn_quick_1h.clicked.connect(lambda: self._quick_pick("1h"))
        quick_row.addWidget(self.btn_quick_1h)

        self.btn_quick_tonight = QPushButton("tonight")
        self.btn_quick_tonight.setToolTip("Tonight at 22:00")
        self.btn_quick_tonight.clicked.connect(lambda: self._quick_pick("tonight"))
        quick_row.addWidget(self.btn_quick_tonight)

        self.btn_quick_tomorrow = QPushButton("tomorrow")
        self.btn_quick_tomorrow.setToolTip("Tomorrow at 09:00")
        self.btn_quick_tomorrow.clicked.connect(lambda: self._quick_pick("tomorrow"))
        quick_row.addWidget(self.btn_quick_tomorrow)

        quick_row.addStretch(1)
        root.addLayout(quick_row)

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

        # Ask the agents instead of watching for the banner by hand. Reads
        # their chat text over the debugger and fills the form from whatever
        # they actually say - it types nothing, so it is safe mid-work.
        self.btn_scan = QPushButton(tr("Scan agents", self.lang))
        self.btn_scan.setToolTip(tr(
            "Read every debuggable agent and see which are rate-limited.\n"
            "A reset time in their own words fills the form; when they name\n"
            "none, the window length above is used and labelled assumed.",
            self.lang))
        self.btn_scan.clicked.connect(self.scan_agent_limits)
        limit.addWidget(self.btn_scan)
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

        # T-1005/T-1006: one shared behaviour editor owns notify / top-bar /
        # colour / volume / single-sound / random-pool. Alarm and Calendar forms
        # both instantiate it, so the behaviour truth lives in exactly one place.
        self._behavior = _TimerBehaviorEditor(self.main_win, self.lang, self)
        self._behavior.previewRequested.connect(self._preview_sound)
        opts.addWidget(self._behavior)

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

        # Keep the legacy attribute names working for callers/tests that
        # reached the Alarm sound controls directly.
        self.cb_sound = self._behavior.cb_sound
        self.spin_vol = self._behavior.spin_vol
        self.cb_temp = self._behavior.cb_temp

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

        self.btn_toggle = QPushButton(tr("Disable", self.lang))
        self.btn_toggle.setToolTip(tr("Disable or enable the selected timer", self.lang))
        self.btn_toggle.clicked.connect(self.toggle_selected)
        actions.addWidget(self.btn_toggle)

        self.btn_snooze = QPushButton(tr("+10m", self.lang))
        self.btn_snooze.setToolTip(tr("Push the selected timer back 10 minutes", self.lang))
        self.btn_snooze.clicked.connect(self.snooze_selected)
        actions.addWidget(self.btn_snooze)

        self.btn_subtract = QPushButton(tr("-10m", self.lang))
        self.btn_subtract.setToolTip(tr("Pull the selected timer forward 10 minutes", self.lang))
        self.btn_subtract.clicked.connect(self.subtract_selected)
        actions.addWidget(self.btn_subtract)

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
        self._build_calendar_tab()

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
    # T-1006. Calendar tab: events ARE timers (kind="calendar"), stored in
    # the one timers list with the one scheduler. No second dialog, no second
    # persistence, no interval recurrence here.

    _CAL_REPEATS = (REPEAT_NONE, REPEAT_DAILY, REPEAT_WEEKLY,
                    REPEAT_MONTHLY, REPEAT_YEARLY)

    def _build_calendar_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setSelectionMode(QCalendarWidget.SelectionMode.SingleSelection)
        self.cal.currentPageChanged.connect(self._cal_page_changed)
        self.cal.selectionChanged.connect(self._cal_selection_changed)
        self._style_calendar_widget(self.cal)
        v.addWidget(self.cal)

        self.cal_list = QTreeWidget()
        self.cal_list.setHeaderLabels([
            tr("Time", self.lang), tr("Name", self.lang),
            tr("Repeat", self.lang), tr("Sound", self.lang),
            tr("Notify", self.lang), tr("Top bar", self.lang),
            tr("Status", self.lang),
        ])
        self.cal_list.setRootIsDecorated(False)
        self.cal_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cal_list.itemDoubleClicked.connect(lambda *_: self._cal_edit_selected())
        self.cal_list.currentItemChanged.connect(lambda *_: self._cal_update_buttons())
        v.addWidget(self.cal_list, 1)

        acts = QHBoxLayout()
        acts.setSpacing(4)
        self.cal_btn_new = QPushButton(tr("New event", self.lang))
        self.cal_btn_new.clicked.connect(self._cal_new)
        self.cal_btn_edit = QPushButton(tr("Edit", self.lang))
        self.cal_btn_edit.clicked.connect(self._cal_edit_selected)
        self.cal_btn_toggle = QPushButton(tr("Enable/Disable", self.lang))
        self.cal_btn_toggle.clicked.connect(self._cal_toggle_selected)
        self.cal_btn_delete = QPushButton(tr("Delete", self.lang))
        self.cal_btn_delete.clicked.connect(self._cal_delete_selected)
        acts.addWidget(self.cal_btn_new)
        acts.addWidget(self.cal_btn_edit)
        acts.addWidget(self.cal_btn_toggle)
        acts.addWidget(self.cal_btn_delete)
        acts.addStretch(1)
        v.addLayout(acts)

        # ---- event editor ----
        self.cal_name = QLineEdit()
        self.cal_name.setPlaceholderText(tr("Event name", self.lang))
        v.addWidget(self.cal_name)
        self.cal_desc = QLineEdit()
        self.cal_desc.setPlaceholderText(tr("Description (optional)", self.lang))
        v.addWidget(self.cal_desc)

        when_row = QHBoxLayout()
        when_row.setSpacing(4)
        self.cal_time = QTimeEdit()
        self.cal_time.setDisplayFormat("HH:mm")
        self.cal_time.setTime(QDateTime.currentDateTime().time())
        self.cal_repeat = QComboBox()
        for r in self._CAL_REPEATS:
            self.cal_repeat.addItem(tr(r.capitalize(), self.lang), r)
        self.cal_enabled = QCheckBox(tr("Enabled", self.lang))
        self.cal_enabled.setChecked(True)
        when_row.addWidget(QLabel(tr("Time", self.lang)))
        when_row.addWidget(self.cal_time)
        when_row.addWidget(QLabel(tr("Repeat", self.lang)))
        when_row.addWidget(self.cal_repeat)
        when_row.addWidget(self.cal_enabled)
        when_row.addStretch(1)
        v.addLayout(when_row)

        self._cal_behavior = _TimerBehaviorEditor(self.main_win, self.lang, self)
        self._cal_behavior.previewRequested.connect(self._preview_sound)
        v.addWidget(self._cal_behavior)

        cal_commit_row = QHBoxLayout()
        cal_commit_row.setSpacing(4)
        self.btn_cal_commit = QPushButton(tr("Add event", self.lang))
        self.btn_cal_commit.clicked.connect(self._cal_commit)
        self.btn_cal_cancel = QPushButton(tr("New", self.lang))
        self.btn_cal_cancel.clicked.connect(self._cal_new)
        cal_commit_row.addWidget(self.btn_cal_commit)
        cal_commit_row.addWidget(self.btn_cal_cancel)
        cal_commit_row.addStretch(1)
        v.addLayout(cal_commit_row)

        self.cal_hint = QLabel("")
        self.cal_hint.setWordWrap(True)
        v.addWidget(self.cal_hint)

        self.tabs.addTab(page, tr("Calendar", self.lang))
        self._cal_formatted = set()      # dates currently marked (to clear lazily)
        self._cal_editing_id = None
        self._cal_new()
        self._cal_refresh_markers()
        self._cal_refresh_list()
        self._cal_last_signature = self._cal_signature()

    # -- calendar helpers ---------------------------------------------------
    def _cal_visible_timers(self):
        return [t for t in self.main_win.timers if t.kind == KIND_CALENDAR]

    def _cal_selected_date(self):
        return self.cal.selectedDate().toPyDate()

    def _cal_refresh_markers(self):
        """Mark visible-month dates that have a calendar event. Bounded: only
        the dates we formatted last time are cleared, never every date.
        A day whose events are ALL disabled is marked dimmed, never left
        indistinguishable from the background."""
        from PyQt6.QtCore import QDate
        from PyQt6.QtGui import QColor, QTextCharFormat

        # clear only previously-set formats
        for d in list(self._cal_formatted):
            self.cal.setDateTextFormat(QDate(d[0], d[1], d[2]),
                                        QTextCharFormat())
        self._cal_formatted.clear()

        y, m = self.cal.yearShown(), self.cal.monthShown()
        try:
            from fastprompter.theme.themes import THEMES
            theme = THEMES.get(self.main_win.data.get("theme", "Default")) or {}
            raw = theme.get("raw_colors", {}) or {}
        except Exception:
            raw = {}
        accent = QColor(raw.get("accent", "#f0d060"))
        muted = QColor(raw.get("text_dim", "#7a7468"))
        # a date's marker is ACCENT if any of its events is enabled, dimmed
        # if every event on it is disabled
        states = {}
        for t in self._cal_visible_timers():
            for date in occurrences_in_month(t, y, m):
                key = (date.year, date.month, date.day)
                states.setdefault(key, False)
                if t.enabled:
                    states[key] = True
        for (yy, mm, dd), any_enabled in states.items():
            fmt = QTextCharFormat()
            fmt.setForeground(accent if any_enabled else muted)
            self.cal.setDateTextFormat(QDate(yy, mm, dd), fmt)
            self._cal_formatted.add((yy, mm, dd))

    def _cal_refresh_list(self):
        keep = self.cal_list.currentItem()
        keep_id = keep.data(0, Qt.ItemDataRole.UserRole) if keep else None
        self.cal_list.blockSignals(True)
        self.cal_list.clear()
        sel = self._cal_selected_date()
        for t in sorted(self._cal_visible_timers(), key=lambda x: x.target):
            if not occurs_on_date(t, sel):
                continue
            repeat = tr(t.repeat.capitalize(), self.lang)
            sound = (tr("Random pool", self.lang) if t.sound_mode == SOUND_MODE_POOL
                     else t.sound)
            status = tr("On", self.lang) if t.enabled else tr("Paused", self.lang)
            item = QTreeWidgetItem([
                t.target.strftime("%H:%M"), t.name, repeat, sound,
                "On" if t.show_notification else "Off",
                "On" if t.show_in_top_bar else "Off",
                status,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, t.id)
            if not t.enabled:
                from PyQt6.QtGui import QColor
                muted = QColor("#8a8371")
                for col in range(item.columnCount()):
                    item.setForeground(col, muted)
            self.cal_list.addTopLevelItem(item)
            if t.id == keep_id:
                self.cal_list.setCurrentItem(item)
        if keep_id is None and self.cal_list.topLevelItemCount():
            self.cal_list.setCurrentItem(self.cal_list.topLevelItem(0))
        self.cal_list.blockSignals(False)
        self._cal_update_buttons()

    def _cal_page_changed(self, _y, _m):
        self._cal_refresh_markers()

    def _cal_selection_changed(self):
        self._cal_refresh_list()

    def _cal_update_buttons(self):
        item = self.cal_list.currentItem()
        has = item is not None
        for b in (self.cal_btn_edit, self.cal_btn_toggle, self.cal_btn_delete):
            b.setEnabled(has)
        if has:
            t = self._cal_selected()
            if t is not None:
                self.cal_btn_toggle.setText(
                    tr("Disable", self.lang) if t.enabled
                    else tr("Enable", self.lang))

    def _cal_signature(self):
        """Snapshot of everything the calendar tab mirrors from the model.

        The dialog re-renders the month markers and the event list only when
        this changes, so an open dialog tracks scheduler advances (collect_due
        rolling a timer) without rebuilding widgets on every idle tick.
        """
        sig = []
        for t in sorted(self._cal_visible_timers(),
                        key=lambda x: (x.id, x.target)):
            sig.append((t.id, t.target, t.repeat, t.repeat_anchor, t.enabled,
                        t.name, t.sound_mode, t.show_notification,
                        t.show_in_top_bar))
        return sig

    def _cal_refresh_if_changed(self):
        """Re-render the calendar tab when the model moved under it."""
        sig = self._cal_signature()
        if sig == self._cal_last_signature:
            return
        self._cal_last_signature = sig
        self._cal_refresh_markers()
        self._cal_refresh_list()

    def _cal_new(self):
        self._cal_editing_id = None
        self.cal_name.clear()
        self.cal_desc.clear()
        self.cal_time.setTime(QDateTime.currentDateTime().time())
        self.cal_repeat.setCurrentIndex(0)
        self.cal_enabled.setChecked(True)
        self._cal_behavior.reset_defaults()
        self.cal_hint.setText("")
        self.btn_cal_commit.setText(tr("Add event", self.lang))

    def _cal_selected(self):
        item = self.cal_list.currentItem()
        if item is None:
            return None
        tid = item.data(0, Qt.ItemDataRole.UserRole)
        return next((t for t in self._cal_visible_timers() if t.id == tid), None)

    def _cal_edit_selected(self):
        t = self._cal_selected()
        if t is None:
            return
        self._cal_editing_id = t.id
        # Bind the editor to the SERIES base date, not the occurrence row the
        # user happened to be viewing: editing a 31-Jan monthly series from
        # its 28-Feb occurrence must not re-anchor the series to 28 Feb.
        try:
            base = datetime.date.fromisoformat(t.repeat_anchor)
        except (TypeError, ValueError):
            base = t.target.date()
        self.cal.setSelectedDate(QDate(base.year, base.month, base.day))
        self.cal_name.setText(t.name)
        self.cal_desc.setText(t.description)
        self.cal_time.setTime(QDateTime.fromString(
            t.target.strftime("%H:%M"), "HH:mm").time())
        idx = self.cal_repeat.findData(t.repeat)
        if idx >= 0:
            self.cal_repeat.setCurrentIndex(idx)
        self.cal_enabled.setChecked(t.enabled)
        self._cal_behavior.load_timer(t)
        self.cal_hint.setText("")
        self.btn_cal_commit.setText(tr("Save event", self.lang))

    def _cal_commit(self):
        err = self._cal_behavior.validate()
        if err is not None:
            self._cal_behavior.select_bad_row()
            self.cal_hint.setText(err)
            return
        sel = self._cal_selected_date()
        h, mi = self.cal_time.time().hour(), self.cal_time.time().minute()
        target = datetime.datetime(sel.year, sel.month, sel.day, h, mi, 0)
        repeat = self.cal_repeat.currentData()
        kw = self._cal_behavior.timer_kwargs()
        if repeat in (REPEAT_MONTHLY, REPEAT_YEARLY):
            kw["repeat_anchor"] = sel.isoformat()
        kw["kind"] = KIND_CALENDAR
        kw["enabled"] = self.cal_enabled.isChecked()
        now = datetime.datetime.now()
        # Past-schedule rule: an ENABLED repeating event is rolled forward to
        # its next future occurrence (no retro-fire); an ENABLED one-shot in
        # the past is refused. Disabled events may stay historical.
        if self.cal_enabled.isChecked() and target <= now:
            if repeat == REPEAT_NONE:
                self.cal_hint.setText(tr(
                    "Event time is in the past; pick a future time or "
                    "disable the event.", self.lang))
                return
            kw["_normalize_past"] = True
        else:
            kw["_normalize_past"] = False
        if self._cal_editing_id:
            existing = next((t for t in self.main_win.timers
                            if t.id == self._cal_editing_id), None)
            if existing is not None:
                existing.name = self.cal_name.text().strip() or tr("Event", self.lang)
                existing.description = self.cal_desc.text().strip()
                existing.target = target
                existing.repeat = repeat
                existing.kind = KIND_CALENDAR
                existing.show_notification = kw["show_notification"]
                existing.show_in_top_bar = kw["show_in_top_bar"]
                existing.sound_mode = kw["sound_mode"]
                existing.sound_rules = kw["sound_rules"]
                existing.sound = kw["sound"]
                existing.volume = kw["volume"]
                existing.color_mode = kw["color_mode"]
                existing.enabled = kw["enabled"]
                existing.repeat_anchor = kw.get("repeat_anchor") or target.date().isoformat()
                existing.fired = False
                if kw["_normalize_past"]:
                    existing.advance(now)
        else:
            normalize_past = kw.pop("_normalize_past", False)
            timer = Timer(
                name=self.cal_name.text().strip() or tr("Event", self.lang),
                description=self.cal_desc.text().strip(),
                target=target, repeat=repeat, **kw)
            if normalize_past:
                timer.advance(now)
            self.main_win.timers.append(timer)
        self._cal_new()
        self._timer_changed(alarm=False, calendar=True)

    def _cal_toggle_selected(self):
        t = self._cal_selected()
        if t is None:
            return
        if not t.enabled:
            now = datetime.datetime.now()
            if t.repeat == REPEAT_NONE and t.target <= now:
                self.cal_hint.setText(tr(
                    "Event time is in the past; pick a future time to "
                    "enable it.", self.lang))
                return
            if t.repeat != REPEAT_NONE and t.target <= now:
                t.advance(now)
        t.enabled = not t.enabled
        if t.enabled:
            t.fired = False
        self._timer_changed(alarm=False, calendar=True)

    def _cal_delete_selected(self):
        t = self._cal_selected()
        if t is None:
            return
        if self._cal_editing_id == t.id:
            self._cal_new()
        self.main_win.timers = [x for x in self.main_win.timers if x.id != t.id]
        self._timer_changed(alarm=False, calendar=True)

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
        kw = self._behavior.timer_kwargs()
        repeat = self.cb_repeat.currentData()
        t = Timer(
            name=self.in_name.text().strip() or tr("Timer", self.lang),
            description=self.in_desc.text().strip(),
            target=target or datetime.datetime.now(),
            repeat=repeat,
            interval_minutes=self._interval_minutes(),
            **kw,
        )
        if repeat in (REPEAT_MONTHLY, REPEAT_YEARLY):
            t.repeat_anchor = t.target.date().isoformat()
        return t

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
        err = self._behavior.validate()
        if err is not None:
            self._behavior.select_bad_row()
            self.lbl_limit_hint.setText(err)
            return
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
            **self._behavior.timer_kwargs(),
        )
        self.main_win.timers.append(timer)
        self.clear_form()
        self._timer_changed(alarm=True, calendar=False)
        self.lbl_limit_hint.setText(describe(timer))
        return timer

    def scan_agent_limits(self):
        """Sweep the configured agents and turn what they say into timers.

        One timer per limited agent, named after it. An agent that already
        has a limit timer is UPDATED rather than duplicated - scanning twice
        must not leave two countdowns for the same reset.
        """
        from fastprompter.core.limits import assume_window
        from fastprompter.core.watcher.limit_scan import scan_all, limited

        try:
            adapters, _limits, _errors = self.main_win.watcher_adapters()
        except Exception as exc:
            self.lbl_limit_hint.setText(
                tr("Could not read the agent config: {}", self.lang).format(exc))
            return []

        err = self._behavior.validate()
        if err is not None:
            self._behavior.select_bad_row()
            self.lbl_limit_hint.setText(err)
            return []
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText(tr("Scanning…", self.lang))
        QApplication.processEvents()
        try:
            results = scan_all(adapters)
        except Exception as exc:
            self.lbl_limit_hint.setText(str(exc)[:120])
            return []
        finally:
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText(tr("Scan agents", self.lang))

        hit = limited(results)
        made = []
        for res in hit:
            assumed = res.state.resets_at is None
            target = res.state.resets_at or assume_window(
                hours=self.spin_limit_hours.value())
            name = tr("{} limit", self.lang).format(res.name) \
                if "{}" in tr("{} limit", self.lang) else f"{res.name} limit"
            
            limit_key = res.name
            existing = next(
                (t for t in self.main_win.timers
                 if t.kind == KIND_ALARM and (
                     t.auto_limit_key == limit_key or 
                     (t.auto_limit_key is None and t.name == name)
                 )), None)
            
            if existing is not None:
                if res.state.resets_at:
                    existing.target = res.state.resets_at
                    existing.enabled = True
                    existing.auto_limit_key = limit_key
                    existing.name = name
                    made.append(existing)
                continue
            timer = limit_window(
                name,
                hours=self.spin_limit_hours.value(),
                anchor=target - datetime.timedelta(
                    hours=self.spin_limit_hours.value()),
                description=(tr("assumed window", self.lang) if assumed
                             else res.state.matched[:60]),
                **self._behavior.timer_kwargs(),
            )
            timer.auto_limit_key = limit_key
            self.main_win.timers.append(timer)
            made.append(timer)

        if made:
            self._timer_changed(alarm=True, calendar=False)

        self.lbl_limit_hint.setText(self._scan_summary(results, made))
        return made

    def _scan_summary(self, results, made):
        """One line the user can act on: who is capped, who could not answer."""
        if not results:
            return tr("No agents configured for the debugger.", self.lang)
        capped = [r for r in results if r.reachable and r.state.reached]
        clear = [r for r in results if r.reachable and not r.state.reached]
        unreachable = [r for r in results if not r.reachable]
        bits = []
        if capped:
            bits.append(tr("limited: {}", self.lang).format(
                ", ".join(r.name for r in capped))
                if "{}" in tr("limited: {}", self.lang)
                else "limited: " + ", ".join(r.name for r in capped))
        if clear:
            bits.append(f"clear: {len(clear)}")
        if unreachable:
            bits.append(f"no answer: {len(unreachable)}")
        if made:
            bits.append(f"{len(made)} timer(s) set")
        return " · ".join(bits) or tr("Nothing to report.", self.lang)

    def test_now(self):
        """Fire a throwaway copy in 5s — sound and popup, nothing saved.

        Copies ALL behaviour the test needs (sound, volume, sound_mode, pool
        rules, show_notification, colour) so the preview is honest. It is
        never persisted. If Show notification is OFF the test still exercises
        sound-only behaviour — it does not force a popup on.
        """
        err = self._behavior.validate()
        if err is not None:
            self._behavior.select_bad_row()
            self.lbl_hint.setText(err)
            return
        self.main_win.test_timer_notification(self._form_timer(), _TEST_DELAY_S)
        self.lbl_hint.setText(
            tr("Test fires in {} seconds", self.lang).format(_TEST_DELAY_S))

    def _preview_sound(self, ref, volume):
        """Audition a sound immediately, through the real alarm path.

        The behaviour editor already emitted the EFFECTIVE volume (a pool
        row's "inherit" resolved against its own volume spin), so the host
        never guesses which editor a request came from. Never throws; a
        missing file is the scheduler's problem, not the dialog's.
        """
        if volume is None:
            return
        try:
            self.main_win.sound_manager.play_sound_ref(ref, volume)
        except Exception:
            pass

    def _fill_sound_choices(self):
        """Delegates to the shared behaviour editor (built once per dialog)."""
        self._behavior._fill_sound_choices()

    def _select_sound(self, value):
        """Point the combo at a stored value, event name or `file:` alike."""
        self._behavior.select_sound(value)

    def _calendar_sheet(self):
        """One theme rule for every QCalendarWidget — the picker popup and the
        Calendar tab share it so the two giant QSS strings never drift."""
        try:
            from fastprompter.theme.themes import THEMES

            theme = THEMES.get(self.main_win.data.get("theme", "Default")) or {}
            c = dict(theme.get("raw_colors") or {})
        except Exception:
            c = {}
        bg = c.get("bg_text", "#1a1810")
        panel = c.get("bg_main", "#232018")
        fg = c.get("text_main", "#d4c89a")
        btn = c.get("btn_bg", "#332e22")
        edge = c.get("border_light", "#5a5040")
        accent = c.get("accent", "#f0d060")
        return f"""
        QCalendarWidget QWidget {{ background: {panel}; color: {fg}; }}
        QCalendarWidget QAbstractItemView {{
            background: {bg}; color: {fg};
            selection-background-color: {accent}; selection-color: {panel};
            outline: none; }}
        QCalendarWidget QAbstractItemView:disabled {{ color: {edge}; }}
        QCalendarWidget QToolButton {{
            background: {btn}; color: {fg}; border: 1px solid {edge}; }}
        QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
        QCalendarWidget QSpinBox {{
            background: {bg}; color: {fg}; border: 1px solid {edge}; }}
        QCalendarWidget QMenu {{ background: {panel}; color: {fg}; }}
        QCalendarWidget QHeaderView {{ background: {panel}; border: none; }}
        QCalendarWidget QHeaderView::section {{
            background: {panel}; color: {fg}; border: none; padding: 2px; }}
        QCalendarWidget QTableView {{
            gridline-color: {edge}; selection-background-color: {accent}; }}
        """

    def _style_calendar_widget(self, cal):
        """Theme the Calendar-tab QCalendarWidget with the shared rule."""
        try:
            cal.setStyleSheet(self._calendar_sheet())
        except Exception:
            pass

    def _style_calendar_popup(self):
        """Theme the calendar popup, which the app stylesheet cannot reach.

        `setCalendarPopup(True)` builds a QCalendarWidget in its OWN top-level
        window, with its own QTableView, nav-bar buttons and month/year spin.
        None of those inherit the sheet this dialog copies from the main
        window, so the popup came up stock white inside a dark golden app —
        and so did the up/down arrows on the field itself.
        """
        sheet = self._calendar_sheet()
        self.date_time_picker.setStyleSheet(sheet)
        cal = self.date_time_picker.calendarWidget()
        if cal is not None:
            # The popup is a separate window: setting the sheet on the field
            # alone leaves it untouched.
            cal.setStyleSheet(sheet)

    def _use_picker_value(self):
        """Fill the text field with the picker's date/time in a readable format."""
        dt = self.date_time_picker.dateTime()
        # Format as "YYYY-MM-DD HH:MM" which is parseable by resolve_target
        text = dt.toString("yyyy-MM-dd HH:mm")
        self.in_when.setText(text)
        self.in_when.setFocus()

    def _quick_when(self, kind):
        """Resolve a quick-preset label to a concrete ISO moment."""
        now = datetime.datetime.now()
        if kind == "10m":
            target = now + datetime.timedelta(minutes=10)
        elif kind == "1h":
            target = now + datetime.timedelta(hours=1)
        elif kind == "tonight":
            target = now.replace(hour=22, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
        elif kind == "tomorrow":
            target = (now + datetime.timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0)
        else:
            return None
        return target.strftime("%Y-%m-%d %H:%M")

    def _quick_pick(self, kind):
        """One-click preset: write a concrete parseable moment, show the
        preview, and sync the calendar picker so the two cannot disagree."""
        text = self._quick_when(kind)
        if not text:
            return
        self.in_when.setText(text)
        from PyQt6.QtCore import QDateTime
        self.date_time_picker.setDateTime(
            QDateTime.fromString(text, "yyyy-MM-dd HH:mm"))
        self._preview(text)
        self.in_when.setFocus()

    def commit(self):
        """Add a new timer, or save the one being edited."""
        err = self._behavior.validate()
        if err is not None:
            self._behavior.select_bad_row()
            self.lbl_hint.setText(err)
            return
        text = self.in_when.text().strip()
        target = resolve_target(text)
        if target is None:
            self.lbl_hint.setText(tr("Not a time I understand", self.lang))
            self.in_when.setFocus()
            return

        if self._editing_id:
            existing = next((t for t in self.main_win.timers
                             if t.kind == KIND_ALARM and t.id == self._editing_id), None)
            if existing is not None:
                form = self._form_timer(target)
                # A monthly/yearly timer whose SCHEDULING DATE did not change
                # keeps its original series anchor: changing the name of a
                # 31-Jan series from its 28-Feb occurrence must not re-anchor
                # the series to 28 Feb. A deliberately new date re-anchors.
                if (form.repeat in (REPEAT_MONTHLY, REPEAT_YEARLY)
                        and self._editing_original_target is not None
                        and form.target.date() == self._editing_original_target.date()):
                    form.repeat_anchor = (self._editing_original_anchor
                                          or form.repeat_anchor)
                existing.name = form.name
                existing.description = form.description
                existing.target = target
                existing.repeat = form.repeat
                existing.sound = form.sound
                existing.volume = form.volume
                existing.color_mode = form.color_mode
                existing.interval_minutes = form.interval_minutes
                existing.kind = form.kind
                existing.show_notification = form.show_notification
                existing.show_in_top_bar = form.show_in_top_bar
                existing.sound_mode = form.sound_mode
                existing.sound_rules = form.sound_rules
                existing.repeat_anchor = form.repeat_anchor
                if form.repeat == REPEAT_INTERVAL:
                    # the edit text names the window START; the timer's
                    # target is the first FUTURE reset (start + k*period),
                    # never the start itself — name-only edits keep the
                    # series exactly where it was
                    step = datetime.timedelta(minutes=existing.interval_minutes)
                    existing.target = target + step
                    while existing.target <= datetime.datetime.now():
                        existing.target += step
                else:
                    existing.target = target
                    existing.advance()
                existing.fired = False        # re-arm after an edit
        else:
            self.main_win.timers.append(self._form_timer(target))

        self.clear_form()
        self._timer_changed(alarm=True, calendar=False)

    def _timer_changed(self, *, alarm=True, calendar=True):
        """One canonical post-mutation path: persist + refresh + top bar.

        Every mutation previously repeated the save/refresh glue in its own
        way — one refreshed the list but not the markers, another saved while
        the top-bar label waited for the next 1s tick. Everything lands here.
        """
        self.main_win.save_timers_to_data()
        if alarm:
            self.refresh()
        if calendar:
            self._cal_last_signature = self._cal_signature()
            self._cal_refresh_markers()
            self._cal_refresh_list()
        upd = getattr(self.main_win, "_update_timer_label", None)
        if callable(upd):
            upd()

    def clear_form(self):
        self._editing_id = None
        self._editing_original_target = None
        self._editing_original_anchor = None
        self.in_name.clear()
        self.in_desc.clear()
        self.in_when.clear()
        self.lbl_hint.setText("")
        self._behavior.reset_defaults()
        self.btn_commit.setText(tr("Add", self.lang))
        self.in_name.setFocus()

    def _selected(self):
        item = self.list.currentItem()
        if item is None:
            return None
        tid = item.data(0, Qt.ItemDataRole.UserRole)
        return next((t for t in self.main_win.timers
                     if t.kind == KIND_ALARM and t.id == tid), None)

    def edit_selected(self):
        t = self._selected()
        if t is None:
            return
        self._editing_id = t.id
        self._editing_original_target = t.target
        self._editing_original_anchor = t.repeat_anchor
        self.in_name.setText(t.name)
        self.in_desc.setText(t.description)
        if t.repeat == REPEAT_INTERVAL and getattr(t, "interval_minutes", 0):
            self.spin_limit_hours.setValue(t.interval_minutes / 60.0)
            start_time = t.target - datetime.timedelta(minutes=t.interval_minutes)
            self.in_when.setText(start_time.strftime("%Y-%m-%d %H:%M"))
        else:
            # an absolute date+time, never a bare HH:MM: on commit the bare
            # form re-resolves to today/tomorrow and silently drags a
            # months-away alarm back into this week
            self.in_when.setText(t.target.strftime("%Y-%m-%d %H:%M"))
        idx = self.cb_repeat.findData(t.repeat)
        if idx >= 0:
            self.cb_repeat.setCurrentIndex(idx)
        self._behavior.load_timer(t)
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
        self._timer_changed(alarm=True, calendar=False)

    def snooze_selected(self):
        t = self._selected()
        if t is None:
            return
        t.snooze(10)
        self._timer_changed(alarm=True, calendar=False)

    def subtract_selected(self):
        t = self._selected()
        if t is None:
            return
        t.shift(-10)
        self._timer_changed(alarm=True, calendar=False)

    def remove_selected(self):
        t = self._selected()
        if t is None:
            return
        if self._editing_id == t.id:
            self.clear_form()
        self.main_win.timers = [x for x in self.main_win.timers if x.id != t.id]
        self._timer_changed(alarm=True, calendar=False)

    def _update_buttons(self):
        t = self._selected()
        has = t is not None
        for b in (self.btn_edit, self.btn_toggle, self.btn_snooze, self.btn_subtract, self.btn_remove):
            b.setEnabled(has)
        if has:
            self.btn_toggle.setText(
                tr("Enable", self.lang) if not t.enabled else tr("Disable", self.lang))

    def refresh(self):
        if hasattr(self, "lbl_pomo_clock"):
            self._refresh_pomo()
        from PyQt6.QtGui import QColor

        keep = self.list.currentItem()
        keep_id = keep.data(0, Qt.ItemDataRole.UserRole) if keep else None

        self.list.blockSignals(True)
        self.list.clear()
        now = datetime.datetime.now()
        alarm_timers = [t for t in self.main_win.timers if t.kind == KIND_ALARM]
        for t in sorted(alarm_timers, key=lambda x: x.target):
            rem = t.remaining(now)
            when = t.target.strftime("%d.%m %H:%M")
            if not t.enabled:
                tail = tr("paused", self.lang)
            elif rem <= 0:
                tail = tr("done", self.lang)
            else:
                tail = format_remaining(rem)
            repeat = "" if t.repeat == "once" else f" ({t.repeat})"
            item = QTreeWidgetItem([f"{t.name}{repeat}", when, tail])
            item.setData(0, Qt.ItemDataRole.UserRole, t.id)
            tip = [t.name]
            if t.description:
                tip.append(t.description)
            tip.append(f"{when}  ({tail})")
            if t.sound_mode == SOUND_MODE_POOL:
                tip.append(tr("Random pool: {} rules", self.lang).format(
                    len(t.sound_rules)))
            else:
                tip.append(f"{tr('Sound', self.lang)}: {t.sound}  vol {t.volume}")
            tip.append(f"{tr('Notification', self.lang)}: "
                       f"{'On' if t.show_notification else 'Off'}")
            tip.append(f"{tr('Top bar', self.lang)}: "
                       f"{'On' if t.show_in_top_bar else 'Off'}")
            item.setToolTip(0, "\n".join(tip))
            item.setToolTip(1, item.toolTip(0))
            item.setToolTip(2, item.toolTip(0))
            if t.enabled:
                color = QColor(t.display_color(now))
                item.setForeground(0, color)
                item.setForeground(1, color)
                item.setForeground(2, color)
            self.list.addTopLevelItem(item)
            if t.id == keep_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

        if keep_id is None and self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self._update_buttons()
        self._cal_refresh_if_changed()

    def closeEvent(self, event):
        self._tick.stop()
        super().closeEvent(event)
