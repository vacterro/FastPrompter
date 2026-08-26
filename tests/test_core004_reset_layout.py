"""CORE-004 regression: reset_ui_layout must restore the shipped DEFAULT_PROFILE
layout values (lists for splitters, not ""), not drifted hardcodes.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.ui.window_mixin as wm  # noqa: E402
from fastprompter.core.default_profile import DEFAULT_PROFILE  # noqa: E402


class _Fake:
    def __init__(self):
        self.data = {
            "toolbar_order": ["x", "y"],
            "splitter_sizes_left": [1, 2, 3],
            "splitter_sizes_right": [4, 5, 6],
            "sidebar_right": "False",
            "ui_scale": 0.25,
            "button_scale": 2.0,
            "last_geometry": "garbage",
        }
        self.sidebar_visible = False

    def play_sound(self, *a, **k):
        pass

    def apply_toolbar_order(self):
        pass

    def apply_sidebar_position(self):
        pass

    def _sync_layout_controls(self):
        pass

    def apply_scaled_ui(self):
        pass

    def isMaximized(self):
        return False

    def adjustSize(self):
        pass

    def mark_dirty(self):
        pass


def _bind(fake):
    fake.reset_ui_layout = wm.WindowMixin.reset_ui_layout.__get__(fake)
    return fake


def test_reset_copies_default_profile_values():
    f = _bind(_Fake())
    f.reset_ui_layout(confirm=False)
    # splitter keys are now real lists copied from defaults, never ""
    assert isinstance(f.data["splitter_sizes_left"], list)
    assert f.data["splitter_sizes_left"] == list(DEFAULT_PROFILE["splitter_sizes_left"])
    assert isinstance(f.data["splitter_sizes_right"], list)
    assert f.data["splitter_sizes_right"] == list(DEFAULT_PROFILE["splitter_sizes_right"])
    # other layout keys track the shipped defaults
    assert f.data["sidebar_right"] == str(DEFAULT_PROFILE["sidebar_right"])
    assert f.data["ui_scale"] == DEFAULT_PROFILE["ui_scale"]
    assert f.data["button_scale"] == DEFAULT_PROFILE["button_scale"]
    # geometry reset target stays a reset sentinel
    assert f.data["last_geometry"] == ""
    # editor/snippet content untouched (not present, but no corruption)
    assert "toolbar_order" in f.data


def test_reset_splitter_never_empty_string():
    f = _bind(_Fake())
    f.data["splitter_sizes_left"] = ""
    f.data["splitter_sizes_right"] = ""
    f.reset_ui_layout(confirm=False)
    assert f.data["splitter_sizes_left"] != ""
    assert f.data["splitter_sizes_right"] != ""
    assert isinstance(f.data["splitter_sizes_left"], list)
