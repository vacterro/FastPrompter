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
    "btn_clear_fmt": 24,
    "btn_files": 24,
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

    # Text must stay readable at EVERY scale (50-150%): fonts never go
    # below 8pt and heights never below what an 8pt line + theme borders
    # need (16px clipped descenders at 50%).
    MIN_FONT_PT = 8.0
    MIN_BTN_PX = 20
    # 12pt at 100% keeps all five steps distinct above the 8pt floor:
    # 50->8, 75->9, 100->12, 125->15, 150->18
    BASE_FONT_PT = 12.0

    def _effective_scale(self):
        """The single unified UI scale."""
        try:
            return self._ui_scale
        except Exception:
            return 1.0

    def _scale_button_font(self, widget, scale):
        """Scale a button's font with a readable floor."""
        try:
            font = widget.font()
            font.setPointSizeF(max(self.MIN_FONT_PT, self.BASE_FONT_PT * scale))
            widget.setFont(font)
        except Exception:
            logger.debug("Failed to scale font on %s", widget)

    def apply_button_size(self, widget, base_w, base_h=None):
        """Set widget size based on the combined UI x button scale."""
        scale = self._effective_scale()
        widget._base_size = (base_w, base_h)
        min_sz = max(self.MIN_BTN_PX, int(base_w * scale))
        if base_h is None:
            if getattr(widget, "is_squishable", False):
                widget.setMaximumHeight(max(self.MIN_BTN_PX, int(base_w * scale)))
                widget.setMinimumHeight(1)
            else:
                widget.setFixedHeight(min_sz)
        else:
            sz = max(self.MIN_BTN_PX, int(base_h * scale))
            widget.setFixedSize(min_sz, sz)
        self._scale_button_font(widget, scale)

    def refresh_button_scale(self):
        """Re-apply the combined scale to all children with _base_size."""
        scale = self._effective_scale()
        for widget in self.findChildren(QPushButton):
            if not _is_deleted(widget) and hasattr(widget, "_base_size") and widget._base_size is not None:
                base_w, base_h = widget._base_size
                try:
                    min_sz = max(self.MIN_BTN_PX, int(base_w * scale))
                    if base_h is None:
                        if getattr(widget, "is_squishable", False):
                            widget.setMaximumHeight(max(self.MIN_BTN_PX, int(base_w * scale)))
                            widget.setMinimumHeight(1)
                        else:
                            widget.setFixedHeight(min_sz)
                    else:
                        sz = max(self.MIN_BTN_PX, int(base_h * scale))
                        widget.setFixedSize(min_sz, sz)
                    self._scale_button_font(widget, scale)
                except Exception:
                    logger.debug("Failed to resize widget: %s", widget)

    def cycle_button_scale(self):
        """Cycle the unified Scale through 50/75/100/125/150%."""
        scales = [0.5, 0.75, 1.0, 1.25, 1.5]
        try:
            current = self._ui_scale
        except Exception:
            current = 1.0
        try:
            idx = min(range(len(scales)), key=lambda i: abs(scales[i] - current))
            next_idx = (idx + 1) % len(scales)
        except ValueError:
            next_idx = 2  # default to 100%
        self._set_unified_scale(scales[next_idx])
        self.save_data_to_db(force=True)

    def _set_unified_scale(self, value):
        """One knob scales the whole program: app font, editor font,
        every sized button, sidebar rows, pie menu, window minimum."""
        value = max(0.5, min(1.75, round(float(value), 2)))
        self.data["ui_scale"] = f"{value:.2f}"
        # kept equal for backward compatibility with old data readers
        self.data["button_scale"] = str(value)
        self.mark_dirty()
        if hasattr(self, "btn_button_scale") and not _is_deleted(self.btn_button_scale):
            self.btn_button_scale.setText(f"Scale: {int(value * 100)}%")
        self._refresh_settings_cache()
        self.apply_scaled_ui()
        self.refresh_button_scale()
        self.apply_font()
        if not getattr(self, "is_locked", False):
            self.setMinimumSize(max(320, int(480 * value)), max(240, int(320 * value)))

    def adjust_font_size(self, step):
        """Adjust font size by step, clamped within font_spin range."""
        base = int(self.font_spin.value())
        new_size = max(self.font_spin.minimum(), min(self.font_spin.maximum(), base + step))
        if new_size != base:
            self.font_spin.setValue(new_size)

    def adjust_ui_scale(self, delta):
        """Fine-adjust the unified scale (Ctrl+plus / Ctrl+minus)."""
        try:
            current = self._ui_scale
        except Exception:
            current = 1.0
        self._set_unified_scale(current + delta)

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
                    w.setFixedHeight(max(self.MIN_BTN_PX, int(round(base * scale))))
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set height on %s", name)

                try:
                    font = w.font()
                    font.setPointSizeF(max(self.MIN_FONT_PT, self.BASE_FONT_PT * scale))
                    w.setFont(font)
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set font on %s", name)

        if hasattr(self, "btn_sidebar_toggle") and not _is_deleted(self.btn_sidebar_toggle):
            self.btn_sidebar_toggle.setFixedWidth(max(self.MIN_BTN_PX, int(round(24 * scale))))
        for btn_name in _BTN_WIDTH_SCALE_NAMES:
            w = getattr(self, btn_name, None)
            if w is not None:
                try:
                    w.setFixedWidth(max(self.MIN_BTN_PX, int(round(24 * scale))))
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set width on %s", btn_name)

                try:
                    font = w.font()
                    font.setPointSizeF(max(self.MIN_FONT_PT, self.BASE_FONT_PT * scale))
                    w.setFont(font)
                except Exception:
                    logger.debug("apply_scaled_ui: failed to set font on %s", btn_name)
