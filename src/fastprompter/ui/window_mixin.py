"""Window management mixin for FastPrompter — positioning, visibility, geometry,
AOT, sidebar layout, focus mode, and UI toggle callbacks.

Extracted from main.py Wave 4 of the modularization plan.
Provides WindowMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import ctypes

from PyQt6 import sip
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from fastprompter.core.logging import logger

_is_deleted = sip.isdeleted


class WindowMixin:
    """Mixin providing window positioning, visibility, and always-on-top management.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.data, self._always_on_top, self._normal_window,
        self.cb_top, self.cb_lock_window, self.cb_lock_cursor,
        self.topmost_timer, self.text_area, self.snippets_section,
        self.is_locked, self._locked_geometry
    """

    def enforce_topmost(self) -> None:
        """Re-apply WS_EX_TOPMOST flag via Win32 SetWindowPos every 2 seconds."""
        if self._always_on_top and not self.isHidden():
            if self._normal_window:
                return
            try:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 1
                SWP_NOMOVE = 2
                ctypes.windll.user32.SetWindowPos(
                    int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
                )
            except Exception:
                logger.exception("Failed to enforce always-on-top")

    def toggle_visibility(self, force_sidebar: bool = False) -> None:
        """Toggle window visibility: show if hidden, hide+suspend if visible."""
        if (
            self.isHidden()
            or self.isMinimized()
            or not self.isVisible()
            or not self.isActiveWindow()
        ):
            if force_sidebar and not self.snippets_section.isVisible():
                self.toggle_sidebar_visibility()
            self.show_window()
        elif force_sidebar:
            self.toggle_sidebar_visibility()
        else:
            if hasattr(self, "topmost_timer") and not _is_deleted(self.topmost_timer):
                self.topmost_timer.stop()
            self.hide_and_save()

    def show_window(self, by_hotkey: bool = False) -> None:
        """Show the window, reposition if lock-to-cursor, re-register hotkeys."""
        if (
            by_hotkey
            and hasattr(self, "cb_lock_cursor")
            and not _is_deleted(self.cb_lock_cursor)
            and self.cb_lock_cursor.isChecked()
        ):
            self.place_window()
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.register_all_hotkeys()
        if (
            hasattr(self, "topmost_timer")
            and not _is_deleted(self.topmost_timer)
            and self._always_on_top
        ):
            self.topmost_timer.start(30000)
        self.raise_()
        self.activateWindow()
        self.text_area.setFocus()

    def place_window(self) -> None:
        """Restore or calculate window position and size from saved geometry."""
        geo_str = self.data.get("last_geometry", "")

        # 1. First, restore or calculate the size
        if geo_str:
            try:
                _, _, saved_w, saved_h = map(int, geo_str.split(","))
                w, h = max(saved_w, self.minimumWidth()), max(saved_h, self.minimumHeight())
                self.resize(w, h)
            except Exception:
                self.adjustSize()
        else:
            self.adjustSize()

        QApplication.processEvents()
        fw = self.frameGeometry().width()
        fh = self.frameGeometry().height()

        # 2. Then, determine and set the position
        if self.cb_lock_cursor.isChecked():
            cp = QCursor.pos()
            screen = QApplication.screenAt(cp) or QApplication.primaryScreen()
            screen_geom = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

            x = cp.x() - fw // 2
            y = cp.y() - fh // 2

            x = max(screen_geom.left(), min(x, screen_geom.right() - fw))
            y = max(screen_geom.top(), min(y, screen_geom.bottom() - fh))

            self.move(x, y)
        elif geo_str:
            try:
                saved_x, saved_y, _, _ = map(int, geo_str.split(","))
                valid_screen = False
                window_rect = QRect(saved_x, saved_y, fw, fh)
                for screen in QApplication.screens():
                    if screen.availableGeometry().intersects(window_rect):
                        valid_screen = True
                        break
                if not valid_screen:
                    cp = QCursor.pos()
                    saved_x, saved_y = cp.x() - fw // 2, cp.y() - fh // 2
                self.move(saved_x, saved_y)
            except Exception:
                cp = QCursor.pos()
                self.move(cp.x() - fw // 2, cp.y() - fh // 2)
        else:
            cp = QCursor.pos()
            self.move(cp.x() - fw // 2, cp.y() - fh // 2)

    def toggle_aot(self, checked: bool) -> None:
        """Toggle always-on-top using Win32 SetWindowPos or window flags."""
        self.data["always_on_top"] = "True" if checked else "False"
        self.mark_dirty()

        if self._normal_window:
            self.apply_window_flags()
            return

        try:
            hwnd = int(self.winId())
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST if checked else HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE,
            )
        except Exception:
            logger.exception("Failed to toggle always-on-top")
        # Only poll when AOT is on
        if hasattr(self, "topmost_timer") and not _is_deleted(self.topmost_timer):
            if checked:
                self.topmost_timer.start(30000)
            else:
                self.topmost_timer.stop()

    def _update_last_geometry(self) -> None:
        """Save current window geometry to data for persistence."""
        if getattr(self, "is_locked", False):
            return
        if not self.isVisible() or self.isMinimized():
            return

        geo = self.geometry()
        fgeo = self.frameGeometry()
        x, y, w, h = fgeo.x(), fgeo.y(), geo.width(), geo.height()

        if (
            hasattr(self, "cb_lock_cursor")
            and not _is_deleted(self.cb_lock_cursor)
            and self.cb_lock_cursor.isChecked()
        ):
            old_geo = self.data.get("last_geometry", "")
            if old_geo:
                try:
                    ox, oy, _, _ = map(int, old_geo.split(","))
                    x, y = ox, oy
                except Exception:
                    logger.exception("Failed to parse last_geometry")

        new_geo = f"{x},{y},{w},{h}"
        if self.data.get("last_geometry", "") != new_geo:
            self.data["last_geometry"] = new_geo
            self.mark_dirty()

    def set_lock_state(self, checked: bool) -> None:
        """Lock/unlock window size by setting min and max size to current geometry."""
        self.is_locked = bool(checked)
        self.data["window_locked"] = "True" if checked else "False"
        self._locked_geometry = self.geometry()
        if checked:
            self.setMinimumSize(self.size())
            self.setMaximumSize(self.size())
        else:
            self.setMinimumSize(480, 320)
            self.setMaximumSize(16777215, 16777215)
        self.mark_dirty()

    def toggle_lock(self) -> None:
        """Toggle lock state via the lock checkbox."""
        self.cb_lock_window.setChecked(not self.cb_lock_window.isChecked())

    def toggle_always_on_top(self) -> None:
        """Toggle always-on-top via the AOT checkbox."""
        self.cb_top.setChecked(not self.cb_top.isChecked())

    # --- Sidebar / layout management ---

    def toggle_sidebar_visibility(self) -> None:
        """Toggle sidebar panel visibility."""
        sizes = self.splitter.sizes()
        is_right = self._sidebar_right
        idx = 1 if is_right else 0

        if sizes[idx] == 0:
            restored = getattr(self, "_saved_sidebar_size", 130)
            if restored <= 0:
                restored = 130
            sizes[idx] = restored
            sizes[1 - idx] = max(0, self.width() - restored)
        else:
            self._saved_sidebar_size = sizes[idx]
            sizes[1 - idx] += sizes[idx]
            sizes[idx] = 0

        self.splitter.setSizes(sizes)
        self.mark_dirty()

    def toggle_focus_mode(self) -> None:
        """Toggle Zen/Focus mode: hide header, settings, sidebar, and search."""
        self.focus_mode = not getattr(self, "focus_mode", False)

        if self.focus_mode:
            self._pre_focus_header = self.header_widget.isVisible()
            self._pre_focus_mini = self.mini_settings_frame.isVisible()
            self._pre_focus_sizes = self.splitter.sizes()
            self._pre_focus_search = self.search_frame.isVisible()
            self._pre_focus_sidebar = getattr(self, "sidebar_visible", True)

            self.header_widget.setVisible(False)
            self.mini_settings_frame.setVisible(False)
            self.search_frame.setVisible(False)
            if self._sidebar_right:
                self.splitter.setSizes([self.width(), 0])
            else:
                self.splitter.setSizes([0, self.width()])
            self.sidebar_visible = False
            self.btn_sidebar_toggle.setChecked(False)
            if hasattr(self, "btn_focus_toggle"):
                self.btn_focus_toggle.setChecked(True)
        else:
            self.header_widget.setVisible(self._pre_focus_header)
            self.mini_settings_frame.setVisible(self._pre_focus_mini)
            self.search_frame.setVisible(self._pre_focus_search)
            self.sidebar_visible = getattr(self, "_pre_focus_sidebar", True)
            self.btn_sidebar_toggle.setChecked(self.sidebar_visible)
            self.splitter.setSizes(self._pre_focus_sizes)

    def toggle_sidebar_position(self, checked: bool) -> None:
        """Toggle sidebar between left and right."""
        self.data["sidebar_right"] = "True" if checked else "False"
        self.apply_sidebar_position()
        self.mark_dirty()

    def apply_sidebar_position(self) -> None:
        """Layout sidebar on the left or right based on _sidebar_right."""
        is_right = self._sidebar_right
        if is_right:
            self.splitter.insertWidget(0, self.center_panel)
            self.splitter.insertWidget(1, self.left_panel)
            self.splitter.setCollapsible(0, False)
            self.splitter.setCollapsible(1, True)
        else:
            self.splitter.insertWidget(0, self.left_panel)
            self.splitter.insertWidget(1, self.center_panel)
            self.splitter.setCollapsible(0, True)
            self.splitter.setCollapsible(1, False)

        key = "splitter_sizes_right" if is_right else "splitter_sizes_left"
        raw_sizes = self.data.get(key)
        if isinstance(raw_sizes, str):
            import ast
            try:
                raw_sizes = ast.literal_eval(raw_sizes)
            except Exception:
                raw_sizes = [0, 0]
        
        try:
            sizes = [int(x) for x in raw_sizes] if raw_sizes else [0, 0]
            if sum(sizes) > 0:
                sidebar_idx = 1 if is_right else 0
                center_idx = 0 if is_right else 1
                # If sidebar somehow captured >80% of space and center is tiny, reset to prevent getting stuck
                if sizes[sidebar_idx] > self.width() * 0.8 and sizes[center_idx] < 200:
                    sizes = [0, 0]
        except (ValueError, TypeError):
            sizes = [0, 0]

        if sum(sizes) == 0:
            if is_right:
                sizes = [self.width() - 130, 130]
            else:
                sizes = [130, self.width() - 130]
        self.splitter.setSizes(sizes)

    def toggle_mini_settings(self) -> None:
        """Toggle the mini settings footer frame."""
        is_hidden = self.mini_settings_frame.isVisible()
        self.mini_settings_frame.setVisible(not is_hidden)
        self.data["hide_extra"] = "True" if is_hidden else "False"
        self.mark_dirty()

    # --- Simple toggle callbacks ---

    def on_hide_shortkeys_toggled(self, checked: bool) -> None:
        """Toggle display of shortcut key labels on snippet buttons."""
        self.data["hide_shortkeys"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def on_lock_cursor_toggled(self, checked: bool) -> None:
        """Toggle lock-to-cursor (window opens at cursor on hotkey)."""
        self.data["lock_to_cursor"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_snippets_panel()

    def on_silo_home_toggled(self, checked: bool) -> None:
        """Toggle silo-home behavior (silos open at startup)."""
        self.data["silo_home"] = "True" if checked else "False"
        self.mark_dirty()

    def on_sound_toggled(self, checked: bool) -> None:
        """Toggle UI sounds on/off."""
        self.data["sound_ui"] = "True" if checked else "False"
        self.mark_dirty()

    def on_typewriter_toggled(self, checked: bool) -> None:
        """Toggle typewriter sound effect on/off."""
        self.data["sound_typewriter"] = "True" if checked else "False"
        self.mark_dirty()
