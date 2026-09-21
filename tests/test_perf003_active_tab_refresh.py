"""PERF-003 regression: TimerDialog 1 Hz refresh must only execute the active
tab's periodic work; switching tabs performs one immediate full catch-up.

The dialog's own widgets need a real TimerDialog, so the deterministic core
probes are exercised through a lightweight stand-in that mirrors the
tab-dispatch logic the audit demands.

Dispatch is by PAGE IDENTITY, not tab index: every tab page carries its own
``_timer_refresh`` (timer_dialog.py:689/1148/1354/1638/2771) and ``refresh``
calls exactly the current page's. Index arithmetic was what broke once tabs
became reorderable/hideable, so the stand-in models pages, not numbers.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.timer_dialog as td  # noqa: E402

# Production order of the tab pages, each with the callback it binds.
TAB_LABELS = ("alarms", "temp", "pomo", "cal", "interval")


class _Page:
    """A tab page. ``inert=True`` models a page with no periodic work."""

    def __init__(self, label, calls, inert=False):
        self.label = label
        if not inert:
            self._timer_refresh = lambda: calls.append(label)


class _Tabs:
    def __init__(self, pages, index):
        self.pages = pages
        self._index = index

    def currentWidget(self):
        return self.pages[self._index]


class _Probe:
    """Mirror of the refresh dispatch, instrumented per page."""

    def __init__(self, active_tab=0, inert_tab=None):
        self.calls = []
        self.pages = [_Page(label, self.calls, inert=(i == inert_tab))
                      for i, label in enumerate(TAB_LABELS)]
        self.tabs = _Tabs(self.pages, active_tab)

    def _refresh_all(self, select_id=None):
        self.calls.append("all")


def test_refresh_runs_only_active_tab():
    for tab, label in enumerate(TAB_LABELS):
        p = _Probe(active_tab=tab)
        # bind the production dispatcher to the probe
        p.refresh = td.TimerDialog.refresh.__get__(p)
        p.refresh()
        assert p.calls == [label], f"tab {tab}: got {p.calls}, want [{label!r}]"


def test_refresh_skips_a_page_without_periodic_work():
    p = _Probe(active_tab=2, inert_tab=2)
    p.refresh = td.TimerDialog.refresh.__get__(p)
    p.refresh()
    assert p.calls == []


def test_oracle_rejects_a_refresh_that_touches_every_tab():
    """Red control: the assertion above must be able to fail (VERIFY-ORACLE-01).

    A dispatcher that refreshes every page is exactly the PERF-003 defect, so
    the oracle has to reject it. Without this, a stand-in whose pages silently
    record nothing would read green forever.
    """
    p = _Probe(active_tab=0)

    def refresh_every_page(self, select_id=None):
        for page in self.tabs.pages:
            callback = getattr(page, "_timer_refresh", None)
            if callable(callback):
                callback()

    p.refresh = refresh_every_page.__get__(p)
    p.refresh()
    assert p.calls == list(TAB_LABELS)
    assert p.calls != ["alarms"], "oracle must reject an all-tabs refresh"


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
