"""T-1461: deterministic cross-Windows control rendering.

Measured defect (real Windows desktop, ``windowsvista`` style): Qt painted its
own sub-controls and IGNORED the theme stylesheet, so a themed dark dialog
carried a near-white radio indicator and ~1000 px of near-white inside every
silo table. The headless suite never saw it because the offscreen platform
resolves ``fusion``, which honours the stylesheet.

The contract these tests pin:

1. ``configure_deterministic_style()`` runs BEFORE ``QApplication(sys.argv)``
   in ``main_entry`` (the style is read once, at construction).
2. Under the native Windows platform the pin resolves the app to ``fusion``.
3. A themed dark control gallery renders with ZERO near-white pixels once the
   style is pinned -- the defect is the *unstyled* native sub-control.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.theme.themes import (  # noqa: E402
    THEMES,
    control_surfaces_qss,
    header_view_qss,
    scrollbar_qss,
)
from fastprompter.ui import qt_style  # noqa: E402

#: A dark theme whose styled surfaces are far from white. Vintage Classic is
#: deliberately pale (its own bg_text IS #ffffff), so it is excluded -- a
#: white pixel there is the theme's choice, not an unstyled artifact.
DARK_THEMES = ("Golden Default", "Golden Vintage", "Default", "Dark 2 (OLED)",
               "Dracula", "Nord", "Solarized Dark")


def _accent_is_near_white(theme_name: str) -> bool:
    """Dark 2 (OLED) chooses #ffffff as its accent, so a white checked dot is
    correct there -- the right contract is identity, not "never white"."""
    raw = THEMES[theme_name]["raw_colors"]
    c = raw["accent"].lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return r >= 245 and g >= 245 and b >= 245


#: Themes whose own palette guarantees a styled control can never be white.
NO_WHITE_THEMES = tuple(t for t in DARK_THEMES if not _accent_is_near_white(t))

def _near_white_count(image, threshold: int = 245) -> int:
    n = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.red() >= threshold and c.green() >= threshold and c.blue() >= threshold:
                n += 1
    return n

def _apply(app, theme_name: str) -> None:
    """Apply the SAME QSS stack ``apply_theme`` injects, in the same order.

    Omitting ``scrollbar_qss`` leaves Fusion's own white scrollbar groove in
    the frame, which is not an artifact of the style pin -- the app always
    injects it (``thin_scrollbars`` defaults on).
    """
    theme = THEMES[theme_name]
    raw = theme["raw_colors"]
    app.setStyleSheet(
        theme["stylesheet"] + scrollbar_qss(raw) + header_view_qss(raw)
        + control_surfaces_qss(raw))

class TestThePinIsDeterministic:
    def test_the_pin_is_the_documented_style(self):
        assert qt_style.DETERMINISTIC_STYLE == "Fusion"

    def test_the_pin_runs_before_the_application_is_built(self):
        """A style set after QApplication() is a no-op on some platforms, and
        the whole point is that it is read at construction."""
        from fastprompter import main as main_mod

        src = inspect.getsource(main_mod.main_entry)
        pin = src.index("configure_deterministic_style()")
        build = src.index("app = QApplication(sys.argv)")
        assert pin < build, "style must be pinned before QApplication exists"

    def test_the_pin_never_raises_when_fusion_is_unavailable(self, monkeypatch):
        """A machine without the Fusion style must still start the app."""
        from PyQt6.QtWidgets import QStyleFactory

        monkeypatch.setattr(QStyleFactory, "create", staticmethod(lambda name: None))
        assert qt_style.configure_deterministic_style() == ""

    def test_under_the_native_platform_the_pin_resolves_fusion(self):
        """The real defect platform is the native Windows plugin. A child
        process that pins before building the app must resolve to fusion even
        though the same platform defaults to windowsvista."""
        script = (
            "import os, sys;"
            "root=os.getcwd();"
            "sys.path.insert(0, os.path.join(root,'src'));"
            "from fastprompter.ui.qt_style import configure_deterministic_style;"
            "configure_deterministic_style();"
            "from PyQt6.QtWidgets import QApplication;"
            "app=QApplication([]);"
            "print('STYLE=%s' % app.style().objectName())"
        )
        env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
        done = subprocess.run(
            [sys.executable, "-c", script], cwd=str(_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=300)
        assert done.returncode == 0, (done.stdout, done.stderr)
        assert "STYLE=fusion" in done.stdout, (done.stdout, done.stderr)

    def test_the_native_platform_default_is_not_already_fusion(self):
        """Guard for the test above: if the machine's native default were
        already fusion, that test would pass for the wrong reason."""
        script = (
            "from PyQt6.QtWidgets import QApplication;"
            "app=QApplication([]);"
            "print('DEFAULT=%s' % app.style().objectName())"
        )
        env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
        done = subprocess.run(
            [sys.executable, "-c", script], cwd=str(_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=300)
        assert done.returncode == 0, (done.stdout, done.stderr)
        assert "DEFAULT=" in done.stdout
        assert "DEFAULT=fusion" not in done.stdout, (
            "native platform already defaults to fusion; the pin test proves "
            "nothing on this machine")

class TestThemedControlsRenderWithNoWhiteArtifacts:
    @pytest.mark.parametrize("theme_name", DARK_THEMES)
    def test_the_themed_table_has_no_near_white_pixels(self, qapp, theme_name):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QStandardItem, QStandardItemModel
        from PyQt6.QtWidgets import QTableView

        _apply(qapp, theme_name)
        model = QStandardItemModel(4, 3)
        for c in range(3):
            model.setHorizontalHeaderItem(c, QStandardItem(f"H{c}"))
        for r in range(4):
            for c in range(3):
                model.setItem(r, c, QStandardItem(f"{r},{c}"))
        view = QTableView()
        view.setModel(model)
        view.setSortingEnabled(True)
        view.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        view.resize(240, 140)
        view.show()
        qapp.processEvents()
        try:
            whites = _near_white_count(view.grab().toImage())
        finally:
            view.close()
        assert whites == 0, (
            f"{theme_name}: themed table painted {whites} near-white px "
            f"under style {qapp.style().objectName()!r}")

    @pytest.mark.parametrize("theme_name", NO_WHITE_THEMES)
    def test_the_themed_radio_indicator_has_no_near_white_pixels(self, qapp, theme_name):
        from PyQt6.QtWidgets import QRadioButton

        _apply(qapp, theme_name)
        radio = QRadioButton("Radio")
        radio.setChecked(True)
        radio.resize(140, 24)
        radio.show()
        qapp.processEvents()
        try:
            img = radio.grab().toImage()
        finally:
            radio.close()
        # The indicator is the left ~18px; the label is theme text.
        whites = 0
        for y in range(img.height()):
            for x in range(min(18, img.width())):
                c = img.pixelColor(x, y)
                if c.red() >= 245 and c.green() >= 245 and c.blue() >= 245:
                    whites += 1
        assert whites == 0, (
            f"{theme_name}: radio indicator painted {whites} near-white px")

    def test_the_pinned_style_is_what_the_running_app_uses(self, qapp):
        """The suite's own app must be on the deterministic style, otherwise
        every rendering assertion above measures the wrong style.

        Measured pitfall: ``app.style().objectName()`` returns ``''`` as soon
        as ANY global stylesheet is set, because ``setStyleSheet`` wraps the
        base style in a ``QStyleSheetStyle`` proxy whose name is empty. The
        suite shares one QApplication across files, so a prior file's stylesheet
        makes the naive name check fail in a full run while passing standalone.
        Clearing the sheet for the measurement reveals the base style, which is
        the thing the pin actually controls.
        """
        saved = qapp.styleSheet()
        qapp.setStyleSheet("")
        try:
            name = qapp.style().objectName().lower()
        finally:
            qapp.setStyleSheet(saved)
        assert name == qt_style.DETERMINISTIC_STYLE.lower(), name


class TestControlSurfacesFollowTheTheme:
    """The radio dot, combo/spin arrows and menu ticks are drawn by the style
    engine, not the widget frame. No theme sheet styled them, so on the native
    Windows style they took the OS chrome and under Fusion they take Fusion's
    grey -- either way, not the theme. ``control_surfaces_qss`` fixes that."""

    @pytest.mark.parametrize("theme_name", sorted(THEMES))
    def test_every_theme_defines_the_control_surfaces(self, theme_name):
        raw = THEMES[theme_name]["raw_colors"]
        qss = control_surfaces_qss(raw)
        for selector in ("QRadioButton::indicator", "QComboBox::down-arrow",
                         "QSpinBox::up-arrow", "QSpinBox::down-arrow",
                         "QMenu::indicator"):
            assert selector in qss, f"{theme_name}: {selector} not themed"

    @pytest.mark.parametrize("theme_name", sorted(THEMES))
    def test_the_surfaces_take_the_theme_accent_not_a_hardcoded_colour(self, theme_name):
        raw = THEMES[theme_name]["raw_colors"]
        qss = control_surfaces_qss(raw)
        accent = raw["accent"]
        assert f"QRadioButton::indicator:checked {{ background: {accent}" in qss, theme_name
        assert f"QMenu::indicator:checked {{ background: {accent}" in qss, theme_name

    @pytest.mark.parametrize("theme_name", sorted(THEMES))
    def test_the_surfaces_keep_the_square_corner_invariant(self, theme_name):
        """UI.md's Golden Default is a HARD invariant: zero rounded corners.

        The first cut of this block rounded the radio indicator to 6px, which
        contradicted both the rule and the function's own docstring. A rounded
        radius anywhere in the block is a regression."""
        import re

        raw = THEMES[theme_name]["raw_colors"]
        qss = control_surfaces_qss(raw)
        radii = re.findall(r"border-radius:\s*([^;]+);", qss)
        assert radii, f"{theme_name}: no explicit radius, Qt's default is round"
        for value in radii:
            assert value.strip() in ("0", "0px"), (
                f"{theme_name}: rounded corner {value!r} violates UI.md")

    def test_the_block_reaches_the_application_sheet(self):
        """One injection point, so every dialog gets it."""
        import inspect

        from fastprompter.ui import theme_mixin
        src = inspect.getsource(theme_mixin)
        assert "control_surfaces_qss(raw)" in src, "control surfaces are never injected"

    @pytest.mark.parametrize("theme_name", DARK_THEMES)
    def test_the_checked_radio_dot_uses_the_theme_accent(self, qapp, theme_name):
        from collections import Counter

        from PyQt6.QtWidgets import QRadioButton

        _apply(qapp, theme_name)
        radio = QRadioButton("Radio")
        radio.setChecked(True)
        radio.resize(140, 24)
        radio.show()
        qapp.processEvents()
        try:
            img = radio.grab().toImage()
        finally:
            radio.close()
        accent = THEMES[theme_name]["raw_colors"]["accent"].lower()
        seen = Counter()
        for y in range(img.height()):
            for x in range(min(18, img.width())):
                seen[img.pixelColor(x, y).name().lower()] += 1
        assert seen[accent] > 0, (
            f"{theme_name}: checked radio dot is not the theme accent "
            f"(saw {seen.most_common(4)})")
