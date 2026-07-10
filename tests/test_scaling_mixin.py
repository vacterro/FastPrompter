"""Tests for fastprompter.ui.scaling_mixin — button sizes, UI scaling, cycle logic."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# PyQt6 stubs
# ---------------------------------------------------------------------------


class _MockQt:
    pass


class _MockQPushButton:
    """Stand-in for QPushButton — tracks setFixedHeight, setFixedSize calls."""

    def __init__(self, name=""):
        self._base_size = None
        self._fixed_height = None
        self._fixed_width = None
        self._fixed_size = None
        self._max_height = None
        self._min_height = 0
        self._font = _MockQFont()
        self._name = name
        self._text = ""
        self.is_squishable = False

    def setFixedHeight(self, h):
        self._fixed_height = h

    def setFixedWidth(self, w):
        self._fixed_width = w

    def setFixedSize(self, w, h):
        self._fixed_size = (w, h)

    def setMaximumHeight(self, h):
        self._max_height = h

    def setMinimumHeight(self, h):
        self._min_height = h

    def setText(self, text):
        self._text = text

    def font(self):
        return self._font

    def setFont(self, font):
        pass

    def objectName(self):
        return self._name


class _MockQFont:
    def __init__(self):
        self._point_size = 9.0

    def setPointSizeF(self, size):
        self._point_size = size

    def pointSizeF(self):
        return self._point_size


class _MockQApplication:
    @staticmethod
    def font():
        return _MockQFont()

    @staticmethod
    def setFont(font):
        pass


_mock_sip = MagicMock()
_mock_sip.isdeleted.return_value = False
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6"].sip = _mock_sip
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtGui"].QFont = _MockQFont
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["PyQt6.QtWidgets"].QPushButton = _MockQPushButton
sys.modules["PyQt6.QtWidgets"].QApplication = _MockQApplication

from fastprompter.ui.scaling_mixin import _BTN_BASE_HEIGHTS, _BTN_WIDTH_SCALE_NAMES, ScalingMixin

# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------


class TestButtonBaseHeights:
    """Verify _BTN_BASE_HEIGHTS dict covers all expected buttons."""

    ESSENTIAL_BUTTONS = [
        "btn_clear",
        "btn_format",
        "btn_save",
        "btn_new",
        "btn_home",
        "btn_end",
        "btn_bold",
        "btn_italic",
        "btn_under",
        "btn_strike",
        "btn_find_prev",
        "btn_find_next",
        "btn_close_search",
        "btn_replace",
        "btn_replace_all",
        "btn_sidebar_toggle",
        "btn_settings_toggle",
        "btn_backup",
        "btn_restore",
    ]

    def test_all_essential_buttons_present(self):
        for name in self.ESSENTIAL_BUTTONS:
            assert name in _BTN_BASE_HEIGHTS, f"Missing essential button: {name}"

    def test_all_heights_are_positive(self):
        for name, height in _BTN_BASE_HEIGHTS.items():
            assert height > 0, f"Non-positive height for {name}: {height}"

    def test_all_heights_are_integers(self):
        for name, height in _BTN_BASE_HEIGHTS.items():
            assert isinstance(height, int), f"Non-int height for {name}: {type(height).__name__}"

    def test_has_enough_buttons(self):
        """At least 25 distinct buttons should be mapped."""
        assert len(_BTN_BASE_HEIGHTS) >= 25

    def test_common_buttons_have_reasonable_heights(self):
        """Common action buttons should be 24px base height."""
        for name in ["btn_save", "btn_new", "btn_clear", "btn_format"]:
            assert _BTN_BASE_HEIGHTS.get(name) == 24, f"{name} should have base height 24"

    def test_smaller_buttons_have_lower_heights(self):
        """Navigation buttons should be 14px base height."""
        for name in ["btn_page_up", "btn_page_down", "btn_silo_up", "btn_silo_down"]:
            assert _BTN_BASE_HEIGHTS.get(name) == 14, f"{name} should have base height 14"


class TestWidthScaleNames:
    """Verify _BTN_WIDTH_SCALE_NAMES covers format toolbar buttons."""

    FORMAT_BUTTONS = [
        "btn_bold",
        "btn_italic",
        "btn_under",
        "btn_strike",
    ]

    SEARCH_BUTTONS = [
        "btn_find_prev",
        "btn_find_next",
        "btn_close_search",
    ]

    def test_all_format_buttons_present(self):
        for name in self.FORMAT_BUTTONS:
            assert name in _BTN_WIDTH_SCALE_NAMES, f"Missing format button: {name}"

    def test_all_search_buttons_present(self):
        for name in self.SEARCH_BUTTONS:
            assert name in _BTN_WIDTH_SCALE_NAMES, f"Missing search button: {name}"

    def test_total_count(self):
        assert len(_BTN_WIDTH_SCALE_NAMES) == len(self.FORMAT_BUTTONS) + len(self.SEARCH_BUTTONS)

    def test_no_duplicates(self):
        assert len(_BTN_WIDTH_SCALE_NAMES) == len(set(_BTN_WIDTH_SCALE_NAMES))


# ---------------------------------------------------------------------------
# cycle_button_scale logic
# ---------------------------------------------------------------------------


class TestCycleButtonScale:
    """Test the numeric cycling logic independent of Qt widget updates."""

    SCALES = [0.5, 0.75, 1.0, 1.25, 1.5]

    def _make_mixin(self, current_scale=1.0):
        m = ScalingMixin()
        m._button_scale = current_scale
        m._ui_scale = current_scale
        m.data = {"button_scale": str(current_scale)}
        m.save_data_to_db = MagicMock()
        m.mark_dirty = MagicMock()
        # Real _refresh_settings_cache updates _button_scale from data
        def _refresh():
            try:
                m._button_scale = float(m.data.get("button_scale", "1.0"))
                m._ui_scale = float(m.data.get("ui_scale", "1.0"))
            except (ValueError, TypeError):
                m._button_scale = 1.0
                m._ui_scale = 1.0
        m._refresh_settings_cache = MagicMock(wraps=_refresh)
        m.refresh_button_scale = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.setMinimumSize = MagicMock()
        m.apply_font = MagicMock()
        return m

    def test_cycles_to_next_scale(self):
        m = self._make_mixin(1.0)
        # Call cycle_button_scale — needs btn_button_scale
        m.btn_button_scale = _MockQPushButton("btn_button_scale")
        m.cycle_button_scale()
        assert m._button_scale == 1.25
        assert m.data["button_scale"] == "1.25"

    def test_cycles_wraps_around(self):
        m = self._make_mixin(1.5)
        m.btn_button_scale = _MockQPushButton("btn_button_scale")
        m.cycle_button_scale()
        assert m._button_scale == 0.5
        assert m.data["button_scale"] == "0.5"

    def test_unknown_scale_defaults_to_1_0(self):
        m = self._make_mixin(0.0)  # not in scales list
        m.btn_button_scale = _MockQPushButton("btn_button_scale")
        m.cycle_button_scale()
        # 0.0 is closest to 0.5 (idx 0), next cycle is idx 1 = 0.75
        assert m._button_scale == 0.75

    def test_persistence_called(self):
        m = self._make_mixin(1.0)
        m.btn_button_scale = _MockQPushButton("btn_button_scale")
        m.cycle_button_scale()
        m.save_data_to_db.assert_called_once()
        m._refresh_settings_cache.assert_called_once()
        m.refresh_button_scale.assert_called_once()

    def test_button_text_updated(self):
        m = self._make_mixin(1.0)
        btn = _MockQPushButton("btn_button_scale")
        btn.text = "Btn Scale: 100%"
        m.btn_button_scale = btn
        m.cycle_button_scale()
        assert "125%" in btn._text

    def test_cycles_from_0_75(self):
        m = self._make_mixin(0.75)
        m.btn_button_scale = _MockQPushButton("btn_button_scale")
        m.cycle_button_scale()
        assert m._button_scale == 1.0


# ---------------------------------------------------------------------------
# apply_button_size logic
# ---------------------------------------------------------------------------


class TestApplyButtonSize:
    def test_base_size_stored(self):
        m = ScalingMixin()
        m._button_scale = 1.0
        m._ui_scale = 1.0
        btn = _MockQPushButton("test_btn")
        m.apply_button_size(btn, 24, 24)
        assert btn._base_size == (24, 24)

    def test_scale_applied_to_width_height(self):
        m = ScalingMixin()
        m._button_scale = 1.5
        m._ui_scale = 1.5
        btn = _MockQPushButton("test_btn")
        m.apply_button_size(btn, 24, 24)
        # min_w = max(18, 24*1.5) = 36
        # min_h = max(18, 24*1.5) = 36
        assert btn._fixed_size == (36, 36)

    def test_scale_minimum_clamp(self):
        m = ScalingMixin()
        m._button_scale = 0.3
        m._ui_scale = 0.3
        btn = _MockQPushButton("test_btn")
        m.apply_button_size(btn, 20, 20)
        # min_w = max(20, 20*0.3) = 20 — floor fits 8pt text + borders
        assert btn._fixed_size == (20, 20)

    def test_squishable_uses_max_height(self):
        m = ScalingMixin()
        m._button_scale = 1.0
        m._ui_scale = 1.0
        btn = _MockQPushButton("test_btn")
        btn.is_squishable = True
        m.apply_button_size(btn, 24)
        assert btn._max_height == 24

    def test_missing_button_scale_falls_back_to_1(self):
        m = ScalingMixin()
        # don't set _button_scale — should default to 1.0 via try/except
        btn = _MockQPushButton("test_btn")
        m.apply_button_size(btn, 24, 24)
        assert btn._fixed_size == (24, 24)


# ---------------------------------------------------------------------------
# adjust_font_size logic
# ---------------------------------------------------------------------------


class TestAdjustFontSize:
    def test_increases_size(self):
        m = ScalingMixin()
        m.font_spin = MagicMock()
        m.font_spin.value.return_value = 11
        m.font_spin.minimum.return_value = 8
        m.font_spin.maximum.return_value = 24
        m.adjust_font_size(2)
        m.font_spin.setValue.assert_called_once_with(13)

    def test_decreases_size(self):
        m = ScalingMixin()
        m.font_spin = MagicMock()
        m.font_spin.value.return_value = 11
        m.font_spin.minimum.return_value = 8
        m.font_spin.maximum.return_value = 24
        m.adjust_font_size(-2)
        m.font_spin.setValue.assert_called_once_with(9)

    def test_clamps_at_minimum(self):
        m = ScalingMixin()
        m.font_spin = MagicMock()
        m.font_spin.value.return_value = 9
        m.font_spin.minimum.return_value = 8
        m.font_spin.maximum.return_value = 24
        m.adjust_font_size(-5)
        m.font_spin.setValue.assert_called_once_with(8)

    def test_clamps_at_maximum(self):
        m = ScalingMixin()
        m.font_spin = MagicMock()
        m.font_spin.value.return_value = 22
        m.font_spin.minimum.return_value = 8
        m.font_spin.maximum.return_value = 24
        m.adjust_font_size(5)
        m.font_spin.setValue.assert_called_once_with(24)

    def test_no_change_when_same(self):
        m = ScalingMixin()
        m.font_spin = MagicMock()
        m.font_spin.value.return_value = 11
        m.font_spin.minimum.return_value = 8
        m.font_spin.maximum.return_value = 24
        m.adjust_font_size(0)
        m.font_spin.setValue.assert_not_called()


# ---------------------------------------------------------------------------
# adjust_ui_scale logic
# ---------------------------------------------------------------------------


class TestAdjustUiScale:
    def test_increases(self):
        m = ScalingMixin()
        m._ui_scale = 1.0
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(0.1)
        assert m.data["ui_scale"] == "1.10"
        m.apply_font.assert_called_once()
        m.apply_scaled_ui.assert_called_once()
        m.mark_dirty.assert_called_once()

    def test_decreases(self):
        m = ScalingMixin()
        m._ui_scale = 1.0
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(-0.1)
        assert m.data["ui_scale"] == "0.90"

    def test_clamps_minimum(self):
        m = ScalingMixin()
        m._ui_scale = 0.5
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(-0.1)
        assert m.data["ui_scale"] == "0.50"

    def test_clamps_maximum(self):
        m = ScalingMixin()
        m._ui_scale = 1.75
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(0.1)
        assert m.data["ui_scale"] == "1.75"

    def test_near_boundary(self):
        m = ScalingMixin()
        m._ui_scale = 1.74
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(0.05)
        assert m.data["ui_scale"] == "1.75"  # clamped from 1.79

    def test_missing_ui_scale_defaults_to_1(self):
        m = ScalingMixin()
        # no _ui_scale set — try/except defaults to 1.0
        m.data = {}
        m.apply_font = MagicMock()
        m.apply_scaled_ui = MagicMock()
        m.refresh_button_scale = MagicMock()
        m.mark_dirty = MagicMock()
        m._refresh_settings_cache = MagicMock()
        m.setMinimumSize = MagicMock()
        m.adjust_ui_scale(0.1)
        assert "1.10" in m.data["ui_scale"]


# ---------------------------------------------------------------------------
# apply_scaled_ui data integrity
# ---------------------------------------------------------------------------


class TestApplyScaledUi:
    def test_all_base_heights_have_corresponding_method(self):
        """Every button in _BTN_BASE_HEIGHTS should be resizeable."""
        m = ScalingMixin()
        m._ui_scale = 1.0
        # If a button name maps to a widget attr, the method should catch
        # AttributeError and log a debug message rather than crashing.
        # Just verify it doesn't raise.
        m.apply_scaled_ui()  # All widget attrs will be None — should log debug, not crash

    def test_width_scale_buttons_handled_gracefully(self):
        m = ScalingMixin()
        m._ui_scale = 1.0
        # All attrs are None — should not crash
        m.apply_scaled_ui()


# ---------------------------------------------------------------------------
# refresh_button_scale data integrity
# ---------------------------------------------------------------------------


class TestRefreshButtonScale:
    def test_no_children_does_not_crash(self):
        m = ScalingMixin()
        m._button_scale = 1.0
        m._ui_scale = 1.0
        m.findChildren = MagicMock(return_value=[])
        m.refresh_button_scale()
        # Should not crash

    def test_children_without_base_size_skipped(self):
        m = ScalingMixin()
        m._button_scale = 1.0
        m._ui_scale = 1.0
        btn = _MockQPushButton("test")
        m.findChildren = MagicMock(return_value=[btn])
        m.refresh_button_scale()
        # btn has no _base_size — should be skipped
