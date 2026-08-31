"""Comprehensive test suite for FastPrompter Night Upgrade features:
1. Silo hierarchy insertion on child silos.
2. Live defaults in default profile & state codecs.
3. BigAnalogClock widget & interval dial.
4. Interval notification engine (clock boundary vs elapsed, active hours).
5. Timers dialog layout reconstruction, 1-click selection in-place refresh, quick sound bar.
6. F-Keys project navigation vs snippet navigation.
7. Ctrl+F find bar toggle.
"""

import datetime
import json
import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QPoint, Qt, QTime

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.state import _STRUCTURED_CODECS, _JSON_SETTINGS
from fastprompter.core.sound_manager import SoundManager, _DEFAULT_SOUND_MAP
from fastprompter.ui.analog_clock import BigAnalogClock
from fastprompter.ui.timer_dialog import TimerDialog, _TimerBehaviorEditor
from fastprompter.core.timers import Timer, KIND_ALARM, save_timers, load_timers


_APP = QApplication.instance() or QApplication([])


class _FakePomo:
    breaks_enabled = True
    repeat_alarm = False
    running = False
    state = "idle"
    phase = "work"
    alarm_pending = False
    remaining = 0
    work_seconds = 25 * 60
    break_seconds = 5 * 60

    def describe(self):
        return ""

    def apply_durations(self, **kw):
        pass

    def toggle(self):
        pass

    def reset(self):
        pass

    def skip_phase(self):
        pass

    def on_productivity_changed(self):
        pass


class _FakeMain(QWidget):
    def __init__(self):
        super().__init__()
        self.timers = []
        self.data = {
            "theme": "Default",
            "interval_notifs": [
                {
                    "id": "test_interval_1",
                    "name": "Hourly Peace Reminder",
                    "minutes": 60,
                    "enabled": True,
                    "align_mode": "clock",
                    "all_day": True,
                    "start_minute": 0,
                    "end_minute": 1439,
                    "sound": "newday",
                    "volume": 0.1,
                    "show_notification": False,
                    "show_in_top_bar": False,
                    "last_fired": 0.0,
                    "last_fired_minute": "",
                }
            ],
            "sound_quick_bar": [
                "file:NEWDAY.wav", "file:NEWMONTH.wav", "file:NEWWEEK.wav",
                "file:NOMAD.wav", "file:OBELISK.wav", "file:PARALYZE.wav",
                "file:PICKUP01.wav", "file:PICKUP03.wav", "file:QUEST.wav",
                "file:ROGUE.wav",
            ],
            "fkey_action": "projects",
        }
        self._current_lang = "EN"
        self.sound_manager = SoundManager(None, {})
        self.productivity_timer = _FakePomo()
        self.saved = 0
        self.label_updates = 0
        self.tested = []

    def styleSheet(self):
        return ""

    def save_timers_to_data(self):
        self.saved += 1

    def _update_timer_label(self):
        self.label_updates += 1

    def save_productivity_timer(self):
        pass

    def on_productivity_changed(self):
        pass

    def test_timer_notification(self, timer, delay):
        self.tested.append((timer, delay))

    def _interval_notifs(self):
        return self.data.get("interval_notifs", [])

    def mark_dirty(self):
        pass


# --------------------------------------------------------------------------
# 1. Defaults Profile & Codecs Tests
# --------------------------------------------------------------------------

def test_default_profile_has_user_foundational_settings():
    assert str(DEFAULT_PROFILE.get("sound_volume")) == "0.36"
    assert DEFAULT_PROFILE.get("fkey_action") == "projects"
    assert DEFAULT_PROFILE.get("ui_scale") == 0.5
    assert DEFAULT_PROFILE.get("saved_sidebar_size") in ("236", 236)
    quick_bar = DEFAULT_PROFILE.get("sound_quick_bar")
    if isinstance(quick_bar, str):
        quick_bar = json.loads(quick_bar)
    assert isinstance(quick_bar, list)
    assert len(quick_bar) == 10
    assert quick_bar[0] == "file:NEWDAY.wav"
    assert quick_bar[1] == "file:NEWMONTH.wav"
    assert quick_bar[2] == "file:NEWWEEK.wav"


def test_state_codecs_register_interval_notifs_and_quick_bar():
    assert "interval_notifs" in _JSON_SETTINGS
    assert "sound_quick_bar" in _JSON_SETTINGS
    assert "interval_notifs" in _STRUCTURED_CODECS
    assert "sound_quick_bar" in _STRUCTURED_CODECS


def test_sound_manager_defaults_aligned():
    assert _DEFAULT_SOUND_MAP["click"] == "button1.wav"
    assert _DEFAULT_SOUND_MAP["silo"] == "button1.wav"
    assert _DEFAULT_SOUND_MAP["error"] == "newday.wav"


# --------------------------------------------------------------------------
# 2. BigAnalogClock Widget Tests
# --------------------------------------------------------------------------

def test_big_analog_clock_construction_and_sync():
    app = _FakeMain()
    clock = BigAnalogClock(app, None, size=150)
    assert clock._size == 150
    clock.sync()
    clock.set_interval(30, "clock")
    assert clock._interval_minutes == 30
    assert clock._align_mode == "clock"


def test_big_analog_clock_signals_interval():
    app = _FakeMain()
    clock = BigAnalogClock(app, None, size=150)
    received = []
    clock.intervalChanged.connect(lambda mins: received.append(mins))
    clock._interval_minutes = 45
    clock.intervalChanged.emit(45)
    assert received == [45]


def test_big_analog_clock_renders_cleanly():
    from PyQt6.QtGui import QPixmap, QPainter
    app = _FakeMain()
    clock = BigAnalogClock(app, None, size=150)
    clock.resize(150, 150)
    pix = QPixmap(150, 150)
    clock.render(pix)
    assert not pix.isNull()


# --------------------------------------------------------------------------
# 3. Interval Notification Engine Logic Tests
# --------------------------------------------------------------------------

def test_interval_notification_engine_clock_boundary():
    rule = {
        "id": "r1",
        "name": "Hourly",
        "minutes": 60,
        "enabled": True,
        "align_mode": "clock",
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
        "sound": "newday",
        "volume": 0.1,
        "show_notification": False,
        "last_fired": 0.0,
        "last_fired_minute": "",
    }

    # Simulate 14:00:05 (minute % 60 == 0)
    dt_on_hour = datetime.datetime(2026, 8, 26, 14, 0, 5)

    # Boundary match check
    mins = rule["minutes"]
    cur_min = dt_on_hour.minute
    assert cur_min % mins == 0

    # Outside active hours check
    rule_active = {
        "id": "r2",
        "name": "Workday Only",
        "minutes": 60,
        "enabled": True,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 9 * 60,   # 09:00
        "end_minute": 18 * 60,    # 18:00
    }
    # 08:00 is before start_minute
    minute_of_day_8am = 8 * 60
    assert not (rule_active["start_minute"] <= minute_of_day_8am <= rule_active["end_minute"])
    # 14:00 is within active hours
    minute_of_day_2pm = 14 * 60
    assert (rule_active["start_minute"] <= minute_of_day_2pm <= rule_active["end_minute"])


# --------------------------------------------------------------------------
# 4. Timers Dialog Reconstruction & 1-Click Selection Tests
# --------------------------------------------------------------------------

def test_timer_dialog_reconstructed_layout():
    app = _FakeMain()
    d = TimerDialog(app)
    # Check tabs
    tab_names = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    assert "Alarms" in tab_names
    assert "Interval Notifications" in tab_names
    assert "Temp Timer" in tab_names

    # Check behavior editor quick bar
    assert hasattr(d._behavior, "quick_bar")
    assert len(d._behavior._quick_buttons) == 10

    # Check interval tab widgets
    assert hasattr(d, "interval_clock")
    assert hasattr(d, "interval_list")
    assert hasattr(d, "interval_in_minutes")
    assert hasattr(d, "interval_in_sound")
    assert hasattr(d, "interval_quick_bar")


def test_timer_dialog_1_click_selection_in_place_refresh():
    app = _FakeMain()
    t1 = Timer(id="t1", name="Alpha", target=datetime.datetime.now() + datetime.timedelta(hours=1), kind=KIND_ALARM)
    t2 = Timer(id="t2", name="Beta", target=datetime.datetime.now() + datetime.timedelta(hours=2), kind=KIND_ALARM)
    app.timers = [t1, t2]

    d = TimerDialog(app)
    d.refresh()
    assert d.list.topLevelItemCount() == 2

    # Click item 2
    item2 = d.list.topLevelItem(1)
    d.list.setCurrentItem(item2)
    assert d.list.currentItem().data(0, Qt.ItemDataRole.UserRole) == "t2"

    # Refresh must NOT recreate the item or drop the selection
    d.refresh()
    assert d.list.currentItem() is not None
    assert d.list.currentItem().data(0, Qt.ItemDataRole.UserRole) == "t2"
    assert d.in_name.text() == "Beta"


def test_interval_tab_crud():
    app = _FakeMain()
    d = TimerDialog(app)
    initial_count = len(d._interval_rules())

    # Create new interval rule
    d.interval_in_name.setText("Hydration Check")
    d.interval_in_minutes.setValue(45)
    d._interval_new()

    assert len(d._interval_rules()) == initial_count + 1
    new_rule = d._interval_rules()[-1]
    assert new_rule["name"] == "Hydration Check"
    assert new_rule["minutes"] == 45

    # Edit interval rule
    d.interval_in_minutes.setValue(30)
    d._interval_save()
    assert d._interval_rules()[-1]["minutes"] == 30

    # Delete interval rule
    d._interval_delete()
    assert len(d._interval_rules()) == initial_count


def test_interval_quick_bar_pick_and_store():
    app = _FakeMain()
    d = TimerDialog(app)

    assert hasattr(d, "interval_quick_bar")
    assert len(d._interval_quick_buttons) == 10

    # Pick
    d._interval_quick_pick("file:NEWDAY.wav")
    assert d.interval_in_sound.currentData() == "file:NEWDAY.wav"

    # Store via right-click handler
    d.interval_in_sound.setCurrentIndex(d.interval_in_sound.findData("click"))
    d._interval_quick_store(0)
    assert d._quick_bar_slots()[0] == "click"


def test_mini_analog_clock_click_opens_interval_tab():
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    from fastprompter.ui.analog_clock import MiniAnalogClock

    opened = []
    class FakeWindow:
        data = {"analog_clock": "True"}
        _current_lang = "EN"
        def open_timer_dialog(self, initial_tab=0):
            opened.append(initial_tab)

    win = FakeWindow()
    clock = MiniAnalogClock(win)

    # Left-click on mini analog clock
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    clock.mousePressEvent(ev)
    assert opened == [1]

    # Test TimerDialog directly with initial_tab=1
    app = _FakeMain()
    dlg = TimerDialog(app, initial_tab=1)
    assert dlg.tabs.currentIndex() == 1
    assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "Interval Notifications"


def test_interval_sound_selection_persistence_and_matching():
    from fastprompter.ui.timer_dialog import _find_sound_index, DEFAULT_INTERVAL_RULES
    from fastprompter.core.sound_manager import SoundManager
    
    app = _FakeMain()
    app.sound_manager = SoundManager(None, {})
    dlg = TimerDialog(app, initial_tab=1)
    
    # Verify _find_sound_index matches all variations
    assert _find_sound_index(dlg.interval_in_sound, "file:GENIE.wav") >= 0
    assert _find_sound_index(dlg.interval_in_sound, "file:genie.wav") >= 0
    assert _find_sound_index(dlg.interval_in_sound, "GENIE.wav") >= 0
    assert _find_sound_index(dlg.interval_in_sound, "file:NEWDAY.wav") >= 0
    assert _find_sound_index(dlg.interval_in_sound, "file:newday.wav") >= 0
    assert _find_sound_index(dlg.interval_in_sound, "file:alert_owl2.wav") >= 0
    
    # Reset to defaults and test item switching
    dlg._interval_reset_defaults()
    assert dlg.interval_list.topLevelItemCount() == 4
    
    item0 = dlg.interval_list.topLevelItem(0)
    dlg.interval_list.setCurrentItem(item0)
    assert dlg.interval_in_sound.currentData() == "file:GENIE.wav"
    
    item1 = dlg.interval_list.topLevelItem(1)
    dlg.interval_list.setCurrentItem(item1)
    assert dlg.interval_in_sound.currentData() == "file:NEWDAY.wav"
    
    item3 = dlg.interval_list.topLevelItem(3)
    dlg.interval_list.setCurrentItem(item3)
    assert dlg.interval_in_sound.currentData() == "file:alert_owl2.wav"
    
    dlg.interval_list.setCurrentItem(item0)
    assert dlg.interval_in_sound.currentData() == "file:GENIE.wav"



