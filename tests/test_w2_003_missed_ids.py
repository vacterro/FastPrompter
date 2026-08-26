"""W2-003 regression: missed (passed) one-shot timer IDs must persist to the
active profile and survive restart, prune on delete/disable, and never be
resurrected from a fired (acknowledged) state or foreign profile.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.timers import Timer, REPEAT_NONE  # noqa: E402


class _Sound:
    def play_sound_ref(self, *a, **k):
        return True


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


def _make_fake(data=None, timers=None):
    class _Fake:
        def __init__(self):
            self.data = data or {}
            self.timers = timers or []
            self._missed_timer_ids = set()
            self.sound_manager = _Sound()
            self.tray_icon = None
            self._current_lang = "EN"
            self.productivity_timer = _FakePomo()

        def styleSheet(self):
            return ""

        def mark_dirty(self, *a, **k):
            pass

        def save_timers_to_data(self):
            main_mod.FastPrompter.save_timers_to_data.__get__(self)()

        def _update_date_label(self):
            pass

        def _apply_date_alert_style(self):
            pass
    f = _Fake()
    f._load_missed_ids = main_mod.FastPrompter._load_missed_ids.__get__(f)
    f._persist_missed_ids = main_mod.FastPrompter._persist_missed_ids.__get__(f)
    f._missed_attention = main_mod.FastPrompter._missed_attention.__get__(f)
    f._clear_missed_alert = main_mod.FastPrompter._clear_missed_alert.__get__(f)
    f._notify_timer = main_mod.FastPrompter._notify_timer.__get__(f)
    f._ack_missed = main_mod.FastPrompter._ack_missed.__get__(f)
    f._play_timer_sound = main_mod.FastPrompter._play_timer_sound.__get__(f)
    f._snooze_timer = main_mod.FastPrompter._snooze_timer.__get__(f)
    f._load_missed_ids()
    return f


def _oneshot():
    import datetime as _dt
    past = _dt.datetime.now() - _dt.timedelta(minutes=1)
    t = Timer("ev", past, repeat="once", sound="tick", volume=0.5)
    t.fired = True  # a one-shot that already went off
    return t


def test_fire_persists_id(monkeypatch):
    from fastprompter.ui import timer_toast as tt
    monkeypatch.setattr(tt, "show_toast", lambda *a, **k: object())
    t = _oneshot()
    f = _make_fake(timers=[t])
    f._notify_timer(t, fired_at=__import__("datetime").datetime.now())
    assert t.id in f._missed_timer_ids
    assert f.data.get("missed_timer_ids") == [t.id]


def test_reload_survives_restart():
    t = _oneshot()
    f1 = _make_fake(timers=[t])
    f1._missed_timer_ids.add(t.id)
    f1._persist_missed_ids()
    raw = f1.data["missed_timer_ids"]
    # reopen with the persisted list and the same timer present
    f2 = _make_fake(data={"missed_timer_ids": raw}, timers=[t])
    assert f2._missed_attention() == [t]


def test_foreign_or_missing_timer_pruned_on_load():
    t = _oneshot()
    # data carries an id with no matching timer -> must be dropped on load
    f = _make_fake(data={"missed_timer_ids": [t.id]}, timers=[])
    assert f._missed_timer_ids == set()


def test_ack_removes_and_persists():
    t = _oneshot()
    f = _make_fake(timers=[t])
    f._missed_timer_ids.add(t.id)
    f._persist_missed_ids()
    f._ack_missed(t)
    assert t.id not in f._missed_timer_ids
    assert f.data["missed_timer_ids"] == []


def test_disable_prunes_on_save():
    t = _oneshot()
    f = _make_fake(timers=[t])
    f._missed_timer_ids.add(t.id)
    f._persist_missed_ids()
    t.enabled = False
    f.save_timers_to_data()
    assert t.id not in f._missed_timer_ids
    assert f.data.get("missed_timer_ids") == []


def test_repeating_never_missed(monkeypatch):
    from fastprompter.ui import timer_toast as tt
    monkeypatch.setattr(tt, "show_toast", lambda *a, **k: object())
    import datetime as _dt
    t = Timer("rep", _dt.datetime.now(), repeat="daily",
              sound="tick", volume=0.5)
    f = _make_fake(timers=[t])
    f._notify_timer(t, fired_at=_dt.datetime.now())
    assert t.id not in f._missed_timer_ids


def test_open_timer_dialog_clears_missed_alert(monkeypatch):
    t = _oneshot()
    f = _make_fake(timers=[t])
    f._clear_missed_alert = main_mod.FastPrompter._clear_missed_alert.__get__(f)
    f._increment_focus_lock = lambda: None
    f._decrement_focus_lock = lambda: None
    f.save_productivity_timer = lambda: None
    f.open_timer_dialog = main_mod.FastPrompter.open_timer_dialog.__get__(f)

    f._missed_timer_ids.add(t.id)
    f._persist_missed_ids()
    assert f.data.get("missed_timer_ids") == [t.id]

    class _MockDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0

    from fastprompter.ui import timer_dialog
    monkeypatch.setattr(timer_dialog, "TimerDialog", _MockDialog)

    f.open_timer_dialog()
    assert t.id not in f._missed_timer_ids
    assert f.data.get("missed_timer_ids") == []


def test_timer_dialog_direct_init_clears_missed_alert(qapp):
    t = _oneshot()
    f = _make_fake(timers=[t])
    f._clear_missed_alert = main_mod.FastPrompter._clear_missed_alert.__get__(f)
    f._missed_timer_ids.add(t.id)
    f._persist_missed_ids()
    assert f.data.get("missed_timer_ids") == [t.id]

    from fastprompter.ui.timer_dialog import TimerDialog
    dlg = TimerDialog(f)
    try:
        assert t.id not in f._missed_timer_ids
        assert f.data.get("missed_timer_ids") == []
    finally:
        dlg.close()
