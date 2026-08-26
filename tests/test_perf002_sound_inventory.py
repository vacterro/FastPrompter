"""PERF-002 regression: the sound-choice inventory is built once per dialog and
shared by every selector, so the sound library is scanned a single time.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.timer_dialog as td_mod  # noqa: E402


class _CountingSound:
    def __init__(self, files):
        self._files = files
        self.calls = 0

    def get_available_sounds(self):
        self.calls += 1
        return list(self._files)


class _FakeDialog:
    def __init__(self, files):
        self.main_win = type("M", (), {})()
        self.main_win.sound_manager = _CountingSound(files)
        self.main_win.data = {}
        self._sound_inventory_cache = None

    def _sound_inventory(self):
        return td_mod.TimerDialog._sound_inventory.__get__(self)()


def test_inventory_built_once():
    files = ["a.wav", "b.wav"]
    d = _FakeDialog(files)
    first = d._sound_inventory()
    second = d._sound_inventory()
    # single scan of the library
    assert d.main_win.sound_manager.calls == 1
    # identical content, independent of call count
    assert first is second or first == second
    # named events + files present
    names = [disp for disp, ref in first]
    for f in files:
        assert f in names
    assert "tick" in names


def test_inventory_independent_per_dialog():
    d1 = _FakeDialog(["x.wav"])
    d2 = _FakeDialog(["y.wav", "z.wav"])
    i1 = d1._sound_inventory()
    i2 = d2._sound_inventory()
    # different dialogs do not share a process-lifetime cache
    assert [r for _, r in i1] != [r for _, r in i2]
    assert d1.main_win.sound_manager.calls == 1
    assert d2.main_win.sound_manager.calls == 1
