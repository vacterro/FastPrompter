"""Tests for applying a window preset's APP state, not just its rectangle.

The rectangle half was always cheap. The app-state half — theme, font size, UI
scale, toolbar side — went through the same setters a user click uses, and it
called them unconditionally: picking a Presets zone re-applied the theme that
was already active, which rebuilds the whole application stylesheet and
rehighlights the whole document. Measured on a 400-block silo that was ~3.5s of
frozen UI on every second or third Ctrl+Q, and the window had not changed at
all.

So each of these asserts the same pair: a preset that DIFFERS is still applied,
and a preset that matches costs nothing.
"""

from __future__ import annotations

import os

import pytest

# Before ANY PyQt6 import, as every Qt-touching test here does: a module that
# lets Qt bind the native Windows platform plugin first makes the next real
# QApplication in the same process abort the interpreter (0xC0000409).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from fastprompter.ui.fancy_zones import (  # noqa: E402
    _font_already,
    _scale_already,
    apply_ui_state,
)


class _Spin:
    def __init__(self, value=11):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def minimum(self):
        return 8

    def maximum(self):
        return 48

    def blockSignals(self, _on):
        pass


class _Win:
    """Records which setters ran, so a no-op can be told from a re-apply."""

    def __init__(self, **data):
        self.data = {"theme": "Default", "font_size": 11, "ui_scale": "1.00",
                     "toolbar_position": "top", **data}
        self.font_spin = _Spin(int(self.data["font_size"]))
        self.calls: list[str] = []
        self.focus_mode = False
        self.sidebar_visible = True

    # -- the four expensive setters
    def change_theme(self, name):
        self.calls.append(f"theme:{name}")
        self.data["theme"] = name

    def change_font_size(self, size):
        self.calls.append(f"font:{size}")
        self.data["font_size"] = int(size)
        self.font_spin.setValue(int(size))

    def _set_unified_scale(self, value):
        self.calls.append(f"scale:{value}")
        self.data["ui_scale"] = f"{float(value):.2f}"

    def apply_toolbar_position(self, bottom=None):
        self.calls.append(f"toolbar:{bottom}")
        self.data["toolbar_position"] = "bottom" if bottom else "top"


def _preset(**over):
    base = {"name": "p", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5,
            "state": "normal"}
    base.update(over)
    return base


class TestIdenticalStateIsNotReapplied:
    def test_the_same_theme_is_not_rebuilt(self):
        """The whole 3.5s stall: one setStyleSheet + one full rehighlight."""
        win = _Win(theme="Golden Default")
        apply_ui_state(win, _preset(theme="Golden Default"))
        assert win.calls == []

    def test_the_same_font_size_is_not_reapplied(self):
        win = _Win(font_size=10)
        win.font_spin.setValue(10)
        apply_ui_state(win, _preset(font_size="10"))
        assert win.calls == []

    def test_the_same_scale_is_not_reapplied(self):
        win = _Win(ui_scale="0.50")
        apply_ui_state(win, _preset(ui_scale="0.50"))
        assert win.calls == []

    def test_the_same_toolbar_side_is_not_reapplied(self):
        win = _Win(toolbar_position="top")
        apply_ui_state(win, _preset(toolbar_position="top"))
        assert win.calls == []

    def test_the_users_own_preset_shape_is_a_complete_no_op(self):
        """Exactly the Preset 4 that froze the window, field for field."""
        win = _Win(theme="Golden Default", font_size=10, ui_scale="0.50",
                   toolbar_position="top")
        win.font_spin.setValue(10)
        apply_ui_state(win, _preset(
            theme="Golden Default", font_size="10", ui_scale="0.50",
            toolbar_position="top", zen=False, zen_solo=False, sidebar=True))
        assert win.calls == []


class TestDifferingStateIsStillApplied:
    def test_a_different_theme_is_applied(self):
        win = _Win(theme="Default")
        apply_ui_state(win, _preset(theme="Nord"))
        assert win.calls == ["theme:Nord"]

    def test_a_different_font_size_is_applied(self):
        win = _Win(font_size=11)
        apply_ui_state(win, _preset(font_size="21"))
        assert win.calls == ["font:21"]

    def test_a_different_scale_is_applied(self):
        win = _Win(ui_scale="1.00")
        apply_ui_state(win, _preset(ui_scale="1.25"))
        assert win.calls == ["scale:1.25"]

    def test_a_different_toolbar_side_is_applied(self):
        win = _Win(toolbar_position="top")
        apply_ui_state(win, _preset(toolbar_position="bottom"))
        assert win.calls == ["toolbar:True"]

    def test_all_four_at_once(self):
        win = _Win()
        apply_ui_state(win, _preset(theme="Nord", font_size="21",
                                    ui_scale="1.25",
                                    toolbar_position="bottom"))
        assert win.calls == ["theme:Nord", "font:21", "scale:1.25",
                             "toolbar:True"]

    def test_a_preset_carrying_nothing_touches_nothing(self):
        """Presets saved before app-state existed must force no field."""
        win = _Win()
        apply_ui_state(win, _preset())
        assert win.calls == []


class TestSkippingNeverHidesADriftedControl:
    def test_a_stale_spin_box_is_still_resynced(self):
        """``change_font_size`` exists partly to fix exactly this drift.

        ``data`` alone saying 10 is not enough to skip: a spin box left at 9 by
        a programmatic path would stay wrong forever, and the next wheel would
        snap the editor back to it.
        """
        win = _Win(font_size=10)
        win.font_spin.setValue(9)          # drifted
        apply_ui_state(win, _preset(font_size="10"))
        assert win.calls == ["font:10"]
        assert win.font_spin.value() == 10

    def test_font_already_needs_data_and_control_to_agree(self):
        win = _Win(font_size=10)
        win.font_spin.setValue(10)
        assert _font_already(win, 10) is True
        win.font_spin.setValue(9)
        assert _font_already(win, 10) is False

    def test_a_window_without_a_spin_box_compares_data_only(self):
        win = _Win(font_size=10)
        win.font_spin = None
        assert _font_already(win, 10) is True
        assert _font_already(win, 11) is False


class TestComparisonsAreClampAware:
    def test_an_out_of_range_scale_settles_instead_of_looping(self):
        """A preset holding 3.0 must not re-run the pass against a stored 1.75."""
        win = _Win(ui_scale="1.75")
        assert _scale_already(win, 3.0) is True
        apply_ui_state(win, _preset(ui_scale="3.0"))
        assert win.calls == []

    def test_float_noise_is_not_a_difference(self):
        win = _Win(ui_scale="0.50")
        assert _scale_already(win, 0.5001) is True
        apply_ui_state(win, _preset(ui_scale="0.5001"))
        assert win.calls == []

    def test_a_real_scale_step_still_counts(self):
        win = _Win(ui_scale="0.50")
        assert _scale_already(win, 0.75) is False

    def test_garbage_values_never_skip_silently(self):
        """Unparseable state must fall through to the setter's own clamping."""
        win = _Win()
        assert _scale_already(win, 1.0) is True
        win.data["ui_scale"] = "not a number"
        assert _scale_already(win, 1.0) is False
        win.data["font_size"] = "nonsense"
        assert _font_already(win, 11) is False

    def test_an_unparseable_preset_value_is_ignored_not_guessed(self):
        win = _Win()
        apply_ui_state(win, _preset(font_size="huge", ui_scale="wide"))
        assert win.calls == []
