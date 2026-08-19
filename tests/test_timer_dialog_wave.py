"""Offscreen tests for the Timer/Calendar wave UI in TimerDialog.

These exercise the shared behaviour editor (notify / top-bar / single vs
random-pool sound) and the Calendar tab, which are pure Qt widget logic that
does not need a real FastPrompter window. A minimal fake stands in for
main_win.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime  # noqa: E402

from PyQt6.QtCore import (  # noqa: E402
    QDate,
    Qt,  # noqa: E402
    QTime,
)
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.core.timers import (  # noqa: E402
    KIND_ALARM,
    KIND_CALENDAR,
    REPEAT_MONTHLY,
    SOUND_MODE_POOL,
)
from fastprompter.ui.timer_dialog import TimerDialog, _TimerBehaviorEditor  # noqa: E402

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
        self.data = {"theme": "Default"}
        self._current_lang = "EN"
        self.sound_manager = SoundManager(None, {})
        self.productivity_timer = _FakePomo()
        self.saved = 0
        self.tested = []

    def styleSheet(self):
        return ""

    def save_timers_to_data(self):
        self.saved += 1

    def save_productivity_timer(self):
        pass

    def on_productivity_changed(self):
        pass

    def test_timer_notification(self, timer, delay):
        self.tested.append((timer, delay))


def _dlg():
    return TimerDialog(_FakeMain())


def test_behavior_editor_defaults_on():
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    assert b.cb_show_notif.isChecked()
    assert b.cb_show_topbar.isChecked()
    assert b.cb_temp.isChecked()
    assert b.spin_vol.value() == 5


def test_pool_toggle_swaps_single_and_table():
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    b.show()
    assert b.cb_sound.isVisible()
    assert not b.pool.isVisible()
    b.cb_pool.setChecked(True)
    assert not b.cb_sound.isVisible()
    assert b.pool.isVisible()
    b.cb_pool.setChecked(False)
    assert b.cb_sound.isVisible()


def test_pool_caps_at_ten_rows():
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    b.cb_pool.setChecked(True)
    for _ in range(15):
        b._pool_add()
    assert b.pool.rowCount() == 10
    assert not b.btn_pool_add.isEnabled()


def test_pool_rule_roundtrip_reads_back():
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    b.cb_pool.setChecked(True)
    b._pool_add()
    row = 0
    b.pool.cellWidget(row, 0).setChecked(True)
    b.pool.cellWidget(row, 2).setChecked(False)  # all_day off
    b.pool.cellWidget(row, 3).setTime(QTime(6, 0))
    b.pool.cellWidget(row, 4).setTime(QTime(12, 0))
    b.pool.cellWidget(row, 5).setValue(3)
    rules = b._read_pool_rules()
    assert len(rules) == 1
    r = rules[0]
    assert r["enabled"] is True
    assert r["all_day"] is False
    assert r["start_minute"] == 360
    assert r["end_minute"] == 720
    assert r["volume"] == 3


def test_preview_only_on_user_activation():
    d = _dlg()
    seen = []
    d._behavior.previewRequested.connect(lambda ref, vol: seen.append((ref, vol)))
    d._behavior.cb_sound.setCurrentIndex(0)
    assert seen == []
    d._behavior.cb_sound.activated.emit(0)
    assert len(seen) == 1


def test_dialog_constructs_with_calendar_tab():
    d = _dlg()
    assert d.tabs.count() == 3  # Alarms, Calendar, Productivity
    assert d.cal is not None


def test_calendar_add_edit_delete_event():
    d = _dlg()
    sel = QDate(2026, 9, 15)
    d.cal.setSelectedDate(sel)
    d.cal_name.setText("Standup")
    d.cal_time.setTime(QTime(9, 30))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData(REPEAT_MONTHLY))
    d._cal_commit()
    cal = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR]
    assert len(cal) == 1
    assert cal[0].name == "Standup"
    assert cal[0].repeat == REPEAT_MONTHLY
    assert cal[0].repeat_anchor == "2026-09-15"
    assert cal[0].target == datetime.datetime(2026, 9, 15, 9, 30, 0)
    eid = cal[0].id
    d._cal_editing_id = eid
    d.cal_name.setText("Standup v2")
    d._cal_commit()
    names = [t.name for t in d.main_win.timers if t.kind == KIND_CALENDAR]
    assert names == ["Standup v2"]
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == eid:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_delete_selected()
    assert [t for t in d.main_win.timers if t.kind == KIND_CALENDAR] == []


def test_calendar_markers_mark_visible_month():
    d = _dlg()
    d.cal.setCurrentPage(2026, 9)
    d.cal.setSelectedDate(QDate(2026, 9, 15))
    d.cal_name.setText("Rent")
    d.cal_time.setTime(QTime(8, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData(REPEAT_MONTHLY))
    d._cal_commit()
    fmt = d.cal.dateTextFormat(QDate(2026, 9, 15))
    assert fmt.foreground().color().isValid()


def test_alarm_commit_carries_behavior_flags():
    d = _dlg()
    d.in_name.setText("Wake")
    d.in_when.setText("06:00")
    d._behavior.cb_show_notif.setChecked(False)
    d._behavior.cb_show_topbar.setChecked(False)
    d._behavior.cb_pool.setChecked(True)
    d._behavior._pool_add()
    d._behavior._pool_append_row({"sound": "tick", "enabled": True,
                                  "all_day": True, "volume": None,
                                  "start_minute": 0, "end_minute": 0})
    d.commit()
    t = d.main_win.timers[-1]
    assert t.show_notification is False
    assert t.show_in_top_bar is False
    assert t.sound_mode == SOUND_MODE_POOL
    assert len(t.sound_rules) == 2


# ==================================================== T-1005 stabilization


def test_real_dialog_editors_offer_library_files_from_one_inventory():
    """The production TimerDialog must wire the behaviour editors to the
    REAL main window, so direct WAV choices appear (not just named events)."""
    d = _dlg()
    inventory = d.main_win.sound_manager.get_available_sounds()
    assert len(inventory) > 300

    def file_refs(editor):
        return [ref for _disp, ref in editor._sound_choices
                if isinstance(ref, str) and ref.startswith("file:")]

    alarm_files = file_refs(d._behavior)
    cal_files = file_refs(d._cal_behavior)
    assert len(alarm_files) == len(inventory)
    assert set(alarm_files) == {f"file:{rel}" for rel in inventory}
    assert set(cal_files) == set(alarm_files)   # same SoundManager inventory


def test_pool_row_signals_survive_row_removal():
    """Signals must capture widgets, not table row indexes: after removing an
    earlier row the surviving rows preview and toggle THEIR OWN widgets."""
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    b.cb_pool.setChecked(True)
    b._pool_append_row({"sound": "tick", "enabled": True, "all_day": True,
                        "start_minute": 0, "end_minute": 0, "volume": None})
    b._pool_append_row({"sound": "click", "enabled": True, "all_day": False,
                        "start_minute": 360, "end_minute": 720, "volume": 4})
    b._pool_append_row({"sound": "file:alert_b.wav", "enabled": True,
                        "all_day": True, "start_minute": 0, "end_minute": 0,
                        "volume": None})

    seen = []
    b.previewRequested.connect(lambda ref, vol: seen.append((ref, vol)))
    b.pool.removeRow(0)
    assert b.pool.rowCount() == 2

    # old row1 (click) is now row0; activating ITS combo must preview click
    b.pool.cellWidget(0, 1).activated.emit(0)
    assert seen == [("click", 4)], seen
    seen.clear()

    # old row2 (file) is now row1; its all-day toggle must drive ITS From/To
    # and never touch row0's widgets
    row1_frm = b.pool.cellWidget(1, 3)
    row1_to = b.pool.cellWidget(1, 4)
    b.pool.cellWidget(1, 2).setChecked(False)
    assert row1_frm.isEnabled() and row1_to.isEnabled()
    assert b.pool.cellWidget(0, 3).isEnabled() is True    # row0 unaffected
    b.pool.cellWidget(1, 2).setChecked(True)
    assert not row1_frm.isEnabled() and not row1_to.isEnabled()
    assert b.pool.cellWidget(0, 3).isEnabled() is True    # row0 still unaffected


def test_calendar_inherited_volume_uses_calendar_editor_volume():
    """Pool-row 'inherit' preview must resolve against the EDITOR that owns
    the row, never against the Alarm editor's volume."""
    d = _dlg()
    d._behavior.spin_vol.setValue(2)        # Alarm tab volume
    d._cal_behavior.spin_vol.setValue(9)    # Calendar tab volume
    d._cal_behavior.cb_pool.setChecked(True)
    d._cal_behavior._pool_append_row({"sound": "tick", "enabled": True,
                                      "all_day": True, "start_minute": 0,
                                      "end_minute": 0, "volume": None})
    seen = []
    d._cal_behavior.previewRequested.connect(lambda ref, vol: seen.append((ref, vol)))
    d._cal_behavior._preview_pool_row(0)
    assert seen == [("tick", 9)], seen   # inherited -> Calendar editor volume

    seen.clear()
    d._cal_behavior.pool.cellWidget(0, 5).setValue(6)
    d._cal_behavior._preview_pool_row(0)
    assert seen == [("tick", 6)], seen   # explicit row volume wins


def test_zero_length_window_refused_at_alarm_commit():
    d = _dlg()
    d._behavior.cb_pool.setChecked(True)
    d._behavior._pool_append_row({"sound": "tick", "enabled": True,
                                  "all_day": False, "start_minute": 360,
                                  "end_minute": 360, "volume": None})
    err = d._behavior.validate()
    assert err is not None and "empty time range" in err
    d.in_name.setText("Zero")
    d.in_when.setText("06:00")
    d.commit()
    assert d.main_win.timers == []          # refused: nothing saved
    assert d.lbl_hint.text()               # form-level error shown
    assert d._behavior.pool.currentRow() == 0   # offending row selected


def test_overnight_window_remains_valid():
    b = _TimerBehaviorEditor(_FakeMain(), "EN")
    b.cb_pool.setChecked(True)
    b._pool_append_row({"sound": "tick", "enabled": True, "all_day": False,
                        "start_minute": 22 * 60, "end_minute": 6 * 60,
                        "volume": None})
    assert b.validate() is None            # 22:00 -> 06:00 overnight is valid


def test_zero_length_window_refused_at_calendar_commit():
    d = _dlg()
    d.cal_name.setText("Bad")
    d._cal_behavior.cb_pool.setChecked(True)
    d._cal_behavior._pool_append_row({"sound": "tick", "enabled": True,
                                      "all_day": False, "start_minute": 300,
                                      "end_minute": 300, "volume": None})
    d._cal_commit()
    assert [t for t in d.main_win.timers if t.kind == KIND_CALENDAR] == []
    assert d.cal_hint.text()               # calendar form-level error


# ==================================================== T-1006 stabilization


def test_alarm_list_isolated_from_calendar_events():
    d = _dlg()
    d.in_name.setText("Alarm A")
    d.in_when.setText("06:00")
    d.commit()
    d.cal.setSelectedDate(QDate(2026, 9, 15))
    d.cal_name.setText("Cal B")
    d.cal_time.setTime(QTime(9, 0))
    d._cal_commit()
    d.refresh()

    kinds = {t.kind for t in d.main_win.timers}
    assert kinds == {KIND_ALARM, KIND_CALENDAR}
    # Alarm list shows exactly the alarm
    assert d.list.topLevelItemCount() == 1
    assert d.list.topLevelItem(0).text(0) == "Alarm A"
    # editing the alarm must not touch the calendar event
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    d._editing_id = alarm.id
    d.in_name.setText("Alarm A2")
    d.commit()
    cal = next(t for t in d.main_win.timers if t.kind == KIND_CALENDAR)
    assert cal.name == "Cal B"
    assert cal.kind == KIND_CALENDAR


def test_scan_limits_never_hijack_calendar_event():
    import types

    import fastprompter.core.watcher.limit_scan as limit_scan_mod

    d = _dlg()
    d.cal.setSelectedDate(QDate(2026, 9, 15))
    d.cal_name.setText("Claude limit")
    d.cal_time.setTime(QTime(9, 0))
    d._cal_commit()

    hit = types.SimpleNamespace(
        name="Claude",
        reachable=True,
        state=types.SimpleNamespace(
            resets_at=None, matched="assumed", reached=False),
    )
    d.main_win.watcher_adapters = lambda: ([], [], [])
    limit_scan_mod.scan_all = lambda adapters: [hit]
    d.scan_agent_limits()

    alarms = [t for t in d.main_win.timers if t.kind == KIND_ALARM]
    cals = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR]
    # calendar event named "Claude limit" untouched, still calendar
    assert len(cals) == 1 and cals[0].name == "Claude limit"
    assert cals[0].kind == KIND_CALENDAR
    # a NEW alarm was created instead of hijacking the calendar event
    assert len(alarms) == 1
    assert alarms[0].name == "Claude limit"


def test_recurring_calendar_edit_keeps_series_anchor():
    d = _dlg()
    y = datetime.date.today().year + 1          # future: no past-normalization
    d.cal.setSelectedDate(QDate(y, 1, 28))
    d.cal_name.setText("Payday")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData(REPEAT_MONTHLY))
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    assert ev.repeat_anchor == f"{y}-01-28"

    # browse the 28-Feb occurrence (day 28 exists in every February) and edit
    # ONLY the name
    d.cal.setSelectedDate(QDate(y, 2, 28))
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == ev.id:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_edit_selected()
    assert d.cal.selectedDate().toPyDate() == datetime.date(y, 1, 28)
    d.cal_name.setText("Payday v2")
    d._cal_commit()

    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    assert ev.repeat_anchor == f"{y}-01-28"          # anchor untouched
    assert ev.target == datetime.datetime(y, 1, 28, 9, 0, 0)
    from fastprompter.core.timers import occurrences_in_month
    assert occurrences_in_month(ev, y, 3) == [datetime.date(y, 3, 28)]


def test_recurring_calendar_edit_keeps_feb29_anchor():
    d = _dlg()
    y = datetime.date.today().year
    while (y % 4 != 0) or (y % 100 == 0 and y % 400 != 0):
        y += 1                                   # next leap year
    d.cal.setSelectedDate(QDate(y, 2, 29))
    d.cal_name.setText("Leapday")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("yearly"))
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    assert ev.repeat_anchor == f"{y}-02-29"

    # browse the clamped 28-Feb occurrence of the NEXT (non-leap) year
    d.cal.setSelectedDate(QDate(y + 1, 2, 28))
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == ev.id:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_edit_selected()
    assert d.cal.selectedDate().toPyDate() == datetime.date(y, 2, 29)
    d.cal_name.setText("Leapday v2")
    d._cal_commit()

    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    assert ev.repeat_anchor == f"{y}-02-29"          # anchor untouched
    from fastprompter.core.timers import occurrences_in_month
    y2 = y + 1
    while (y2 % 4 != 0) or (y2 % 100 == 0 and y2 % 400 != 0):
        y2 += 1
    assert occurrences_in_month(ev, y2, 2) == [datetime.date(y2, 2, 29)]


def test_past_recurring_calendar_normalized_no_retro_fire():
    d = _dlg()
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    d.cal.setSelectedDate(QDate(yesterday.year, yesterday.month, yesterday.day))
    d.cal_name.setText("Daily")
    d.cal_time.setTime(QTime(0, 1))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    assert ev.enabled
    assert ev.target > datetime.datetime.now()      # rolled to future
    assert ev.target.strftime("%H:%M") == "00:01"
    assert ev.fired is False


def test_past_once_event_refused_when_enabled():
    d = _dlg()
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    d.cal.setSelectedDate(QDate(yesterday.year, yesterday.month, yesterday.day))
    d.cal_name.setText("Once")
    d.cal_time.setTime(QTime(9, 0))
    d._cal_commit()
    assert [t for t in d.main_win.timers if t.kind == KIND_CALENDAR] == []
    assert d.cal_hint.text()                       # refusal message


def test_disabled_past_once_storable_then_enable_refused():
    d = _dlg()
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    d.cal.setSelectedDate(QDate(yesterday.year, yesterday.month, yesterday.day))
    d.cal_name.setText("Old once")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_enabled.setChecked(False)
    d._cal_commit()
    cals = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR]
    assert len(cals) == 1 and cals[0].enabled is False   # historical, allowed

    # select it in the list and try to enable -> refused
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == cals[0].id:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_toggle_selected()
    assert cals[0].enabled is False
    assert d.cal_hint.text()


def test_disabled_past_repeating_enable_normalizes():
    d = _dlg()
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    d.cal.setSelectedDate(QDate(yesterday.year, yesterday.month, yesterday.day))
    d.cal_name.setText("Old daily")
    d.cal_time.setTime(QTime(0, 1))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d.cal_enabled.setChecked(False)
    d._cal_commit()
    cals = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR]
    assert len(cals) == 1 and cals[0].enabled is False

    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == cals[0].id:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_toggle_selected()
    assert cals[0].enabled is True
    assert cals[0].target > datetime.datetime.now()   # normalized, no retro-fire
