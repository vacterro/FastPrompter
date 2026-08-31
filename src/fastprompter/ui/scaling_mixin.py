"""Scaling mixin for FastPrompter — button sizing, UI scaling, and font adjustment.

Extracted from main.py Phase 1 of the modularization plan.
Provides ScalingMixin class for use as a mixin with FastPrompter QMainWindow.
"""

from PyQt6 import sip
from PyQt6.QtWidgets import QPushButton

from fastprompter.core.logging import logger

_is_deleted = sip.isdeleted


def _is_icon_label(text: str) -> bool:
    """True for a label that is glyphs, not words.

    A multi-letter ASCII label ("NEW", "Save", "Line") is a word and the
    theme's text padding is right for it. Everything else — 📁, ☰, ✕, -→•,
    and the single-letter format buttons B / I / U / S / H — is a mark that
    needs the button's whole box. A lone letter counts as a mark: those live
    in 24px squares where 6px of side padding leaves 8px for an 11px glyph.
    """
    if not text:
        return True
    letters = [ch for ch in text if ch.isascii() and ch.isalpha()]
    return len(letters) < 2

# Static button height / font scale data for apply_scaled_ui
_BTN_BASE_HEIGHTS = {
    "btn_clear": 24,
    "btn_clear_fmt": 24,
    "btn_files": 24,
    "btn_header": 24,
    "btn_pin_top": 20,
    "btn_line_nums": 20,
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
    # A label below this is mush rather than small text - measured at 7px on
    # Vintage Classic, where "NEW" came out three pixels tall.
    MIN_LABEL_PX = 9
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

    def scale_button_qss(self, qss):
        """Scale the px lengths inside a per-button stylesheet.

        The theme hands out strings like "font-size: 11px; padding: 4px;
        border: 1px". Those never scaled, while apply_button_size shrank the
        BOX - so at 50% the box floors at 20px while the stylesheet still
        wants 11 + 4*2 + 1*2 = 21px of height, and Qt squashes the label to
        fit. That is the "chewed up" text, and it showed on a theme change
        because that is when these strings are re-applied.
        """
        import re

        scale = self._effective_scale()

        # Budget the box rather than scaling everything blindly. Scaling the
        # font down with the rest made it 7px on Vintage Classic - a label
        # three pixels tall, unreadable mush. The font gets a legibility
        # floor and the PADDING gives way instead, since padding is the part
        # nobody misses at 50%.
        border = 0
        m = re.search(r"border\s*:\s*(\d+)px", qss)
        if m:
            border = int(m.group(1))
        box = max(self.MIN_BTN_PX, int(round(24 * scale)))

        def font_px(value):
            # never GROWN: the button widths do not scale, and enlarging the
            # font at 150% made "Save" ask for 64px inside a 60px box
            return max(self.MIN_LABEL_PX, min(value, int(round(value * scale))))

        sized = re.search(r"font-size\s*:\s*(\d+)px", qss)
        font = font_px(int(sized.group(1))) if sized else self.MIN_LABEL_PX
        # what is left of the height once the font and both borders are in
        room = box - font - 2 * border
        pad = max(1, room // 2)

        def rewrite(match):
            prop, value = match.group(1), int(match.group(2))
            if prop == "font-size":
                return f"font-size: {font_px(value)}px"
            # padding gives way only when the box cannot hold it; at a
            # comfortable size the theme's own value is kept
            return f"{prop}: {min(value, pad)}px"

        return re.sub(r"(font-size|padding|margin)\s*:\s*(\d+)px",
                      rewrite, qss)

    def apply_button_size(self, widget, base_w, base_h=None):
        """Set widget size based on the combined UI x button scale."""
        scale = self._effective_scale()
        widget._base_size = (base_w, base_h)
        min_sz = max(self.MIN_BTN_PX, int(base_w * scale))
        # An icon button cannot afford the theme's TEXT padding. Vintage
        # Classic asks for a 2px border plus 3px/6px padding, which inside a
        # 20x20 button leaves a 4x10 content rect for a glyph that needs 15px
        # — the emoji was painted as a narrow vertical slice, which is what
        # "the icons are cropped" was. Golden Default's 1px + 2px/4px leaves
        # 10x14, which is why the dark themes looked nearly right and the
        # light one looked broken. Decided by the LABEL, not by the shape:
        # 📁 is an icon at any size, NEW and Save are words and keep their
        # padding.
        widget.setProperty("fp_icon_button", _is_icon_label(widget.text()))
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
        self.mark_dirty("settings")
        if hasattr(self, "btn_button_scale") and not _is_deleted(self.btn_button_scale):
            self.btn_button_scale.setText(f"Scale: {int(value * 100)}%")
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

        self.refresh_scaled_button_qss()
        self.enforce_button_fit()

    # How small a label may get before growing the box is the better trade.
    # Below this a glyph is mush, so the box gives way instead.
    FIT_MIN_FONT_PT = 7.0

    def button_content_rect(self, btn):
        """The box a button really has for its label, chrome subtracted.

        MUST come from the style, not from contentsRect(): a QWidget knows
        nothing about the padding and border its stylesheet asks for, so
        contentsRect() cheerfully reports the whole 20x20 while the style is
        handing the label a 4x10 slot. That gap is why every previous size
        check passed while the icons were visibly sliced.
        """
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        opt = QStyleOptionButton()
        btn.initStyleOption(opt)
        return btn.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, btn)

    def _label_fits(self, btn):
        """Does this button's label fit the box the style gives it?"""
        from PyQt6.QtGui import QFontMetrics
        content = self.button_content_rect(btn)
        fm = QFontMetrics(btn.font())
        return (content.width() >= fm.horizontalAdvance(btn.text())
                and content.height() >= fm.height())

    def fit_button_label(self, btn):
        """Guarantee this button's label fits the box the style gives it.

        Two levers, in order of who should give way:

        1. The FONT, while the button has a fixed size. A header button is
           fixed on purpose (the toolbar packs to a budget) so growing it is
           not allowed — the label shrinks, down to FIT_MIN_FONT_PT.
        2. The BOX, for anything the layout is free to size. A settings
           button with a word on it should be as wide as the word.

        Returns True when it had to change something.
        """
        from PyQt6.QtGui import QFontMetrics
        if _is_deleted(btn) or not btn.text():
            return False
        text = btn.text()
        changed = False

        chrome_w = btn.width() - self.button_content_rect(btn).width()
        chrome_h = btn.height() - self.button_content_rect(btn).height()
        fixed_w = btn.minimumWidth() == btn.maximumWidth()
        fixed_h = btn.minimumHeight() == btn.maximumHeight()

        # Start from the size somebody else intended, not from whatever this
        # pass left last time. Without this the shrink is a ratchet: a button
        # squeezed once at 50% scale stays small forever, and the "fix" then
        # depends on the history of themes the window has been through rather
        # than on the theme it is wearing.
        base = btn.property("_fit_base_pt")
        applied = btn.property("_fit_applied_pt")
        current = btn.font().pointSizeF()
        if base is None or applied is None or abs(current - float(applied)) > 0.01:
            base = current                  # a real font change: new baseline
            btn.setProperty("_fit_base_pt", base)
        elif abs(current - float(base)) > 0.01:
            font = btn.font()
            font.setPointSizeF(float(base))
            btn.setFont(font)

        # How far the label may shrink before the box has to give instead.
        # A fixed button (a toolbar square) can go to the hard floor — it is
        # not allowed to grow at all. A free one only gives up 2pt: past that
        # the box growing is the better trade, since the alternative is a
        # settings panel full of tiny text.
        floor = self.FIT_MIN_FONT_PT
        if not (fixed_w or fixed_h):
            floor = max(floor, btn.font().pointSizeF() - 2.0)

        for _ in range(24):                       # 24 half-point steps floor-ward
            content = self.button_content_rect(btn)
            fm = QFontMetrics(btn.font())
            need_w, need_h = fm.horizontalAdvance(text), fm.height()
            if content.width() >= need_w and content.height() >= need_h:
                btn.setProperty("_fit_applied_pt", btn.font().pointSizeF())
                return changed
            size = btn.font().pointSizeF()
            if size <= floor:
                break
            font = btn.font()
            font.setPointSizeF(max(floor, size - 0.5))
            btn.setFont(font)
            changed = True

        # Still short, and the box is free: leave it to the layout. Raising
        # the minimum of a button inside the wrapping settings panel pushes
        # that panel into another row, which is the wasted-vertical-space
        # complaint T-605 was about — and a free button is one the user can
        # give room by widening the window. Only a FIXED box, which no layout
        # will ever grow, has to be enlarged here.
        if not (fixed_w or fixed_h):
            btn.setProperty("_fit_applied_pt", btn.font().pointSizeF())
            return changed

        # Never shrinks a button — only raises the minimum it needs, so a
        # layout that already gave it more keeps that.
        fm = QFontMetrics(btn.font())
        need_w, need_h = fm.horizontalAdvance(text), fm.height()
        content = self.button_content_rect(btn)
        if content.width() < need_w:
            want = need_w + max(0, chrome_w)
            if fixed_w:
                btn.setFixedWidth(want)
            elif btn.minimumWidth() < want:
                btn.setMinimumWidth(want)
            changed = True
        if content.height() < need_h:
            want = need_h + max(0, chrome_h)
            if fixed_h:
                btn.setFixedHeight(want)
            elif btn.minimumHeight() < want:
                btn.setMinimumHeight(want)
            changed = True
        btn.setProperty("_fit_applied_pt", btn.font().pointSizeF())
        return changed

    def enforce_button_fit(self):
        """Run fit_button_label over every button in the window.

        One pass, after the theme and the scale have settled. Deliberately
        not a per-button opt-in: the cropped-icon bug survived years of
        per-button fixes precisely because every new button, theme and scale
        combination was a fresh chance to get it wrong. Measuring every
        button after every change is the only version of this that stays
        fixed.
        """
        from PyQt6.QtWidgets import QApplication, QPushButton
        if not hasattr(self, "findChildren"):
            return 0            # the mixin used on its own, without a widget
        style = QApplication.style()
        fixed = 0
        for btn in self.findChildren(QPushButton):
            if _is_deleted(btn) or btn.isHidden() or not btn.text():
                continue

            # Tag by label HERE, not only in apply_button_size. Half the
            # buttons in the app are built by panels that never call it — the
            # snippet row's ▲ ▶ ▼ among them — and those kept the theme's
            # text padding, which on Vintage Classic left 10px of a 20px box
            # for an 11px mark. Tagging centrally is the difference between
            # "the buttons I remembered" and "every button".
            want_icon = _is_icon_label(btn.text())
            tag_changed = btn.property("fp_icon_button") != want_icon
            if tag_changed:
                btn.setProperty("fp_icon_button", want_icon)
            # Repolish whenever the tag CHANGED, and also whenever a tagged
            # button still does not fit: a property set before the theme's
            # stylesheet existed (apply_button_size runs during construction)
            # is not re-evaluated on its own, so the padding rule silently
            # never applied to it and the measurement below was of the old
            # chrome. Only offenders pay for the repolish.
            if style is not None and (tag_changed or
                                      (want_icon and not self._label_fits(btn))):
                style.unpolish(btn)
                style.polish(btn)
            # Only marks and fixed boxes are guaranteed. A word in a layout
            # that squeezes it gets elided by Qt — "+ Fon…" is legible and
            # the user can widen the window; forcing those wider instead
            # makes the settings panel wrap into extra rows, which is the
            # wasted-vertical-space complaint T-605 was about. A MARK cannot
            # elide into anything readable: half a folder is just a slice.
            if not (btn.property("fp_icon_button")
                    or btn.minimumWidth() == btn.maximumWidth()
                    or btn.minimumHeight() == btn.maximumHeight()):
                continue
            # is_squishable is a deliberate "this may be squeezed" mark on the
            # snippet-row arrows; they are meant to lose a pixel rather than
            # push the row taller, so the guarantee does not apply to them.
            if getattr(btn, "is_squishable", False):
                continue
            try:
                if self.fit_button_label(btn):
                    fixed += 1
            except Exception:
                logger.debug("fit pass failed on %s", btn.objectName(), exc_info=True)
        return fixed

    def refresh_scaled_button_qss(self):
        """Re-apply the themed button stylesheets at the current scale.

        Changing the scale resizes the boxes but does not re-run apply_theme,
        so without this the fixed px font and padding in those strings stayed
        at their 100% values while the box shrank.
        """
        theme = getattr(self, "_theme_cache", None)
        if not theme:
            return
        for name, key in (("btn_new", "btn_new"), ("btn_save", "btn_save")):
            btn = getattr(self, name, None)
            if btn is None or _is_deleted(btn) or key not in theme:
                continue
            try:
                btn.setStyleSheet(self.scale_button_qss(theme[key]))
            except Exception:
                logger.debug("failed to rescale the stylesheet on %s", name)
