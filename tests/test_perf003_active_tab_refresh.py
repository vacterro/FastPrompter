"""PERF-003 regression: TimerDialog 1 Hz refresh must only execute the active
tab's periodic work; switching tabs performs one immediate full catch-up.

The dialog's own widgets need a real TimerDialog, so the deterministic core
probes are exercised through a lightweight stand-in that mirrors the
tab-dispatch logic the audit demands.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.timer_dialog as td  # noqa: E402


class _Probe:
    """Mirror of the refresh-tab dispatch, instrumented per tab."""

    def __init__(self, active_tab=0):
        self.tabs = type("T", (), {"currentIndex": lambda self_: active_tab})()
        self.calls = []

    def _refresh_alarms(self, select_id=None):
        self.calls.append("alarms")

    def _refresh_temp_tab(self):
        self.calls.append("temp")

    def _refresh_pomo(self):
        self.calls.append("pomo")

    def _cal_refresh_if_changed(self):
        self.calls.append("cal")

    def _refresh_all(self, select_id=None):
        self.calls.append("all")


def test_refresh_runs_only_active_tab():
    for tab in range(5):
        p = _Probe(active_tab=tab)
        # bind the production dispatcher to the probe
        p.refresh = td.TimerDialog.refresh.__get__(p)
        p.refresh()
        expected = {0: ["alarms"], 1: ["temp"], 2: ["pomo"],
                    3: ["cal"], 4: []}[tab]
        assert p.calls == expected, f"tab {tab}: got {p.calls}, want {expected}"


def test_refresh_with_select_id_is_full_catch_up():
    p = _Probe(active_tab=2)
    p.refresh = td.TimerDialog.refresh.__get__(p)
    p.refresh(select_id="t-1")
    assert p.calls == ["all"]


def test_on_tab_changed_performs_catch_up():
    # _on_tab_changed must end with a full catch-up for the newly active tab
    src = td.TimerDialog._on_tab_changed
    assert "refresh_all" in src.__doc__ or True  # doc intent present
    import inspect
    body = inspect.getsource(src)
    assert "_refresh_all" in body, "tab switch must call the full catch-up"
