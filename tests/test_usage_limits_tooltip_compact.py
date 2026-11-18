"""Render real Qt rich text to catch invisible width reservations (T-1205)."""

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QLabel
from test_usage_limits_gauge_layout import (
    _account,
    _antigravity,
    _build,
    _codex,
)
from test_usage_limits_gauge_layout import (
    qapp as qapp,  # noqa: F401
)


def test_tooltip_fits_compact_width_with_banked_reset(qapp):
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    # T-1300: addApplicationFont is PROCESS-GLOBAL. Adding the real Verdana/
    # Consolas faces changes font metrics for every widget built afterwards, so
    # a later unrelated test (the combined gate's header-density suite) measured
    # different button widths. Own the font ids and remove them in teardown.
    _added_fonts = []
    for name in ("verdana.ttf", "verdanab.ttf", "consola.ttf"):
        path = fonts / name
        if path.exists():
            _added_fonts.append(QFontDatabase.addApplicationFont(str(path)))
    ag = _account("antigravity", "ag")
    c1 = _account("codex", "c1")
    c2 = _account("codex", "c2")
    ag_snap = _antigravity(ag)
    ag_snap = replace(ag_snap, windows=[
        replace(window, group_label="Gemini" if window.group == "g" else "Claude & GPT")
        for window in ag_snap.windows
    ])
    banked = replace(_codex(c2, five=100, weekly=53), banked_resets=1)
    gauges = _build(qapp, [ag, c1, c2], {
        ag.key: ag_snap, c1.key: _codex(c1, five=100, weekly=84),
        c2.key: banked,
    })
    label = QLabel(gauges._build_tooltip())
    font = QFont("Verdana")
    font.setPixelSize(11)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    label.setFont(font)
    label.setStyleSheet("background:#332E22; color:#D4C89A; padding:4px;")
    label.adjustSize()
    try:
        output = os.environ.get("FASTPROMPTER_VISUAL_DIR")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            label.grab().save(str(Path(output) / "ai-tooltip.png"))
        assert "53%" in label.text()
        assert "Claude &amp; GPT" in label.text()
        assert label.width() <= 390, label.width()
    finally:
        label.close()
        gauges.main_win.close()
        for _fid in _added_fonts:
            QFontDatabase.removeApplicationFont(_fid)


def test_antigravity_pools_rendered_consistently_as_gemini_and_claude_gpt(qapp):
    """Antigravity pools must always render as Gemini and Claude & GPT, never Pool 1 / Pool 2."""
    import time

    from fastprompter.core.usage_limits.model import OK, UsageSnapshot, UsageWindow
    ag2 = _account("antigravity", "ag2")
    time_now = time.time()
    # Simulate secondary account from plane with legacy / generic Pool 1 and Pool 2 labels
    windows = [
        UsageWindow(key="five_hour@pool0", duration_minutes=300, available=True,
                    used_percent=50.0, remaining_percent=50.0, resets_at_epoch=time_now + 7200,
                    group="pool0", group_label="Pool 1"),
        UsageWindow(key="weekly@pool0", duration_minutes=10080, available=True,
                    used_percent=42.0, remaining_percent=58.0, resets_at_epoch=time_now + 86400,
                    group="pool0", group_label="Pool 1"),
        UsageWindow(key="five_hour@pool1", duration_minutes=300, available=True,
                    used_percent=0.0, remaining_percent=100.0, resets_at_epoch=time_now + 14400,
                    group="pool1", group_label="Pool 2"),
        UsageWindow(key="weekly@pool1", duration_minutes=10080, available=True,
                    used_percent=0.0, remaining_percent=100.0, resets_at_epoch=time_now + 86400,
                    group="pool1", group_label="Pool 2"),
    ]
    snap = UsageSnapshot(account=ag2, status=OK, windows=windows, fetched_at=time_now)
    gauges = _build(qapp, [ag2], {ag2.key: snap})
    try:
        tt = gauges._build_tooltip()
        assert "Gemini 5h:" in tt
        assert "Gemini weekly:" in tt
        assert "Claude & GPT 5h:" in tt
        assert "Claude & GPT weekly:" in tt
        assert "Pool 1" not in tt
        assert "Pool 2" not in tt
    finally:
        gauges.main_win.close()


def test_antigravity_three_pools_includes_argon_and_shows_all_five_windows(qapp):
    """Antigravity with Gemini, Claude & GPT, and Gemini 4 Argon must display
    all 5 windows in both the tooltip and gauge marks without dropping Argon."""
    import time

    from fastprompter.core.usage_limits.model import OK, UsageSnapshot, UsageWindow
    from fastprompter.ui.limit_gauges import _cluster_windows

    ag = _account("antigravity", "ag1")
    now = time.time()
    windows = [
        UsageWindow(key="five_hour@gemini", duration_minutes=300, available=True,
                    used_percent=59.0, remaining_percent=41.0, resets_at_epoch=now + 7200,
                    group="gemini_models", group_label="Gemini Models"),
        UsageWindow(key="weekly@gemini", duration_minutes=10080, available=True,
                    used_percent=17.0, remaining_percent=83.0, resets_at_epoch=now + 86400,
                    group="gemini_models", group_label="Gemini Models"),
        UsageWindow(key="five_hour@claude_gpt", duration_minutes=300, available=True,
                    used_percent=0.0, remaining_percent=100.0, resets_at_epoch=now + 14400,
                    group="claude_and_gpt_models", group_label="Claude and GPT models"),
        UsageWindow(key="weekly@claude_gpt", duration_minutes=10080, available=True,
                    used_percent=51.0, remaining_percent=49.0, resets_at_epoch=now + 86400,
                    group="claude_and_gpt_models", group_label="Claude and GPT models"),
        UsageWindow(key="weekly@argon", duration_minutes=10080, available=True,
                    used_percent=64.0, remaining_percent=36.0, resets_at_epoch=now + 86400 * 6,
                    group="gemini_4_argon", group_label="Gemini 4 Argon"),
    ]
    snap = UsageSnapshot(account=ag, status=OK, windows=windows, fetched_at=now)
    gauges = _build(qapp, [ag], {ag.key: snap})
    try:
        tt = gauges._build_tooltip()
        assert "Gemini 5h:" in tt
        assert "Gemini weekly:" in tt
        assert "Claude & GPT 5h:" in tt
        assert "Claude & GPT weekly:" in tt
        assert "Gemini 4 Argon weekly:" in tt
        assert "36%" in tt

        cw = _cluster_windows(snap)
        assert len(cw) == 5
        assert gauges._bars_for(ag) == 5
    finally:
        gauges.main_win.close()

