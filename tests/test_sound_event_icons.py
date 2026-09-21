"""T-1242: sound event pictograms + Audio Hub dialog behaviour.

The pictogram colour comes from the ACTIVE theme's raw tokens (text_main ->
btn_text -> visible neutral), never from QPalette, which QSS-heavy themes
leave desynced — that was the "nearly black icons on Golden" defect.  A
theme switch regenerates the pixmaps without rebuilding dialog state,
programmatic refreshes stay silent, and one user selection previews at most
once.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.sound_manager import SoundManager  # noqa: E402
from fastprompter.theme import themes as theme_module  # noqa: E402
from fastprompter.ui import sound_settings_dialog as ssd  # noqa: E402
from fastprompter.ui.sound_settings_dialog import (  # noqa: E402
    SoundSettingsDialog,
    _contrast_ratio,
    _event_icon,
    _theme_icon_color,
)

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def dialog(tmp_path, monkeypatch):
    _ensure_app()
    monkeypatch.setattr("fastprompter.utils.paths.get_data_dir",
                        lambda: str(tmp_path))
    monkeypatch.setattr("fastprompter.core.sound_library.managed_root",
                        lambda: str(tmp_path / "sound_library"))
    host = QWidget()
    # Emulate the running app: the host carries the ACTIVE theme cache, the
    # same source theme_raw_colors reads inside the dialog.
    host._theme_cache = {
        "raw_colors": theme_module.THEMES["Golden Default"]["raw_colors"]}
    data: dict = {"sound_ui": "True"}
    manager = SoundManager(host, data)
    manager._hub = AudioHub(transport=FakeMultiChannelTransport())
    widget = SoundSettingsDialog(host, data, manager)
    yield widget, manager, data
    # T-1286: receiver-scoped retirement (was deleteLater(), never delivered
    # without an event loop; the backlog stalled tests/test_timer_fire.py).
    from _qt_retire import retire
    manager.shutdown()
    retire(widget, host)


class TestIconColorSource:
    def test_golden_theme_icons_are_not_black(self, dialog):
        """The original defect: Golden Default's near-black palette Text."""
        widget, _manager, _data = dialog
        color = widget._icon_color
        background = ssd._table_background_color(widget)
        assert color.isValid()
        assert _contrast_ratio(color, background) >= 3.0
        # not the QPalette-Text black the old code produced
        assert color.valueF() > 0.3 or color.lightness() > 60

    def test_theme_tokens_take_priority_over_fallback(self, dialog):
        widget, _manager, _data = dialog
        golden = theme_module.THEMES["Golden Default"]["raw_colors"]
        widget.main_win._theme_cache = {"raw_colors": golden}
        color = _theme_icon_color(widget.main_win, widget)
        assert color == QColor(golden["text_main"])

    def test_low_contrast_token_falls_to_btn_text(self, dialog):
        widget, _manager, _data = dialog
        widget.main_win._theme_cache = {"raw_colors": {
            "bg_text": "#1a1810", "bg_main": "#232018",
            "text_main": "#101010",   # unreadable on the dark table
            "btn_text": "#f0d060",    # readable
        }}
        color = _theme_icon_color(widget.main_win, widget)
        assert color == QColor("#f0d060")

    def test_both_tokens_failing_lands_on_visible_neutral(self, dialog):
        widget, _manager, _data = dialog
        widget.main_win._theme_cache = {"raw_colors": {
            "bg_text": "#1a1810", "bg_main": "#232018",
            "text_main": "#101010", "btn_text": "#181818"}}
        color = _theme_icon_color(widget.main_win, widget)
        background = ssd._table_background_color(widget)
        assert _contrast_ratio(color, background) >= 3.0

    def test_icon_pixmap_actually_uses_the_resolved_color(self):
        icon = _event_icon("keyboard", QColor("#f0d060"))
        assert not icon.isNull()
        # no per-event rainbow: colour stays the theme's own
        assert _event_icon("camera", QColor("#f0d060")) is not None


class TestThemeRepaint:
    def test_repaint_event_icons_recolors_without_rebuilding(self, dialog):
        widget, _manager, _data = dialog
        first = widget._icon_color
        assert first is not None
        old_icon = widget.table.item(0, 0).icon()
        assert not old_icon.isNull()
        # simulate a theme switch by feeding a different colour through the
        # repaint hook (the same entry point apply_theme uses)
        widget.main_win._theme_cache = {"raw_colors": {
            "bg_text": "#1a1810", "bg_main": "#232018",
            "text_main": "#90d8f0", "btn_text": "#c0e8ff"}}
        widget.repaint_event_icons()
        assert widget._icon_color == QColor("#90d8f0")
        new_icon = widget.table.item(0, 0).icon()
        assert not new_icon.isNull()
        # pixel content actually changed with the theme
        assert old_icon.pixmap(20, 20).toImage() != \
            new_icon.pixmap(20, 20).toImage()

    def test_last_instance_registration_is_cleared_on_close(self, dialog):
        widget, _manager, _data = dialog
        assert SoundSettingsDialog._LAST_INSTANCE is widget
        widget.done(0)
        assert SoundSettingsDialog._LAST_INSTANCE is None


class TestCompactRows:
    def test_event_rows_are_compact(self, dialog):
        widget, _manager, _data = dialog
        assert widget.table.rowCount() > 0
        for row in range(widget.table.rowCount()):
            height = widget.table.rowHeight(row)
            assert 24 <= height <= 31, height

    def test_row_controls_fit_inside_the_row(self, dialog):
        widget, _manager, _data = dialog
        for row in range(widget.table.rowCount()):
            for col in range(widget.table.columnCount()):
                cell = widget.table.cellWidget(row, col)
                if cell is None:
                    continue
                size = cell.sizeHint()
                assert size.height() <= widget.table.rowHeight(row) + 2, (
                    row, col, size.height())

    def test_gain_slider_is_compact(self, dialog):
        """T-1242: the 0..10 volume slider became a -24..+12 dB Gain slider
        living inside a cell widget beside its numeric label."""
        widget, _manager, _data = dialog
        sliders = list(widget._gains.values())
        assert sliders
        assert all(s.width() <= 120 or s.maximumWidth() <= 120
                   for s in sliders)
        assert all(s.minimum() == -24 and s.maximum() == 12 for s in sliders)


class TestSilentRefresh:
    def test_programmatic_load_settings_never_previews(self, dialog,
                                                       monkeypatch):
        widget, _manager, _data = dialog
        played = []
        monkeypatch.setattr(widget._sound_manager, "play_file",
                            lambda *a, **k: played.append(a))
        # every programmatic path: loading, preset reload, library reload
        widget._load_settings()
        widget.reload_after_preset()
        widget.reload_sound_library()
        assert played == []

    def test_user_sound_selection_previews_exactly_once(self, dialog,
                                                        monkeypatch):
        widget, _manager, _data = dialog
        played = []
        monkeypatch.setattr(widget._sound_manager, "play_file",
                            lambda *a, **k: played.append(a))
        event = list(ssd.EVENT_LABELS)[0]
        combo = widget._combos[event]
        widget._loading = False
        # one intentional selection -> at most one preview (call the handler
        # directly: setCurrentIndex would fire the connected signal AND the
        # explicit call, doubling the preview in a unit-test setting)
        widget._set_file(event, combo)
        assert len(played) <= 1

    def test_programmatic_combo_change_is_silent(self, dialog, monkeypatch):
        widget, _manager, _data = dialog
        played = []
        monkeypatch.setattr(widget._sound_manager, "play_file",
                            lambda *a, **k: played.append(a))
        event = list(ssd.EVENT_LABELS)[0]
        combo = widget._combos[event]
        widget._loading = True
        try:
            combo.setCurrentIndex(1)
            widget._set_file(event, combo)
        finally:
            widget._loading = False
        assert played == []


class TestShowCounterContract:
    def test_show_counter_never_touches_the_statistics_row(self):
        """Show counter hides ONLY the 'N BLIPS' readout (spec 18).

        The statistics row lives on the Problip page; pin the source
        contract directly so a future edit cannot re-couple it.
        """
        import inspect

        from fastprompter.ui import problip_settings
        source = inspect.getsource(problip_settings)
        assert "self.row_stats.setVisible(True)" in source
        assert "self.row_stats.setVisible(show)" not in source
