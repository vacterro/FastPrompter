"""W2-006 regression: a toast may only advertise actions the runtime accepts.

Test probes (never added to self.timers) and delete-after-fire Temp timers must
not register orphan missed-attention IDs nor receive a Snooze callback;
TimerToast must render no Snooze buttons when on_snooze is not callable.
Owned persistent one-shots keep both.
"""

import os
import sys
import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.timers import Timer  # noqa: E402


class _Sound:
    def play_sound_ref(self, ref, vol):
        return True


class _Fake:
    def __init__(self, timers=None):
        self.timers = timers if timers is not None else []
        self._missed_timer_ids = set()
        self.sound_manager = _Sound()
        self._persisted = []

    def _play_timer_sound(self, timer, fired_at=None):
        return True

    def _persist_missed_ids(self):
        self._persisted.append(sorted(self._missed_timer_ids))

    def _snooze_timer(self, timer, minutes):
        pass


def _mk(name, **kw):
    kw.setdefault("repeat", 0)  # one-shot
    kw.setdefault("show_notification", True)
    return Timer(name, datetime.datetime.now() + datetime.timedelta(hours=1), **kw)


def test_probe_registers_no_missed_and_no_snooze():
    fake = _Fake(timers=[])
    probe = _mk("probe")
    fake._notify_timer = main_mod.FastPrompter._notify_timer.__get__(fake)
    calls = {}
    fake.show_toast_calls = []
    import fastprompter.ui.timer_toast as tt

    def spy(self_, timer, on_snooze=None, on_dismiss=None):
        calls["snooze"] = on_snooze
        return None

    orig = tt.show_toast
    tt.show_toast = spy
    try:
        fake._notify_timer(probe)
    finally:
        tt.show_toast = orig
    assert fake._missed_timer_ids == set(), "probe must not add orphan missed IDs"
    assert calls.get("snooze") is None, "probe toast must have no snooze callback"


def test_delete_after_fire_temp_no_snooze_no_missed():
    fake = _Fake(timers=[])
    t = _mk("temp", temporary=True, delete_after_fire=True)
    # delete-after-fire timers are still owned at notify time (removed after)
    fake.timers = [t]
    fake._notify_timer = main_mod.FastPrompter._notify_timer.__get__(fake)
    calls = {}
    import fastprompter.ui.timer_toast as tt

    def spy(self_, timer, on_snooze=None, on_dismiss=None):
        calls["snooze"] = on_snooze
        return None

    orig = tt.show_toast
    tt.show_toast = spy
    try:
        fake._notify_timer(t)
    finally:
        tt.show_toast = orig
    assert calls.get("snooze") is None, \
        "delete-after-fire must not advertise a Snooze it would reject"
    assert fake._missed_timer_ids == set(), \
        "delete-after-fire must not accumulate missed attention"


def test_owned_one_shot_keeps_snooze_and_missed():
    fake = _Fake(timers=[])
    t = _mk("owned")
    fake.timers = [t]
    fake._notify_timer = main_mod.FastPrompter._notify_timer.__get__(fake)
    calls = {}
    import fastprompter.ui.timer_toast as tt

    def spy(self_, timer, on_snooze=None, on_dismiss=None):
        calls["snooze"] = on_snooze
        return None

    orig = tt.show_toast
    tt.show_toast = spy
    try:
        fake._notify_timer(t)
    finally:
        tt.show_toast = orig
    assert calls.get("snooze") is not None, "owned one-shot keeps its Snooze"
    assert t.id in fake._missed_timer_ids, "owned one-shot registers missed"


def test_toast_renders_no_snooze_buttons_without_callback():
    from fastprompter.ui.timer_toast import TimerToast, _SNOOZE_CHOICES
    from PyQt6.QtWidgets import QApplication, QPushButton
    _APP = QApplication.instance() or QApplication([])

    class Win:
        _current_lang = "EN"

        def geometry(self):
            from PyQt6.QtCore import QRect
            return QRect(0, 0, 100, 100)

    no_cb = TimerToast(Win(), _mk("no-snooze"), on_snooze=None)
    btns = [b for b in no_cb.findChildren(QPushButton)
            if b.text() in {f"+{m}m" for m in _SNOOZE_CHOICES}]
    assert btns == [], "no Snooze buttons when on_snooze is None"
    no_cb.close()

    with_cb = TimerToast(Win(), _mk("with-snooze"), on_snooze=lambda t, m: None)
    btns2 = [b for b in with_cb.findChildren(QPushButton)
             if b.text() in {f"+{m}m" for m in _SNOOZE_CHOICES}]
    assert len(btns2) == len(_SNOOZE_CHOICES), "Snooze buttons render when callable"
    with_cb.close()


def test_snooze_guard_refuses_unowned():
    fake = _Fake(timers=[])
    stale = _mk("stale")
    fake._snooze_timer = main_mod.FastPrompter._snooze_timer.__get__(fake)
    fake.save_timers_to_data = lambda: None
    fake._update_date_label = lambda: None
    fake._snooze_timer(stale, 5)  # not in self.timers -> no-op, no crash
    assert fake.timers == []
