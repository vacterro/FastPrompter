"""W2-004 regression: interval_notifs must heal malformed entries at the decode
boundary — drop non-dicts, fix minutes/bools/alignment/bounds/volume/strings,
collapse duplicate ids, and round-trip to canonical JSON. _check_interval_notifs
must not loop on a bad list.
"""

import os
import sys
import time as _time_mod
import datetime as _dt_mod
import json as _json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402

RealDateTime = _dt_mod.datetime


class _Sound:
    def play_sound_ref(self, *a, **k):
        return True


class _Fake:
    def __init__(self, data):
        self.data = data
        self.sound_manager = _Sound()
        self._current_lang = "EN"
        self.fired = []

    def _interval_notifs(self):
        return main_mod.FastPrompter._interval_notifs.__get__(self)()

    def _heal_interval_rule(self, rule):
        return main_mod.FastPrompter._heal_interval_rule.__get__(self)(rule)

    def _check_interval_notifs(self):
        return main_mod.FastPrompter._check_interval_notifs.__get__(self)()

    def _fire_interval_notif(self, rule):
        self.fired.append(rule.get("id"))

    def mark_dirty(self, *a, **k):
        pass


_CLOCK = {"dt": RealDateTime(2026, 1, 1, 0, 0, 0), "ts": 1000.0}


class _FakeDateTime:
    @staticmethod
    def now():
        return _CLOCK["dt"]


def _patch(monkeypatch):
    monkeypatch.setattr(_dt_mod, "datetime", _FakeDateTime)
    monkeypatch.setattr(_time_mod, "time", lambda: _CLOCK["ts"])


def test_non_dict_dropped():
    f = _Fake({"interval_notifs": [42, "junk", {"minutes": 30}]})
    healed = f._interval_notifs()
    assert all(isinstance(r, dict) for r in healed)
    assert len(healed) == 1
    assert healed[0]["minutes"] == 30


def test_fields_healed():
    r = {
        "id": "r1", "minutes": "45", "enabled": "true", "all_day": 0,
        "align_mode": "bogus", "start_minute": "100", "end_minute": 9999,
        "volume": 5, "sound": "newday", "name": 123,
    }
    h = _Fake({})._heal_interval_rule(r)
    assert h["minutes"] == 45
    assert h["enabled"] is True
    assert h["all_day"] is False
    assert h["align_mode"] == "clock"
    assert h["start_minute"] == 100
    assert h["end_minute"] == 1439
    assert h["volume"] == 0.5            # legacy 5 -> 0.5
    assert h["name"] == "Interval"       # non-string name -> default


def test_missing_id_generated():
    h = _Fake({})._heal_interval_rule({"minutes": 15})
    assert isinstance(h["id"], str) and h["id"]


def test_duplicate_ids_collapsed():
    f = _Fake({"interval_notifs": [
        {"id": "dup", "minutes": 15},
        {"id": "dup", "minutes": 30},
        {"id": "ok", "minutes": 45},
    ]})
    healed = f._interval_notifs()
    ids = [r["id"] for r in healed]
    assert ids == ["dup", "ok"]          # first dup wins, no cross-edit
    assert healed[0]["minutes"] == 15


def test_roundtrip_canonical_json():
    f = _Fake({"interval_notifs": [
        {"minutes": "45", "volume": "0.5", "enabled": "1"},
        99,
        {"id": "x", "align_mode": "elapsed", "start_minute": "700",
         "end_minute": "800"},
    ]})
    healed = f._interval_notifs()
    blob = _json.dumps(healed, sort_keys=True)
    reloaded = _json.loads(blob)
    f2 = _Fake({"interval_notifs": reloaded})
    healed2 = f2._interval_notifs()
    assert len(healed2) == 2
    assert all(isinstance(r, dict) for r in healed2)


def test_check_no_exception_on_malformed(monkeypatch):
    _patch(monkeypatch)
    _CLOCK["dt"] = RealDateTime(2026, 1, 1, 0, 7, 0)   # no boundary this minute
    f = _Fake({"interval_notifs": [
        99, "bad", {"minutes": 15}, {"minutes": "oops", "id": "z"},
        {"id": "a", "minutes": 60},
    ]})
    # must not raise; only valid rules present, none fire this minute
    f._check_interval_notifs()
    assert f.fired == []
