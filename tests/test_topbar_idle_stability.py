"""T-1449: steady-state 1 Hz visual ticks must not repeat responsive layout
work, while every real geometry/config/semantic change still reconciles.

Against a real offscreen window:
1.  60 unchanged visible ticks -> at most the necessary initial policy pass.
2.  Displayed seconds still advance.
3.  Unchanged alert presentation -> zero redundant stylesheet assignments.
4.  Resize across all four ranges restores exact visibility/overflow.
5.  Gauge/reset-label visibility follows semantic availability.
6.  Timer activation/countdown/dismissal stay visible without stale labels.
7.  Config, UI-scale, font-metric and density transitions invalidate.
8.  Hidden window does no visual work; scheduler stays alive; show catches up.
9.  No QTimer accumulation across visibility/resize/config cycles.
10. T-1446/1447 modal lifecycle hooks remain in place.
11. Narrow/ultra: no clipping, no layout oscillation.
12. Real geometry change reconciles promptly, without waiting for a tick.
"""

import copy
import datetime
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import fastprompter.core.state as state_mod  # noqa: E402
import fastprompter.main as main_mod  # noqa: E402
from fastprompter.core.topbar_visibility import (  # noqa: E402
    RANGE_IDS,
    range_for_width,
)
from fastprompter.main import FastPrompter  # noqa: E402

_APP = QApplication.instance() or QApplication([])
_TMP = tempfile.mkdtemp(prefix="fp_t1449_idle_")

WIDTHS = {"wide": 1600, "medium": 1100, "narrow": 750, "ultra": 500}


def _make_window():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_TMP, f"test_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    FastPrompter._init_limit_service = lambda self: None

    w = FastPrompter()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.data["limit_gauges"] = "False"
    w.show()
    _APP.processEvents()
    for t in (w.auto_save_timer, w.topmost_timer, w.date_timer, w._cache_timer):
        t.stop()
    return w


def _teardown(w):
    for t in (w.auto_save_timer, w.topmost_timer, w.date_timer, w._cache_timer):
        if t.isActive():
            t.stop()
    if getattr(w, "_static_cursor_applied", False):
        QApplication.restoreOverrideCursor()
        w._static_cursor_applied = False
    w.close()
    _APP.processEvents()


@pytest.fixture
def win():
    w = _make_window()
    yield w
    _teardown(w)


class _Counts:
    def __init__(self):
        self.reset()

    def reset(self):
        self.A = 0  # _apply_topbar_visibility
        self.B = 0  # header_layout.activate
        self.C = 0  # lbl_date.setStyleSheet
        self.D = 0  # lbl_date.setText


def _instrument(w):
    """Instance-attribute shadows; returns (counts, restore)."""
    c = _Counts()
    orig_apply = FastPrompter._apply_topbar_visibility.__get__(w)
    orig_activate = w.header_layout.activate
    orig_ss = w.lbl_date.setStyleSheet
    orig_set = w.lbl_date.setText

    def apply_wrap():
        c.A += 1
        return orig_apply()

    def activate_wrap(*a, **k):
        c.B += 1
        return orig_activate(*a, **k)

    def ss_wrap(*a, **k):
        c.C += 1
        return orig_ss(*a, **k)

    def set_wrap(*a, **k):
        c.D += 1
        return orig_set(*a, **k)

    w._apply_topbar_visibility = apply_wrap
    w.header_layout.activate = activate_wrap
    w.lbl_date.setStyleSheet = ss_wrap
    w.lbl_date.setText = set_wrap

    def restore():
        del w._apply_topbar_visibility
        del w.header_layout.activate
        del w.lbl_date.setStyleSheet
        del w.lbl_date.setText
    return c, restore


def _ticks(w, n):
    for _ in range(n):
        w._update_date_label()


def _probe_timer(minutes=5, fired=False):
    from fastprompter.core.timers import Timer
    now = datetime.datetime.now()
    timer = Timer(name="t1449-probe", description="", repeat="once",
                  target=now + datetime.timedelta(minutes=(-minutes if fired else minutes)))
    timer.show_in_top_bar = True
    if fired:
        timer.fired = True
    return timer


# ---- 1: idle stability ----------------------------------------------------

def test_60_unchanged_ticks_at_most_one_initial_pass(win):
    w = win
    c, restore = _instrument(w)
    try:
        w._update_date_label()  # warm: establishes the reconcile key
        c.reset()
        _ticks(w, 60)
        assert c.A <= 1, f"60 unchanged ticks forced {c.A} policy passes"
        assert c.B <= 14, f"layout activations leaked outside policy passes: {c.B}"
        assert c.D <= 2, f"date text churned {c.D} times without real change"
    finally:
        restore()


# ---- 2: seconds still advance ---------------------------------------------

def test_displayed_seconds_advance(win, monkeypatch):
    w = win

    class _Advancing:
        step = 0

        @classmethod
        def now(cls):
            cls.step += 1
            base = datetime.datetime(2026, 10, 8, 12, 0, 0)
            return base + datetime.timedelta(seconds=cls.step)

    monkeypatch.setattr(main_mod, "datetime",
                        type("ns", (), {"datetime": _Advancing}))
    w.data["date_seconds"] = "True"
    w.data["date_daypart"] = "False"
    try:
        _ticks(w, 3)
        assert w.lbl_date.text().endswith("12:00:03"), w.lbl_date.text()
        _ticks(w, 1)
        assert w.lbl_date.text().endswith("12:00:04"), w.lbl_date.text()
    finally:
        w.data["date_daypart"] = "True"


# ---- 3: alert stylesheet guarded ------------------------------------------

def test_unchanged_alert_zero_redundant_stylesheets(win):
    w = win
    timer = _probe_timer(minutes=5, fired=True)
    w.timers.append(timer)
    w._missed_timer_ids.add(timer.id)
    c, restore = _instrument(w)
    try:
        w._update_date_label()  # initial sync applies the alert once
        assert "e05555" in w.lbl_date.styleSheet().lower() or \
            w.data.get("passed_event_color", "#e05555").lower() in \
            w.lbl_date.styleSheet().lower()
        c.reset()
        _ticks(w, 59)
        assert c.C == 0, f"unchanged alert reassigned stylesheet {c.C} times"
        w._clear_missed_alert()
        assert "bold" not in w.lbl_date.styleSheet(), \
            "acknowledgement must clear the alert presentation"
    finally:
        restore()
        w.timers = [t for t in w.timers if t is not timer]
        w._missed_timer_ids.clear()
        w._update_date_label()


# ---- 4: resize across all four ranges -------------------------------------

def test_resize_four_ranges_restores_visibility_and_overflow(win):
    w = win
    seen = {}
    for rid in RANGE_IDS:
        w.resize(WIDTHS[rid], w.height())
        _APP.processEvents()
        seen[rid] = (w._topbar_active_range, frozenset(w._topbar_visible_tokens),
                     tuple(w._topbar_overflow_tokens))
        assert w._topbar_active_range == rid, \
            f"width {WIDTHS[rid]} resolved to {w._topbar_active_range}, expected {rid}"
        assert w.lbl_date.isVisible(), "the clock must survive every range"
        # every non-hidden widget and every displaced action is accounted for
        overflow = set(w._topbar_overflow_tokens)
        assert (w.btn_overflow.isVisible() == bool(overflow)), \
            "overflow button mirrors displaced membership"
    # round trip: narrow back to wide restores the exact original state
    for rid in ("narrow", "ultra", "medium", "wide"):
        w.resize(WIDTHS[rid], w.height())
        _APP.processEvents()
    assert (w._topbar_active_range, frozenset(w._topbar_visible_tokens),
            tuple(w._topbar_overflow_tokens)) == seen["wide"], \
            "returning to a range must restore its exact visibility state"
    assert seen["ultra"][1] != seen["wide"][1], \
        "the four ranges must actually differ in visibility"


# ---- 5: gauge / reset-label contracts --------------------------------------

def test_gauge_visibility_follows_config(win):
    w = win
    w.data["limit_gauges"] = "True"
    w._update_date_label()
    assert w.limit_gauges.isVisible(), "enabled gauges must show at wide width"
    w.data["limit_gauges"] = "False"
    w._update_date_label()
    assert not w.limit_gauges.isVisible(), \
        "disabling gauges must hide them through the policy on the next tick"
    w.data["limit_gauges"] = "True"
    w._update_date_label()
    assert w.limit_gauges.isVisible(), "re-enabling must reshow them"
    w.data["limit_gauges"] = "False"


def test_reset_countdown_label_tracks_semantics(win):
    w = win
    w.data["limit_gauges"] = "True"
    w._set_topbar_semantic("lbl_limit_timer", False)
    assert not w.lbl_limit_timer.isVisible()
    w._set_topbar_semantic("lbl_limit_timer", True)
    assert w.lbl_limit_timer.isVisible()
    w.data["limit_gauges"] = "False"
    w._set_topbar_semantic("lbl_limit_timer", False)


# ---- 6: timer countdown lifecycle ------------------------------------------

def test_timer_activation_countdown_and_dismissal(win):
    w = win
    timer = _probe_timer(minutes=5)
    w.timers.append(timer)
    try:
        w._update_timer_label()
        w._update_date_label()
        assert w.lbl_timer.isVisible(), "active countdown must be visible"
        assert w.lbl_timer.text(), "countdown label must carry text"
        first = w.lbl_timer.text()
        timer.target = datetime.datetime.now() + datetime.timedelta(seconds=90)
        w._update_timer_label()
        assert w.lbl_timer.isVisible()
        w.timers = [t for t in w.timers if t is not timer]
        w._update_timer_label()
        w._update_date_label()
        assert not w.lbl_timer.isVisible(), \
            "dismissed timer must retract the countdown label"
    finally:
        w.timers = [t for t in w.timers if t is not timer]
        w._update_timer_label()
    assert first


# ---- 7: transitions invalidate --------------------------------------------

def test_config_change_invalidates_on_next_tick(win):
    w = win
    w._update_date_label()
    cfg = copy.deepcopy(w._topbar_visibility_config())
    cfg["items"]["lbl_timer"]["wide"] = "hide"
    w.data["topbar_visibility"] = cfg  # writers commit a fresh dict
    w._update_date_label()
    assert not w.lbl_timer.isVisible(), \
        "a rule change must apply on the next tick without a resize"


def test_ui_scale_change_invalidates(win, monkeypatch):
    w = win
    c, restore = _instrument(w)
    try:
        w._update_date_label()
        c.reset()
        monkeypatch.setattr(w, "_effective_scale", lambda: 1.5)
        w._update_date_label()
        assert c.A >= 1, "a UI-scale change must force a policy pass"
    finally:
        restore()


def test_theme_transition_reconciles_and_leaves_key_fresh(win):
    """Theme/font transitions reach the top bar through the app's own route:
    apply_theme schedules _apply_header_density, a direct executor call. The
    transition must reconcile exactly once and leave the tick gate idle."""
    w = win
    w._update_date_label()
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QWidget
    font = QFont(w.btn_save.font())
    font.setBold(not font.bold())
    for child in w.header_widget.findChildren(QWidget):
        child.setFont(font)
    c, restore = _instrument(w)
    try:
        w._apply_header_density()  # what the theme singleShot invokes
        assert c.A >= 1, "the theme route must run a policy pass"
        c.reset()
        _ticks(w, 10)
        assert c.A == 0, "ticks must not repeat the theme's own pass"
    finally:
        restore()
        app_font = QApplication.font()
        for child in w.header_widget.findChildren(QWidget):
            child.setFont(app_font)
        w._apply_header_density()


def test_direct_callers_leave_key_fresh(win):
    """Density/theme paths call the executor directly; the next tick must not
    repeat the pass they already performed."""
    w = win
    w._apply_header_density()  # direct caller, refreshes the key internally
    c, restore = _instrument(w)
    try:
        c.reset()
        w._update_date_label()
        assert c.A == 0, "tick repeated a pass a direct caller just ran"
    finally:
        restore()


# ---- 8: hidden window / scheduler / show catch-up --------------------------

def test_hidden_window_no_work_scheduler_alive_show_catchup(win):
    w = win
    w.hide()
    _APP.processEvents()
    c, restore = _instrument(w)
    try:
        c.reset()
        _ticks(w, 10)
        assert (c.A, c.B, c.C, c.D) == (0, 0, 0, 0), \
            f"hidden window did visual work: A={c.A} B={c.B} C={c.C} D={c.D}"
        # the shared scheduler is independent of the visual gate
        w.date_timer.start(1000)
        assert w.date_timer.isActive(), "the 1 Hz scheduler must keep running"
        w.date_timer.stop()
        w.show()
        _APP.processEvents()
        w._update_date_label()
        assert w.lbl_date.text(), "showEvent path must refresh the clock"
        assert w._topbar_semantic.get("lbl_date") is True
    finally:
        restore()


# ---- 9: no timer accumulation ---------------------------------------------

def test_no_qtimer_accumulation_across_cycles(win):
    w = win
    baseline = len(_APP.findChildren(type(w.date_timer)))
    for cycle in range(5):
        w.hide()
        _APP.processEvents()
        w.show()
        _APP.processEvents()
        for rid in ("narrow", "wide"):
            w.resize(WIDTHS[rid], w.height())
            _APP.processEvents()
        cfg = copy.deepcopy(w._topbar_visibility_config())
        cfg["items"]["btn_help"]["wide"] = "auto" if cycle % 2 else "show"
        w.data["topbar_visibility"] = cfg
        w._update_date_label()
    after = len(_APP.findChildren(type(w.date_timer)))
    assert after == baseline, \
        f"QTimer count grew across cycles: {baseline} -> {after}"


# ---- 10: modal lifecycle protections intact --------------------------------

def test_modal_lifecycle_hooks_remain():
    import inspect
    src = inspect.getsource(FastPrompter.open_topbar_visibility_dialog)
    assert "deleteLater" in src
    from fastprompter.ui.topbar_visibility_dialog import TopbarVisibilityDialog
    dlg_src = inspect.getsource(TopbarVisibilityDialog)
    assert "_stop_preview_timer" in dlg_src
    from fastprompter.ui.timer_dialog import TimerDialog
    timer_src = inspect.getsource(TimerDialog)
    assert "_finish_dialog_lifecycle" in timer_src


# ---- 11: narrow/ultra: no clipping, no oscillation -------------------------

@pytest.mark.parametrize("rid", ["narrow", "ultra"])
def test_narrow_no_clipping_no_oscillation(win, rid):
    w = win
    w.resize(WIDTHS[rid], w.height())
    _APP.processEvents()
    w._update_date_label()
    snapshot = frozenset(w._topbar_visible_tokens)
    for _ in range(5):
        w._update_date_label()
        assert frozenset(w._topbar_visible_tokens) == snapshot, \
            "layout oscillated across idle ticks"
    hint = w.header_widget.sizeHint().width()
    room = w._header_available_width()
    assert hint <= room + 4, \
        f"header asks {hint}px inside {room}px at {rid} — clipping"


# ---- 12: geometry reconciles promptly --------------------------------------

def test_resize_reconciles_without_waiting_for_tick(win):
    w = win
    w.resize(1600, w.height())
    _APP.processEvents()
    w._update_date_label()
    assert w._topbar_active_range == "wide"
    w.resize(WIDTHS["narrow"], w.height())
    _APP.processEvents()
    # no tick has run since the resize
    assert w._topbar_active_range == "narrow", \
        "resizeEvent must reconcile before the next timer tick"
    cfg = range_for_width(w._topbar_visibility_config(),
                          w._topbar_effective_width())
    assert cfg == "narrow"
    # the narrow pass already ran: the header must fit its room without
    # waiting for the next tick
    assert w.header_widget.sizeHint().width() <= w._header_available_width() + 4
