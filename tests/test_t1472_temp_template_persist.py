"""T-1472 regression: a temp-timer template change is dropped while a temp
timer is live.

configure_temp_timer stores the template and, when a timer is live, copies a
fixed key list onto the timer object and delegates to save_timers_to_data.
That helper's PERF-001 guard says nothing about the template: change the
increment alone (a key it does not copy) and the timer list is unchanged, so
the guard returns early, settings are never marked dirty, and the next save
takes the partial ui_settings path that never encodes temp_timer_settings.
The reload therefore shows the old increment.
"""

import datetime
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.state import _encode_settings  # noqa: E402
from fastprompter.core.timers import Timer  # noqa: E402


class _Fake:
    """Main-window surface configure_temp_timer and save_timers_to_data touch.

    save_timers_to_data is the REAL body, not a stub: the bug only shows up
    through its change-aware guard.
    """

    def __init__(self, settings=None, with_timer=True):
        self.data = {"temp_timer_settings": dict(settings or {})}
        self.timers = []
        self.dirty = []                      # [(domain, ...)] in call order
        if with_timer:
            self.timers.append(Timer(
                "Temp Timer",
                datetime.datetime.now() + datetime.timedelta(minutes=10),
                temporary=True))
            # an already-persisted running timer: this is the scenario the
            # guard is about, and the one that hides a template-only change
            self.data["timers"] = [t.to_dict() for t in self.timers]

    def _temp_timer(self):
        return next((t for t in self.timers
                     if getattr(t, "temporary", False)), None)

    def mark_dirty(self, domain=None):
        self.dirty.append(domain)

    def save_timers_to_data(self):
        new = [t.to_dict() for t in self.timers]
        if self.data.get("timers") == new:
            return
        self.data["timers"] = new
        self.mark_dirty("settings")

    def _update_timer_label(self):
        pass

    def play_sound(self, *a, **k):
        pass


def _bind(fake):
    fake.temp_timer_template = \
        main_mod.FastPrompter.temp_timer_template.__get__(fake)
    fake.configure_temp_timer = \
        main_mod.FastPrompter.configure_temp_timer.__get__(fake)
    return fake


def _reload(fake):
    """What a restart reads back: the encoded row decoded by the codec."""
    encoded = _encode_settings(fake.data)["temp_timer_settings"]
    return json.loads(encoded)


def test_increment_persists_with_live_temp_timer():
    fake = _bind(_Fake({"increment_minutes": 15}))
    fake.configure_temp_timer({"increment_minutes": 45})

    assert fake.dirty == ["settings"], \
        "the template changed, yet nothing marked settings dirty"
    assert _reload(fake)["increment_minutes"] == 45, \
        "the persisted template row does not carry the new increment"


def test_template_row_reloads_the_new_increment():
    fake = _bind(_Fake({"increment_minutes": 15}))
    fake.configure_temp_timer({"increment_minutes": 45})
    # the restarted app rebuilds its template from the persisted row
    assert main_mod.FastPrompter.temp_timer_template.__get__(
        _Fake(_reload(fake)))()["increment_minutes"] == 45


def test_live_timer_still_receives_its_keys():
    fake = _bind(_Fake({"increment_minutes": 15, "name": "Old"}))
    fake.configure_temp_timer({"increment_minutes": 45, "name": "Focus Block"})

    assert fake._temp_timer().name == "Focus Block", \
        "the live timer lost the name it is supposed to receive"


def test_no_live_timer_still_persists():
    fake = _bind(_Fake({"increment_minutes": 15}, with_timer=False))
    fake.configure_temp_timer({"increment_minutes": 45})

    assert fake.dirty == ["settings"]
    assert _reload(fake)["increment_minutes"] == 45


def test_unchanged_template_stays_quiet():
    """Negative control: the guard's whole point is that a no-op stays clean.

    save_timers_to_data fires first (it sees unchanged timers and returns
    early), so an unchanged template must not dirty settings on its own.
    """
    fake = _bind(_Fake({"increment_minutes": 15}))
    fake.configure_temp_timer({"increment_minutes": 15})

    assert fake.dirty == [], \
        "re-saving an identical template marked settings dirty"
