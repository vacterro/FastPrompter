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
