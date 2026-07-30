"""Window management mixin for FastPrompter — positioning, visibility, geometry,
AOT, sidebar layout, focus mode, and UI toggle callbacks.

Extracted from main.py Wave 4 of the modularization plan.
Provides WindowMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import ctypes

from PyQt6 import sip
from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr

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
        if by_hotkey:
            # activateWindow() is ASYNC on Windows: the window is not active
            # yet when the setFocus above runs, so the caret often did not
            # land in the silo and the first keystroke went nowhere. Re-apply
            # once activation has settled. Guarded because a deferred call
            # into a destroyed widget is an access violation, not an
            # exception (same class as H-406).
            QTimer.singleShot(0, self._focus_text_silo)

    def _focus_text_silo(self) -> None:
        """Put the caret in the editor. Safe to call from a deferred slot."""
        if _is_deleted(self):
            return
        ta = getattr(self, "text_area", None)
        if ta is None or _is_deleted(ta):
            return
        ta.setFocus()

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
                self.resize(960, 600)
        else:
            self.resize(960, 600)

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
        """Toggle sidebar panel visibility.

        Panes are located by identity. This used to assume the sidebar was
        pane 1 when it sat on the right and pane 0 otherwise; the files dock
        added a third pane, so on the right that index pointed at the CENTRE
        and the hamburger grew the sidebar instead of hiding it.
        """
        sizes = self.splitter.sizes()
        idx = self.splitter.indexOf(self.left_panel)
        centre = self.splitter.indexOf(self.center_panel)
        if idx < 0 or centre < 0 or idx >= len(sizes):
            return

        if sizes[idx] == 0:
            restored = getattr(self, "_saved_sidebar_size", 130)
            if restored <= 0:
                restored = 130
            sizes[idx] = restored
            sizes[centre] = max(0, sizes[centre] - restored)
        else:
            self._saved_sidebar_size = sizes[idx]
            sizes[centre] += sizes[idx]
            sizes[idx] = 0

        self.sidebar_visible = sizes[idx] > 0
        btn = getattr(self, "btn_sidebar_toggle", None)
        if btn is not None and btn.isCheckable():
            btn.setChecked(self.sidebar_visible)
        self.splitter.setSizes(sizes)
        # Persist here too. Sizes were only ever written by splitterMoved, so
        # a sidebar collapsed with the hamburger came back open on the next
        # start — the layout you left was not the layout you returned to.
        key = ("splitter_sizes_right" if self._sidebar_right
               else "splitter_sizes_left")
        self.data[key] = list(sizes)
        self.data["saved_sidebar_size"] = str(getattr(self, "_saved_sidebar_size", 130))
        self.mark_dirty()

    def cycle_focus_mode(self) -> None:
        """What Ctrl+D does. Three stages:

        1st press  Zen: header, footer, search and sidebar go away.
        2nd press  Solo: every OTHER window on the desktop is minimised too.
        3rd press  back to normal — and so is anything that takes the window
                   away (click-out, minimise, tray, hotkey hide), because a
                   desktop left swept clean by an app you are no longer
                   looking at is the worst possible outcome here.

        Kept separate from toggle_focus_mode on purpose. That one is the
        plain two-state switch a dozen callers already use, and folding the
        stages into it made "toggle twice" mean "sweep the desktop" for every
        one of them.
        """
        if getattr(self, "zen_solo", False):
            self.exit_zen_solo()
            self.toggle_focus_mode()        # third press leaves Zen as well
            return
        if getattr(self, "focus_mode", False):
            self._enter_zen_solo()
            return
        self.toggle_focus_mode()

    def toggle_focus_mode(self) -> None:
        """Zen on/off: hide header, settings, sidebar and search."""
        if getattr(self, "zen_solo", False):
            self.exit_zen_solo()
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
            # by identity, not by a 2-element list: with the files dock the
            # splitter has three panes and a short list left the extra one
            # untouched, so Zen mode kept a sidebar on screen
            zen = [0] * self.splitter.count()
            centre = self.splitter.indexOf(self.center_panel)
            if 0 <= centre < len(zen):
                zen[centre] = self.width()
            self.splitter.setSizes(zen)
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

    def _own_hwnds(self):
        """Every window id this app owns, so Zen never minimises itself."""
        from PyQt6.QtWidgets import QApplication
        out = []
        for w in [self] + list(QApplication.topLevelWidgets()):
            try:
                wid = int(w.winId())
            except Exception:
                # a window being torn down has no id; skipping it is right,
                # but say so — this list decides what Zen solo may minimise
                logger.debug("zen: window without an id, skipped", exc_info=True)
                continue
            if wid:
                out.append(wid)
        return out

    def _enter_zen_solo(self) -> None:
        import time as _t

        from fastprompter.ui import zen_desktop
        self._zen_minimised = zen_desktop.minimise_others(self._own_hwnds())
        self.zen_solo = True
        # minimising other windows churns the foreground, and one of those
        # transient deactivations would otherwise undo solo the instant it
        # started. Ignore deactivations for a moment after entering.
        self._zen_solo_at = _t.time()
        # Windows hands the foreground to whatever it un-minimised last, so
        # take it back explicitly — the point of solo is being the only thing
        # in front of the user.
        self.raise_()
        self.activateWindow()

    def exit_zen_solo(self, grace: bool = False) -> None:
        """Put the desktop back. Safe to call when solo was never entered."""
        if not getattr(self, "zen_solo", False):
            return
        if grace:
            import time as _t
            if _t.time() - getattr(self, "_zen_solo_at", 0.0) < 1.0:
                return
        from fastprompter.ui import zen_desktop
        self.zen_solo = False
        zen_desktop.restore(getattr(self, "_zen_minimised", []))
        self._zen_minimised = []
        
        # Windows hands the foreground to whatever it un-minimised last, so
        # take it back explicitly — the user was just looking at FastPrompter.
        self.raise_()
        self.activateWindow()

    def toggle_sidebar_position(self, checked: bool) -> None:
        """Toggle sidebar between left and right."""
        self.data["sidebar_right"] = "True" if checked else "False"
        self.apply_sidebar_position()
        self.mark_dirty()

    def reset_ui_layout(self, confirm=True):
        """Put every layout choice back to its default.

        Toolbar order already had its own reset, but the splitter widths,
        the sidebar side and the window size had no way back short of
        deleting the database — a window dragged somewhere unusable stayed
        that way.
        """
        if confirm:
            from PyQt6.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self, tr("Reset UI Layout", getattr(self, "_current_lang", "EN")),
                tr("Reset the toolbar, sidebar and window size to defaults?\n"
                   "Your text, snippets and silos are not touched.",
                   getattr(self, "_current_lang", "EN")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False

        for key in ("toolbar_order", "last_geometry",
                    "splitter_sizes_left", "splitter_sizes_right"):
            self.data[key] = ""
        self.data["sidebar_right"] = "False"
        self.data["ui_scale"] = "0.5"
        self.data["button_scale"] = "1.0"

        self.sidebar_visible = True
        if hasattr(self, "btn_sidebar_toggle"):
            self.btn_sidebar_toggle.setChecked(True)
        if hasattr(self, "apply_toolbar_order"):
            self.apply_toolbar_order()
        self.apply_sidebar_position()
        self._sync_layout_controls()
        if hasattr(self, "apply_scaled_ui"):
            self.apply_scaled_ui()
        if not self.isMaximized():
            self.adjustSize()
        self.mark_dirty()
        return True

    def _sync_layout_controls(self) -> None:
        """Make the Settings controls agree with the layout data.

        Resetting the layout changed `data` and re-laid the window, but the
        checkboxes still showed the old choice - so "Sidebar Right" stayed
        ticked next to a sidebar that had moved left, and the next click on
        it toggled from the wrong state. Signals are blocked because these
        controls write back to the same keys when they change.
        """
        cb = getattr(self, "cb_sidebar", None)
        if cb is not None and not sip.isdeleted(cb):
            cb.blockSignals(True)
            cb.setChecked(self.data.get("sidebar_right", "False") == "True")
            cb.blockSignals(False)

        btn = getattr(self, "btn_button_scale", None)
        if btn is not None and not sip.isdeleted(btn):
            try:
                pct = int(float(self.data.get("ui_scale", "0.5")) * 100)
            except (TypeError, ValueError):
                pct = 100
            btn.setText(
                f"{tr('Scale', getattr(self, '_current_lang', 'EN'))}: {pct}%")

    def _place_sidebar_toggle(self, is_right: bool) -> None:
        """Keep the hamburger on the same side as the sidebar it opens.

        It used to be pinned to the far left of the header, so with the
        sidebar on the right the button sat at the opposite edge from the
        thing it toggles.
        """
        btn = getattr(self, "btn_sidebar_toggle", None)
        layout = getattr(self, "header_layout", None)
        if btn is None or layout is None:
            return
        layout.removeWidget(btn)
        if is_right:
            layout.addWidget(btn)
        else:
            layout.insertWidget(0, btn)

    def apply_sidebar_position(self) -> None:
        """Layout sidebar on the left or right based on _sidebar_right."""
        is_right = self._sidebar_right
        self._place_sidebar_toggle(is_right)
        # The files dock always takes the side the silo sidebar does not, so
        # the two never fight over an edge: sidebar right -> files left.
        dock = getattr(self, "files_dock", None)
        if is_right:
            if dock is not None:
                self.splitter.insertWidget(0, dock)
            self.splitter.insertWidget(1 if dock is not None else 0, self.center_panel)
            self.splitter.insertWidget(2 if dock is not None else 1, self.left_panel)
            self.splitter.setCollapsible(self.splitter.indexOf(self.center_panel), False)
            self.splitter.setCollapsible(self.splitter.indexOf(self.left_panel), True)
        else:
            self.splitter.insertWidget(0, self.left_panel)
            self.splitter.insertWidget(1, self.center_panel)
            if dock is not None:
                self.splitter.insertWidget(2, dock)
            self.splitter.setCollapsible(self.splitter.indexOf(self.left_panel), True)
            self.splitter.setCollapsible(self.splitter.indexOf(self.center_panel), False)
        if dock is not None:
            self.splitter.setCollapsible(self.splitter.indexOf(dock), True)

        key = "splitter_sizes_right" if is_right else "splitter_sizes_left"
        raw_sizes = self.data.get(key)
        if isinstance(raw_sizes, str):
            import ast
            try:
                raw_sizes = ast.literal_eval(raw_sizes)
            except Exception:
                logger.debug("unreadable splitter sizes %r, using defaults",
                             raw_sizes, exc_info=True)
                raw_sizes = [0, 0]
        
        # panes are read back by identity, not by a hardcoded index: the
        # files dock made "sidebar is pane 0 or 1" wrong in both directions
        sidebar_idx = self.splitter.indexOf(self.left_panel)
        center_idx = self.splitter.indexOf(self.center_panel)
        count = self.splitter.count()

        try:
            sizes = [int(x) for x in raw_sizes] if raw_sizes else []
            if len(sizes) < count:
                sizes += [0] * (count - len(sizes))
            sizes = sizes[:count]
            if sum(sizes) > 0:
                # If sidebar somehow captured >80% of space and center is tiny, reset to prevent getting stuck
                if sizes[sidebar_idx] > self.width() * 0.8 and sizes[center_idx] < 200:
                    sizes = [0] * count
        except (ValueError, TypeError):
            sizes = [0] * count

        if sum(sizes) == 0:
            sizes = [0] * count
            sizes[sidebar_idx] = 130
            sizes[center_idx] = max(200, self.width() - 130)
        self.splitter.setSizes(sizes)

        # A saved size list predates the dock (or was saved for the other
        # side), so the dock lands at 0 width and looks like it vanished when
        # the sidebar is flipped. Give it its width back if it is open.
        if (dock is not None and not dock.isHidden()
                and hasattr(self, "_show_files_dock")):
            self._show_files_dock(True)

        # a sidebar the user collapsed stays collapsed across a restart, so
        # the toggle button has to agree with it from the first paint
        self.sidebar_visible = sizes[sidebar_idx] > 0
        btn = getattr(self, "btn_sidebar_toggle", None)
        if btn is not None and btn.isCheckable():
            btn.setChecked(self.sidebar_visible)
        try:
            self._saved_sidebar_size = max(
                60, int(self.data.get("saved_sidebar_size", 130)))
        except (TypeError, ValueError):
            self._saved_sidebar_size = 130

    def toggle_mini_settings(self) -> None:
        """Toggle the mini settings footer frame."""
        was_visible = self.mini_settings_frame.isVisible()
        self.mini_settings_frame.setVisible(not was_visible)
        if not was_visible and hasattr(self, "_fit_settings_tabs"):
            self._fit_settings_tabs()
            QTimer.singleShot(0, self._fit_settings_tabs)
        self.data["hide_extra"] = "True" if was_visible else "False"
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
