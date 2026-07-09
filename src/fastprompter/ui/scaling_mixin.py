"""Scaling mixin for FastPrompter — button sizing, UI scaling, and font adjustment.

Extracted from main.py Phase 1 of the modularization plan.
Provides ScalingMixin class for use as a mixin with FastPrompter QMainWindow.
"""

from PyQt6 import sip
from PyQt6.QtWidgets import QPushButton

from fastprompter.core.logging import logger

_is_deleted = sip.isdeleted

# Static button height / font scale data for apply_scaled_ui
_BTN_BASE_HEIGHTS = {
    "btn_clear": 24,
    "btn_format": 24,
    "btn_clear_fmt": 24,
    "btn_clean_space": 24,
    "btn_add_line": 24,
    "btn_bullet_toggle": 24,
    "btn_save": 24,
    "btn_home": 24,
    "btn_end": 24,
    "btn_new": 24,
    "btn_add_tab": 24,
    "btn_del_tab": 24,
    "btn_settings_toggle": 24,
    "btn_page_up": 14,
    "btn_page_down": 14,
    "btn_silo_up": 14,
    "btn_silo_down": 14,
    "btn_add_snip": 18,
    "btn_del_snip": 18,
    "btn_hotkeys": 20,
    "btn_backup": 20,
    "btn_restore": 20,
    "btn_sidebar_toggle": 24,
    "btn_bold": 24,
    "btn_italic": 24,
    "btn_under": 24,
    "btn_strike": 24,
    "btn_find_prev": 24,
    "btn_find_next": 24,
    "btn_close_search": 24,
    "btn_replace": 24,
    "btn_replace_all": 24,
}

# Width-scaling button names for apply_scaled_ui (format toolbar)
_BTN_WIDTH_SCALE_NAMES = (
    "btn_bold",
    "btn_italic",
    "btn_under",
    "btn_strike",
    "btn_find_prev",
    "btn_find_next",
    "btn_close_search",
)


class ScalingMixin:
    """Mixin providing button scaling, UI scaling, and font adjustment.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self._button_scale, self._ui_scale, self.data, self.font_spin
    """

    def _scale_button_font(self, widget, scale):
        """Shrink a button's font below 100% scale so text isn't clipped."""
        try:
            font = widget.font()
            font.setPointSizeF(max(6.0, 9.0 * min(1.0, scale)))
            widget.setFont(font)
        except Exception:
            logger.debug("Failed to scale font on %s", widget)

    def apply_button_size(self, widget, base_w, base_h=None):
        """Set widget size based on button scale."""
        try:
            scale = self._button_scale
        except Exception:
            scale = 1.0
        widget._base_size = (base_w, base_h)
        min_sz = max(12, int(base_w * scale))
        if base_h is None:
            if getattr(widget, "is_squishable", False):
                widget.setMaximumHeight(int(base_w * scale))
                widget.setMinimumHeight(1)
            else:
                widget.setFixedHeight(min_sz)
        else:
            sz = max(12, int(base_h * scale))
            widget.setFixedSize(min_sz, sz)
        if scale < 1.0:
            self._scale_button_font(widget, scale)

    def refresh_button_scale(self):
        """Re-apply button scale to all children with _base_size."""
        try:
            scale = self._button_scale
        except Exception:
            scale = 1.0
        for widget in self.findChildren(QPushButton):
            if not _is_deleted(widget) and hasattr(widget, "_base_size") and widget._base_size is not None:
                base_w, base_h = widget._base_size
                try:
                    min_sz = max(12, int(base_w * scale))
                    if base_h is None:
                        if getattr(widget, "is_squishable", False):
                            widget.setMaximumHeight(int(base_w * scale))
                            widget.setMinimumHeight(1)
                        else:
                            widget.setFixedHeight(min_sz)
                    else:
                        sz = max(12, int(base_h * scale))
                        widget.setFixedSize(min_sz, sz)
                    self._scale_button_font(widget, scale)
                except Exception:
                    logger.debug("Failed to resize widget: %s", widget)

    def cycle_button_scale(self):
        """Cycle through preset button scale values (0.5, 0.75, 1.0, 1.25, 1.5)."""
        scales = [0.5, 0.75, 1.0, 1.25, 1.5]
        try:
            current = self._button_scale
        except Exception:
            current = 1.0
        try:
            idx = min(range(len(scales)), key=lambda i: abs(scales[i] - current))
            next_idx = (idx + 1) % len(scales)
        except ValueError:
            next_idx = 2  # default to 100%
        new_scale = scales[next_idx]
        self.data["button_scale"] = str(new_scale)
        # mark_dirty is required — the state layer skips saving when clean,
        # which silently lost the scale between sessions.
        self.mark_dirty()
        self.save_data_to_db(force=True)
        if hasattr(self, "btn_button_scale") and not _is_deleted(self.btn_button_scale):
            self.btn_button_scale.setText(f"Scale: {int(new_scale * 100)}%")
        self._refresh_settings_cache()
        self.refresh_button_scale()
        self.apply_font()

    def adjust_font_size(self, step):
        """Adjust font size by step, clamped within font_spin range."""
        base = int(self.font_spin.value())
        new_size = max(self.font_spin.minimum(), min(self.font_spin.maximum(), base + step))
        if new_size != base:
            self.font_spin.setValue(new_size)

    def adjust_ui_scale(self, delta):
        """Adjust UI scale by delta, clamped between 0.75 and 1.75."""
        try:
            current = self._ui_scale
        except Exception:
            current = 1.0
        current = max(0.75, min(1.75, round(current + delta, 2)))
        self.data["ui_scale"] = f"{current:.2f}"
        self.apply_font()
        self.apply_scaled_ui()
        self.mark_dirty()

    def apply_scaled_ui(self):
        """Apply UI scale to button heights, fonts, and widths."""
        try:
            scale = self._ui_scale
        except Exception:
            scale = 1.0

        for name, base in _BTN_BASE_HEIGHTS.items():
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.setFixedHeight(max(14, int(round(base * scale))))
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set height on %s", name)

                try:
                    font = w.font()
                    font.setPointSizeF(max(7.0, 9.0 * scale))
                    w.setFont(font)
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set font on %s", name)

        if hasattr(self, "btn_sidebar_toggle") and not _is_deleted(self.btn_sidebar_toggle):
            self.btn_sidebar_toggle.setFixedWidth(max(14, int(round(24 * scale))))
        for btn_name in _BTN_WIDTH_SCALE_NAMES:
            w = getattr(self, btn_name, None)
            if w is not None:
                try:
                    w.setFixedWidth(max(14, int(round(24 * scale))))
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set width on %s", btn_name)

                try:
                    font = w.font()
                    font.setPointSizeF(max(7.0, 9.0 * scale))
                    w.setFont(font)
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set font on %s", btn_name)
