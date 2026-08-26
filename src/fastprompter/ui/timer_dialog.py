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
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
from fastprompter.ui.analog_clock import BigAnalogClock

_SOUNDS = ("tick", "click", "new", "save", "delete", "clear", "silo", "snippet")
_TEST_DELAY_S = 5

DEFAULT_INTERVAL_RULES = [
    {
        "id": "interval_default_noon",
        "name": "Noon (12:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:GENIE.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 720,
        "end_minute": 779,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_morning",
        "name": "Morning (07:00 - 11:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:newday.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 420,
        "end_minute": 719,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_day",
        "name": "Day & Evening (13:00 - 21:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:newday.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 780,
        "end_minute": 1319,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
    {
        "id": "interval_default_night",
        "name": "Night (22:00 - 06:00)",
        "minutes": 60,
        "enabled": True,
        "sound": "file:alert_owl2.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 1320,
        "end_minute": 419,
        "last_fired": 0.0,
        "last_fired_minute": "",
    },
]


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

    # (sound_ref, volume) the host should audition immediately — volume 0.0-1.0
    previewRequested = pyqtSignal(str, float)

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

        self.spin_vol = QDoubleSpinBox()
        self.spin_vol.setRange(0.0, 1.0)
        self.spin_vol.setDecimals(2)
        self.spin_vol.setSingleStep(0.05)
        self.spin_vol.setValue(0.5)
        self.spin_vol.setToolTip(tr("Alarm volume (0.00-1.00)", lang))
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

        sound_row = QHBoxLayout()
        sound_row.setSpacing(4)
        self.cb_sound = QComboBox()
        self.cb_sound.setMaxVisibleItems(20)
        self.cb_sound.setToolTip(tr(
            "Alarm sound — the named events first, then every file in the "
            "library", lang))
        self._fill_sound_choices()
        sound_row.addWidget(self.cb_sound, 1)

        self.btn_preview_sound = QPushButton(tr("Test", lang))
        self.btn_preview_sound.setToolTip(tr("Preview currently selected sound", lang))
        self.btn_preview_sound.clicked.connect(self._preview_single)
        sound_row.addWidget(self.btn_preview_sound)
        lay.addLayout(sound_row)

        # Quick Sound bar (10 buttons, 2x5 grid)
        self.quick_bar = QWidget()
        qb_lay = QGridLayout(self.quick_bar)
        qb_lay.setContentsMargins(0, 0, 0, 0)
        qb_lay.setSpacing(2)
        lay.addWidget(self.quick_bar)
        self._quick_buttons = []
        self._rebuild_quick_bar()

        # ---- pool editor ----
        self.pool = QTableWidget()
        self.pool.setColumnCount(5)
        self.pool.setHorizontalHeaderLabels([
            tr("On", lang), tr("Sound", lang),
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
        self.btn_pool_add.setVisible(False)
        self.btn_pool_remove.setVisible(False)

        self.cb_pool.toggled.connect(self._on_pool_toggled)
        self._suppress_preview = False
        self.cb_sound.currentIndexChanged.connect(self._on_sound_index_changed)
        self.cb_sound.activated.connect(lambda _i: self._preview_single())
        lay.addStretch(1)

    def _on_sound_index_changed(self, index):
        if getattr(self, "_suppress_preview", False):
            return
        self._preview_single()

    def _quick_bar_slots(self):
        saved = getattr(self.main_win, "data", {}).get("sound_quick_bar")
        if isinstance(saved, list) and len(saved) == 10:
            return list(saved)
        return [
            "file:NEWDAY.wav", "file:NEWMONTH.wav", "file:NEWWEEK.wav",
            "file:NOMAD.wav", "file:OBELISK.wav", "file:PARALYZE.wav",
            "file:PICKUP01.wav", "file:PICKUP03.wav", "file:QUEST.wav",
            "file:ROGUE.wav",
        ]

    def _save_quick_bar_slots(self, slots):
        if hasattr(self.main_win, "data") and isinstance(self.main_win.data, dict):
            self.main_win.data["sound_quick_bar"] = list(slots)
            self.main_win.mark_dirty()

    def _rebuild_quick_bar(self):
        lay = self.quick_bar.layout()
        while self._quick_buttons:
            self._quick_buttons.pop().deleteLater()
        for idx, ref in enumerate(self._quick_bar_slots()):
            label = ref[5:] if ref.startswith("file:") else ref
            if label.lower().endswith(".wav"):
                label = label[:-4]
            btn = QPushButton(label or "-")
            btn.setFixedHeight(20)
            btn.setToolTip(tr(
                "Click: pick '{}' & preview.\nRight-click: store current sound here.",
                self.lang).format(label))
            btn.clicked.connect(lambda _=False, i=idx: self._quick_pick(i))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, i=idx: self._quick_store(i))
            lay.addWidget(btn, idx // 5, idx % 5)
            self._quick_buttons.append(btn)

    def _quick_pick(self, idx):
        slots = self._quick_bar_slots()
        if 0 <= idx < len(slots):
            ref = slots[idx]
            self.select_sound(ref)
            self._preview_single()

    def _quick_store(self, idx):
        ref = self.cb_sound.currentData()
        if not ref:
            return
        slots = self._quick_bar_slots()
        if 0 <= idx < len(slots):
            slots[idx] = ref
            self._save_quick_bar_slots(slots)
            self._rebuild_quick_bar()

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
            favs = set(self.main_win.data.get("sound_favorites", [])) if self.main_win else set()
            self.cb_sound.insertSeparator(self.cb_sound.count())
            for rel in files:
                text = f"★ {rel}" if rel in favs else rel
                self._sound_choices.append((text, f"file:{rel}"))
                self.cb_sound.addItem(text, f"file:{rel}")

    def select_sound(self, value):
        self._suppress_preview = True
        try:
            idx = self.cb_sound.findData(value or "tick")
            if idx < 0:
                idx = self.cb_sound.findData("tick")
            if idx >= 0:
                self.cb_sound.setCurrentIndex(idx)
        finally:
            self._suppress_preview = False

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

        frm = QTimeEdit()
        frm.setDisplayFormat("HH:mm")
        frm.setToolTip(tr("00:00 to 00:00 means All Day", self.lang))
        # Support legacy "all_day" flag if it exists, translating to 00:00-00:00
        is_all_day = bool(rule.get("all_day", True))
        st = 0 if is_all_day else rule.get("start_minute", 0)
        en_m = 0 if is_all_day else rule.get("end_minute", 0)
        frm.setTime(_minute_to_time(st))
        self.pool.setCellWidget(r, 2, frm)

        to = QTimeEdit()
        to.setDisplayFormat("HH:mm")
        to.setToolTip(tr("00:00 to 00:00 means All Day", self.lang))
        to.setTime(_minute_to_time(en_m))
        self.pool.setCellWidget(r, 3, to)

        vol = QDoubleSpinBox()
        vol.setRange(-1.0, 1.0)
        vol.setDecimals(2)
        vol.setSingleStep(0.05)
        vol.setSpecialValueText(tr("Timer", self.lang))
        v = rule.get("volume", None)
        # legacy int 0-10 -> 0.0-1.0
        if v is not None:
            try:
                if isinstance(v, bool):
                    v = None
                else:
                    fv = float(v)
                    if fv > 1.0 and fv <= 10.0 and float(fv).is_integer():
                        fv = fv / 10.0
                    v = max(0.0, min(1.0, fv))
            except (TypeError, ValueError):
                v = None
        vol.setValue(-1.0 if v is None else float(v))
        self.pool.setCellWidget(r, 4, vol)

        sound.currentIndexChanged.connect(
            lambda _i, s=sound, v=vol: self._on_pool_sound_changed(s, v))
        sound.activated.connect(
            lambda _i, s=sound, v=vol: self._preview_pool_widgets(s, v))

    def _on_pool_sound_changed(self, sound, vol):
        if getattr(self, "_suppress_preview", False):
            return
        self._preview_pool_widgets(sound, vol)

    def _read_pool_rules(self):
        out = []
        for r in range(self.pool.rowCount()):
            en = self.pool.cellWidget(r, 0)
            sound = self.pool.cellWidget(r, 1)
            frm = self.pool.cellWidget(r, 2)
            to = self.pool.cellWidget(r, 3)
            vol = self.pool.cellWidget(r, 4)
            ref = sound.currentData() or "tick"
            start = _time_to_minute(frm.time())
            end = _time_to_minute(to.time())
            # If 0 to 0, it means all_day = True in the config
            all_day = (start == 0 and end == 0)
            v = vol.value()
            out.append({
                "sound": ref,
                "enabled": en.isChecked(),
                "all_day": all_day,
                "start_minute": start if not all_day else 0,
                "end_minute": end if not all_day else 0,
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
        vol = self.pool.cellWidget(row, 4)
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
            frm = self.pool.cellWidget(i, 2)
            to = self.pool.cellWidget(i, 3)
            start = _time_to_minute(frm.time())
            end = _time_to_minute(to.time())
            if start == end and start != 0:
                return tr("Sound rule {} has an empty time range.", self.lang) \
                    .format(i + 1)
        return None

    def select_bad_row(self):
        """Highlight the first offending pool row, if any."""
        for i in range(self.pool.rowCount()):
            frm = self.pool.cellWidget(i, 2)
            to = self.pool.cellWidget(i, 3)
            start = _time_to_minute(frm.time())
            end = _time_to_minute(to.time())
            if start == end and start != 0:
                self.pool.setCurrentCell(i, 0)
                return True
        return False

    # -- public API used by the forms ---------------------------------------
    def load_timer(self, timer):
        self._suppress_preview = True
        try:
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
        finally:
            self._suppress_preview = False

    def reset_defaults(self):
        self._suppress_preview = True
        try:
            self.cb_show_notif.setChecked(True)
            self.cb_show_topbar.setChecked(True)
            self.cb_temp.setChecked(True)
            self.spin_vol.setValue(0.5)
            self.select_sound("tick")
            self.cb_pool.setChecked(False)
            self.pool.setRowCount(0)
            self._refresh_pool_buttons()
        finally:
            self._suppress_preview = False
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
    def __init__(self, main_win, initial_tab: int | str = 0):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self._editing_id = None
        self._editing_original_target = None
        self._editing_original_anchor = None
        self.setWindowTitle(tr("Timers", self.lang))
        self.resize(780, 520)
        self.setMinimumSize(560, 360)
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
        root.setSpacing(4)
        self.tabs.addTab(alarms_page, tr("Alarms", self.lang))
        self._build_interval_tab()

        # ---- existing timers tree ----
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Name", self.lang), tr("Time", self.lang), tr("Remaining", self.lang)])
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setRootIsDecorated(False)
        self.list.setMinimumHeight(100)
        self.list.setMaximumHeight(135)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(1, 110)
        self.list.setColumnWidth(2, 95)
        self.list.setToolTip(tr(
            "Click a timer to edit it.\nColour shows how close it is.",
            self.lang))
        self.list.itemClicked.connect(lambda *_: self.edit_selected())
        self.list.currentItemChanged.connect(self._on_timer_current_changed)
        root.addWidget(self.list, 0)

        # ---- row actions directly under list ----
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
        self.btn_remove.setToolTip(tr("Delete the selected timer", self.lang))
        self.btn_remove.clicked.connect(self.remove_selected)
        actions.addWidget(self.btn_remove)

        actions.addStretch(1)
        self.btn_cancel_edit = QPushButton(tr("New", self.lang))
        self.btn_cancel_edit.setToolTip(tr("Clear the form", self.lang))
        self.btn_cancel_edit.clicked.connect(self.clear_form)
        actions.addWidget(self.btn_cancel_edit)
        root.addLayout(actions)

        # ---- Grouped Form Panels ----
        form_split = QHBoxLayout()
        form_split.setSpacing(6)

        # Left Group: Timing & Details
        group_timing = QGroupBox(tr("Alarm Details & Timing", self.lang).replace("&", "&&"))
        timing_lay = QVBoxLayout(group_timing)
        timing_lay.setContentsMargins(6, 6, 6, 6)
        timing_lay.setSpacing(4)

        # Name & Description
        name_desc_lay = QHBoxLayout()
        name_desc_lay.setSpacing(4)
        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText(tr("Name (e.g. Claude limit)", self.lang))
        self.in_name.setToolTip(tr("What is resetting", self.lang))
        name_desc_lay.addWidget(self.in_name, 2)

        self.in_desc = QLineEdit()
        self.in_desc.setPlaceholderText(tr("Description (optional)", self.lang))
        self.in_desc.setToolTip(tr("Shown in notification popup", self.lang))
        self.in_desc.returnPressed.connect(self.commit)
        name_desc_lay.addWidget(self.in_desc, 2)
        timing_lay.addLayout(name_desc_lay)

        # Quick Delays Bar
        quick_row = QHBoxLayout()
        quick_row.setSpacing(3)
        self.btn_quick_10m = QPushButton(tr("in 10m", self.lang))
        self.btn_quick_10m.clicked.connect(lambda: self._quick_pick("10m"))
        quick_row.addWidget(self.btn_quick_10m)

        self.btn_quick_1h = QPushButton(tr("in 1h", self.lang))
        self.btn_quick_1h.clicked.connect(lambda: self._quick_pick("1h"))
        quick_row.addWidget(self.btn_quick_1h)

        self.btn_quick_tonight = QPushButton(tr("tonight", self.lang))
        self.btn_quick_tonight.clicked.connect(lambda: self._quick_pick("tonight"))
        quick_row.addWidget(self.btn_quick_tonight)

        self.btn_quick_tomorrow = QPushButton(tr("tomorrow", self.lang))
        self.btn_quick_tomorrow.clicked.connect(lambda: self._quick_pick("tomorrow"))
        quick_row.addWidget(self.btn_quick_tomorrow)
        timing_lay.addLayout(quick_row)

        # Time Input + Preset Combo + Repeat
        when_row = QHBoxLayout()
        when_row.setSpacing(4)
        self.in_when = QLineEdit()
        self.in_when.setPlaceholderText(tr("4 days 11 hours / 18:30", self.lang))
        self.in_when.setToolTip(tr(
            "A delay: 4 days 11 hours, 4d 11h, 90m, 1h30, 1.5h\n"
            "or a clock time: 18:30, tomorrow 9:00\n"
            "Russian works too. Press Enter to add.", self.lang))
        self.in_when.returnPressed.connect(self.commit)
        when_row.addWidget(self.in_when, 3)

        self.cb_preset = QComboBox()
        self.cb_preset.setToolTip(tr("Ready-made delays", self.lang))
        self.cb_preset.addItem(tr("Preset", self.lang), "")
        for label, value in PRESETS:
            self.cb_preset.addItem(label, value)
        self.cb_preset.currentIndexChanged.connect(self._preset_picked)
        when_row.addWidget(self.cb_preset, 2)

        self.cb_repeat = QComboBox()
        self.cb_repeat.setToolTip(tr("How often it repeats", self.lang))
        for r in REPEAT_CHOICES:
            self.cb_repeat.addItem(tr(r.capitalize(), self.lang), r)
        when_row.addWidget(self.cb_repeat, 2)
        timing_lay.addLayout(when_row)

        # Picker Row
        picker_row = QHBoxLayout()
        picker_row.setSpacing(4)
        self.date_time_picker = QDateTimeEdit()
        self.date_time_picker.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.date_time_picker.setCalendarPopup(True)
        self.date_time_picker.setTimeSpec(Qt.TimeSpec.LocalTime)
        self.date_time_picker.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self._style_calendar_popup()
        picker_row.addWidget(self.date_time_picker, 3)

        self.btn_pick_now = QPushButton(tr("Now", self.lang))
        self.btn_pick_now.clicked.connect(lambda: self.date_time_picker.setDateTime(QDateTime.currentDateTime()))
        picker_row.addWidget(self.btn_pick_now, 1)

        self.btn_use_picker = QPushButton(tr("Use Picker", self.lang))
        self.btn_use_picker.clicked.connect(self._use_picker_value)
        picker_row.addWidget(self.btn_use_picker, 1)
        timing_lay.addLayout(picker_row)

        # Limit Quota Row (Inputs)
        limit_row = QHBoxLayout()
        limit_row.setSpacing(4)
        self.lbl_limit = QLabel(tr("Limit window:", self.lang))
        limit_row.addWidget(self.lbl_limit)

        self.spin_limit_hours = QDoubleSpinBox()
        self.spin_limit_hours.setRange(0.25, 72.0)
        self.spin_limit_hours.setSingleStep(0.5)
        self.spin_limit_hours.setDecimals(2)
        self.spin_limit_hours.setValue(5.0)
        self.spin_limit_hours.setSuffix(tr(" h", self.lang))
        limit_row.addWidget(self.spin_limit_hours)

        self.in_limit_start = QLineEdit()
        self.in_limit_start.setPlaceholderText(tr("started (blank = now)", self.lang))
        self.in_limit_start.returnPressed.connect(self.add_limit_window)
        limit_row.addWidget(self.in_limit_start, 1)
        timing_lay.addLayout(limit_row)

        # Limit Buttons Row
        limit_btns = QHBoxLayout()
        limit_btns.setSpacing(4)
        self.btn_limit = QPushButton(tr("Catch limit", self.lang))
        self.btn_limit.clicked.connect(self.add_limit_window)
        limit_btns.addWidget(self.btn_limit, 1)

        self.btn_scan = QPushButton(tr("Scan agents", self.lang))
        self.btn_scan.setToolTip(tr("Scan agents for usage and rate limits", self.lang))
        self.btn_scan.clicked.connect(self.scan_agent_limits)
        limit_btns.addWidget(self.btn_scan, 1)
        timing_lay.addLayout(limit_btns)

        self.lbl_limit_hint = QLabel("")
        self.lbl_limit_hint.setWordWrap(True)
        timing_lay.addWidget(self.lbl_limit_hint)
        timing_lay.addStretch(1)
        self.in_limit_start.textChanged.connect(self._preview_limit)
        self.spin_limit_hours.valueChanged.connect(
            lambda _v: self._preview_limit(self.in_limit_start.text()))

        form_split.addWidget(group_timing, 1)

        # Right Group: Sound & Notification
        group_sound = QGroupBox(tr("Notification & Sound", self.lang).replace("&", "&&"))
        sound_lay = QVBoxLayout(group_sound)
        sound_lay.setContentsMargins(6, 6, 6, 6)
        sound_lay.setSpacing(3)

        self._behavior = _TimerBehaviorEditor(self.main_win, self.lang, self)
        self._behavior.previewRequested.connect(self._preview_sound)
        sound_lay.addWidget(self._behavior)

        form_split.addWidget(group_sound, 1)
        root.addLayout(form_split)

        # Legacy aliases for tests/callers
        self.cb_sound = self._behavior.cb_sound
        self.spin_vol = self._behavior.spin_vol
        self.cb_temp = self._behavior.cb_temp
        self.btn_test = getattr(self._behavior, "btn_preview_sound", None)

        # Feedback label
        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)
        self.in_when.textChanged.connect(self._preview)

        # Bottom master actions
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(6)
        self.btn_commit = QPushButton(tr("Add", self.lang))
        self.btn_commit.clicked.connect(self.commit)
        bottom_bar.addWidget(self.btn_commit)

        bottom_bar.addStretch(1)
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        root.addLayout(bottom_bar)

        self._build_temp_tab()
        self._build_productivity_tab()
        self._build_calendar_tab()

        # Size to the Calendar tab's natural height so it fits without a
        # scrollbar by default; smaller screens still scroll via the
        # QScrollArea fallback inside _build_calendar_tab.
        cal_page = self.cal.parent()
        if cal_page is not None:
            bar = self.tabs.tabBar()
            bar_h = bar.height() if bar is not None else 30
            want = cal_page.sizeHint().height() + bar_h + 20
            screen = QApplication.primaryScreen()
            max_h = int(screen.availableGeometry().height() * 0.85) if screen else 820
            self.resize(780, min(max(520, want), max_h))

        self.tabs.currentChanged.connect(self._on_tab_changed)
        target_tab = 0
        if isinstance(initial_tab, int):
            if 0 <= initial_tab < self.tabs.count():
                target_tab = initial_tab
        elif isinstance(initial_tab, str):
            for idx in range(self.tabs.count()):
                if initial_tab.lower() in self.tabs.tabText(idx).lower():
                    target_tab = idx
                    break
        self.tabs.setCurrentIndex(target_tab)
        self._on_tab_changed(target_tab)

        # keep the countdown column honest while the dialog is open
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh)
        self._tick.start(1000)

        self.refresh()

    _TAB_SIZES = {
        0: (740, 460),  # Alarms
        1: (740, 390),  # Interval Notifications
        2: (640, 300),  # Temp Timer
        3: (480, 220),  # Productivity
        4: (740, 480),  # Calendar
    }
    _TAB_MIN_SIZES = {
        0: (640, 390),
        1: (620, 340),
        2: (500, 220),
        3: (380, 160),
        4: (640, 390),
    }

    def _on_tab_changed(self, idx):
        """Dynamically fit dialog dimensions to the active tab's content."""
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget is not None:
                if i == idx:
                    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                else:
                    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        min_w, min_h = self._TAB_MIN_SIZES.get(idx, (480, 220))
        target_w, target_h = self._TAB_SIZES.get(idx, (680, 380))
        self.setMinimumSize(min_w, min_h)
        self.resize(target_w, target_h)
        self.adjustSize()
        self.resize(max(target_w, min_w), max(target_h, min_h))

    def _on_timer_current_changed(self, current, _previous=None):
        """Keep row actions in sync with the list view and load it into the editor form."""
        self._update_buttons()
        if current is not None:
            try:
                self.list.scrollToItem(
                    current, QAbstractItemView.ScrollHint.EnsureVisible)
            except Exception:
                pass
            self.edit_selected()

    def _build_temp_tab(self):
        """Temporary countdown timer that doesn't need to be saved as an alarm."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        intro = QLabel(tr(
            "Shift+Click the clock for a quick timer. Each press adds time to the same countdown; "
            "normal alarms stay untouched.", self.lang))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        mid_lay = QHBoxLayout()
        mid_lay.setSpacing(6)

        # Left Group: Controls & Actions
        left_group = QGroupBox(tr("Alarm Details & Timing", self.lang).replace("&", "&&"))
        left_lay = QVBoxLayout(left_group)
        left_lay.setContentsMargins(6, 6, 6, 6)
        left_lay.setSpacing(4)

        cfg_factory = getattr(self.main_win, "temp_timer_template", None)
        cfg = cfg_factory() if callable(cfg_factory) else {
            "name": "Temp Timer", "increment_minutes": 15,
            "description": "",
            "delete_after_fire": False, "sound": "tick", "volume": 5,
            "color_mode": COLOR_TEMPERATURE,
            "show_notification": True, "show_in_top_bar": True,
            "sound_mode": SOUND_MODE_SINGLE, "sound_rules": [],
        }

        # Name & Description
        self.in_temp_name = QLineEdit(cfg["name"])
        self.in_temp_name.setPlaceholderText(tr("Name (e.g. Temp Timer)", self.lang))
        self.in_temp_name.setToolTip(tr("Name shown beside the countdown", self.lang))
        self.in_temp_name.editingFinished.connect(self._temp_settings_changed)
        left_lay.addWidget(self.in_temp_name)

        self.in_temp_desc = QLineEdit(cfg.get("description", ""))
        self.in_temp_desc.setPlaceholderText(tr("Optional notification text", self.lang))
        self.in_temp_desc.setToolTip(tr(
            "Shown in the notification popup when Temp Timer fires", self.lang))
        self.in_temp_desc.editingFinished.connect(self._temp_settings_changed)
        left_lay.addWidget(self.in_temp_desc)

        # Quick Add Buttons
        quick_lbl = QLabel(tr("Add now", self.lang))
        left_lay.addWidget(quick_lbl)
        quick = QHBoxLayout()
        quick.setSpacing(3)
        for minutes, label in ((15, "+15m"), (30, "+30m"),
                               (45, "+45m"), (60, "+1h"), (75, "+1h15m")):
            button = QPushButton(label)
            button.setToolTip(tr("Add {} minutes to Temp Timer", self.lang).format(minutes))
            button.clicked.connect(lambda _checked=False, m=minutes: self._add_temp(m))
            quick.addWidget(button)
        left_lay.addLayout(quick)

        # Default increment & Delete after fire
        inc_row = QHBoxLayout()
        inc_row.setSpacing(4)
        inc_row.addWidget(QLabel(tr("Default add:", self.lang)))
        self.spin_temp_increment = QSpinBox()
        self.spin_temp_increment.setRange(1, 24 * 60)
        self.spin_temp_increment.setSuffix(tr(" min", self.lang))
        self.spin_temp_increment.setValue(cfg["increment_minutes"])
        self.spin_temp_increment.valueChanged.connect(self._temp_settings_changed)
        inc_row.addWidget(self.spin_temp_increment)
        inc_row.addStretch(1)
        left_lay.addLayout(inc_row)

        self.cb_temp_delete = QCheckBox(tr("Delete after fire", self.lang))
        self.cb_temp_delete.setChecked(cfg["delete_after_fire"])
        self.cb_temp_delete.setToolTip(tr(
            "Remove this temporary timer after its sound and notification. "
            "Off keeps it visible as done until you remove it.", self.lang))
        self.cb_temp_delete.toggled.connect(self._temp_settings_changed)
        left_lay.addWidget(self.cb_temp_delete)

        self.lbl_temp_status = QLabel("")
        self.lbl_temp_status.setWordWrap(True)
        left_lay.addWidget(self.lbl_temp_status)

        left_lay.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.btn_temp_test = QPushButton(tr("Test", self.lang))
        self.btn_temp_test.setToolTip(tr(
            "Test these settings in 5 seconds; nothing is saved as a timer.",
            self.lang))
        self.btn_temp_test.clicked.connect(self._test_temp)
        actions.addWidget(self.btn_temp_test)
        self.btn_temp_add = QPushButton(tr("Start / Add", self.lang))
        self.btn_temp_add.clicked.connect(lambda: self._add_temp())
        actions.addWidget(self.btn_temp_add)
        self.btn_temp_remove = QPushButton(tr("Remove Temp Timer", self.lang))
        self.btn_temp_remove.clicked.connect(self._remove_temp)
        actions.addWidget(self.btn_temp_remove)
        left_lay.addLayout(actions)

        mid_lay.addWidget(left_group, 1)

        # Right Group: Behavior & Sound
        right_group = QGroupBox(tr("Notification & Sound", self.lang).replace("&", "&&"))
        right_lay = QVBoxLayout(right_group)
        right_lay.setContentsMargins(6, 6, 6, 6)
        right_lay.setSpacing(3)

        self._temp_behavior = _TimerBehaviorEditor(self.main_win, self.lang, self)
        self._temp_behavior.previewRequested.connect(self._preview_sound)
        temp_factory = getattr(self.main_win, "_temp_timer", None)
        existing = temp_factory() if callable(temp_factory) else None
        if existing is not None:
            self.in_temp_name.setText(existing.name)
            self.in_temp_desc.setText(existing.description)
            self.cb_temp_delete.blockSignals(True)
            self.cb_temp_delete.setChecked(existing.delete_after_fire)
            self.cb_temp_delete.blockSignals(False)
            self._temp_behavior.load_timer(existing)
        else:
            from fastprompter.core.timers import Timer
            self._temp_behavior.load_timer(Timer(
                cfg["name"], datetime.datetime.now(),
                sound=cfg["sound"], volume=cfg["volume"],
                color_mode=cfg["color_mode"],
                show_notification=cfg["show_notification"],
                show_in_top_bar=cfg["show_in_top_bar"],
                sound_mode=cfg["sound_mode"], sound_rules=cfg["sound_rules"],
            ))
        right_lay.addWidget(self._temp_behavior)
        mid_lay.addWidget(right_group, 1)

        lay.addLayout(mid_lay)

        self.tabs.addTab(page, tr("Temp Timer", self.lang))
        self._refresh_temp_tab()

    def _temp_settings(self):
        values = self._temp_behavior.timer_kwargs()
        values.update({
            "name": self.in_temp_name.text().strip() or tr("Temp Timer", self.lang),
            "description": self.in_temp_desc.text().strip(),
            "increment_minutes": self.spin_temp_increment.value(),
            "delete_after_fire": self.cb_temp_delete.isChecked(),
        })
        return values

    def _temp_settings_changed(self, _value=None):
        if (hasattr(self, "_temp_behavior")
                and hasattr(self.main_win, "configure_temp_timer")):
            self.main_win.configure_temp_timer(self._temp_settings())

    def _add_temp(self, minutes=None):
        settings = self._temp_settings()
        if hasattr(self.main_win, "add_temp_timer"):
            self.main_win.add_temp_timer(minutes, settings)
        self._refresh_temp_tab()

    def _test_temp(self):
        """Test the current Temp Timer behaviour without creating a timer."""
        if not hasattr(self.main_win, "test_timer_notification"):
            return
        err = self._temp_behavior.validate()
        if err is not None:
            self.lbl_temp_status.setText(err)
            self._temp_behavior.select_bad_row()
            return
        values = self._temp_settings()
        probe = Timer(
            name=values["name"],
            description=values["description"],
            target=datetime.datetime.now(),
            repeat=REPEAT_NONE,
            temporary=True,
            delete_after_fire=values["delete_after_fire"],
            **{key: values[key] for key in (
                "sound", "volume", "color_mode", "show_notification",
                "show_in_top_bar", "sound_mode", "sound_rules")},
        )
        self.main_win.test_timer_notification(probe, _TEST_DELAY_S)
        self.lbl_temp_status.setText(
            tr("Test fires in {} seconds", self.lang).format(_TEST_DELAY_S))

    def _remove_temp(self):
        if hasattr(self.main_win, "remove_temp_timer"):
            self.main_win.remove_temp_timer()
        self._refresh_temp_tab()

    def _refresh_temp_tab(self):
        if not hasattr(self, "lbl_temp_status"):
            return
        temp_factory = getattr(self.main_win, "_temp_timer", None)
        temp = temp_factory() if callable(temp_factory) else None
        if temp is None:
            self.lbl_temp_status.setText(tr("No Temp Timer running.", self.lang))
            self.btn_temp_remove.setEnabled(False)
            return
        state = tr("done", self.lang) if temp.fired else format_remaining(temp.remaining())
        self.lbl_temp_status.setText(
            tr("{} — {}", self.lang).format(temp.name, state))
        self.btn_temp_remove.setEnabled(True)

    # ------------------------------------------------------------------
    def _build_productivity_tab(self):
        """Work/break timer, the my_timer2 model as a first-class feature."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)

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
        v.setSpacing(4)

        mid_lay = QHBoxLayout()
        mid_lay.setSpacing(6)

        # Left Column: Calendar + Events List + Actions
        left_col = QVBoxLayout()
        left_col.setSpacing(3)

        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setSelectionMode(QCalendarWidget.SelectionMode.SingleSelection)
        self.cal.currentPageChanged.connect(self._cal_page_changed)
        self.cal.selectionChanged.connect(self._cal_selection_changed)
        self._style_calendar_widget(self.cal)
        left_col.addWidget(self.cal)

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
        self.cal_list.setMaximumHeight(90)
        left_col.addWidget(self.cal_list, 1)

        acts = QHBoxLayout()
        acts.setSpacing(3)
        self.cal_btn_new = QPushButton(tr("New event", self.lang))
        self.cal_btn_new.clicked.connect(self._cal_new)
        self.cal_btn_edit = QPushButton(tr("Edit", self.lang))
        self.cal_btn_edit.clicked.connect(self._cal_edit_selected)
        self.cal_btn_toggle = QPushButton(tr("Enable/Disable", self.lang))
        self.cal_btn_toggle.clicked.connect(self._cal_toggle_selected)
        self.cal_btn_delete = QPushButton(tr("Delete", self.lang))
        self.cal_btn_delete.clicked.connect(self._cal_delete_selected)
        self.cal_btn_today = QPushButton(tr("Today", self.lang))
        self.cal_btn_today.clicked.connect(self._cal_goto_today)
        acts.addWidget(self.cal_btn_new)
        acts.addWidget(self.cal_btn_edit)
        acts.addWidget(self.cal_btn_toggle)
        acts.addWidget(self.cal_btn_delete)
        acts.addWidget(self.cal_btn_today)
        acts.addStretch(1)
        left_col.addLayout(acts)

        mid_lay.addLayout(left_col, 1)

        # Right Column: Event Editor & Behavior
        right_col = QVBoxLayout()
        right_col.setSpacing(3)

        group_event = QGroupBox(tr("Alarm Details & Timing", self.lang).replace("&", "&&"))
        group_event_lay = QVBoxLayout(group_event)
        group_event_lay.setContentsMargins(6, 6, 6, 6)
        group_event_lay.setSpacing(3)

        self.cal_name = QLineEdit()
        self.cal_name.setPlaceholderText(tr("Event name", self.lang))
        group_event_lay.addWidget(self.cal_name)
        self.cal_desc = QLineEdit()
        self.cal_desc.setPlaceholderText(tr("Description (optional)", self.lang))
        group_event_lay.addWidget(self.cal_desc)

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
        group_event_lay.addLayout(when_row)
        right_col.addWidget(group_event)

        group_sound = QGroupBox(tr("Notification & Sound", self.lang).replace("&", "&&"))
        group_sound_lay = QVBoxLayout(group_sound)
        group_sound_lay.setContentsMargins(6, 6, 6, 6)
        group_sound_lay.setSpacing(3)

        self._cal_behavior = _TimerBehaviorEditor(self.main_win, self.lang, self)
        self._cal_behavior.previewRequested.connect(self._preview_sound)
        group_sound_lay.addWidget(self._cal_behavior)
        right_col.addWidget(group_sound)

        cal_commit_row = QHBoxLayout()
        cal_commit_row.setSpacing(4)
        self.btn_cal_commit = QPushButton(tr("Add event", self.lang))
        self.btn_cal_commit.clicked.connect(self._cal_commit)
        self.btn_cal_cancel = QPushButton(tr("New", self.lang))
        self.btn_cal_cancel.clicked.connect(self._cal_new)
        cal_commit_row.addWidget(self.btn_cal_commit)
        cal_commit_row.addWidget(self.btn_cal_cancel)
        cal_commit_row.addStretch(1)
        right_col.addLayout(cal_commit_row)

        self.cal_hint = QLabel("")
        self.cal_hint.setWordWrap(True)
        right_col.addWidget(self.cal_hint)
        right_col.addStretch(1)

        mid_lay.addLayout(right_col, 1)
        v.addLayout(mid_lay)

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

    def _cal_goto_today(self):
        """Jump the calendar back to today's month/date."""
        from PyQt6.QtCore import QDate

        self.cal.setSelectedDate(QDate.currentDate())
        self.cal.showToday()
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
                # Adopt/refresh the matched timer unconditionally — both the
                # exact-reset path (resets_at known) and the assumed-window
                # path (resets_at is None). Skipping the update on the assumed
                # path left a legacy keyless timer stale, keyless and
                # duplicable after a language switch: it matched only by name,
                # which is localized and changes with the UI language, so a
                # re-scan could not find it and created a second countdown.
                # CORE-011: refresh the SCHEDULING state too, not just the
                # identity/target. A legacy or previously-fired one-shot adopted
                # as a new auto-limit must become an active rolling interval
                # timer on the CURRENT configured window: clear fired, install
                # interval recurrence and the refreshed interval_minutes. Only
                # the user's intended notification/sound prefs are preserved.
                existing.target = target
                existing.enabled = True
                existing.auto_limit_key = limit_key
                existing.name = name
                existing.fired = False
                existing.repeat = REPEAT_INTERVAL
                existing.interval_minutes = self._interval_minutes()
                if getattr(existing, "repeat_anchor", None) is not None \
                        and existing.repeat != REPEAT_MONTHLY \
                        and existing.repeat != REPEAT_YEARLY:
                    existing.repeat_anchor = None
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
        # Muted, non-acidic accent for strips/grid — the bright `accent` reads
        # as neon on a dark golden theme, so the calendar uses the softer
        # border tone instead of the raw highlight colour.
        soft = c.get("border_light", "#5a5040")
        return f"""
        QCalendarWidget QWidget {{ background: {panel}; color: {fg}; }}
        QCalendarWidget #qt_calendar_navigationbar {{
            background: {panel}; border: none; }}
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
            background: {panel}; color: {fg};
            border: none; border-bottom: 1px solid {soft}; padding: 2px; }}
        QCalendarWidget QTableView {{
            gridline-color: {soft}; selection-background-color: {accent}; }}
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
            target_id = self._editing_id
        else:
            new_timer = self._form_timer(target)
            self.main_win.timers.append(new_timer)
            target_id = new_timer.id

        self.clear_form()
        self._timer_changed(alarm=True, calendar=False, select_id=target_id)

    def _timer_changed(self, *, alarm=True, calendar=True, select_id=None):
        """One canonical post-mutation path: persist + refresh + top bar.

        Every mutation previously repeated the save/refresh glue in its own
        way — one refreshed the list but not the markers, another saved while
        the top-bar label waited for the next 1s tick. Everything lands here.
        """
        self.main_win.save_timers_to_data()
        if alarm:
            self.refresh(select_id=select_id)
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

    def refresh(self, select_id=None):
        if hasattr(self, "lbl_pomo_clock"):
            self._refresh_pomo()
        if hasattr(self, "interval_clock"):
            self.interval_clock.sync()
        from PyQt6.QtGui import QColor

        keep = self.list.currentItem()
        keep_id = select_id or (keep.data(0, Qt.ItemDataRole.UserRole) if keep else None)

        now = datetime.datetime.now()
        alarm_timers = [t for t in self.main_win.timers
                        if t.kind == KIND_ALARM
                        and not getattr(t, "temporary", False)]
        sorted_timers = sorted(alarm_timers, key=lambda x: x.target)
        sorted_ids = [t.id for t in sorted_timers]

        existing_items = {}
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            existing_items[it.data(0, Qt.ItemDataRole.UserRole)] = it

        existing_ids = [self.list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                        for i in range(self.list.topLevelItemCount())]

        if existing_ids != sorted_ids:
            self.list.blockSignals(True)
            self.list.clear()
            for t in sorted_timers:
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
        else:
            for t in sorted_timers:
                item = existing_items.get(t.id)
                if not item:
                    continue
                rem = t.remaining(now)
                when = t.target.strftime("%d.%m %H:%M")
                if not t.enabled:
                    tail = tr("paused", self.lang)
                elif rem <= 0:
                    tail = tr("done", self.lang)
                else:
                    tail = format_remaining(rem)
                repeat = "" if t.repeat == "once" else f" ({t.repeat})"
                item.setText(0, f"{t.name}{repeat}")
                item.setText(1, when)
                item.setText(2, tail)
                if t.enabled:
                    color = QColor(t.display_color(now))
                    item.setForeground(0, color)
                    item.setForeground(1, color)
                    item.setForeground(2, color)
            if select_id and select_id in existing_items:
                self.list.setCurrentItem(existing_items[select_id])

        self._update_buttons()
        self._cal_refresh_if_changed()
        self._refresh_temp_tab()

    def closeEvent(self, event):
        if (hasattr(self, "_temp_behavior")
                and hasattr(self.main_win, "configure_temp_timer")):
            self.main_win.configure_temp_timer(self._temp_settings())
        self._tick.stop()
        super().closeEvent(event)


    # ------------------------------------------------------------------
    # Shared interval notification tab methods
    def _build_interval_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # Split into Left Column (Rules + Dial) and Right Column (Settings Form)
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(6)

        # Left Column: Periodic Rules List + Analog Clock + Presets
        clock_box = QGroupBox(tr("Periodic Reminders & Dial", self.lang).replace("&", "&&"))
        clock_box_lay = QVBoxLayout(clock_box)
        clock_box_lay.setContentsMargins(6, 6, 6, 6)
        clock_box_lay.setSpacing(3)

        self.interval_list = QTreeWidget()
        self.interval_list.setHeaderLabels([
            tr("State", self.lang),
            tr("Name", self.lang),
            tr("Every", self.lang),
        ])
        self.interval_list.setRootIsDecorated(False)
        self.interval_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.interval_list.setMinimumHeight(60)
        self.interval_list.setMaximumHeight(85)
        self.interval_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.interval_list.setColumnWidth(0, 50)
        self.interval_list.setColumnWidth(2, 60)
        self.interval_list.setDragEnabled(True)
        self.interval_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.interval_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.interval_list.setDropIndicatorShown(True)
        self.interval_list.itemClicked.connect(lambda item, *_: self._interval_load(item))
        self.interval_list.currentItemChanged.connect(lambda cur, *_: self._interval_load(cur) if cur else None)
        try:
            self.interval_list.model().rowsMoved.connect(self._interval_reorder)
        except Exception:
            pass
        clock_box_lay.addWidget(self.interval_list)

        list_btns = QHBoxLayout()
        list_btns.setSpacing(3)
        self.interval_btn_new = QPushButton(tr("+ New", self.lang))
        self.interval_btn_new.clicked.connect(self._interval_new)
        list_btns.addWidget(self.interval_btn_new)

        self.interval_btn_delete = QPushButton(tr("Delete", self.lang))
        self.interval_btn_delete.clicked.connect(self._interval_delete)
        list_btns.addWidget(self.interval_btn_delete)

        self.interval_btn_defaults = QPushButton(tr("Defaults", self.lang))
        self.interval_btn_defaults.setToolTip(tr("Reset to default 24h chime schedule (0.05 volume)", self.lang))
        self.interval_btn_defaults.clicked.connect(self._interval_reset_defaults)
        list_btns.addWidget(self.interval_btn_defaults)

        self.interval_btn_presets = QPushButton(tr("Presets…", self.lang))
        self.interval_btn_presets.setToolTip(tr("Choose from predefined interval schedule presets", self.lang))
        self.interval_btn_presets.clicked.connect(self._interval_show_presets_menu)
        list_btns.addWidget(self.interval_btn_presets)
        clock_box_lay.addLayout(list_btns)

        self.interval_clock = BigAnalogClock(self.main_win, self, size=120)
        self.interval_clock.intervalChanged.connect(self._on_clock_interval_picked)
        clock_box_lay.addWidget(self.interval_clock, 0, Qt.AlignmentFlag.AlignCenter)

        pills_grid = QGridLayout()
        pills_grid.setSpacing(2)
        quick_intervals = [(15, "15m"), (30, "30m"), (45, "45m"), (60, "🔔 1h (:00)"), (120, "2h (:00)"), (240, "4h (:00)")]
        for idx, (mins, lbl) in enumerate(quick_intervals):
            btn = QPushButton(lbl)
            btn.setFixedHeight(20)
            btn.clicked.connect(lambda _=False, m=mins: self._set_interval_minutes(m))
            pills_grid.addWidget(btn, idx // 3, idx % 3)
        clock_box_lay.addLayout(pills_grid)
        clock_box_lay.addStretch(1)
        mid_layout.addWidget(clock_box, 1)

        # Right Column: Rich Interval Settings Form
        form_box = QGroupBox(tr("Interval Configuration", self.lang))
        form_lay = QVBoxLayout(form_box)
        form_lay.setContentsMargins(6, 6, 6, 6)
        form_lay.setSpacing(3)

        # Row 1: Name + Enabled checkbox
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        r1.addWidget(QLabel(tr("Name:", self.lang)))
        self.interval_in_name = QLineEdit()
        self.interval_in_name.setPlaceholderText(tr("Every New Hour", self.lang))
        r1.addWidget(self.interval_in_name, 1)

        self.interval_in_enabled = QCheckBox(tr("Enabled", self.lang))
        self.interval_in_enabled.setChecked(True)
        r1.addWidget(self.interval_in_enabled)
        form_lay.addLayout(r1)

        # Row 2: Duration + Mode
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        r2.addWidget(QLabel(tr("Interval:", self.lang)))
        self.interval_in_minutes = QSpinBox()
        self.interval_in_minutes.setRange(1, 10080)
        self.interval_in_minutes.setValue(60)
        self.interval_in_minutes.setSuffix(tr(" min", self.lang))
        self.interval_in_minutes.valueChanged.connect(self._on_spin_interval_changed)
        r2.addWidget(self.interval_in_minutes)

        r2.addWidget(QLabel(tr("Mode:", self.lang)))
        self.interval_cb_align = QComboBox()
        self.interval_cb_align.addItem(tr("Exact New Hour / Clock Boundary (:00)", self.lang), "clock")
        self.interval_cb_align.addItem(tr("Elapsed Timer from Start", self.lang), "elapsed")
        self.interval_cb_align.currentIndexChanged.connect(
            lambda *_: self.interval_clock.set_interval(self.interval_in_minutes.value(), self.interval_cb_align.currentData() or "clock"))
        r2.addWidget(self.interval_cb_align, 1)
        form_lay.addLayout(r2)

        # Row 3: Active Hours Window
        r3 = QHBoxLayout()
        r3.setSpacing(4)
        self.interval_cb_allday = QCheckBox(tr("All Day (24/7)", self.lang))
        self.interval_cb_allday.setChecked(True)
        r3.addWidget(self.interval_cb_allday)

        r3.addWidget(QLabel(tr("From:", self.lang)))
        self.interval_time_start = QTimeEdit()
        self.interval_time_start.setDisplayFormat("HH:mm")
        self.interval_time_start.setTime(_minute_to_time(0))
        self.interval_time_start.setEnabled(False)
        r3.addWidget(self.interval_time_start)

        r3.addWidget(QLabel(tr("To:", self.lang)))
        self.interval_time_end = QTimeEdit()
        self.interval_time_end.setDisplayFormat("HH:mm")
        self.interval_time_end.setTime(_minute_to_time(1439))
        self.interval_time_end.setEnabled(False)
        r3.addWidget(self.interval_time_end)

        self.interval_cb_allday.toggled.connect(lambda on: (
            self.interval_time_start.setEnabled(not on),
            self.interval_time_end.setEnabled(not on)
        ))
        form_lay.addLayout(r3)

        # Row 4: Sound + Volume + Test Sound
        r4 = QHBoxLayout()
        r4.setSpacing(4)
        r4.addWidget(QLabel(tr("Sound:", self.lang)))
        self.interval_in_sound = QComboBox()
        self.interval_in_sound.setMaxVisibleItems(20)
        self._fill_interval_sound_choices()
        self._suppress_interval_preview = False
        self.interval_in_sound.currentIndexChanged.connect(self._on_interval_sound_changed)
        self.interval_in_sound.activated.connect(lambda _i: self._interval_test_sound())
        r4.addWidget(self.interval_in_sound, 1)

        r4.addWidget(QLabel(tr("Vol:", self.lang)))
        self.interval_in_volume = QDoubleSpinBox()
        self.interval_in_volume.setRange(0.0, 1.0)
        self.interval_in_volume.setDecimals(2)
        self.interval_in_volume.setSingleStep(0.01)
        self.interval_in_volume.setValue(0.05)
        r4.addWidget(self.interval_in_volume)

        self.interval_btn_test = QPushButton(tr("Test", self.lang))
        self.interval_btn_test.clicked.connect(self._interval_test_sound)
        r4.addWidget(self.interval_btn_test)
        form_lay.addLayout(r4)

        # Row 5: 10 Quick Favorite Sounds Bar
        form_lay.addWidget(QLabel(tr("Quick Sounds:", self.lang)))
        self.interval_quick_bar = QWidget()
        iqb_lay = QGridLayout(self.interval_quick_bar)
        iqb_lay.setContentsMargins(0, 0, 0, 0)
        iqb_lay.setSpacing(2)
        form_lay.addWidget(self.interval_quick_bar)
        self._interval_quick_buttons = []
        self._rebuild_interval_quick_bar()

        # Row 6: Popups / Top bar toggles
        r6 = QHBoxLayout()
        r6.setSpacing(6)
        self.interval_in_notify = QCheckBox(tr("Show notification popup", self.lang))
        self.interval_in_notify.setChecked(False)
        r6.addWidget(self.interval_in_notify)

        self.interval_in_topbar = QCheckBox(tr("Show in top bar", self.lang))
        self.interval_in_topbar.setChecked(False)
        r6.addWidget(self.interval_in_topbar)
        r6.addStretch(1)
        form_lay.addLayout(r6)

        self.interval_btn_save = QPushButton(tr("Save Changes", self.lang))
        self.interval_btn_save.clicked.connect(self._interval_save)
        form_lay.addWidget(self.interval_btn_save)
        form_lay.addStretch(1)

        mid_layout.addWidget(form_box, 1)
        lay.addLayout(mid_layout)

        # Bottom Actions Bar
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

        self.tabs.addTab(page, tr("Interval Notifications", self.lang))
        self._interval_reload()

    def _fill_interval_sound_choices(self):
        self.interval_in_sound.clear()
        for name in _SOUNDS:
            self.interval_in_sound.addItem(name, name)
        try:
            files = self.main_win.sound_manager.get_available_sounds() or []
        except Exception:
            files = []
        if files:
            favs = set(self.main_win.data.get("sound_favorites", [])) if self.main_win else set()
            self.interval_in_sound.insertSeparator(self.interval_in_sound.count())
            for rel in files:
                text = f"★ {rel}" if rel in favs else rel
                self.interval_in_sound.addItem(text, f"file:{rel}")

    def _quick_bar_slots(self):
        saved = getattr(self.main_win, "data", {}).get("sound_quick_bar")
        if isinstance(saved, list) and len(saved) == 10:
            return list(saved)
        return [
            "file:NEWDAY.wav", "file:NEWMONTH.wav", "file:NEWWEEK.wav",
            "file:NOMAD.wav", "file:OBELISK.wav", "file:PARALYZE.wav",
            "file:PICKUP01.wav", "file:PICKUP03.wav", "file:QUEST.wav",
            "file:ROGUE.wav",
        ]

    def _save_quick_bar_slots(self, slots):
        if hasattr(self.main_win, "data") and isinstance(self.main_win.data, dict):
            self.main_win.data["sound_quick_bar"] = list(slots)
            self.main_win.mark_dirty()

    def _rebuild_interval_quick_bar(self):
        lay = self.interval_quick_bar.layout()
        while self._interval_quick_buttons:
            self._interval_quick_buttons.pop().deleteLater()
        slots = self._quick_bar_slots()
        for idx, ref in enumerate(slots):
            label = ref[5:] if ref.startswith("file:") else ref
            if label.lower().endswith(".wav"):
                label = label[:-4]
            btn = QPushButton(label or "-")
            btn.setFixedHeight(20)
            btn.setToolTip(tr(
                "Click: pick '{}' & preview.\nRight-click: store current sound here.",
                self.lang).format(label))
            btn.clicked.connect(lambda _=False, r=ref: self._interval_quick_pick(r))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, i=idx: self._interval_quick_store(i))
            lay.addWidget(btn, idx // 5, idx % 5)
            self._interval_quick_buttons.append(btn)

    def _interval_quick_pick(self, ref):
        self._interval_set_sound(ref)
        self._interval_test_sound()

    def _interval_quick_store(self, idx):
        ref = self.interval_in_sound.currentData()
        if not ref:
            return
        slots = self._quick_bar_slots()
        if 0 <= idx < len(slots):
            slots[idx] = ref
            self._save_quick_bar_slots(slots)
            if hasattr(self, "_behavior") and hasattr(self._behavior, "_rebuild_quick_bar"):
                self._behavior._rebuild_quick_bar()
            self._rebuild_interval_quick_bar()

    def _on_clock_interval_picked(self, mins):
        self.interval_in_minutes.setValue(mins)

    def _set_interval_minutes(self, mins):
        self.interval_in_minutes.setValue(mins)
        if mins >= 60 and mins % 60 == 0:
            idx = self.interval_cb_align.findData("clock")
            if idx >= 0:
                self.interval_cb_align.setCurrentIndex(idx)
        align = self.interval_cb_align.currentData() or "clock"
        self.interval_clock.set_interval(mins, align)

    def _on_spin_interval_changed(self, mins):
        align = self.interval_cb_align.currentData() or "clock"
        self.interval_clock.set_interval(mins, align)

    def _on_interval_sound_changed(self, _i):
        if getattr(self, "_suppress_interval_preview", False):
            return
        self._interval_test_sound()

    def _interval_test_sound(self):
        ref = self.interval_in_sound.currentData() or "newday"
        vol = self.interval_in_volume.value()
        try:
            self.main_win.sound_manager.play_sound_ref(ref, vol)
        except Exception:
            pass

    def _interval_set_sound(self, ref):
        self._suppress_interval_preview = True
        try:
            idx = self.interval_in_sound.findData(ref)
            if idx < 0:
                idx = self.interval_in_sound.findData("newday")
            if idx >= 0:
                self.interval_in_sound.setCurrentIndex(idx)
        finally:
            self._suppress_interval_preview = False

    def _interval_rules(self):
        rules = getattr(self.main_win, "data", {}).get("interval_notifs")
        if not isinstance(rules, list):
            meth = getattr(self.main_win, "_interval_notifs", None)
            if callable(meth):
                rules = meth()
            else:
                rules = []
                if hasattr(self.main_win, "data") and isinstance(self.main_win.data, dict):
                    self.main_win.data["interval_notifs"] = rules
        return rules

    def _interval_reload(self):
        self._suppress_interval_preview = True
        try:
            cur = getattr(self, "_interval_cur", None)
            self.interval_list.clear()
            rules = self._interval_rules()
            for rule in rules:
                state = tr("ON", self.lang) if rule.get("enabled") else tr("OFF", self.lang)
                name = str(rule.get("name") or tr("Hourly Reminder", self.lang))
                mins = int(rule.get("minutes") or 60)
                if mins % 60 == 0:
                    interval_str = f"{mins // 60} h"
                else:
                    interval_str = f"{mins} m"
                item = QTreeWidgetItem([state, name, interval_str])
                item.setData(0, Qt.ItemDataRole.UserRole, rule.get("id"))
                if rule.get("enabled"):
                    from PyQt6.QtGui import QColor
                    gold = QColor(217, 179, 64)
                    item.setForeground(0, gold)
                    item.setForeground(1, gold)
                self.interval_list.addTopLevelItem(item)
                if cur is not None and rule.get("id") == cur:
                    self.interval_list.setCurrentItem(item)
            if cur is None and self.interval_list.topLevelItemCount():
                self.interval_list.setCurrentItem(self.interval_list.topLevelItem(0))
        finally:
            self._suppress_interval_preview = False

    def _interval_reorder(self, *args):
        """Draggable priority: topmost wins on collision. Persist UI order to data."""
        try:
            new_ids = []
            for i in range(self.interval_list.topLevelItemCount()):
                it = self.interval_list.topLevelItem(i)
                if it is not None:
                    new_ids.append(it.data(0, Qt.ItemDataRole.UserRole))
            rules = self._interval_rules()
            id_to_rule = {r.get("id"): r for r in rules if isinstance(r, dict)}
            reordered = [id_to_rule[rid] for rid in new_ids if rid in id_to_rule]
            # keep any not in UI (defensive)
            remaining = [r for r in rules if r.get("id") not in new_ids]
            reordered.extend(remaining)
            if len(reordered) == len(rules):
                rules[:] = reordered
                self.main_win.mark_dirty()
        except Exception:
            pass

    def _interval_load(self, item):
        if item is None:
            return
        self._suppress_interval_preview = True
        try:
            rid = item.data(0, Qt.ItemDataRole.UserRole)
            for rule in self._interval_rules():
                if rule.get("id") == rid:
                    self._interval_cur = rid
                    self.interval_in_name.setText(str(rule.get("name") or ""))
                    mins = int(rule.get("minutes") or 60)
                    self.interval_in_minutes.setValue(mins)
                    self.interval_in_enabled.setChecked(bool(rule.get("enabled", True)))
                    align = str(rule.get("align_mode", "clock"))
                    idx = self.interval_cb_align.findData(align)
                    if idx >= 0:
                        self.interval_cb_align.setCurrentIndex(idx)
                    self.interval_cb_allday.setChecked(bool(rule.get("all_day", True)))
                    self.interval_time_start.setTime(_minute_to_time(rule.get("start_minute", 0)))
                    self.interval_time_end.setTime(_minute_to_time(rule.get("end_minute", 1439)))
                    self._interval_set_sound(str(rule.get("sound") or "newday"))
                    v = rule.get("volume", 0.05)
                    try:
                        fv = float(v)
                        if fv > 1.0 and fv <= 10.0 and float(fv).is_integer():
                            fv = fv / 10.0
                        v = max(0.0, min(1.0, fv))
                    except (TypeError, ValueError):
                        v = 0.05
                    self.interval_in_volume.setValue(float(v))
                    self.interval_in_notify.setChecked(bool(rule.get("show_notification", True)))
                    self.interval_in_topbar.setChecked(bool(rule.get("show_in_top_bar", False)))
                    self.interval_clock.set_interval(mins, align)
                    return
        finally:
            self._suppress_interval_preview = False

    def _interval_reset_defaults(self):
        import copy
        self.main_win.data["interval_notifs"] = copy.deepcopy(DEFAULT_INTERVAL_RULES)
        self._interval_cur = None
        self.main_win.mark_dirty()
        self._interval_reload()

    def _interval_show_presets_menu(self):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtCore import QPoint
        import copy
        menu = QMenu(self)
        
        a_default = menu.addAction(tr("Default 24h Chime (Genie / NewDay / Owl @ 0.05)", self.lang))
        a_workday = menu.addAction(tr("Workday Hours (09:00 - 18:00 @ 0.05)", self.lang))
        a_hourly = menu.addAction(tr("Hourly Bell (24/7 @ 0.05)", self.lang))
        a_pomo = menu.addAction(tr("Pomodoro Focus (Every 25m @ 0.05)", self.lang))
        a_night = menu.addAction(tr("Night Owl (22:00 - 06:00 @ 0.05)", self.lang))

        pos = self.interval_btn_presets.mapToGlobal(QPoint(0, self.interval_btn_presets.height()))
        act = menu.exec(pos)
        if not act:
            return

        if act == a_default:
            self.main_win.data["interval_notifs"] = copy.deepcopy(DEFAULT_INTERVAL_RULES)
        elif act == a_workday:
            self.main_win.data["interval_notifs"] = [{
                "id": "interval_workday",
                "name": tr("Workday (09:00 - 18:00)", self.lang),
                "minutes": 60,
                "enabled": True,
                "sound": "file:newday.wav",
                "volume": 0.05,
                "show_notification": True,
                "show_in_top_bar": False,
                "align_mode": "clock",
                "all_day": False,
                "start_minute": 540,
                "end_minute": 1079,
            }]
        elif act == a_hourly:
            self.main_win.data["interval_notifs"] = [{
                "id": "interval_hourly",
                "name": tr("Hourly Bell (24/7)", self.lang),
                "minutes": 60,
                "enabled": True,
                "sound": "file:newday.wav",
                "volume": 0.05,
                "show_notification": True,
                "show_in_top_bar": False,
                "align_mode": "clock",
                "all_day": True,
                "start_minute": 0,
                "end_minute": 1439,
            }]
        elif act == a_pomo:
            self.main_win.data["interval_notifs"] = [{
                "id": "interval_pomo",
                "name": tr("Pomodoro Focus (25m)", self.lang),
                "minutes": 25,
                "enabled": True,
                "sound": "file:QUEST.wav",
                "volume": 0.05,
                "show_notification": True,
                "show_in_top_bar": True,
                "align_mode": "elapsed",
                "all_day": True,
                "start_minute": 0,
                "end_minute": 1439,
            }]
        elif act == a_night:
            self.main_win.data["interval_notifs"] = [{
                "id": "interval_night",
                "name": tr("Night Owl (22:00 - 06:00)", self.lang),
                "minutes": 60,
                "enabled": True,
                "sound": "file:alert_owl2.wav",
                "volume": 0.05,
                "show_notification": True,
                "show_in_top_bar": False,
                "align_mode": "clock",
                "all_day": False,
                "start_minute": 1320,
                "end_minute": 419,
            }]

        self._interval_cur = None
        self.main_win.mark_dirty()
        self._interval_reload()

    def _interval_new(self):
        import uuid
        rule = {
            "id": f"interval_{uuid.uuid4().hex[:8]}",
            "name": self.interval_in_name.text().strip() or tr("Reminder", self.lang),
            "minutes": self.interval_in_minutes.value(),
            "enabled": self.interval_in_enabled.isChecked(),
            "align_mode": self.interval_cb_align.currentData() or "clock",
            "all_day": self.interval_cb_allday.isChecked(),
            "start_minute": _time_to_minute(self.interval_time_start.time()),
            "end_minute": _time_to_minute(self.interval_time_end.time()),
            "sound": self.interval_in_sound.currentData() or "newday",
            "volume": self.interval_in_volume.value(),
            "show_notification": self.interval_in_notify.isChecked(),
            "show_in_top_bar": self.interval_in_topbar.isChecked(),
            "last_fired": 0.0,
            "last_fired_minute": "",
        }
        self._interval_rules().append(rule)
        self._interval_cur = rule["id"]
        self.main_win.mark_dirty()
        self._interval_reload()

    def _interval_save(self):
        rid = getattr(self, "_interval_cur", None)
        if rid is None:
            items = self.interval_list.selectedItems()
            if items:
                rid = items[0].data(0, Qt.ItemDataRole.UserRole)
        for rule in self._interval_rules():
            if rule.get("id") == rid:
                rule["name"] = self.interval_in_name.text().strip() or tr("Reminder", self.lang)
                rule["minutes"] = self.interval_in_minutes.value()
                rule["enabled"] = self.interval_in_enabled.isChecked()
                rule["align_mode"] = self.interval_cb_align.currentData() or "clock"
                rule["all_day"] = self.interval_cb_allday.isChecked()
                rule["start_minute"] = _time_to_minute(self.interval_time_start.time())
                rule["end_minute"] = _time_to_minute(self.interval_time_end.time())
                rule["sound"] = self.interval_in_sound.currentData() or "newday"
                rule["volume"] = self.interval_in_volume.value()
                rule["show_notification"] = self.interval_in_notify.isChecked()
                rule["show_in_top_bar"] = self.interval_in_topbar.isChecked()
                self.main_win.mark_dirty()
                self._interval_reload()
                return

    def _interval_delete(self):
        rid = getattr(self, "_interval_cur", None)
        if rid is None:
            return
        rules = self._interval_rules()
        self.main_win.data["interval_notifs"] = [
            r for r in rules if r.get("id") != rid]
        self._interval_cur = None
        self.main_win.mark_dirty()
        self._interval_reload()
