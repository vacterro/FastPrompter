"""T-1483 real-Windows acceptance probe: one hovered element, one presentation.

Runs on the REAL Windows platform plugin (``QT_QPA_PLATFORM=windows``) with a
REAL pointer: the cursor is moved with ``QCursor.setPos`` and the platform
delivers genuine Enter/Leave/ToolTip events.  Nothing here is synthesised with
``QApplication.sendEvent``, and nothing calls ``show_card()``/``cancel_hide()``
to fake the interaction it is supposed to measure.

What it measures now (T-1483)
-----------------------------
The T-1482 probe COMPUTED acceptance metrics but always returned 0, and it
counted ``hide_now()`` calls while the grace timer closes the card through
``QWidget.hide()`` -- so a broken run could report process success and a real
close was invisible to the counter.  This version:

  * records every ``QEvent.Show`` / ``QEvent.Hide`` a ``LimitHoverCard``
    actually receives, plus the sampled ``isVisible()`` state on every step,
    so a close is observed however it was reached (``hide_now()``, the grace
    timer's ``hide()``, or an indirect parent hide);
  * drives the POINTER from the gauge across the real intervening gap into
    the visible card, holds it there longer than ``HIDE_GRACE_MS``, returns to
    the gauge and only then abandons both surfaces;
  * evaluates an explicit acceptance predicate per cycle and exits non-zero
    when any requirement breaks, still writing the structured report;
  * can inject one fault at a time (``--negative-control``) and proves the
    oracle REJECTS it.  A control that the oracle does not catch fails the run.

Per cycle it records:

  * how many hover presentations were on screen (must be exactly 1),
  * whether a native QToolTip was visible beside the card (must be false),
  * whether the first hover of the run opened the card (no missed first hover),
  * whether the card stayed visible for every phase of the traversal,
  * whether the card survived a content refresh while the pointer was inside,
  * whether returning to the gauge rebuilt (re-showed) the card,
  * whether the card survived the permitted grace interval and then closed,
  * the observed close latency, the main window's focus-lock count and
    whether the window stayed visible,
  * how often the hover sound fired (exactly once per card session),
  * the card's border pixels (the theme accent, 2 px) at the real DPI.

Politeness (a real cursor means a real hand)
-------------------------------------------
The probe drives the REAL system pointer, so it must never fight the person
at the keyboard.  It therefore:

  * waits for the desktop to be IDLE (``GetLastInputInfo``) before every
    cycle, and never starts on a busy machine;
  * aborts a cycle the instant the pointer stops being where the probe put it
    (the human moved the mouse), restoring the saved pointer position;
  * never activates or raises the main window (``WA_ShowWithoutActivating``),
    so typing is not interrupted;
  * does not play the hover sound: the emission is counted, the audio sink is
    not called (``--audible`` restores playback on a dedicated machine);
  * restores the pointer to where the user left it when it stops.

Usage::

    python tools/probe_tooltip_ownership.py --cycles 30 \
        --json .saipen/evidence/t1483/tooltip_acceptance_windows.json
    python tools/probe_tooltip_ownership.py --cycles 1 --negative-control all
    python tools/probe_tooltip_ownership.py --cycles 1 --negative-control stale_card
    python tools/probe_tooltip_ownership.py --no-wait   # dedicated machine only

Exit codes::

    0  every acceptance requirement held on every measured cycle
    1  at least one requirement broke (the report names the cycles)
    2  the probe could not complete a measurement (harness error)
    3  the measurement was VOID: something else drove the system cursor,
       so no cycle describes the product (re-run untouched)

The provider is never contacted: the usage-limit service's scheduler is
stubbed out, the networked providers are removed from the roster and the
reset queue is fed with synthetic snapshots, exactly like the offscreen
regressions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

os.environ["QT_QPA_PLATFORM"] = "windows"

from _qt_retire import retire  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QEvent, QEventLoop, QObject, QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QToolTip  # noqa: E402

import fastprompter.core.state as state_mod  # noqa: E402
from fastprompter.core.usage_limits.model import (  # noqa: E402
    FIVE_HOUR,
    OK,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.main import FastPrompter  # noqa: E402
from fastprompter.ui.limit_hover_card import HIDE_GRACE_MS, LimitHoverCard  # noqa: E402

# -- acceptance thresholds (documented on purpose) ---------------------------
#
# First-entry latency: the card is shown synchronously inside the Enter
# handler, so the observed latency is one sampling step.  Measured maxima are
# 20-60 ms; 400 ms is the point where the popup stops feeling immediate.
MAX_OPEN_LATENCY_MS = 400
# Windows' native tooltip wake-up delay is 700 ms; wait past it before
# declaring that no native tooltip appeared.
NATIVE_TOOLTIP_SETTLE_MS = 900
# One pointer step across the gap between the gauge and the card.
TRAVERSE_STEP_MS = 25
# Hold inside the card this long BEYOND the grace interval: a card that
# still closes while the pointer rests on it cannot pass.
HOLD_EXTRA_MS = 400
# Sample the permitted grace interval, stopping short of its end so timer
# granularity cannot make a correct close look early.
GRACE_PROBE_MS = max(120, HIDE_GRACE_MS - 100)
# After the grace interval the card must be gone within this extra window.
HIDE_SLACK_MS = 500
# A card that renders less than this much text is an empty popup.
MIN_CARD_CONTENT_CHARS = 200
# The card must not shrink or jump while its content refreshes.
GEOMETRY_TOLERANCE_PX = 0
# How far the system cursor may sit from the point the probe asked it to
# hold before the cycle is considered externally driven.
CURSOR_DRIFT_TOLERANCE_PX = 4
# Consecutive drifted samples that invalidate a cycle.
TAKEOVER_SAMPLES = 3
# Full-cycle retries allowed when the pointer is taken over mid-cycle.
TAKEOVER_RETRIES = 3
# The desktop must be quiet for this long before a cycle may start.
IDLE_GATE_MS = 800
# How long the probe is willing to WAIT for a quiet desktop before it gives up
# and reports a void run instead of taking the pointer away from a human.
MAX_QUIET_WAIT_S = 120

#: Harness policy: how the probe behaves around the human at the keyboard.
POLICY = {
    "restore_cursor": True,
    "audible": False,
    "wait_for_quiet": True,
    "patient": False,
    "cursor_home": None,
    "waited_ms": 0,
    "gate": None,
    "idle_ms": IDLE_GATE_MS,
}

CONTROL_NAMES = (
    "native_tooltip",
    "two_cards",
    "no_open",
    "close_inside",
    "stale_card",
    "no_border",
    "focus_leak",
    "window_hide",
    "skip_cycle",
)


class DesktopGate:
    """Refuse to take the pointer while the human is using the machine.

    ``GetLastInputInfo`` reports the last hardware input (mouse or keyboard),
    so a person typing or moving the mouse is visible without installing a
    hook.  The probe's own ``QCursor.setPos`` also counts as input, which is
    why the gate is consulted BEFORE a cycle moves anything, never during one
    (mid-cycle interference is caught by the cursor-position check instead).
    """

    def __init__(self) -> None:
        self._user32 = None
        self._kernel32 = None
        self._info = None
        try:
            import ctypes
            from ctypes import wintypes

            class LastInputInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT),
                            ("dwTime", wintypes.DWORD)]

            self._ctypes = ctypes
            self._info = LastInputInfo()
            self._info.cbSize = ctypes.sizeof(LastInputInfo)
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
        except Exception:      # not Windows, or no ctypes: gate is a no-op
            self._user32 = None

    def idle_ms(self) -> int:
        if self._user32 is None:
            return 10 ** 9
        try:
            if not self._user32.GetLastInputInfo(
                    self._ctypes.byref(self._info)):
                return 10 ** 9
            tick = self._kernel32.GetTickCount64()
        except Exception:
            return 10 ** 9
        return int((tick - int(self._info.dwTime)) & 0xFFFFFFFF)

    def wait_for_quiet(self, idle_ms: int, max_wait_s: float,
                       patient: bool | None = None) -> bool:
        """Block (without touching the pointer) until the desktop is idle.

        ``patient`` mode never gives up: it borrows the mouse for one cycle
        whenever the human pauses, then hands it straight back.  That is the
        mode to use on a machine somebody is actually working on.
        """
        if not POLICY["wait_for_quiet"]:
            return True
        if patient is None:
            patient = POLICY["patient"]
        started = time.monotonic()
        while True:
            if self.idle_ms() >= idle_ms:
                POLICY["waited_ms"] += int(
                    (time.monotonic() - started) * 1000)
                return True
            if not patient and time.monotonic() - started > max_wait_s:
                POLICY["waited_ms"] += int(
                    (time.monotonic() - started) * 1000)
                return False
            _pump(100)


def _cursor_home():
    """The pointer position the human left behind, saved once."""
    if POLICY["cursor_home"] is None:
        try:
            POLICY["cursor_home"] = QCursor.pos()
        except (RuntimeError, AttributeError):
            POLICY["cursor_home"] = None
    return POLICY["cursor_home"]


def _restore_cursor() -> None:
    """Hand the pointer back exactly where the user left it."""
    if not POLICY["restore_cursor"]:
        return
    home = POLICY["cursor_home"]
    if home is None:
        return
    try:
        QCursor.setPos(home)
    except (RuntimeError, AttributeError):
        pass


def _pump(ms: int) -> None:
    """Let the REAL event loop run for ``ms`` milliseconds."""
    app = QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    while True:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
        if time.monotonic() >= end:
            return
        time.sleep(0.002)


def _snapshot(provider="claude", stable="s1", name="Claude", epoch=None):
    acc = AccountRef(provider, stable, name, "auto_default")
    window = UsageWindow(FIVE_HOUR, 300, True, 10.0, 90.0,
                         resets_at_epoch=epoch)
    return UsageSnapshot(acc, OK, [window])


def _install_snapshots(window, snapshots) -> None:
    from fastprompter.core.usage_limits.service import ServiceState

    accounts = [snap.account for snap in snapshots.values()]
    window.limit_service._state = ServiceState(
        accounts=accounts, snapshots=dict(snapshots))


# -- observation -------------------------------------------------------------

class Observer(QObject):
    """The authoritative transition record.

    ``QEvent.Show`` / ``QEvent.Hide`` are what the widget system actually
    delivered, so the grace timer's ``QWidget.hide()`` is visible here while
    the ``hide_now()`` method counter never saw it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.show_events = 0
        self.hide_events = 0
        self.sounds = 0
        self.show_calls = 0
        self.hide_calls = 0
        self.transitions: list[tuple[str, float]] = []

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Type.Show, QEvent.Type.Hide):
            try:
                is_card = isinstance(obj, LimitHoverCard)
            except RuntimeError:
                return False
            if is_card:
                if kind == QEvent.Type.Show:
                    self.show_events += 1
                else:
                    self.hide_events += 1
                if len(self.transitions) < 400:
                    self.transitions.append((kind.name, time.monotonic()))
        return False

    def install_hooks(self) -> None:
        """Count requests and hover sounds as DIAGNOSTICS only."""
        import fastprompter.ui.appearance_sounds as sounds

        observer = self
        real_sound = sounds.emit_hover_card_show
        real_show = LimitHoverCard.show_card
        real_hide = LimitHoverCard.hide_now

        def sound(*args, **kwargs):
            # Count the emission (that is the behaviour under test) but stay
            # silent unless the operator asked for audible feedback.
            observer.sounds += 1
            if not POLICY["audible"]:
                return None
            return real_sound(*args, **kwargs)

        def show(self, *args, **kwargs):
            observer.show_calls += 1
            return real_show(self, *args, **kwargs)

        def hide(self, *args, **kwargs):
            observer.hide_calls += 1
            return real_hide(self, *args, **kwargs)

        sounds.emit_hover_card_show = sound
        LimitHoverCard.show_card = show
        LimitHoverCard.hide_now = hide


@dataclass
class Phase:
    """Aggregated observation of one step of a cycle."""

    name: str
    samples: int = 0
    own_min: int | None = None
    own_max: int = 0
    total_max: int = 0
    hidden_samples: int = 0
    tooltip_samples: int = 0
    over_target_samples: int = 0
    over_card_samples: int = 0
    gap_samples: int = 0
    focus_max: int = 0
    window_hidden_samples: int = 0
    first_visible_ms: int | None = None
    last_visible_ms: int | None = None
    end_visible: int = 0
    drift_max: int = 0
    takeover_samples: int = 0
    invalidated: bool = False

    def add(self, elapsed_ms: int, sample: dict, expected=None) -> None:
        self.samples += 1
        own = int(sample["own_visible"])
        total = int(sample["visible"])
        self.own_min = own if self.own_min is None else min(self.own_min, own)
        self.own_max = max(self.own_max, own)
        self.total_max = max(self.total_max, total)
        if own:
            if self.first_visible_ms is None:
                self.first_visible_ms = elapsed_ms
            self.last_visible_ms = elapsed_ms
        else:
            self.hidden_samples += 1
        if sample["tooltip"]:
            self.tooltip_samples += 1
        if sample["over_target"]:
            self.over_target_samples += 1
        if sample["over_card"]:
            self.over_card_samples += 1
        if not sample["over_target"] and not sample["over_card"]:
            self.gap_samples += 1
        self.focus_max = max(self.focus_max, int(sample["focus_lock"]))
        if not sample["window_visible"]:
            self.window_hidden_samples += 1
        if expected is not None:
            try:
                position = QCursor.pos()
            except (RuntimeError, AttributeError):
                position = None
            if position is not None:
                drift = max(abs(position.x() - int(expected.x())),
                            abs(position.y() - int(expected.y())))
                self.drift_max = max(self.drift_max, drift)
                if drift > CURSOR_DRIFT_TOLERANCE_PX:
                    self.takeover_samples += 1
        self.end_visible = own

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "samples": self.samples,
            "own_visible_min": self.own_min,
            "own_visible_max": self.own_max,
            "total_visible_max": self.total_max,
            "hidden_samples": self.hidden_samples,
            "tooltip_samples": self.tooltip_samples,
            "over_target_samples": self.over_target_samples,
            "over_card_samples": self.over_card_samples,
            "gap_samples": self.gap_samples,
            "focus_lock_max": self.focus_max,
            "window_hidden_samples": self.window_hidden_samples,
            "first_visible_ms": self.first_visible_ms,
            "last_visible_ms": self.last_visible_ms,
            "end_visible": self.end_visible,
            "cursor_drift_max": self.drift_max,
            "takeover_samples": self.takeover_samples,
            "invalidated": self.invalidated,
        }


def _anchor_of(card):
    try:
        return card._anchor
    except (RuntimeError, AttributeError):
        return None


def _card_text(card) -> str:
    try:
        return card._label.text() or ""
    except (RuntimeError, AttributeError):
        return ""


def _owns_pointer(widget, under) -> bool:
    if widget is None or under is None:
        return False
    if under is widget:
        return True
    try:
        return widget.isAncestorOf(under)
    except (RuntimeError, TypeError):
        return False


def _sample(window, target) -> dict:
    cards = LimitHoverCard.visible_cards()
    own = sum(1 for card in cards if _anchor_of(card) is target)
    try:
        under = QApplication.instance().widgetAt(QCursor.pos())
    except (RuntimeError, AttributeError):
        under = None
    return {
        "visible": len(cards),
        "own_visible": own,
        "tooltip": QToolTip.isVisible(),
        "over_target": _owns_pointer(target, under),
        "over_card": any(_owns_pointer(card, under) for card in cards
                         if _anchor_of(card) is target),
        "focus_lock": int(getattr(window, "_focus_lock_count", 0)),
        "window_visible": bool(window.isVisible() and not window.isMinimized()),
        "under": type(under).__name__ if under is not None else "",
    }


def _own_card(target, *, visible_only: bool = False):
    """This target's card, found by ANCHOR rather than by private attribute."""
    for card in list(LimitHoverCard._live_cards):
        try:
            if sip.isdeleted(card) or _anchor_of(card) is not target:
                continue
            if visible_only and not card.isVisible():
                continue
        except (RuntimeError, TypeError):
            continue
        return card
    return None


class Runner:
    """Sample the real state of one target in bounded phases."""

    def __init__(self, window, target) -> None:
        self.window = window
        self.target = target

    def phase(self, name: str, ms: int, *, every: int = 20,
              on_sample=None, until=None, expect=None) -> Phase:
        """Sample one phase; ``expect`` is a point or a point-for-elapsed fn."""
        phase = Phase(name)
        start = time.monotonic()
        while True:
            elapsed = int((time.monotonic() - start) * 1000)
            sample = _sample(self.window, self.target)
            expected = expect(elapsed) if callable(expect) else expect
            phase.add(elapsed, sample, expected)
            if on_sample is not None:
                on_sample(elapsed, sample, phase)
            if phase.takeover_samples >= TAKEOVER_SAMPLES:
                phase.invalidated = True
                return phase
            if until is not None and until(elapsed, sample, phase):
                return phase
            if elapsed >= ms:
                return phase
            _pump(max(2, min(every, ms - elapsed)))


# -- geometry helpers --------------------------------------------------------

def _accent(main_window) -> QColor:
    try:
        from fastprompter.ui.limit_colors import resolve_hex
        return QColor(resolve_hex(main_window, "good"))
    except Exception:
        return QColor("#D9B340")


def _border_report(card, accent) -> dict:
    """The 2 px accent border, checked at the widget's real device ratio."""
    try:
        image = card.grab().toImage()
    except (RuntimeError, AttributeError):
        return {"ok": False, "reason": "grab failed"}
    w, h = image.width(), image.height()
    if w < 8 or h < 8:
        return {"ok": False, "reason": f"card too small {w}x{h}"}
    try:
        ratio = max(1.0, float(card.devicePixelRatioF()))
    except (RuntimeError, AttributeError):
        ratio = 1.0
    expected = max(1, round(2 * ratio))
    # Thickness of the accent run at the top edge centre.
    thickness = 0
    while thickness < h and image.pixelColor(w // 2, thickness) == accent:
        thickness += 1
    edge_failures = 0
    for x in range(w):
        for y in (0, h - 1):
            if image.pixelColor(x, y) != accent:
                edge_failures += 1
    for y in range(h):
        for x in (0, w - 1):
            if image.pixelColor(x, y) != accent:
                edge_failures += 1
    inner_clean = True
    inner_x = min(expected + 1, w - 1)
    inner_y = h // 2
    if image.pixelColor(inner_x, inner_y) == accent:
        inner_clean = False
    ok = edge_failures == 0 and abs(thickness - expected) <= 1 and inner_clean
    return {
        "ok": ok,
        "thickness_device_px": thickness,
        "thickness_expected": expected,
        "edge_failures": edge_failures,
        "inner_clean": inner_clean,
        "device_ratio": ratio,
        "size_device_px": [w, h],
    }


def _move_onto(target) -> tuple[bool, str, str]:
    """Put the REAL cursor on the target; report (targeted, reason, blocker).

    Four outcomes are different facts and must not be conflated:

    * the widget sees the pointer             -> "targeted"
    * the pointer does not stay where asked   -> "pulled"   (externally driven)
    * another APPLICATION owns that point     -> "foreign"  (desktop in use)
    * our own layout covers the target        -> "covered"  (a real finding)
    """
    app = QApplication.instance()
    covered = ""
    for _ in range(15):
        point = target.mapToGlobal(target.rect().center())
        QCursor.setPos(point)
        _pump(70)
        if target.underMouse():
            return True, "targeted", ""
        try:
            position = QCursor.pos()
        except (RuntimeError, AttributeError):
            continue
        drift = max(abs(position.x() - point.x()),
                    abs(position.y() - point.y()))
        if drift > CURSOR_DRIFT_TOLERANCE_PX:
            return False, "pulled", ""
        under = app.widgetAt(point)
        if under is None:
            # ``widgetAt`` only knows THIS application's widgets, so None
            # means another window owns the point: the desktop is not ours.
            return False, "foreign", ""
        covered = type(under).__name__
        _pump(40)
    return False, "covered", covered


def _glide(points, step_ms: int = 60) -> None:
    """Walk the cursor through points, letting each position settle."""
    for point in points:
        QCursor.setPos(point)
        _pump(step_ms)


def _traversal_path(target, card) -> tuple[list[QPoint], int]:
    """The real pointer path from the gauge surface into the visible card."""
    a_tl = target.mapToGlobal(QPoint(0, 0))
    a_bottom = a_tl.y() + target.height()
    c_tl = card.mapToGlobal(QPoint(0, 0))
    gap_px = c_tl.y() - a_bottom
    x = a_tl.x() + target.width() // 2
    path = [QPoint(x, a_bottom - 1)]
    if gap_px > 0:
        path.append(QPoint(x, a_bottom + max(1, gap_px // 2)))
    # The card's own surface first (inside the 2 px border, in the margin),
    # so the Enter event is delivered to the card itself.
    path.append(c_tl + QPoint(6, 6))
    path.append(c_tl + QPoint(min(60, max(12, card.width() - 12)),
                              min(30, max(12, card.height() - 12))))
    return path, gap_px


def _inject_refresh(window, target) -> str:
    """Refresh the open card's content the way the app really does."""
    try:
        if target is getattr(window, "limit_gauges", None):
            window.limit_gauges.refresh_hover_card()
        else:
            window._update_limit_timer_label()
    except Exception as exc:          # recorded, never swallowed silently
        return f"{type(exc).__name__}: {exc}"
    return ""


# -- one full cycle ----------------------------------------------------------

def _cycle(target, window, obs, neutral, accent, *, index, style="bars",
           hooks=None) -> dict:
    """Hover the target, traverse into the card, hold, return, leave.

    Every phase records the point the probe asked the OS cursor to hold.  If
    the system cursor departs from it (another process, a remote session or a
    human hand is driving the pointer), the cycle is INVALIDATED rather than
    blamed on the UI: a measurement of a pointer that is not where the probe
    put it says nothing about the product.
    """
    hooks = hooks or {}
    runner = Runner(window, target)
    focus_baseline = int(getattr(window, "_focus_lock_count", 0))
    row: dict = {
        "cycle": index,
        "target": _target_name(window, target),
        "style": style,
        "target_blocker": "",
        "takeover": False,
        "invalid_reason": "",
        "cursor_drift_max": 0,
        "targeted": False,
        "opened": False,
        "open_latency_ms": None,
        "phases": {},
        "card_entered": False,
        "crossed_gap": False,
        "gap_px": None,
        "presentations_max": 0,
        "native_tooltip_visible": False,
        "rebuild_on_return": False,
        "refresh_geometry_drift": None,
        "refresh_errors": [],
        "border_golden": False,
        "border": {},
        "card_geometry": [0, 0],
        "card_content_chars": 0,
        "hide_latency_ms": None,
        "focus_lock_baseline": focus_baseline,
        "focus_lock_after": focus_baseline,
        "focus_lock_max": 0,
        "window_visible": True,
        "window_hidden": False,
        "show_events": 0,
        "hide_events": 0,
        "sound_calls": 0,
    }
    shows0, hides0, sounds0 = obs.show_events, obs.hide_events, obs.sounds
    phase_objs: list[Phase] = []

    def finish(reason: str = "") -> dict:
        row["presentations_max"] = max(
            (phase.total_max for phase in phase_objs), default=0)
        row["focus_lock_max"] = max(
            (phase.focus_max for phase in phase_objs), default=0)
        row["window_hidden"] = any(
            phase.window_hidden_samples for phase in phase_objs)
        row["window_visible"] = bool(window.isVisible())
        row["focus_lock_after"] = int(
            getattr(window, "_focus_lock_count", 0))
        row["show_events"] = obs.show_events - shows0
        row["hide_events"] = obs.hide_events - hides0
        row["sound_calls"] = obs.sounds - sounds0
        row["cursor_drift_max"] = max(
            (phase.drift_max for phase in phase_objs), default=0)
        if reason:
            row["takeover"] = True
            row["invalid_reason"] = reason
            # Hand the pointer back the moment the cycle stops being ours.
            _restore_cursor()
        return row

    QToolTip.hideText()
    _pump(120)
    fired = {"open": False, "enter": False}

    def dispatch(sample):
        """Fire the one-shot hooks on the observation that triggers them."""
        if sample["own_visible"] and not fired["open"]:
            fired["open"] = True
            hook = hooks.get("on_open")
            if hook is not None:
                hook()
        if sample["over_card"] and not fired["enter"]:
            fired["enter"] = True
            hook = hooks.get("on_enter")
            if hook is not None:
                hook()

    def on_hover(elapsed, sample, phase):
        dispatch(sample)

    def settled(elapsed, sample, phase):
        return (phase.first_visible_ms is not None
                and elapsed - phase.first_visible_ms >= NATIVE_TOOLTIP_SETTLE_MS)

    anchor_point = target.mapToGlobal(target.rect().center())
    targeted, reason, blocker = _move_onto(target)
    row["targeted"] = targeted
    row["target_blocker"] = blocker
    if reason in ("pulled", "foreign"):
        return finish("the pointer could not be taken: "
                      + ("it was moved by someone else" if reason == "pulled"
                         else "another window owns the desktop"))
    # An untargeted hover cannot validate the cursor: the probe never asked
    # the pointer to be there, so there is nothing to attribute.
    hover = runner.phase("hover", 2600, on_sample=on_hover, until=settled,
                         expect=anchor_point if targeted else None)
    row["phases"]["hover"] = hover.as_dict()
    phase_objs.append(hover)
    row["opened"] = hover.first_visible_ms is not None
    row["open_latency_ms"] = hover.first_visible_ms
    if hover.invalidated:
        return finish("the cursor left the hover target on its own")

    card = _own_card(target, visible_only=True)
    if card is None:
        # Nothing to traverse into; still abandon the surface and measure.
        QCursor.setPos(neutral)
        _pump(HIDE_GRACE_MS + HIDE_SLACK_MS)
        return finish()

    path, gap_px = _traversal_path(target, card)
    row["gap_px"] = gap_px
    #: The point the probe last asked the OS cursor to hold.  Comparing a
    #: sample against an index-derived point instead measured the probe's own
    #: one-step lag and called it external interference, so the expectation
    #: is the last REQUEST, always.
    requested = {"point": path[0]}
    QCursor.setPos(requested["point"])
    _pump(TRAVERSE_STEP_MS)

    def step_traverse(elapsed, sample, phase):
        point = path[min(len(path) - 1, elapsed // TRAVERSE_STEP_MS)]
        if point != requested["point"]:
            requested["point"] = point
            QCursor.setPos(point)

    def on_traverse(elapsed, sample, phase):
        dispatch(sample)
        step_traverse(elapsed, sample, phase)

    traverse = runner.phase(
        "traverse", len(path) * TRAVERSE_STEP_MS + 80,
        on_sample=on_traverse,
        expect=lambda elapsed: requested["point"])
    row["phases"]["traverse"] = traverse.as_dict()
    phase_objs.append(traverse)
    row["crossed_gap"] = traverse.gap_samples > 0 or (gap_px or 0) <= 0
    row["card_entered"] = traverse.over_card_samples > 0
    if traverse.invalidated:
        return finish("the cursor left the traversal path on its own")

    geometry_before = [card.x(), card.width()]
    refresh_errors: list[str] = []
    marks = [120, 320, 520]

    def on_hold(elapsed, sample, phase):
        while marks and elapsed >= marks[0]:
            marks.pop(0)
            error = _inject_refresh(window, target)
            if error:
                refresh_errors.append(error)

    hold_point = path[-1]
    hold = runner.phase("hold_in_card", HIDE_GRACE_MS + HOLD_EXTRA_MS,
                        on_sample=on_hold, expect=hold_point)
    row["phases"]["hold_in_card"] = hold.as_dict()
    phase_objs.append(hold)
    geometry_after = [card.x(), card.width()]
    row["refresh_errors"] = refresh_errors
    row["refresh_geometry_drift"] = {
        "x": geometry_after[0] - geometry_before[0],
        "width": geometry_after[1] - geometry_before[1],
    }
    if hold.invalidated:
        return finish("the cursor left the card on its own")

    border = _border_report(card, accent)
    row["border_golden"] = bool(border.get("ok"))
    row["border"] = border
    row["card_geometry"] = [card.width(), card.height()]
    row["card_content_chars"] = len(_card_text(card))

    shows_before_back = obs.show_events
    sounds_before_back = obs.sounds
    back_path = [path[-1], anchor_point]

    def step_back(elapsed, sample, phase):
        point = back_path[min(len(back_path) - 1, elapsed // 70)]
        if point != requested["point"]:
            requested["point"] = point
            QCursor.setPos(point)

    back = runner.phase(
        "back_on_anchor", 2 * 70 + 60,
        on_sample=step_back,
        expect=lambda elapsed: requested["point"])
    row["phases"]["back_on_anchor"] = back.as_dict()
    phase_objs.append(back)
    row["rebuild_on_return"] = (obs.show_events != shows_before_back
                                or obs.sounds != sounds_before_back)
    if back.invalidated:
        return finish("the cursor left the way back on its own")

    timeline = {"leave_at": None, "hidden_at": None}

    def watch_hide(elapsed, sample, phase):
        if (timeline["leave_at"] is not None
                and timeline["hidden_at"] is None
                and sample["own_visible"] == 0
                and sample["visible"] == 0):
            timeline["hidden_at"] = time.monotonic()

    requested["point"] = neutral
    QCursor.setPos(neutral)
    timeline["leave_at"] = time.monotonic()
    grace = runner.phase("grace", GRACE_PROBE_MS, on_sample=watch_hide,
                         expect=neutral)
    row["phases"]["grace"] = grace.as_dict()
    phase_objs.append(grace)
    if grace.invalidated:
        return finish("the cursor left the neutral point on its own")
    after = runner.phase(
        "after_grace",
        HIDE_GRACE_MS + HIDE_SLACK_MS - GRACE_PROBE_MS,
        on_sample=watch_hide, expect=neutral)
    row["phases"]["after_grace"] = after.as_dict()
    phase_objs.append(after)
    if after.invalidated:
        return finish("the cursor left the neutral point on its own")

    row["hide_latency_ms"] = (
        None if timeline["hidden_at"] is None
        else int((timeline["hidden_at"] - timeline["leave_at"]) * 1000))
    row["native_tooltip_visible"] = any(
        phase.tooltip_samples
        for phase in (hover, traverse, hold, back))
    return finish()


def _target_name(window, target) -> str:
    if target is getattr(window, "limit_gauges", None):
        return "gauge"
    if target is getattr(window, "lbl_limit_timer", None):
        return "reset"
    return "unknown"


def _wait_card(target, ms: int):
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        card = _own_card(target, visible_only=True)
        if card is not None:
            return card
        _pump(20)
    return None


def _settle_at(point, ms: int = 60) -> bool:
    """Put the cursor on ``point`` and confirm the OS kept it there."""
    QCursor.setPos(point)
    _pump(ms)
    try:
        position = QCursor.pos()
    except (RuntimeError, AttributeError):
        return False
    return (max(abs(position.x() - point.x()),
                abs(position.y() - point.y())) <= CURSOR_DRIFT_TOLERANCE_PX)


def _switch_cycle(gauge, label, window, obs, neutral, *, index) -> dict:
    """Rapid switching between the two hover targets."""
    row = {"cycle": index, "target": "switching", "findings": [],
           "takeover": False, "invalid_reason": "", "sound_calls": 0}

    def fail(code, detail):
        row["findings"].append({"code": code, "detail": detail})

    def void(reason):
        row["takeover"] = True
        row["invalid_reason"] = reason
        return row

    gauge_point = gauge.mapToGlobal(gauge.rect().center())
    label_point = label.mapToGlobal(label.rect().center())
    QToolTip.hideText()
    _pump(120)
    focus_baseline = int(getattr(window, "_focus_lock_count", 0))
    sounds0 = obs.sounds

    targeted, reason, blocker = _move_onto(gauge)
    if reason in ("pulled", "foreign"):
        return void(f"the pointer could not be taken ({reason})")
    if not targeted:
        fail("CYCLE_NOT_TARGETED", f"gauge covered by {blocker or 'the layout'}")
    gauge_card = _wait_card(gauge, 1600)
    if gauge_card is None:
        fail("NOT_OPENED", "gauge")
    gauge_text = _card_text(gauge_card) if gauge_card is not None else ""

    if not _settle_at(label_point):
        return void("the cursor was moved during the switch")
    label_card = _wait_card(label, 1600)
    if label_card is None:
        fail("NOT_OPENED", "reset")
    visible = LimitHoverCard.visible_cards()
    if len(visible) > 1:
        fail("DOUBLE_PRESENTATION", f"{len(visible)} cards visible")
    if label_card is not None:
        if _anchor_of(label_card) is not label:
            fail("STALE_POPUP_AFTER_SWITCH",
                 "the visible card is not anchored to the reset label")
        label_text = _card_text(label_card)
        if gauge_text and label_text == gauge_text:
            fail("STALE_CONTENT", "the reset hover shows the gauge content")
    if gauge_card is not None:
        try:
            still = not sip.isdeleted(gauge_card) and gauge_card.isVisible()
        except RuntimeError:
            still = False
        if still:
            fail("STALE_POPUP_AFTER_SWITCH", "the gauge card is still visible")

    if not _settle_at(gauge_point):
        return void("the cursor was moved during the switch back")
    if _wait_card(gauge, 1600) is None:
        fail("NOT_OPENED", "gauge after switching back")
    visible = LimitHoverCard.visible_cards()
    if len(visible) > 1:
        fail("DOUBLE_PRESENTATION",
             f"{len(visible)} cards visible after the return")

    if not _settle_at(neutral, 40):
        return void("the cursor was moved away from the neutral point")
    _pump(HIDE_GRACE_MS + HIDE_SLACK_MS)
    if LimitHoverCard.visible_cards():
        fail("NOT_HIDDEN_AFTER_LEAVE", "a card survived the grace interval")
    if int(getattr(window, "_focus_lock_count", 0)) != focus_baseline:
        fail("FOCUS_LOCK_LEAK",
             f"focus lock {window._focus_lock_count} != {focus_baseline}")
    if not window.isVisible():
        fail("WINDOW_HIDDEN", "the main window was hidden")
    row["sound_calls"] = obs.sounds - sounds0
    return row


# -- the acceptance predicate ------------------------------------------------

def _evaluate_cycle(row: dict) -> list[dict]:
    """Every requirement a single cycle must satisfy."""
    findings: list[dict] = []

    def fail(code, detail):
        findings.append({"code": code, "cycle": row.get("cycle"),
                         "target": row.get("target"), "detail": detail})

    if row.get("takeover"):
        # The pointer was not where this probe put it, so nothing in this
        # cycle describes the product.  Report the void measurement, never a
        # product failure.
        fail("CURSOR_TAKEOVER",
             row.get("invalid_reason") or "the system cursor was moved")
        return findings

    if not row.get("targeted"):
        fail("CYCLE_NOT_TARGETED",
             "the pointer never landed on the requested target")
    if not row.get("opened"):
        fail("NOT_OPENED",
             f"no card within {MAX_OPEN_LATENCY_MS} ms of the hover")
    latency = row.get("open_latency_ms")
    if row.get("opened") and (latency is None or latency > MAX_OPEN_LATENCY_MS):
        fail("OPEN_LATENCY", f"first entry took {latency} ms")
    if row.get("presentations_max", 0) > 1:
        fail("DOUBLE_PRESENTATION",
             f"{row['presentations_max']} presentations at once")
    if row.get("native_tooltip_visible"):
        fail("NATIVE_TOOLTIP", "a native QToolTip was visible beside the card")

    phases = row.get("phases") or {}
    hover = phases.get("hover") or {}
    if hover and (hover.get("own_visible_min") or 0) < 1:
        fail("HOVER_GAP", "the card was not visible for the whole hover")
    traverse = phases.get("traverse") or {}
    if not traverse:
        fail("PHASE_MISSING", "traverse")
    elif not row.get("card_entered"):
        fail("CARD_NOT_ENTERED", "the pointer never entered the visible card")
    elif (traverse.get("own_visible_min") or 0) < 1:
        fail("TRAVERSE_GAP", "the card vanished while crossing the gap")
    if traverse and not row.get("crossed_gap"):
        fail("TRAVERSE_GAP", "the pointer never crossed the intervening gap")
    hold = phases.get("hold_in_card") or {}
    if not hold:
        fail("PHASE_MISSING", "hold_in_card")
    elif (hold.get("own_visible_min") or 0) < 1:
        fail("CARD_HIDDEN_WHILE_INSIDE",
             "the card closed while the pointer rested on it")
    if (hold.get("own_visible_max") or 0) > 1:
        fail("DOUBLE_PRESENTATION", "two cards while holding")
    if row.get("refresh_errors"):
        fail("REFRESH_ERROR", row["refresh_errors"][0])
    drift = row.get("refresh_geometry_drift") or {}
    if drift and (abs(drift.get("x", 0)) > GEOMETRY_TOLERANCE_PX
                  or drift.get("width", 0) < 0):
        fail("GEOMETRY_JUMP",
             f"an open card moved on refresh: x {drift.get('x')}, "
             f"width {drift.get('width')}")
    back = phases.get("back_on_anchor") or {}
    if not back:
        fail("PHASE_MISSING", "back_on_anchor")
    elif (back.get("own_visible_min") or 0) < 1:
        fail("CLOSED_ON_RETURN", "the card closed when the pointer returned")
    if row.get("rebuild_on_return"):
        fail("REBUILD_ON_RETURN",
             "returning to the gauge re-showed the card (new Show event/sound)")
    grace = phases.get("grace") or {}
    if not grace:
        fail("PHASE_MISSING", "grace")
    elif grace.get("hidden_samples"):
        fail("CLOSED_WITHIN_GRACE",
             "the card closed inside the permitted grace interval")
    after = phases.get("after_grace") or {}
    if not after:
        fail("PHASE_MISSING", "after_grace")
    elif after.get("end_visible"):
        # The window opens while the permitted grace interval is still
        # running, so only the END of the window says the card is stale.
        fail("NOT_HIDDEN_AFTER_LEAVE",
             "the card survived both surfaces being abandoned")
    hide_ms = row.get("hide_latency_ms")
    if after and not after.get("end_visible"):
        if hide_ms is None:
            fail("AUTO_HIDE_TIMING", "no observed close transition")
        elif not (HIDE_GRACE_MS - 120 <= hide_ms
                  <= HIDE_GRACE_MS + HIDE_SLACK_MS):
            fail("AUTO_HIDE_TIMING", f"closed {hide_ms} ms after departure")
    if int(row.get("focus_lock_after", 0)) != int(
            row.get("focus_lock_baseline", 0)):
        fail("FOCUS_LOCK_LEAK",
             f"focus lock {row.get('focus_lock_after')} after leave, "
             f"baseline {row.get('focus_lock_baseline')}")
    if row.get("window_hidden") or not row.get("window_visible", True):
        fail("WINDOW_HIDDEN", "the main window was hidden or minimised")
    if not row.get("border_golden"):
        fail("BORDER_MISSING",
             f"accent border not intact: {row.get('border')}")
    if int(row.get("card_content_chars") or 0) < MIN_CARD_CONTENT_CHARS:
        fail("CARD_CONTENT_EMPTY",
             f"{row.get('card_content_chars')} chars rendered")
    if int(row.get("sound_calls") or 0) != 1:
        fail("SOUND_COUNT",
             f"{row.get('sound_calls')} hover sounds for one card session")
    if int(row.get("hide_events") or 0) < 1:
        fail("NO_HIDE_EVENT", "no real Hide event was delivered to the card")
    return findings


def _evaluate(report: dict) -> dict:
    findings: list[dict] = []
    failed_cycles: list[dict] = []

    def fail(code, detail, **extra):
        entry = {"code": code, "detail": detail}
        entry.update(extra)
        findings.append(entry)

    if report.get("platform") != "windows":
        fail("PLATFORM_NOT_WINDOWS",
             f"ran on {report.get('platform')!r}; this probe must use the "
             "real Windows plugin")
    controls = report.get("negative_controls")
    invalidated: list[dict] = []
    # A control run measures the ORACLE, not the product: the injected fault
    # is the subject, so the clean-cycle requirements are not replayed here.
    if controls is None:
        cycles = report.get("cycles") or []
        expected = (report.get("cycles_per_target", 0)
                    * len(report.get("targets", {})))
        stopped = report.get("stopped_reason")
        if stopped:
            # The probe chose not to take the pointer from a person, so this
            # run is incomplete by design, never a product verdict.
            invalidated.append({"cycle": None, "target": "all",
                                "detail": f"stopped early: {stopped}"})
        elif len(cycles) != expected:
            fail("CYCLE_COUNT",
                 f"{len(cycles)} cycles measured, {expected} requested")
        for name in sorted(report.get("targets") or {}):
            rows = [row for row in cycles if row.get("target") == name]
            if not rows:
                if stopped:
                    invalidated.append({"cycle": None, "target": name,
                                        "detail": "not measured before the "
                                                  "stop"})
                else:
                    fail("TARGET_UNMEASURED", name)
                continue
            if not rows[0].get("opened"):
                fail("FIRST_HOVER_MISSED",
                     f"{name}: the first hover opened nothing")
        for row in cycles:
            row_findings = _evaluate_cycle(row)
            if not row_findings:
                continue
            if row.get("takeover"):
                invalidated.append({
                    "cycle": row.get("cycle"),
                    "target": row.get("target"),
                    "detail": row.get("invalid_reason"),
                    "cursor_drift_max": row.get("cursor_drift_max"),
                })
                continue
            failed_cycles.append({
                "cycle": row.get("cycle"),
                "target": row.get("target"),
                "codes": [f["code"] for f in row_findings]})
            findings.extend(row_findings)
        for row in report.get("switching") or []:
            if row.get("takeover"):
                invalidated.append({"cycle": row.get("cycle"),
                                    "target": "switching",
                                    "detail": row.get("invalid_reason")})
                continue
            for finding in row.get("findings") or []:
                entry = {"code": finding["code"],
                         "detail": finding["detail"],
                         "cycle": row.get("cycle"), "target": "switching"}
                findings.append(entry)
                failed_cycles.append({"cycle": row.get("cycle"),
                                      "target": "switching",
                                      "codes": [finding["code"]]})

    controls_failed = []
    if controls is not None:
        baseline = controls.get("baseline") or {}
        if baseline.get("findings"):
            controls_failed.append("baseline_clean_cycle_rejected")
        for control in controls.get("controls") or []:
            if control.get("invalidated"):
                controls_failed.append(
                    f"{control.get('name')}:cursor_takeover")
                continue
            if not control.get("caught"):
                controls_failed.append(control.get("name"))
            elif control.get("expected") not in control.get("codes", []):
                controls_failed.append(control.get("name"))
    return {
        "passed": not findings and not controls_failed and not invalidated,
        "findings": findings,
        "failed_cycles": failed_cycles,
        "invalidated": invalidated,
        "controls_failed": controls_failed,
        "checked_cycles": len(report.get("cycles") or []),
        "mode": "negative_controls" if controls is not None else "acceptance",
        "requirements": _REQUIREMENTS,
    }


_REQUIREMENTS = [
    "every requested cycle targets its widget",
    "the card opens on the first hover and within MAX_OPEN_LATENCY_MS",
    "exactly one presentation is on screen at any moment",
    "no native QToolTip is visible beside the card",
    "the card stays visible while the pointer crosses the gap into it",
    "the card stays visible while the pointer rests on it (beyond HIDE_GRACE_MS)",
    "a content refresh neither closes nor moves the open card",
    "returning to the gauge does not re-show the card",
    "the card survives the permitted grace interval",
    "the card closes within HIDE_GRACE_MS + HIDE_SLACK_MS of departure",
    "no focus lock leaks and the main window stays visible",
    "the 2 px accent border and the card content are intact",
    "exactly one hover sound per card session",
    "every injected fault makes this oracle fail",
]


# -- negative controls -------------------------------------------------------

def _patch(obj, attr, value):
    real = getattr(obj, attr)
    setattr(obj, attr, value)

    def restore():
        setattr(obj, attr, real)

    return restore


#: Probe hygiene counters: things the HARNESS had to repair after an
#: abandoned measurement.  Kept visible in the report so a hard reset can
#: never be mistaken for a product observation.
HYGIENE = {"focus_lock_hard_resets": 0}


def _reset_state(window, neutral) -> None:
    """Return the window to a clean hover state between measurements."""
    QToolTip.hideText()
    QCursor.setPos(neutral)
    for card in list(LimitHoverCard._live_cards):
        try:
            if not sip.isdeleted(card):
                card.hide_now()
        except (RuntimeError, TypeError):
            continue
    _pump(250)
    if not window.isVisible():
        window.show()
        _pump(250)
    window.raise_()          # non-activating; keeps the header on top
    _pump(120)
    _restore_cursor()
    if int(getattr(window, "_focus_lock_count", 0)) != 0:
        # A cycle abandoned mid-flight leaves the card's lock behind.  That is
        # harness debris, not a product finding, so it is counted and then
        # cleared before the next measurement starts from a real baseline.
        HYGIENE["focus_lock_hard_resets"] += 1
        window._focus_lock_count = 0


def _measure_cycle(target, window, obs, neutral, accent, *, index,
                   style="bars", hooks=None, report=None) -> dict:
    """One cycle, retried while something else drives the pointer."""
    last: dict = {}
    attempts = 0
    for attempt in range(TAKEOVER_RETRIES + 1):
        attempts = attempt + 1
        last = _cycle(target, window, obs, neutral, accent, index=index,
                      style=style, hooks=hooks)
        if not last.get("takeover"):
            break
        if report is not None:
            report["cursor_takeovers"] = (
                report.get("cursor_takeovers", 0) + 1)
        print(f"[probe] cycle {index} {last.get('target')} invalidated "
              f"({last.get('invalid_reason')}); retrying", flush=True)
        _reset_state(window, neutral)
        gate = POLICY.get("gate")
        if gate is not None and POLICY["patient"]:
            # Patient mode: do not fight the human.  Wait for the next pause.
            gate.wait_for_quiet(POLICY["idle_ms"], 0, patient=True)
    last["attempts"] = attempts
    return last


def _run_control(name, window, gauge, neutral, accent) -> dict:
    """Inject one fault and require the oracle to reject the cycle."""
    row = {"name": name, "expected": None, "caught": False, "codes": [],
           "detail": ""}
    restores = []
    hooks: dict = {}
    holder: dict = {}
    try:
        if name == "native_tooltip":
            row["expected"] = "NATIVE_TOOLTIP"

            def show_native(card=None, target=gauge):
                QToolTip.showText(target.mapToGlobal(target.rect().center()),
                                  "injected native tooltip", target)
            hooks["on_open"] = show_native
        elif name == "two_cards":
            row["expected"] = "DOUBLE_PRESENTATION"

            def duplicate(target=gauge):
                dup = LimitHoverCard(target)
                dup.set_html("<b>duplicate presentation</b>")
                dup.reposition()
                dup.show()
                holder["dup"] = dup
            hooks["on_open"] = duplicate
        elif name == "no_open":
            row["expected"] = "NOT_OPENED"
            restores.append(_patch(LimitHoverCard, "show_card",
                                   lambda self, html: None))
        elif name == "close_inside":
            row["expected"] = "CARD_HIDDEN_WHILE_INSIDE"

            def close_inside(target=gauge):
                card = _own_card(target, visible_only=True)
                if card is not None:
                    card.hide()
            hooks["on_enter"] = close_inside
        elif name == "stale_card":
            # The grace timer's connection holds a BOUND method made at
            # __init__, so patching ``_maybe_hide`` on the class would be a
            # silent no-op on an existing card.  The lifecycle call that is
            # actually looked up on the instance is ``schedule_hide``.
            row["expected"] = "NOT_HIDDEN_AFTER_LEAVE"
            restores.append(_patch(LimitHoverCard, "schedule_hide",
                                   lambda self: None))
        elif name == "no_border":
            row["expected"] = "BORDER_MISSING"
            restores.append(_patch(LimitHoverCard, "_border_color",
                                   lambda self: QColor(0, 0, 0, 0)))
        elif name == "focus_leak":
            row["expected"] = "FOCUS_LOCK_LEAK"
            restores.append(_patch(LimitHoverCard, "_release_focus_lock",
                                   lambda self: None))
        elif name == "window_hide":
            row["expected"] = "WINDOW_HIDDEN"
            hooks["on_open"] = window.hide
        elif name == "skip_cycle":
            row["expected"] = "CYCLE_NOT_TARGETED"
            restores.append(_patch(sys.modules[__name__], "_move_onto",
                                   lambda target: (False, False)))
        else:
            row["detail"] = "unknown control"
            return row

        observed = _measure_cycle(gauge, window, _observer(), neutral, accent,
                                  index=0, hooks=hooks)
        row["attempts"] = observed.get("attempts")
        row["observations"] = _control_facts(observed)
        if observed.get("takeover"):
            row["invalidated"] = True
            row["detail"] = observed.get("invalid_reason") or "cursor takeover"
            row["caught"] = False
            return row
        findings = _evaluate_cycle(observed)
        row["codes"] = [finding["code"] for finding in findings]
        row["caught"] = bool(findings)
    except Exception as exc:
        row["detail"] = f"{type(exc).__name__}: {exc}"
        row["codes"] = []
        row["caught"] = False
    finally:
        for restore in restores:
            try:
                restore()
            except Exception:
                pass
        restores.clear()
        for widget in holder.values():
            try:
                widget.hide_now()
                retire(widget)
            except Exception:
                pass
        QToolTip.hideText()
    return row


def _control_facts(row: dict) -> dict:
    return {
        "opened": row.get("opened"),
        "presentations_max": row.get("presentations_max"),
        "native_tooltip_visible": row.get("native_tooltip_visible"),
        "card_entered": row.get("card_entered"),
        "rebuild_on_return": row.get("rebuild_on_return"),
        "hide_latency_ms": row.get("hide_latency_ms"),
        "border_golden": row.get("border_golden"),
        "focus_lock_after": row.get("focus_lock_after"),
        "window_hidden": row.get("window_hidden"),
        "targeted": row.get("targeted"),
        "sound_calls": row.get("sound_calls"),
        "takeover": row.get("takeover"),
    }


_ACTIVE_OBSERVER: Observer | None = None


def _observer() -> Observer:
    assert _ACTIVE_OBSERVER is not None
    return _ACTIVE_OBSERVER


# -- harness -----------------------------------------------------------------

def _window_setup() -> FastPrompter:
    global _ACTIVE_OBSERVER
    observer = Observer()
    observer.install_hooks()
    QApplication.instance().installEventFilter(observer)
    _ACTIVE_OBSERVER = observer

    state_mod.get_db_path = lambda profile_id=1: str(
        Path(os.environ.get("TEMP", ".")) / f"t1482_probe_{profile_id}.db")
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    from fastprompter.core.usage_limits.service import UsageLimitService
    UsageLimitService.schedule_auto = lambda *a, **kw: None
    build = UsageLimitService._build_providers

    def local_providers(self):
        providers = build(self)
        providers.pop("zcode", None)
        providers.pop("freebuff", None)
        return providers

    UsageLimitService._build_providers = local_providers

    window = FastPrompter()
    window.data["limit_gauges"] = "True"
    _install_snapshots(window, {
        "claude:s1": _snapshot(epoch=time.time() + 3600),
        "codex:s1": _snapshot("codex", "s2", "Codex",
                              epoch=time.time() + 7200),
    })
    window._update_limit_timer_label()
    # Show without stealing focus: the person at the keyboard keeps typing.
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.show()
    area = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(area.x() + 60, area.y() + 60, 960, 600)
    window.raise_()
    _pump(1200)
    return window


def _summarize(rows: list[dict]) -> dict:
    def phase(row, name):
        return (row.get("phases") or {}).get(name) or {}

    voided = sum(1 for row in rows if row.get("takeover"))
    rows = [row for row in rows if not row.get("takeover")]
    hide_latencies = [row["hide_latency_ms"] for row in rows
                      if row.get("hide_latency_ms") is not None]
    return {
        "cycles": len(rows),
        "voided": voided,
        "styles": sorted({row.get("style") for row in rows}),
        "all_targeted": all(row.get("targeted") for row in rows),
        "all_opened": all(row.get("opened") for row in rows),
        "first_hover_opened": bool(rows and rows[0].get("opened")),
        "max_open_latency_ms": max(
            (row.get("open_latency_ms") or 0 for row in rows), default=0),
        "max_presentations": max(
            (row.get("presentations_max") or 0 for row in rows), default=0),
        "native_tooltip_seen": any(row.get("native_tooltip_visible")
                                   for row in rows),
        "traverse_gaps": sum(
            1 for row in rows
            if (phase(row, "traverse").get("own_visible_min") or 0) < 1),
        "cards_entered": sum(1 for row in rows if row.get("card_entered")),
        "gaps_crossed": sum(1 for row in rows if row.get("crossed_gap")),
        "hold_visibility_failures": sum(
            1 for row in rows
            if (phase(row, "hold_in_card").get("own_visible_min") or 0) < 1),
        "closed_within_grace": sum(
            1 for row in rows
            if phase(row, "grace").get("hidden_samples")),
        "rebuilds_on_return": sum(1 for row in rows
                                  if row.get("rebuild_on_return")),
        "focus_lock_leaks": sum(1 for row in rows
                                if row.get("focus_lock_after")),
        "window_hidden": sum(1 for row in rows if row.get("window_hidden")),
        "border_failures": sum(1 for row in rows
                               if not row.get("border_golden")),
        "sound_total": sum(row.get("sound_calls") or 0 for row in rows),
        "min_card_content_chars": min(
            (row.get("card_content_chars") or 0 for row in rows), default=0),
        "hide_latency_ms": {
            "min": min(hide_latencies, default=None),
            "max": max(hide_latencies, default=None),
            "grace_ms": HIDE_GRACE_MS,
        },
        "card_geometry_first": rows[0].get("card_geometry") if rows else [0, 0],
    }


def _probe_digest() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return ""


def _version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--switch-cycles", type=int, default=3)
    parser.add_argument("--no-switch", action="store_true")
    parser.add_argument("--json", default="")
    parser.add_argument("--negative-control", nargs="*", default=None,
                        metavar="NAME",
                        help=f"inject one fault and require the oracle to "
                             f"reject it; names: {', '.join(CONTROL_NAMES)}, "
                             f"or 'all'")
    parser.add_argument("--idle-ms", type=int, default=IDLE_GATE_MS,
                        help="how quiet the desktop must be before a cycle")
    parser.add_argument("--max-wait-s", type=float, default=MAX_QUIET_WAIT_S,
                        help="how long to wait for that quiet window")
    parser.add_argument("--no-wait", action="store_true",
                        help="DEDICATED MACHINE ONLY: do not wait for idle")
    parser.add_argument("--keep-cursor", action="store_true",
                        help="do not restore the pointer position on exit")
    parser.add_argument("--audible", action="store_true",
                        help="actually play the hover sound (default: silent)")
    parser.add_argument("--patient", action="store_true",
                        help="keep waiting for pauses indefinitely; borrow the "
                             "mouse one cycle at a time and hand it back")
    parser.add_argument("--plan", action="store_true",
                        help="print what would run and exit without touching "
                             "the pointer or the screen")
    args = parser.parse_args(argv)

    if args.plan:
        print(json.dumps({
            "mode": "plan (nothing was started, no pointer taken)",
            "platform": os.environ.get("QT_QPA_PLATFORM"),
            "cycles_per_target": args.cycles,
            "targets": ["gauge (AI Limit Meters)", "reset (Nearest Resets)"],
            "switch_cycles": 0 if args.no_switch else args.switch_cycles,
            "negative_controls": (list(CONTROL_NAMES)
                                  if args.negative_control is not None
                                  else []),
            "policy": {
                "idle_gate_ms": args.idle_ms,
                "max_wait_s": args.max_wait_s,
                "patient": args.patient,
                "restore_cursor": not args.keep_cursor,
                "silent": not args.audible,
            },
        }, indent=2))
        return 0

    POLICY["wait_for_quiet"] = not args.no_wait
    POLICY["restore_cursor"] = not args.keep_cursor
    POLICY["audible"] = bool(args.audible)
    POLICY["patient"] = bool(args.patient)
    POLICY["idle_ms"] = args.idle_ms
    gate = DesktopGate()
    POLICY["gate"] = gate
    if args.no_wait:
        print("[probe] WARNING: --no-wait takes the pointer without waiting "
              "for the desktop to be idle; use it only on a machine nobody "
              "is working on", file=sys.stderr)
    _cursor_home()

    app = QApplication.instance() or QApplication(sys.argv)
    window = None
    report: dict = {
        "probe": "tools/probe_tooltip_ownership.py",
        "ticket": "T-1483",
        "probe_sha256": _probe_digest(),
        "source_version": _version(),
        "platform": app.platformName(),
        "cycles_per_target": args.cycles,
        "thresholds": {
            "max_open_latency_ms": MAX_OPEN_LATENCY_MS,
            "native_tooltip_settle_ms": NATIVE_TOOLTIP_SETTLE_MS,
            "hide_grace_ms": HIDE_GRACE_MS,
            "hold_extra_ms": HOLD_EXTRA_MS,
            "grace_probe_ms": GRACE_PROBE_MS,
            "hide_slack_ms": HIDE_SLACK_MS,
            "min_card_content_chars": MIN_CARD_CONTENT_CHARS,
        },
        "cycles": [],
        "targets": {"gauge": [], "reset": []},
        "switching": [],
        "policy": {
            "idle_ms": args.idle_ms,
            "max_wait_s": args.max_wait_s,
            "patient": POLICY["patient"],
            "wait_for_quiet": POLICY["wait_for_quiet"],
            "restore_cursor": POLICY["restore_cursor"],
            "audible": POLICY["audible"],
        },
    }
    exit_code = 2
    try:
        window = _window_setup()
        observer = _observer()
        gauge = window.limit_gauges
        label = window.lbl_limit_timer
        accent = _accent(window)
        report["accent"] = accent.name()
        neutral = window.mapToGlobal(QPoint(window.width() // 2,
                                            window.height() // 2))

        control_names: list[str] = []
        if args.negative_control is not None:
            requested = args.negative_control or ["all"]
            control_names = (list(CONTROL_NAMES) if "all" in requested
                             else [name for name in requested
                                   if name in CONTROL_NAMES])

        if not control_names:
            styles = ("bars", "dots", "stack")

            def measure(target, index, style="bars"):
                return _measure_cycle(target, window, observer, neutral,
                                      accent, index=index, style=style,
                                      report=report)

            for index in range(args.cycles):
                if not gate.wait_for_quiet(args.idle_ms, args.max_wait_s):
                    report["stopped_reason"] = (
                        "the desktop stayed in use; the probe never took the "
                        f"pointer for cycle {index}")
                    print(f"[probe] desktop busy, stopping before cycle {index}",
                          flush=True)
                    break
                window.raise_()   # non-activating: never steals the keyboard
                style = styles[index % len(styles)]
                window.data["limit_gauges_style"] = style
                window.limit_gauges.refresh_view()
                _pump(140)
                print(f"[probe] cycle {index} gauge style={style}", flush=True)
                report["cycles"].append(measure(gauge, index, style))
                print(f"[probe] cycle {index} reset", flush=True)
                report["cycles"].append(measure(label, index, style))
            if not args.no_switch and not report.get("stopped_reason"):
                for index in range(args.switch_cycles):
                    if not gate.wait_for_quiet(args.idle_ms, args.max_wait_s):
                        report["stopped_reason"] = (
                            "the desktop stayed in use during switching")
                        break
                    print(f"[probe] switch {index}", flush=True)
                    _reset_state(window, neutral)
                    row = _switch_cycle(gauge, label, window, observer,
                                        neutral, index=index)
                    if row.get("takeover"):
                        report["cursor_takeovers"] = (
                            report.get("cursor_takeovers", 0) + 1)
                    report["switching"].append(row)
        else:
            print(f"[probe] negative controls: {', '.join(control_names)}",
                  flush=True)
            _reset_state(window, neutral)
            print("[probe] control baseline (clean cycle)", flush=True)
            baseline = _measure_cycle(gauge, window, observer, neutral,
                                      accent, index=-1)
            baseline_findings = _evaluate_cycle(baseline)
            report["negative_controls"] = {
                "baseline": {"findings": baseline_findings,
                             "facts": _control_facts(baseline)},
                "controls": [],
            }
            for name in control_names:
                if not gate.wait_for_quiet(args.idle_ms, args.max_wait_s):
                    report["stopped_reason"] = (
                        "the desktop stayed in use; the probe never took the "
                        f"pointer for control {name}")
                    break
                print(f"[probe] control {name}", flush=True)
                _reset_state(window, neutral)
                report["negative_controls"]["controls"].append(
                    _run_control(name, window, gauge, neutral, accent))
                _reset_state(window, neutral)

        for name in ("gauge", "reset"):
            rows = [row for row in report["cycles"]
                    if row.get("target") == name]
            report["targets"][name] = _summarize(rows)
        report["policy"]["waited_ms"] = POLICY["waited_ms"]
        report["hygiene"] = dict(HYGIENE)
        report["counters"] = {
            "show_events": observer.show_events,
            "hide_events": observer.hide_events,
            "sounds": observer.sounds,
            "show_calls_diagnostic": observer.show_calls,
            "hide_calls_diagnostic": observer.hide_calls,
        }
        report["acceptance"] = _evaluate(report)
        acceptance = report["acceptance"]
        if acceptance["passed"]:
            exit_code = 0
        elif (acceptance.get("invalidated")
              and not acceptance.get("findings")
              and not acceptance.get("controls_failed")):
            exit_code = 3
        else:
            exit_code = 1
    except Exception as exc:
        traceback.print_exc()
        report["acceptance"] = {
            "passed": False,
            "findings": [{"code": "HARNESS_ERROR", "detail": repr(exc)}],
            "failed_cycles": [],
            "controls_failed": [],
            "checked_cycles": len(report.get("cycles") or []),
            "requirements": _REQUIREMENTS,
        }
        exit_code = 2
    finally:
        if window is not None:
            print("[probe] teardown", flush=True)
            try:
                if getattr(window, "limit_service", None) is not None:
                    window.limit_service.shutdown()
            except Exception:
                pass
            try:
                window._wait_for_undo_saves()
                window.tray_icon.hide()
            except Exception:
                pass
            window.close()
            _pump(300)
            retire(window)
            _restore_cursor()
            print("[probe] teardown done", flush=True)
        if args.json:
            target = Path(args.json)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"written: {target}", flush=True)

    acceptance = report.get("acceptance") or {}
    print(json.dumps({
        "platform": report.get("platform"),
        "acceptance": {
            "passed": acceptance.get("passed"),
            "findings": len(acceptance.get("findings") or []),
            "failed_cycles": len(acceptance.get("failed_cycles") or []),
            "invalidated_cycles": len(acceptance.get("invalidated") or []),
            "controls_failed": acceptance.get("controls_failed"),
        },
        "cursor_takeovers": report.get("cursor_takeovers", 0),
        "targets": {name: {key: value for key, value in summary.items()
                           if key in ("cycles", "max_open_latency_ms",
                                      "max_presentations", "traverse_gaps",
                                      "cards_entered", "closed_within_grace",
                                      "rebuilds_on_return", "sound_total",
                                      "border_failures", "focus_lock_leaks")}
                    for name, summary in (report.get("targets") or {}).items()},
        "exit_code": exit_code,
    }, indent=2))
    for finding in (acceptance.get("findings") or [])[:12]:
        print(f"[FAIL] {finding.get('code')}: {finding.get('detail')}",
              file=sys.stderr)
    for void in (acceptance.get("invalidated") or [])[:6]:
        print(f"[VOID] cycle {void.get('cycle')} {void.get('target')}: "
              f"{void.get('detail')} (cursor drifted "
              f"{void.get('cursor_drift_max')} px)", file=sys.stderr)
    if acceptance.get("controls_failed"):
        print(f"[FAIL] controls not caught: {acceptance['controls_failed']}",
              file=sys.stderr)
    if exit_code == 3:
        reason = report.get("stopped_reason")
        if reason:
            print(f"[VOID] stopped before taking the pointer: {reason}. "
                  "Nothing was taken from you; re-run when the machine is "
                  "free or accept the measured cycles only.", file=sys.stderr)
        else:
            print("[VOID] another process or hand drove the system cursor; "
                  "the measurement says nothing about the product. Re-run "
                  "with the mouse untouched.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
