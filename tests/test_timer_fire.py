"""T-1007 fire-path tests: notification / top-bar / sound policy on the real
``_notify_timer`` and ``test_timer_notification`` logic, without building the
whole FastPrompter window.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.timer_toast as toast_mod  # noqa: E402
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.core.timers import (  # noqa: E402
    KIND_CALENDAR,
    REPEAT_DAILY,
    REPEAT_NONE,
    SOUND_MODE_POOL,
    Timer,
)

_APP = QApplication.instance() or QApplication([])


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *a):
        self.messages.append(a)

    def icon(self):
        return None


class _FakeFire(QWidget):
    """QWidget so Test-notification jobs can be parented to it, like the
    real main window."""

    def __init__(self):
        super().__init__()
        self.data = {"sound_volume": "5", "sound_ui": "False", "theme": "Default"}
        self.sound_manager = SoundManager(None, self.data)
        self.timers = []
        self._current_lang = "EN"
        self.tray_icon = _Tray()
        self.saved = 0
        self._toasts = []
        self._sound_calls = []
        self._timer_test_jobs = {}

    def save_timers_to_data(self):
        self.saved += 1

    def _tick_productivity(self):
        pass

    def _snooze_timer(self, timer, minutes):
        pass

    def _play_spy(self, ref, level):
        self._sound_calls.append((ref, level))
        return self.sound_manager.play_sound_ref(ref, level)

    def _update_date_label(self):
        pass


def _bind(fake):
    # Lazy: importing fastprompter.main at module level caches the real
    # sound_manager BEFORE test_sound_manager's stub-import, which makes its
    # real-QObject classes collide with _MockQObject in combined runs.
    import fastprompter.main as main_mod  # noqa: PLC0415

    fake._notify_timer = main_mod.FastPrompter._notify_timer.__get__(fake)
    fake._check_timers = main_mod.FastPrompter._check_timers.__get__(fake)
    fake._play_timer_sound = main_mod.FastPrompter._play_timer_sound.__get__(fake)
    fake.test_timer_notification = \
        main_mod.FastPrompter.test_timer_notification.__get__(fake)
    fake._fire_timer_test_job = \
        main_mod.FastPrompter._fire_timer_test_job.__get__(fake)
    fake._cancel_timer_test_jobs = \
        main_mod.FastPrompter._cancel_timer_test_jobs.__get__(fake)
    fake._snooze_timer = main_mod.FastPrompter._snooze_timer.__get__(fake)
    def spy(ref, level):
        fake._sound_calls.append((ref, level))
        return True

    fake.sound_manager.play_sound_ref = spy
    return fake


def _patch_toast(monkeypatch, truthy=True):
    seen = []

    def fake(main_win, timer, on_snooze=None, on_dismiss=None):
        seen.append(timer)
        return object() if truthy else None

    monkeypatch.setattr(toast_mod, "show_toast", fake)
    return seen


def _retire(fake, foreign=None):
    """Give back everything this fake owns: jobs, widget, queued deletions.

    T-1260: ``_FakeFire`` is a real QWidget parenting real QTimers, and every
    test built one and walked away. The widgets stayed alive on the module's
    QApplication with their jobs still armed, so a later test could be running
    inside somebody else's leftover event-loop traffic -- which is how the fire
    test passed alone and failed in a full run.
    """
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent, QTimer

    owned_timers = list(fake.findChildren(QTimer))
    try:
        fake._cancel_timer_test_jobs()
    except Exception:
        pass
    assert fake._timer_test_jobs == {}, "test job registry not retired"
    fake.close()
    fake.deleteLater()
    # Receiver-scoped: only this fake's DeferredDelete is delivered. A
    # process-wide drain can destroy unrelated Qt wrappers held by another
    # test and turn a harmless cleanup into a native crash.
    QApplication.sendPostedEvents(fake, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert sip.isdeleted(fake), "fake QWidget survived scoped retirement"
    assert all(sip.isdeleted(timer) for timer in owned_timers), \
        "fake-owned QTimer survived scoped retirement"
    if foreign is not None:
        assert not sip.isdeleted(foreign), "retirement deleted foreign QObject"


@pytest.fixture()
def fire():
    """A bound ``_FakeFire`` that starts clean and is retired afterwards."""
    fake = _bind(_FakeFire())
    assert fake._timer_test_jobs == {}
    try:
        yield fake
    finally:
        _retire(fake)


def _wait_until(predicate, timeout_ms=5000):
    """Spin the REAL Qt event loop until ``predicate()`` or the watchdog fires.

    Condition-driven, not speed-assumed: it returns the moment the job is
    observed, and the watchdog bounds the failure case instead of trading
    correctness for a longer sleep.

    Deliberately ``QTest.qWait`` and NOT a nested ``QEventLoop.exec()``.
    ``exec()`` is a full event loop: it delivers DeferredDelete to every
    receiver in the process, so this wait would retire Qt objects other test
    files still own -- the same hazard as
    ``sendPostedEvents(None, DeferredDelete)``, only spelled differently. In
    the full run that took the interpreter down from inside this function
    ("Fatal Python error: Aborted", 75%). ``qWait`` pumps ``processEvents``,
    which does NOT deliver DeferredDelete, so the timer under test still fires
    through the real scheduler and nobody else's objects are touched.
    """
    import time as _clock

    from PyQt6.QtTest import QTest

    deadline = _clock.monotonic() + timeout_ms / 1000.0
    while True:
        if predicate():
            return True
        if _clock.monotonic() >= deadline:
            return predicate()
        QTest.qWait(5)


def test_notify_on_plays_sound_and_shows_toast(monkeypatch, fire):
    fake = fire
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound="tick", volume=0.7)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen and seen[0] is t
    assert fake._sound_calls == [("tick", 0.7)]


def test_notify_off_no_toast_no_tray_but_sound(monkeypatch, fire):
    fake = fire
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound="tick", volume=0.7,
              show_notification=False)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen == []                       # no popup
    assert fake.tray_icon.messages == []    # no tray fallback either
    assert fake._sound_calls == [("tick", 0.7)]  # sound still plays


def test_global_sound_settings_not_mutated(monkeypatch, fire):
    fake = fire
    _patch_toast(monkeypatch, truthy=True)
    before = dict(fake.data)
    t = Timer("a", datetime.datetime.now(), sound="notify", volume=0.9)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert fake.data == before             # sound_ui/volume untouched


def test_pool_silent_still_notifies(monkeypatch, fire):
    fake = fire
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("a", datetime.datetime.now(), sound_mode=SOUND_MODE_POOL,
              sound_rules=[{"sound": "tick", "enabled": True, "all_day": False,
                            "start_minute": 360, "end_minute": 720}])
    # fire at 18:00 -> no eligible pool rule -> silent, but not notified-off
    fake._notify_timer(t, fired_at=datetime.datetime(2026, 7, 21, 18, 0))
    assert seen and seen[0] is t
    assert fake._sound_calls == []          # no sound chosen


def test_check_timers_fires_alarm_and_calendar(monkeypatch, fire):
    fake = fire
    _patch_toast(monkeypatch, truthy=True)
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    fake.timers = [
        Timer("alarm", now - datetime.timedelta(seconds=1),
              kind="alarm", show_notification=True),
        Timer("cal", now - datetime.timedelta(seconds=1),
              kind=KIND_CALENDAR, show_notification=True),
    ]
    fired = fake.timers
    from fastprompter.core.timers import collect_due
    due = collect_due(fired, now)
    for t in due:
        fake._notify_timer(t, fired_at=now)
    assert len(due) == 2
    assert {t.kind for t in due} == {"alarm", KIND_CALENDAR}


def test_hidden_from_topbar_still_fires(monkeypatch):
    """show_in_top_bar=False must not suppress firing."""
    from fastprompter.core.timers import collect_due, next_due
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    hidden = Timer("hidden", now - datetime.timedelta(seconds=1),
                   show_in_top_bar=False)
    assert collect_due([hidden], now) == [hidden]      # fires anyway
    assert next_due([hidden], now, topbar_only=True) is None


def test_missing_sound_ref_scheduler_survives(monkeypatch, fire):
    fake = fire
    seen = _patch_toast(monkeypatch, truthy=True)
    t = Timer("gone", datetime.datetime.now(), sound="file:no_such.wav",
              volume=0.5)
    fake._notify_timer(t, fired_at=datetime.datetime.now())
    assert seen and seen[0] is t           # visual path unaffected
    assert fake._sound_calls == [("file:no_such.wav", 0.5)]


def test_test_notification_deep_copies_behavior(fire):
    fake = fire
    t = Timer("orig", datetime.datetime.now(), sound="notify", volume=0.3,
              sound_mode=SOUND_MODE_POOL,
              sound_rules=[{"sound": "tick", "enabled": True, "all_day": True,
                            "volume": None, "start_minute": 0, "end_minute": 0}],
              show_notification=False, color_mode="static", color="#123456")
    probe = fake.test_timer_notification(t, delay_seconds=1)
    assert probe.show_notification is False
    assert probe.sound_mode == SOUND_MODE_POOL
    assert probe.sound_rules == t.sound_rules
    assert probe.sound_rules is not t.sound_rules
    assert probe.color == "#123456"


# ---- second wave: snooze ownership/clones, test-job lifecycle, isolation ---

def test_snooze_repeating_creates_one_shot_clone_and_keeps_series(fire):
    fake = fire
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    t = Timer("daily", now - datetime.timedelta(seconds=1),
              repeat=REPEAT_DAILY, sound_mode=SOUND_MODE_POOL,
              sound_rules=[{"sound": "bells", "enabled": True}])
    from fastprompter.core.timers import collect_due
    collect_due([t], now)                    # fired -> advanced to next day
    series_target = t.target
    fake.timers = [t]
    fake._snooze_timer(t, 10)
    assert len(fake.timers) == 2             # original + one-shot reminder
    clone = fake.timers[1]
    assert clone.repeat == REPEAT_NONE
    assert clone.id != t.id
    assert clone.target > now                # this occurrence, now + 10m
    assert t.target == series_target         # series NOT shifted
    assert fake.saved == 1


def test_snooze_one_shot_rearms_legacy(fire):
    fake = fire
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    t = Timer("once", now - datetime.timedelta(seconds=1))
    t.fired = True
    fake.timers = [t]
    fake._snooze_timer(t, 10)
    assert len(fake.timers) == 1             # no clone for one-shot
    assert t.target > now
    assert t.fired is False


def test_snooze_refuses_timer_not_owned_by_current_profile(fire):
    fake = fire
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    stale = Timer("old-profile", now - datetime.timedelta(seconds=1))
    stale.fired = True
    live = Timer("live", now + datetime.timedelta(hours=1))
    fake.timers = [live]
    saved_before = fake.saved
    fake._snooze_timer(stale, 10)
    assert len(fake.timers) == 1             # nothing appended, nothing moved
    assert fake.saved == saved_before
    assert stale.fired is True               # not re-armed either


def test_check_timers_isolates_one_bad_timer(fire):
    fake = fire
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    bad = Timer("bad", now - datetime.timedelta(seconds=1))
    good = Timer("good", now - datetime.timedelta(seconds=1))
    fake.timers = [bad, good]
    fired = []

    def notify(t, fired_at=None):
        if t is bad:
            raise RuntimeError("boom")
        fired.append(t)

    fake._notify_timer = notify
    fake._check_timers()                     # one raise must not eat the batch
    assert fired == [good]


def test_check_timers_still_saves_when_a_timer_raises(fire):
    fake = fire
    now = datetime.datetime(2026, 7, 21, 12, 0, 0)
    fake.timers = [Timer("bad", now - datetime.timedelta(seconds=1))]
    fake._notify_timer = lambda t, fired_at=None: (_ for _ in ()).throw(
        RuntimeError("boom"))
    fake._check_timers()
    assert fake.saved == 1                   # the due-batch save still ran


def test_test_notification_job_is_registered_and_fires(fire):
    """The REAL QTimer path, waited on by CONDITION rather than by clock.

    T-1260: the old shape waited a flat 150 ms, which is generous on an idle
    machine and a coin flip when the whole suite shares this event loop. The
    wait now quits the instant ``_notify_timer`` is observed, with a watchdog
    bounding the failure; a short bounded window afterwards still gives a
    DUPLICATE fire room to land, so "exactly once" keeps its meaning.
    """
    from PyQt6.QtTest import QTest

    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3,
              show_notification=False)
    seen = []
    fire._notify_timer = lambda timer, fired_at=None: seen.append(timer)
    fire.test_timer_notification(t, delay_seconds=0.05)
    assert len(fire._timer_test_jobs) == 1

    assert _wait_until(lambda: bool(seen)), "test job never fired"
    QTest.qWait(150)                         # let a duplicate land if it exists

    assert len(seen) == 1                    # fired exactly once
    assert seen[0].name == "probe"
    assert seen[0].volume == 0.3
    assert seen[0].show_notification is False
    assert fire._timer_test_jobs == {}       # and retired from the registry


def test_the_job_still_fires_exactly_once_behind_queued_traffic(fire):
    """T-1260 contaminator regression: a busy event loop changes nothing.

    Unrelated queued callbacks in front of the job used to be exactly the
    condition the flat wait could not survive. The scheduling integration is
    still the real QTimer -- ``_fire_timer_test_job`` is never called directly,
    or this would stop testing the thing that broke.
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtTest import QTest

    noise = []
    for i in range(200):
        QTimer.singleShot(0, lambda i=i: noise.append(i))

    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3,
              show_notification=False)
    seen = []
    fire._notify_timer = lambda timer, fired_at=None: seen.append(timer)
    fire.test_timer_notification(t, delay_seconds=0.05)

    assert _wait_until(lambda: bool(seen)), "test job never fired"
    QTest.qWait(150)

    assert len(seen) == 1
    assert fire._timer_test_jobs == {}
    assert len(noise) == 200                 # the noise really did run


def test_a_retired_fake_leaves_no_jobs_behind():
    """Leak sentinel: retiring a fake empties its registry, every time."""
    fake = _bind(_FakeFire())
    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3)
    for _ in range(3):
        fake.test_timer_notification(t, delay_seconds=5)
    assert len(fake._timer_test_jobs) == 3
    _retire(fake)
    assert fake._timer_test_jobs == {}


def test_scoped_retirement_leaves_foreign_pending_qobject_alive():
    """The fake cleanup must not drain another QObject's DeferredDelete."""
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent

    fake = _bind(_FakeFire())
    foreign = QWidget()
    foreign.deleteLater()
    try:
        _retire(fake, foreign)
        assert not sip.isdeleted(foreign)
    finally:
        QApplication.sendPostedEvents(foreign, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(foreign)


def test_test_notification_jobs_cancelled_on_shutdown(fire):
    fake = fire
    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3)
    seen = []
    fake._notify_timer = lambda timer, fired_at=None: seen.append(timer)
    fake.test_timer_notification(t, delay_seconds=0.05)
    fake.test_timer_notification(t, delay_seconds=0.05)
    assert len(fake._timer_test_jobs) == 2
    fake._cancel_timer_test_jobs()
    assert fake._timer_test_jobs == {}
    from PyQt6.QtTest import QTest
    QTest.qWait(200)
    assert seen == []                        # nothing fired after the cancel


def test_test_notification_stale_profile_never_fires(fire):
    fake = fire
    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3)
    seen = []
    fake._notify_timer = lambda timer, fired_at=None: seen.append(timer)
    fake.test_timer_notification(t, delay_seconds=0.05)
    fake.data = {"sound_volume": "5", "sound_ui": "False", "theme": "Default"}
    from PyQt6.QtTest import QTest
    QTest.qWait(200)
    assert seen == []                        # profile moved on -> job dropped
    assert fake._timer_test_jobs == {}


def test_test_notification_hundred_jobs_cancel_clean(fire):
    fake = fire
    t = Timer("probe", datetime.datetime.now(), sound="notify", volume=0.3)
    for _ in range(100):
        fake.test_timer_notification(t, delay_seconds=0.05)
    assert len(fake._timer_test_jobs) == 100
    fake._cancel_timer_test_jobs()
    assert fake._timer_test_jobs == {}
    from PyQt6.QtTest import QTest
    QTest.qWait(200)                         # nothing still queued to fire
