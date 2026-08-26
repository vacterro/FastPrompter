"""PERF-001 regression: save_productivity_timer / save_timers_to_data must be
change-aware — a no-op (countdown-only) update must not mark settings dirty.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.pomodoro import ProductivityTimer  # noqa: E402
from fastprompter.core.timers import Timer, save_timers  # noqa: E402


class _Fake:
    def __init__(self):
        self.data = {}
        self.productivity_timer = ProductivityTimer(work_seconds=5, break_seconds=5)
        # seed so the first save is also a no-op
        self.data["productivity_timer"] = self.productivity_timer.to_dict()
        self.timers = [Timer("a", __import__("datetime").datetime.now(),
                             repeat="once", sound="tick", volume=0.5)]
        self.data["timers"] = save_timers(self.timers)
        self.dirty = 0

    def mark_dirty(self, *a, **k):
        self.dirty += 1

    def save_productivity_timer(self):
        main_mod.FastPrompter.save_productivity_timer.__get__(self)()

    def save_timers_to_data(self):
        main_mod.FastPrompter.save_timers_to_data.__get__(self)()


def test_productivity_noop_no_dirty():
    f = _Fake()
    for _ in range(600):
        f.save_productivity_timer()
    assert f.dirty == 0


def test_productivity_real_change_dirties_once():
    f = _Fake()
    f.productivity_timer.volume = 0.9      # a real change
    f.save_productivity_timer()
    assert f.dirty == 1
    # second identical save is a no-op
    f.save_productivity_timer()
    assert f.dirty == 1


def test_timers_noop_no_dirty():
    f = _Fake()
    for _ in range(600):
        f.save_timers_to_data()
    assert f.dirty == 0


def test_timers_real_change_dirties_once():
    f = _Fake()
    f.timers[0].name = "renamed"
    f.save_timers_to_data()
    assert f.dirty == 1
    f.save_timers_to_data()
    assert f.dirty == 1
