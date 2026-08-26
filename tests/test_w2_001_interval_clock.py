"""W2-001 regression: interval clock scheduling must fire on the clock boundary
for ANY interval (45m, 90m, ...), not just divisors of 60, and must fire once
even when the 1Hz tick is delayed past second==0 (boundary crossing, not the
second==0 sample).
"""

import os
import sys
import time as _time_mod
import datetime as _dt_mod

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402

RealDateTime = _dt_mod.datetime  # captured before any patching


class _Sound:
    def __init__(self):
        self.calls = []

    def play_sound_ref(self, ref, vol):
        self.calls.append((ref, vol))
        return True


class _Fake:
    def __init__(self, rules):
        self.data = {"interval_notifs": rules}
        self.sound_manager = _Sound()
        self._current_lang = "EN"
        self.fired = []

    def _interval_notifs(self):
        return self.data["interval_notifs"]

    def _fire_interval_notif(self, rule):
        self.fired.append(rule.get("id"))
        main_mod.FastPrompter._fire_interval_notif.__get__(self)(rule)

    def mark_dirty(self):
        pass


def _bind(fake):
    fake._check_interval_notifs = \
        main_mod.FastPrompter._check_interval_notifs.__get__(fake)
    return fake


def _rule(rid, minutes, **kw):
    r = {
        "id": rid, "name": rid, "minutes": minutes, "enabled": True,
        "sound": "newday", "volume": 0.5, "show_notification": False,
        "show_in_top_bar": False, "align_mode": "clock", "all_day": True,
        "start_minute": 0, "end_minute": 1439,
    }
    r.update(kw)
    return r


# controlled clock
_CLOCK = {"dt": RealDateTime(2026, 1, 1, 0, 0, 0), "ts": 1000.0}


class _FakeDateTime:
    @staticmethod
    def now():
        return _CLOCK["dt"]


def _set(now_dt):
    _CLOCK["dt"] = now_dt


def _patch(monkeypatch):
    monkeypatch.setattr(_dt_mod, "datetime", _FakeDateTime)
    monkeypatch.setattr(_time_mod, "time", lambda: _CLOCK["ts"])


def _mdt(h, m, s=0):
    return RealDateTime(2026, 1, 1, h, m, s)


def test_45m_clock_fires_on_boundary(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("r45", 45)]))
    # at 00:45 -> boundary, fires once
    _set(_mdt(0, 45))
    fake._check_interval_notifs()
    assert "r45" in fake.fired
    # same minute again -> no duplicate
    fake.fired.clear()
    fake._check_interval_notifs()
    assert fake.fired == []
    # at 01:30 (minute_of_day 90) -> next boundary, fires again
    _set(_mdt(1, 30))
    fake._check_interval_notifs()
    assert "r45" in fake.fired


def test_delayed_tick_still_fires(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("r15", 15)]))
    # 14:00:00 missed; tick arrives at 14:00:05 -> must still fire once
    _set(_mdt(14, 0, 5))
    fake._check_interval_notifs()
    assert "r15" in fake.fired
    fake.fired.clear()
    fake._check_interval_notifs()   # same minute, no storm
    assert fake.fired == []


def test_60m_only_at_minute_zero(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("r60", 60)]))
    # 14:15 is not a boundary for a 60m rule
    _set(_mdt(14, 15))
    fake._check_interval_notifs()
    assert fake.fired == []
    # 15:00 is a boundary
    _set(_mdt(15, 0))
    fake._check_interval_notifs()
    assert "r60" in fake.fired


def test_120m_every_two_hours(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("r120", 120)]))
    _set(_mdt(2, 0))
    fake._check_interval_notifs()
    assert "r120" in fake.fired
    fake.fired.clear()
    _set(_mdt(3, 0))   # not a 120 boundary
    fake._check_interval_notifs()
    assert fake.fired == []
    _set(_mdt(4, 0))
    fake._check_interval_notifs()
    assert "r120" in fake.fired


def test_over_24h_covers_midnight(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("rbig", 1500)]))
    _set(_mdt(0, 0))
    fake._check_interval_notifs()
    assert "rbig" in fake.fired
    fake.fired.clear()
    _set(_mdt(12, 0))
    fake._check_interval_notifs()
    assert fake.fired == []   # not a boundary for >24h


def test_elapsed_mode_unchanged(monkeypatch):
    _patch(monkeypatch)
    fake = _bind(_Fake([_rule("rel", 1, align_mode="elapsed")]))
    _CLOCK["ts"] = 1000.0
    _set(_mdt(0, 0))
    fake._check_interval_notifs()   # seeds last_fired, no fire
    assert fake.fired == []
    _CLOCK["ts"] = 1000.0 + 61.0    # > 60s later
    _set(_mdt(0, 1))
    fake._check_interval_notifs()
    assert "rel" in fake.fired
