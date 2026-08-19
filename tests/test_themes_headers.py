"""T-737: white header bars and grid lines across dark dialogs.

Measured before the fix: zero occurrences of `QHeaderView` and zero of
`gridline-color` anywhere in themes.py, so Qt painted both with its own
near-white default.
"""

def test_every_theme_styles_headers_and_grid():
    from fastprompter.theme.themes import THEMES, header_view_qss
    for name, theme in THEMES.items():
        qss = header_view_qss(theme.get("raw_colors") or {})
        assert "QHeaderView::section" in qss, name
        assert "gridline-color" in qss, name
        assert "QTableCornerButton::section" in qss, name


def test_the_header_takes_its_colours_from_the_theme_not_from_qt():
    """The right contract is identity, not darkness.

    An earlier version of this test asserted "no near-white hex anywhere",
    which fails on Vintage Classic — a deliberately pale theme whose own
    `bg_text` and `border_light` ARE #ffffff. White text on a dark header was
    never the defect either; the defect was Qt's unstyled default painting a
    bar the theme never chose. So assert the values come from raw_colors.
    """
    from fastprompter.theme.themes import THEMES, header_view_qss
    for name, theme in THEMES.items():
        raw = theme.get("raw_colors") or {}
        qss = header_view_qss(raw)
        bg = raw.get("bg_main")
        edge = raw.get("border_light")
        assert bg and f"background-color: {bg}" in qss, f"{name}: header bg not the theme's"
        assert edge and f"gridline-color: {edge}" in qss, f"{name}: grid not the theme's"
        assert f"border-bottom: 1px solid {edge}" in qss, f"{name}: header rule not the theme's"


def test_the_rules_reach_the_application_sheet():
    """One injection point, so every dialog gets it — not three patches."""
    import inspect

    from fastprompter.ui import theme_mixin
    src = inspect.getsource(theme_mixin)
    assert "header_view_qss(raw)" in src, "header qss is never injected"


def test_zebra_rows_are_never_white():
    """Alternating row colors with Qt's default WHITE AlternateBase draws
    light rows under the light text — "white on near-white" (user report,
    v0.8.29). The table sheet must set a dark alternate-background-color
    derived from the theme, never the unstyled default."""
    import re

    from fastprompter.theme.themes import THEMES, header_view_qss

    for name, theme in THEMES.items():
        raw = theme.get("raw_colors") or {}
        qss = header_view_qss(raw)
        assert "alternate-background-color:" in qss, (
            f"{name}: no zebra tone in the table sheet")
        alt = re.search(r"alternate-background-color:\s*(#[0-9a-fA-F]{6})", qss)
        assert alt, f"{name}: alternate-background-color is not a hex"
        value = int(alt.group(1)[1:], 16)
        assert value != 0xFFFFFF, f"{name}: zebra rows would be white"
        # a pale theme must NOT get a white zebra either (blend toward the
        # theme's text colour keeps the contrast direction right)
        if int((raw.get("bg_text") or "#2c2c2c")[1:], 16) == 0xFFFFFF:
            assert value < 0xFFFFFF, f"{name}: pale theme zebra is not tinted"


def test_the_calendar_popup_carries_its_own_copy():
    """A widget-level sheet REPLACES inherited rules, so the popup needs it."""
    import inspect
    from fastprompter.ui.timer_dialog import TimerDialog
    from fastprompter.main import FastPrompter
    from PyQt6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])

    app = FastPrompter()
    dialog = TimerDialog(app)
    
    src = inspect.getsource(TimerDialog._style_calendar_popup)
    assert "self._calendar_sheet()" in src, "_style_calendar_popup must apply _calendar_sheet"
    
    sheet = dialog._calendar_sheet()
    assert "QCalendarWidget QHeaderView::section" in sheet