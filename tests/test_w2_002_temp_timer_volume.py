"""W2-002 regression: Temp Timer volume must stay a 0.0-1.0 float, never
int()-truncated. Legacy 0-10 values are healed on read; canonical floats pass
through; malformed falls back to 0.5.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402


class _Fake:
    def __init__(self, settings=None):
        self.data = {"temp_timer_settings": settings or {}}
        self.timers = []

    def _temp_timer(self):
        return next((t for t in self.timers
                     if getattr(t, "temporary", False)), None)

    def mark_dirty(self, *a, **k):
        pass

    def save_timers_to_data(self):
        pass

    def _update_timer_label(self):
        pass

    def play_sound(self, *a, **k):
        pass


def _bind(fake):
    fake.temp_timer_template = \
        main_mod.FastPrompter.temp_timer_template.__get__(fake)
    fake.configure_temp_timer = \
        main_mod.FastPrompter.configure_temp_timer.__get__(fake)
    fake.add_temp_timer = main_mod.FastPrompter.add_temp_timer.__get__(fake)
    return fake


def test_template_float_volume_preserved():
    fake = _bind(_Fake({"volume": 0.5}))
    assert fake.temp_timer_template()["volume"] == 0.5

    fake = _bind(_Fake({"volume": 0.05}))
    assert fake.temp_timer_template()["volume"] == 0.05

    fake = _bind(_Fake({"volume": 1.0}))
    assert fake.temp_timer_template()["volume"] == 1.0

    fake = _bind(_Fake({"volume": 0.0}))
    assert fake.temp_timer_template()["volume"] == 0.0


def test_template_legacy_volume_healed():
    fake = _bind(_Fake({"volume": 5}))        # legacy 5 -> 0.5
    assert fake.temp_timer_template()["volume"] == 0.5
    fake = _bind(_Fake({"volume": "5"}))
    assert fake.temp_timer_template()["volume"] == 0.5
    fake = _bind(_Fake({"volume": 10}))       # legacy 10 -> 1.0
    assert fake.temp_timer_template()["volume"] == 1.0


def test_template_string_canonical():
    fake = _bind(_Fake({"volume": "0.50"}))
    assert fake.temp_timer_template()["volume"] == 0.5
    fake = _bind(_Fake({"volume": "0.05"}))
    assert fake.temp_timer_template()["volume"] == 0.05


def test_template_malformed_falls_back():
    fake = _bind(_Fake({"volume": "garbage"}))
    assert fake.temp_timer_template()["volume"] == 0.5
    fake = _bind(_Fake({"volume": None}))
    assert fake.temp_timer_template()["volume"] == 0.5


def test_configure_persist_reload_canonical():
    fake = _bind(_Fake({}))
    fake.configure_temp_timer({"volume": 0.5})
    stored = fake.data["temp_timer_settings"]["volume"]
    assert stored == 0.5                       # canonical float stored
    assert fake.temp_timer_template()["volume"] == 0.5
    # reload from stored value
    fake2 = _bind(_Fake(dict(fake.data["temp_timer_settings"])))
    assert fake2.temp_timer_template()["volume"] == 0.5


def test_add_uses_canonical_volume():
    fake = _bind(_Fake({"volume": 0.5}))
    t = fake.add_temp_timer(15)
    assert t.volume == 0.5                     # Timer healed to 0.0-1.0
    # legacy stored -> healed through template -> timer
    fake2 = _bind(_Fake({"volume": 2}))        # legacy 2 -> 0.2
    t2 = fake2.add_temp_timer(15)
    assert t2.volume == 0.2
