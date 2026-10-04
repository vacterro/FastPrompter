"""T-1410 — a generic app toast is not a timer toast.

``TimerToast`` built its status row as ``status or tr("Time's up")`` and its
Dismiss tooltip as an unconditional sentence about acknowledging a passed
event. Every app-owned notification that reused the widget inherited both, so
Pack Silo printed "Time's up" under a failure nobody had any business calling
a timer. This file pins the split: TIMER semantics stay exactly as they were,
GENERIC semantics render no timer sentence at all.

Contract under test:
A  a real timer toast with no status still says "Time's up"
B  a generic toast with no status contains no timer sentence, and hides the row
C  a generic toast with a status shows exactly that status
D  a generic Dismiss hover never talks about a passed event
E  a timer Dismiss hover keeps its acknowledgement wording
F  the app's own generic toast route leaks no timer vocabulary at all
"""

import datetime

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

import fastprompter.ui.timer_toast as tt
from fastprompter.core.timers import Timer

TIMER_SENTENCE = "Time's up"
PASSED_EVENT_VOCAB = ("passed event", "passed-event", "red passed-event alert")


class _Win:
    """Minimal window double: palette tokens + a language."""

    def __init__(self):
        self._theme_cache = {"raw_colors": {
            "notif_bg": "#111111", "notif_title": "#222222",
            "notif_accent": "#333333", "notif_text": "#444444",
            "notif_info": "#555555", "border": "#666666",
            "border_dark": "#777777", "btn_bg": "#888888",
            "btn_text": "#999999", "btn_pressed": "#aaaaaa",
        }}
        self._current_lang = "EN"


def _timer():
    t = Timer("Toast", target=datetime.datetime.now())
    t.color = "#666666"
    return t


def _labels(toast):
    return [lbl.text() for lbl in toast.findChildren(QLabel)]


def _dismiss_button(toast):
    for btn in toast.findChildren(QPushButton):
        if btn.text().strip() == "Dismiss":
            return btn
    return None


def _timer_toast(**kw):
    """A toast with a real timer owner: snooze + acknowledge callbacks."""
    return tt.TimerToast(_Win(), _timer(), on_snooze=lambda *_a: None,
                         on_dismiss=lambda *_a: None, **kw)


def _generic_toast(**kw):
    return tt.show_simple_toast(_Win(), "Nothing to pack", "No selected content.",
                                header="Pack Silo", **kw)


def _teardown(toast):
    try:
        toast.close()
    except RuntimeError:
        pass
    QApplication.processEvents()


# --- A: timer semantics preserved ------------------------------------------

@pytest.mark.usefixtures("qapp")
def test_a_timer_toast_with_no_status_still_says_times_up():
    toast = _timer_toast()
    try:
        assert TIMER_SENTENCE in _labels(toast), _labels(toast)
    finally:
        _teardown(toast)


@pytest.mark.usefixtures("qapp")
def test_a_timer_toast_with_an_explicit_status_shows_that_status():
    toast = _timer_toast(status="Resumes in 4 minutes")
    try:
        assert "Resumes in 4 minutes" in _labels(toast), _labels(toast)
    finally:
        _teardown(toast)


# --- B: a generic toast has no timer sentence ------------------------------

@pytest.mark.usefixtures("qapp")
def test_b_a_generic_toast_with_no_status_never_says_times_up():
    toast = _generic_toast()
    try:
        assert toast is not None
        blob = " ".join(_labels(toast))
        assert TIMER_SENTENCE not in blob, blob
    finally:
        _teardown(toast)


@pytest.mark.usefixtures("qapp")
def test_b_a_generic_toast_hides_the_status_row_when_there_is_none():
    toast = _generic_toast()
    try:
        row = toast.findChild(QLabel, "InfoLbl")
        assert row is None or not row.text().strip(), (
            row.text() if row is not None else "no row")
    finally:
        _teardown(toast)


@pytest.mark.usefixtures("qapp")
def test_b_a_generic_toast_is_not_labelled_a_timer_notification():
    toast = _generic_toast()
    try:
        blob = " ".join(_labels(toast))
        assert "Timer Notification" not in blob, blob
    finally:
        _teardown(toast)


# --- C: an explicit status is shown verbatim -------------------------------

@pytest.mark.usefixtures("qapp")
def test_c_a_generic_toast_shows_exactly_the_supplied_status():
    toast = _generic_toast(status="3 item(s) packed · Copied to clipboard")
    try:
        assert "3 item(s) packed · Copied to clipboard" in _labels(toast), _labels(toast)
    finally:
        _teardown(toast)


# --- D/E: the Dismiss tooltip ----------------------------------------------

@pytest.mark.usefixtures("qapp")
def test_d_a_generic_dismiss_hover_never_mentions_a_passed_event():
    toast = _generic_toast()
    try:
        btn = _dismiss_button(toast)
        assert btn is not None, "a generic toast still offers Dismiss"
        tip = btn.toolTip().lower()
        for word in PASSED_EVENT_VOCAB:
            assert word not in tip, (word, btn.toolTip())
    finally:
        _teardown(toast)


@pytest.mark.usefixtures("qapp")
def test_e_a_timer_dismiss_hover_keeps_its_acknowledgement_wording():
    toast = _timer_toast()
    try:
        btn = _dismiss_button(toast)
        assert btn is not None
        tip = btn.toolTip().lower()
        assert "passed event" in tip, btn.toolTip()
    finally:
        _teardown(toast)


# --- F: the app's own generic route ----------------------------------------

def test_f_the_app_generic_toast_route_leaks_no_timer_vocabulary():
    from fastprompter import main as appmain

    shown = {}

    class _Host(appmain.FastPrompter):
        pass

    def _fake(main_win, title, message, **kw):
        shown["title"] = title
        shown["message"] = message
        shown.update(kw)
        return _generic_toast(**{k: v for k, v in kw.items()
                                 if k in ("status", "duration_ms",
                                          "accent_color", "symbol", "actions")})

    import fastprompter.ui.timer_toast as toast_mod
    original = toast_mod.show_simple_toast
    toast_mod.show_simple_toast = _fake
    try:
        host = _Host.__new__(_Host)
        host._current_lang = "EN"
        host._show_in_app_toast("Nothing to pack", "No selected content.",
                                header="Pack Silo")
    finally:
        toast_mod.show_simple_toast = original

    blob = " ".join(str(v) for v in shown.values()).lower()
    for word in (TIMER_SENTENCE.lower(), "passed event", "passed-event",
                 "timer notification"):
        assert word not in blob, (word, blob)
