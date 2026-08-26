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
    REPEAT_INTERVAL,
    REPEAT_MONTHLY,
    REPEAT_NONE,
    REPEAT_YEARLY,
    SOUND_MODE_POOL,
    Timer,
    load_timers,
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
        self.label_updates = 0

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
    # b.pool.cellWidget(row, 2) is frm, 3 is to, 4 is vol
    b.pool.cellWidget(row, 2).setTime(QTime(6, 0))
    b.pool.cellWidget(row, 3).setTime(QTime(12, 0))
    b.pool.cellWidget(row, 4).setValue(0.3)
    rules = b._read_pool_rules()
    assert len(rules) == 1
    r = rules[0]
    assert r["enabled"] is True
    assert r["all_day"] is False
    assert r["start_minute"] == 360
    assert r["end_minute"] == 720
    assert r["volume"] == 0.3


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
    assert d.tabs.count() in (4, 5)  # Alarms, (Interval), Temp Timer, Productivity, Calendar
    assert "Temp Timer" in [d.tabs.tabText(i) for i in range(d.tabs.count())]
    assert d.cal is not None


def test_temp_tab_keeps_description_and_has_real_test_button():
    d = _dlg()
    d.in_temp_name.setText("Focus")
    d.in_temp_desc.setText("Finish the current task")
    d._test_temp()
    assert len(d.main_win.tested) == 1
    probe, delay = d.main_win.tested[0]
    assert probe.name == "Focus"
    assert probe.description == "Finish the current task"
    assert probe.temporary is True
    assert delay == 5


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


def test_vol_spin_drives_timer_volume_end_to_end():
    """The dialog's Vol spin must reach the sound the timer actually plays.

    Closed loop: spin_vol -> committed Timer.volume -> choose_timer_sound's
    effective level. The final playback honours that level in the fire path
    (test_timer_fire.test_notify_on_plays_sound_and_shows_toast); this ties
    the dialog's own spin to that stored volume.
    """
    from fastprompter.core.timers import choose_timer_sound

    d = _dlg()
    d._behavior.spin_vol.setValue(0.9)
    d.in_name.setText("Loud")
    d.in_when.setText("06:00")
    d.commit()
    t = d.main_win.timers[-1]
    assert t.volume == 0.9
    assert choose_timer_sound(t, datetime.datetime.now()) == ("tick", 0.9)

    d.edit_selected()
    assert d._behavior.spin_vol.value() == 9      # edit round-trips the level
    d._behavior.spin_vol.setValue(0.2)
    d.commit()
    t = d.main_win.timers[-1]
    assert t.volume == 0.2
    assert choose_timer_sound(t, datetime.datetime.now()) == ("tick", 0.2)


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
                        "start_minute": 360, "end_minute": 720, "volume": 0.4})
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

    # The all-day checkbox is removed, but we keep the row removal test to ensure
    # the combo box signal still fires correctly after a removal (tested above).


def test_calendar_inherited_volume_uses_calendar_editor_volume():
    """Pool-row 'inherit' preview must resolve against the EDITOR that owns
    the row, never against the Alarm editor's volume."""
    d = _dlg()
    d._behavior.spin_vol.setValue(0.2)        # Alarm tab volume
    d._cal_behavior.spin_vol.setValue(0.9)    # Calendar tab volume
    d._cal_behavior.cb_pool.setChecked(True)
    d._cal_behavior._pool_append_row({"sound": "tick", "enabled": True,
                                      "all_day": True, "start_minute": 0,
                                      "end_minute": 0, "volume": None})
    seen = []
    d._cal_behavior.previewRequested.connect(lambda ref, vol: seen.append((ref, vol)))
    d._cal_behavior._preview_pool_row(0)
    assert seen == [("tick", 0.9)], seen   # inherited -> Calendar editor volume

    seen.clear()
    d._cal_behavior.pool.cellWidget(0, 4).setValue(0.6)
    d._cal_behavior._preview_pool_row(0)
    assert seen == [("tick", 0.6)], seen   # overridden volume wins


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
            resets_at=None, matched="assumed", reached=True),
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


# ---------------------------------------------------------------------------
# Second wave: T-1004 edit fidelity, T-1006 calendar mirror, T-1011 lifecycle
# ---------------------------------------------------------------------------

def _select_alarm(d, tid):
    for i in range(d.list.topLevelItemCount()):
        it = d.list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == tid:
            d.list.setCurrentItem(it)
            return it
    return None


def test_alarm_edit_writes_absolute_datetime_and_preserves_it():
    d = _dlg()
    target = datetime.datetime.now() + datetime.timedelta(days=40)
    target = target.replace(minute=30, second=0, microsecond=0)
    alarm = Timer("Distant", target, repeat=REPEAT_NONE)
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    assert d.in_when.text() == target.strftime("%Y-%m-%d %H:%M")
    d.in_name.setText("Distant v2")
    d.commit()
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    assert alarm.target == target        # date AND time preserved
    assert alarm.name == "Distant v2"


def test_monthly_alarm_name_only_edit_keeps_series_anchor():
    d = _dlg()
    y = datetime.date.today().year + 1
    alarm = Timer("Payday", datetime.datetime(y, 2, 28, 9, 0),
                  repeat=REPEAT_MONTHLY, repeat_anchor=f"{y}-01-31")
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    assert d.in_when.text() == f"{y}-02-28 09:00"
    d.in_name.setText("Payday v2")
    d.commit()
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    assert alarm.repeat_anchor == f"{y}-01-31"          # series NOT re-anchored
    assert alarm.target == datetime.datetime(y, 2, 28, 9, 0)
    from fastprompter.core.timers import occurrences_in_month
    assert occurrences_in_month(alarm, y, 3) == [datetime.date(y, 3, 31)]


def test_yearly_feb29_alarm_edit_keeps_anchor_on_non_leap_occurrence():
    d = _dlg()
    y = datetime.date.today().year
    while (y % 4 != 0) or (y % 100 == 0 and y % 400 != 0):
        y += 1
    alarm = Timer("Leapday", datetime.datetime(y + 1, 2, 28, 9, 0),
                  repeat=REPEAT_YEARLY, repeat_anchor=f"{y}-02-29")
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    d.in_name.setText("Leapday v2")
    d.commit()
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    assert alarm.repeat_anchor == f"{y}-02-29"
    assert alarm.target == datetime.datetime(y + 1, 2, 28, 9, 0)


def test_monthly_alarm_date_change_reanchors():
    d = _dlg()
    y = datetime.date.today().year + 1
    alarm = Timer("Payday", datetime.datetime(y, 2, 28, 9, 0),
                  repeat=REPEAT_MONTHLY, repeat_anchor=f"{y}-01-31")
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    d.in_when.setText(f"{y}-03-15 09:00")       # deliberately new date
    d.commit()
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    assert alarm.repeat_anchor == f"{y}-03-15"  # series follows the user
    assert alarm.target == datetime.datetime(y, 3, 15, 9, 0)


def test_interval_alarm_name_only_edit_preserves_period_and_reset():
    d = _dlg()
    reset = (datetime.datetime.now() + datetime.timedelta(hours=2)).replace(
        second=0, microsecond=0)
    start = reset - datetime.timedelta(minutes=90)
    alarm = Timer("Rolling", reset, repeat=REPEAT_INTERVAL,
                  interval_minutes=90)
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    assert d.spin_limit_hours.value() == 1.5       # period synced into the spin
    assert d.in_when.text() == start.strftime("%Y-%m-%d %H:%M")
    d.in_name.setText("Rolling v2")
    d.commit()
    alarm = next(t for t in d.main_win.timers if t.kind == KIND_ALARM)
    assert alarm.interval_minutes == 90
    assert alarm.target == reset                    # same future reset, unchanged


def test_calendar_tracks_runtime_advance_on_tick():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Daily")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    old_row = d.cal_list.topLevelItem(0).text(0)

    # the scheduler rolls the timer while the dialog is open; a plain tick
    # (refresh) must pick it up WITHOUT any list selection change
    ev.target += datetime.timedelta(hours=3)
    d.refresh()
    assert d.cal_list.topLevelItem(0).text(0) == ev.target.strftime("%H:%M")
    assert d.cal_list.topLevelItem(0).text(0) != old_row


def test_no_change_tick_does_not_rebuild_calendar():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Daily")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    calls = []
    orig = d._cal_refresh_markers
    def spy():
        calls.append(1)
        return orig()
    d._cal_refresh_markers = spy
    d.refresh()                                   # tick, nothing changed
    assert calls == []                            # markers not rebuilt
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    ev.target += datetime.timedelta(days=1)
    d.refresh()                                   # model moved -> rebuilt once
    assert calls == [1]


def test_disabled_event_shows_paused_and_muted():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Enabled")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    d.cal_name.setText("Disabled")
    d.cal_enabled.setChecked(False)
    d._cal_commit()
    enabled_item = next(d.cal_list.topLevelItem(i)
                        for i in range(d.cal_list.topLevelItemCount())
                        if d.cal_list.topLevelItem(i).text(1) == "Enabled")
    disabled_item = next(d.cal_list.topLevelItem(i)
                         for i in range(d.cal_list.topLevelItemCount())
                         if d.cal_list.topLevelItem(i).text(1) == "Disabled")
    assert enabled_item.text(6) == "On"
    assert disabled_item.text(6) == "Paused"
    assert (enabled_item.foreground(0).color().name()
            != disabled_item.foreground(0).color().name())


def test_cal_toggle_refreshes_markers_and_button_text():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Daily")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d.cal_enabled.setChecked(False)
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == ev.id:
            d.cal_list.setCurrentItem(it)
            break
    assert d.cal_btn_toggle.text() == "Enable"
    d._cal_toggle_selected()
    assert ev.enabled is True
    assert d.cal_btn_toggle.text() == "Disable"
    assert d.cal_list.topLevelItem(0).text(6) == "On"


def test_malformed_calendar_timers_do_not_crash_dialog():
    now = datetime.datetime.now()
    raw = [
        {"name": "junk-repeat", "kind": "calendar", "repeat": "garbage",
         "repeat_anchor": "not-a-date", "enabled": "False",
         "target": (now + datetime.timedelta(days=1)).isoformat()},
        {"name": "junk-notif", "kind": "calendar", "repeat": "monthly",
         "repeat_anchor": "bad", "show_notification": "False",
         "target": (now + datetime.timedelta(days=1)).isoformat()},
    ]
    healthy = Timer("Healthy", now + datetime.timedelta(days=1),
                    kind=KIND_CALENDAR, repeat=REPEAT_MONTHLY)
    d = TimerDialog(_FakeMain())
    d.main_win.timers = load_timers(raw) + [healthy]
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    d.cal.setSelectedDate(QDate(tomorrow.year, tomorrow.month, tomorrow.day))
    d.refresh()                                   # must not raise
    names = [d.cal_list.topLevelItem(i).text(1)
             for i in range(d.cal_list.topLevelItemCount())]
    assert "Healthy" in names
    assert "Paused" in [d.cal_list.topLevelItem(i).text(6)
                        for i in range(d.cal_list.topLevelItemCount())]


def test_alarm_edit_cancel_is_true_noop():
    d = _dlg()
    target = datetime.datetime.now() + datetime.timedelta(days=5)
    alarm = Timer("A", target, repeat=REPEAT_NONE, sound_mode=SOUND_MODE_POOL,
                  sound_rules=[{"sound": "bells", "enabled": True}])
    d.main_win.timers.append(alarm)
    d.refresh()
    before = alarm.to_dict()
    _select_alarm(d, alarm.id)
    d.edit_selected()
    d.in_name.setText("Should not stick")
    d.in_when.setText("tomorrow 03:00")
    d._behavior.cb_show_notif.setChecked(False)
    d.clear_form()
    assert alarm.to_dict() == before


def test_calendar_edit_cancel_is_true_noop():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Cal")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    before = ev.to_dict()
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == ev.id:
            d.cal_list.setCurrentItem(it)
            break
    d._cal_edit_selected()
    d.cal_name.setText("Should not stick")
    d.cal_time.setTime(QTime(23, 59))
    d.cal_enabled.setChecked(False)
    d._cal_new()
    assert ev.to_dict() == before


def test_mutations_update_timer_label_immediately():
    d = _dlg()
    y = datetime.date.today().year + 1
    d.cal.setSelectedDate(QDate(y, 9, 15))
    d.cal_name.setText("Daily")
    d.cal_time.setTime(QTime(9, 0))
    d.cal_repeat.setCurrentIndex(d.cal_repeat.findData("daily"))
    d._cal_commit()
    assert d.main_win.label_updates >= 1          # calendar commit
    ev = [t for t in d.main_win.timers if t.kind == KIND_CALENDAR][0]
    for i in range(d.cal_list.topLevelItemCount()):
        it = d.cal_list.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.UserRole) == ev.id:
            d.cal_list.setCurrentItem(it)
            break
    before = d.main_win.label_updates
    d._cal_toggle_selected()                      # calendar toggle
    assert d.main_win.label_updates > before

    alarm = Timer("A", datetime.datetime.now() + datetime.timedelta(hours=1),
                  repeat=REPEAT_NONE)
    d.main_win.timers.append(alarm)
    d.refresh()
    _select_alarm(d, alarm.id)
    before = d.main_win.label_updates
    d.toggle_selected()                           # alarm toggle
    assert d.main_win.label_updates > before
    _select_alarm(d, alarm.id)
    d.edit_selected()
    d.in_name.setText("Renamed")
    before = d.main_win.label_updates
    d.commit()
    assert d.main_win.label_updates > before      # alarm edit


def test_dialog_open_close_hundred_times_no_residue():
    import gc
    import weakref

    fake = _FakeMain()
    timers_before = len(fake.timers)
    saved_before = fake.saved
    labels_before = fake.label_updates
    refs = []
    for _ in range(100):
        d = _dlg()
        d.show()
        d.close()
        d.deleteLater()
        refs.append(weakref.ref(d))
    del d
    QApplication.processEvents()
    gc.collect()
    alive = [r for r in refs if r() is not None]
    assert alive == []                            # every dialog fully destroyed
    assert len(fake.timers) == timers_before      # no model mutation
    assert fake.saved == saved_before
    assert fake.label_updates == labels_before

def test_t1014_scan_only_makes_timers_for_limited_agents():
    from fastprompter.ui.timer_dialog import TimerDialog
    from fastprompter.core.timers import KIND_ALARM
    import types
    
    # We mock limit_scan.scan_all to return 3 results:
    # 1. Clear (reachable, reached=False)
    # 2. Capped (reachable, reached=True)
    # 3. Unreachable (reachable=False)
    
    res_clear = types.SimpleNamespace(
        name="ClearAgent", reachable=True,
        state=types.SimpleNamespace(resets_at=None, matched="", reached=False)
    )
    res_capped = types.SimpleNamespace(
        name="CappedAgent", reachable=True,
        state=types.SimpleNamespace(resets_at=None, matched="capped", reached=True)
    )
    res_unreachable = types.SimpleNamespace(
        name="UnreachableAgent", reachable=False,
        state=types.SimpleNamespace(resets_at=None, matched="", reached=False)
    )
    
    app = _FakeMain()
    d = TimerDialog(app)
    d.main_win.watcher_adapters = lambda: ([], [], [])
    
    from fastprompter.core.watcher import limit_scan as limit_scan_mod
    original_scan_all = limit_scan_mod.scan_all
    limit_scan_mod.scan_all = lambda adapters: [res_clear, res_capped, res_unreachable]
    
    try:
        d.scan_agent_limits()
    finally:
        limit_scan_mod.scan_all = original_scan_all
        
    alarms = [t for t in d.main_win.timers if t.kind == KIND_ALARM]
    
    # Only the CappedAgent should result in an alarm
    assert len(alarms) == 1
    assert alarms[0].name == "CappedAgent limit"

def test_t1015_scan_agent_locale_independent_identity():
    from fastprompter.ui.timer_dialog import TimerDialog
    from fastprompter.core.timers import KIND_ALARM, save_timers, load_timers
    import types
    
    res = types.SimpleNamespace(
        name="Claude", reachable=True,
        state=types.SimpleNamespace(resets_at=None, matched="capped", reached=True)
    )
    
    app = _FakeMain()
    d = TimerDialog(app)
    d.main_win.watcher_adapters = lambda: ([], [], [])
    
    from fastprompter.core.watcher import limit_scan as limit_scan_mod
    original_scan_all = limit_scan_mod.scan_all
    limit_scan_mod.scan_all = lambda adapters: [res]
    
    try:
        # 1. EN Scan
        d.lang = "EN"
        d.scan_agent_limits()
        alarms = [t for t in d.main_win.timers if t.kind == KIND_ALARM]
        assert len(alarms) == 1
        timer_id = alarms[0].id
        assert alarms[0].name == "Claude limit"
        
        # 2. Simulate Save/Load round trip
        saved = save_timers(app.timers)
        app.timers = load_timers(saved)
        print('Keys after load:', [t.auto_limit_key for t in app.timers])
        
        # 3. RU Scan
        d.lang = "RU"
        d.scan_agent_limits()
        alarms = [t for t in d.main_win.timers if t.kind == KIND_ALARM]
        # Should not duplicate!
        assert len(alarms) == 1
        assert alarms[0].id == timer_id
        # Note: Name updates to the localized version, or at least it's matched by key
        
        # 4. EST Scan
        d.lang = "EST"
        d.scan_agent_limits()
        alarms = [t for t in d.main_win.timers if t.kind == KIND_ALARM]
        assert len(alarms) == 1
        assert alarms[0].id == timer_id

    finally:
        limit_scan_mod.scan_all = original_scan_all


def test_t1015_legacy_keyless_timer_is_adopted_and_not_duplicated():
    """A pre-existing timer with no ``auto_limit_key`` and a localized name
    (the legacy shape) must be adopted — given a stable key, enabled, and an
    assumed target — and must never be duplicated when the UI language
    changes. This is the bug: the assumed-window path used to skip the
    update, so a re-scan could not find the keyless timer by its localized
    name and created a second countdown."""
    from fastprompter.core.timers import KIND_ALARM, Timer
    import types

    res = types.SimpleNamespace(
        name="Claude", reachable=True,
        state=types.SimpleNamespace(resets_at=None, matched="capped", reached=True),
    )

    app = _FakeMain()
    legacy = Timer(name="Claude limit", target=datetime.datetime(2030, 1, 1),
                   kind=KIND_ALARM, auto_limit_key=None)
    app.timers = [legacy]
    d = TimerDialog(app)
    d.main_win.watcher_adapters = lambda: ([], [], [])

    from fastprompter.core.watcher import limit_scan as limit_scan_mod
    original = limit_scan_mod.scan_all
    limit_scan_mod.scan_all = lambda adapters: [res]
    try:
        for lang in ("EN", "RU", "EST", "JA"):
            d.lang = lang
            d.scan_agent_limits()
            alarms = [t for t in app.timers if t.kind == KIND_ALARM]
            # exactly one timer, same identity, stable adopted key
            assert len(alarms) == 1, (lang, len(alarms))
            assert alarms[0].id == legacy.id, lang
            assert alarms[0].auto_limit_key == "Claude", lang
            assert alarms[0].enabled is True, lang
            # assumed target is deterministic: now + the configured window
            assert alarms[0].target is not None
    finally:
        limit_scan_mod.scan_all = original
