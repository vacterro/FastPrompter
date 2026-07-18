"""Snippet operations mixin for FastPrompter — CRUD, archive, clipboard, and import/export.

Extracted from main.py Phase 2c of the modularization plan.
Provides SnippetOpsMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import os
import time

from PyQt6 import sip
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from fastprompter.core.translations import tr
from fastprompter.core.logging import logger

_is_deleted = sip.isdeleted


class SnippetOpsMixin:
    """Mixin providing snippet CRUD, archive, clipboard, and file operations.

    Type hints assume these attributes are provided by the FastPrompter
    QMainWindow instance at runtime:
        self.data, self.text_area, self.sound_manager, self.silo_docs,
        self.archive_docs, self.snippet_docs, self.editing_snippet,
        self.active_temp_slot, self.btn_save, self._cache_timer,
        self._suspend_cache, self.silo_last_edited, self._visible_silos,
        self.silo_page, self.cat_combo
    """

    def insert_snippet_text(self, text, position):
        """Insert text at the specified position (top, bot, or ins)."""
        if not text:
            return
        self.sound_manager.play_click()
        self.mark_dirty()
        cursor = self.text_area.textCursor()
        cursor.beginEditBlock()

        if position == "top":
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            if self.text_area.toPlainText():
                cursor.insertText(text + "\n")
            else:
                cursor.insertText(text)
        elif position == "bot":
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if self.text_area.toPlainText() and not self.text_area.toPlainText().endswith("\n"):
                cursor.insertText("\n")
            cursor.insertText(text)
        elif position == "ins":
            cursor.insertText(text)

        cursor.endEditBlock()
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def save_silo_to_file(self):
        """Save the current silo text to a file."""
        text = self.text_area.toPlainText()
        if not text:
            return
        self.ignore_focus_loss = True
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("Save Silo", getattr(self, "_current_lang", "EN")), "", tr("Text Files (*.txt)", getattr(self, "_current_lang", "EN")) + ";;" + tr("Markdown Files (*.md)", getattr(self, "_current_lang", "EN")) + ";;" + tr("All Files (*.*)", getattr(self, "_current_lang", "EN"))
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                QMessageBox.information(self, tr("Saved", getattr(self, "_current_lang", "EN")), tr("Silo successfully saved to:\n{}", getattr(self, "_current_lang", "EN")).format(path))
            except Exception as e:
                QMessageBox.critical(self, tr("Error", getattr(self, "_current_lang", "EN")), tr("Failed to save file:\n{}", getattr(self, "_current_lang", "EN")).format(e))

    def backup_silo_to_files(self, idx, is_archive=False):
        """Save the current silo text as a file in its own file container."""
        import datetime
        import os

        from PyQt6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )

        if is_archive:
            return  # No file folder for archives currently

        silo_text = self.data["temp_presets"][idx]
        if not silo_text.strip():
            return

        from fastprompter.ui.file_container import silo_slug
        safe = silo_slug(silo_text)
        if not safe:
            safe = "_blank"
        folder = os.path.join(self._files_root(), self.get_current_category(), safe)
        if not folder:
            return

        default_name = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        self.ignore_focus_loss = True
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle(tr("Backup Silo", getattr(self, "_current_lang", "EN")))
            layout = QVBoxLayout(dlg)

            layout.addWidget(QLabel(tr("Save current silo as file in its own folder:", getattr(self, "_current_lang", "EN"))))
            le = QLineEdit(default_name)
            layout.addWidget(le)

            btn_layout = QHBoxLayout()
            btn_copy = QPushButton(tr("Copy", getattr(self, "_current_lang", "EN")))
            btn_copy_clear = QPushButton(tr("Copy + Clear current silo", getattr(self, "_current_lang", "EN")))
            btn_cancel = QPushButton(tr("Cancel", getattr(self, "_current_lang", "EN")))

            btn_layout.addWidget(btn_copy)
            btn_layout.addWidget(btn_copy_clear)
            btn_layout.addWidget(btn_cancel)
            layout.addLayout(btn_layout)

            result = [None]

            def on_copy():
                result[0] = "copy"
                dlg.accept()

            def on_copy_clear():
                result[0] = "clear"
                dlg.accept()

            btn_copy.clicked.connect(on_copy)
            btn_copy_clear.clicked.connect(on_copy_clear)
            btn_cancel.clicked.connect(dlg.reject)

            if dlg.exec():
                name = le.text().strip()
                if not name: return

                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, name)
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(silo_text)
                except Exception as e:
                    QMessageBox.warning(self, tr("Error", getattr(self, "_current_lang", "EN")), tr("Failed to save backup:\n{}", getattr(self, "_current_lang", "EN")).format(e))
                    return

                if result[0] == "clear":
                    if is_archive == getattr(self, "active_is_archive", False) and idx == getattr(self, "active_temp_slot", -1):
                        self.clear_text(internal=False)
                    else:
                        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
                        docs = self.archive_docs if is_archive else self.silo_docs
                        if 0 <= idx < len(presets):
                            presets[idx] = ""
                        if 0 <= idx < len(docs):
                            self._set_plain_text_clean(docs[idx], "")
                        self.sound_manager.play("clear")
                self.play_tick_sound()
        finally:
            self.ignore_focus_loss = False
            self.activateWindow()

    def load_snippet_for_edit(self, cat, global_idx, cursor_pos="end"):
        """Load a snippet into the editor for editing."""
        self._cache_timer.stop()  # prevent stale timer from writing to wrong slot
        if self.editing_snippet:
            self.save_snippet(silent=True)
        # Save current silo before loading snippet (sandbox)
        elif 0 <= self.active_temp_slot < len(self.data["temp_presets"]):
            self.data["temp_presets"][self.active_temp_slot] = self.text_area.toPlainText()
        self.sound_manager.play("snippet")

        slot_data = (
            self.data["categories"].get(cat, [None] * 100)[global_idx]
            if cat in self.data["categories"]
            else None
        )
        if not slot_data:
            return
        self.mark_dirty()
        self.ignore_focus_loss, self._suspend_cache = True, True

        self._begin_batch_update()
        try:
            try:
                self.text_area.blockSignals(True)
                snippet_key = f"{cat}_{global_idx}"
                if snippet_key not in self.snippet_docs:
                    doc = QTextDocument()
                    doc.setDefaultFont(self.text_area.font())
                    self.snippet_docs[snippet_key] = doc

                doc = self.snippet_docs[snippet_key]
                if doc.toPlainText() != slot_data["text"]:
                    self._set_plain_text_clean(doc, slot_data["text"])

                self.text_area.set_active_document(doc)

                if cursor_pos == "start":
                    self.text_area.moveCursor(QTextCursor.MoveOperation.Start)
                else:
                    self.text_area.moveCursor(QTextCursor.MoveOperation.End)
            finally:
                self.text_area.blockSignals(False)
                self._suspend_cache, self.ignore_focus_loss = False, False
            self.editing_snippet = (cat, global_idx)
            self.btn_save.setText(tr("Update", getattr(self, "_current_lang", "EN")))
            theme_name = self.data.get("theme", "Default")

            edit_color = "#363b40"
            if theme_name == "Custom":
                custom_colors = self._get_custom_colors()
                if "edit_bg" in custom_colors:
                    edit_color = custom_colors["edit_bg"]

            self._refresh_theme_cache()
            base_style = self._theme_cache.get("btn_save", "")
            self.btn_save.setStyleSheet(
                base_style.replace(
                    "background-color:", f"background-color: {edit_color} !important; /*"
                )
                + f" */ background-color: {edit_color}; color: #ffffff;"
            )
            self.refresh_snippets_panel()
            self.refresh_temp_presets()
            self.update_preview()
            if hasattr(self, "_update_line_count_label"):
                self._update_line_count_label()
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            self.activateWindow()
        finally:
            self._end_batch_update()

    def prompt_delete_snippet(self, cat, global_idx):
        """Prompt the user to confirm and delete a snippet."""
        self.sound_manager.play("delete")
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                tr("Delete Snippet", getattr(self, "_current_lang", "EN")),
                tr("Delete this snippet?", getattr(self, "_current_lang", "EN")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_preset_by_index(cat, global_idx)

    def rename_snippet(self, cat, global_idx):
        """Rename a snippet via input dialog."""
        slots = self.data["categories"][cat]
        if slots[global_idx] is None:
            return
        old_name = slots[global_idx]["name"]
        self.ignore_focus_loss = True
        try:
            new_name, ok = QInputDialog.getText(self, tr("Rename Snippet", getattr(self, "_current_lang", "EN")), tr("New name:", getattr(self, "_current_lang", "EN")), text=old_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and new_name and new_name.strip():
            self.add_data_undo_state("Rename snippet")
            slots[global_idx]["name"] = new_name.strip()
            self.mark_dirty()
            self.refresh_snippets_panel()

    def copy_snippet_to_clipboard(self, text):
        """Copy snippet text to clipboard."""
        self.safe_set_clipboard(text)

    def cancel_editing(self, silent=False):
        """Cancel snippet editing mode and restore button state."""
        self.editing_snippet = None
        self.btn_save.setText(tr("Save", getattr(self, "_current_lang", "EN")))
        self._refresh_theme_cache()
        self.btn_save.setStyleSheet(self._theme_cache.get("btn_save", ""))
        if not silent:
            self.refresh_snippets_panel()
            self.refresh_temp_presets()

    def clear_text(self, internal=False):
        """Clear all text from the editor and the active silo data.

        internal=True: caller already recorded an undo snapshot — pushing a
        second, post-mutation snapshot here would make the first Ctrl+Z a
        no-op (the 'cannot revert deleted silos' bug).
        """
        if not internal:
            self.add_data_undo_state("Clear text")
            self.sound_manager.play("clear")

        # Also clear the underlying silo data so it doesn't persist
        if not getattr(self, "editing_snippet", None):
            is_arc = getattr(self, "active_is_archive", False)
            presets = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
            docs = self.archive_docs if is_arc else self.silo_docs
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(presets):
                presets[slot] = ""
            if 0 <= slot < len(docs):
                self._set_plain_text_clean(docs[slot], "")

        if internal:
            # Don't bump the text-edit clock: Ctrl+Z must route to the
            # caller's data snapshot, which restores the full state.
            self.text_area.blockSignals(True)
        try:
            cursor = self.text_area.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()
            cursor.endEditBlock()
        finally:
            if internal:
                self.text_area.blockSignals(False)
                if hasattr(self, "_update_line_count_label"):
                    self._update_line_count_label()
        self.cancel_editing()
        self.text_area.setFocus()

    def copy_context_to_clipboard(self):
        """Copy entire text area content to clipboard."""
        text = self.text_area.toPlainText()
        QApplication.clipboard().setText(text)

    def copy_context_and_close(self, pos=None):
        """Copy entire text area content to clipboard and hide FastPrompter."""
        self.copy_context_to_clipboard()
        self.hide_and_save()

    def get_current_category(self):
        """Get the category name of the currently selected tab."""
        idx = self.cat_combo.currentIndex()
        if 0 <= idx < len(self.data["cats_order"]):
            return self.data["cats_order"][idx]
        return None

    def save_snippet(self, silent=False):
        """Save the current text as a snippet (new or update existing)."""
        if not silent:
            self.sound_manager.play("snippet")
        text = self.text_area.toPlainText().strip()
        cat = self.get_current_category()

        if self.editing_snippet:
            edit_cat, idx = self.editing_snippet
            if edit_cat in self.data["categories"]:
                slots = self.data["categories"][edit_cat]
                if text:
                    old_name = slots[idx]["name"] if slots[idx] else ""

                    if silent:
                        self.add_data_undo_state("Auto-save snippet")
                    else:
                        self.add_data_undo_state("Save snippet")
                    old_text = slots[idx].get("text", "") if slots[idx] else ""
                    last_edited = slots[idx].get("last_edited", 0) if slots[idx] else 0
                    if text != old_text:
                        last_edited = int(time.time())
                    slots[idx] = {"name": old_name, "text": text, "last_edited": last_edited}
                    self.mark_dirty()
                    self.refresh_snippets_panel()
            self.cancel_editing()
            return

        # cat must be a live category — a tab deleted mid-edit would leave a
        # stale name and KeyError on the slots lookup below.
        if not text or not cat or cat not in self.data["categories"]:
            return
        if silent:
            # Silent saves only update an existing snippet edit — they must
            # never pop the name dialog from a background/auto-save path.
            return
        slots = self.data["categories"][cat]

        if None not in slots:
            return
        auto_name = (
            (text.replace("\n", " ")[:22] + "...") if len(text) > 22 else text.replace("\n", " ")
        )
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, tr("Save Snippet", getattr(self, "_current_lang", "EN")), tr("Name:", getattr(self, "_current_lang", "EN")), text=auto_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name:
            self.add_data_undo_state("Save snippet")
            slots[slots.index(None)] = {"name": name, "text": text, "last_edited": int(time.time())}
            self.mark_dirty()
            self.refresh_snippets_panel()

    def save_snippet_as_number(self):
        """Save current text to a specific numbered slot."""
        self.sound_manager.play("snippet")
        if self.editing_snippet:
            self.save_snippet(silent=True)
        text = self.text_area.toPlainText().strip()
        if not text:
            return
        cat = self.get_current_category()
        if not cat or cat not in self.data["categories"]:
            return
        max_slots = len(self.data["categories"][cat])

        self.ignore_focus_loss = True
        try:
            num, ok = QInputDialog.getInt(
                self, tr("Snippet Number", getattr(self, "_current_lang", "EN")), tr("Enter snippet number (1-{}):", getattr(self, "_current_lang", "EN")).format(max_slots), 1, 1, max_slots
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

        if not ok:
            return
        slot = num - 1
        slots = self.data["categories"][cat]

        if slots[slot] is not None:
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(
                    self,
                    tr("Overwrite Snippet", getattr(self, "_current_lang", "EN")),
                    tr("Snippet #{} already exists. Overwrite?", getattr(self, "_current_lang", "EN")).format(num),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
            finally:
                self.ignore_focus_loss = False
            self.activateWindow()
            if reply != QMessageBox.StandardButton.Yes:
                return

        auto_name = (
            (text.replace("\n", " ")[:22] + "...") if len(text) > 22 else text.replace("\n", " ")
        )
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, tr("Save Snippet", getattr(self, "_current_lang", "EN")), tr("Name:", getattr(self, "_current_lang", "EN")), text=auto_name)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

        if ok and name:
            self.add_data_undo_state("Save snippet as number")
            slots[slot] = {"name": name, "text": text, "last_edited": int(time.time())}
            self.mark_dirty()
            self.refresh_snippets_panel()
            self.cancel_editing()

    def del_last_snippet(self):
        """Delete the last snippet or current silo."""
        cat = self.get_current_category()
        if getattr(self, "editing_snippet", None) and cat and self.editing_snippet[0] == cat:
            idx = self.editing_snippet[1]
            slots = self.data["categories"][cat]
            if slots[idx] and slots[idx].get("text", "").strip():
                self.ignore_focus_loss = True
                try:
                    reply = QMessageBox.question(
                        self,
                        tr("Delete Snippet", getattr(self, "_current_lang", "EN")),
                        tr("Are you sure you want to delete this snippet?", getattr(self, "_current_lang", "EN")),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                finally:
                    self.ignore_focus_loss = False
                self.activateWindow()
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self.sound_manager.play("delete")
            self.delete_preset_by_index(cat, idx)
            return

        current_text = self.text_area.toPlainText().strip()
        if current_text:
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(
                    self,
                    tr("Delete Silo", getattr(self, "_current_lang", "EN")),
                    tr("Are you sure you want to delete this silo and its content?", getattr(self, "_current_lang", "EN")),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
            finally:
                self.ignore_focus_loss = False
            self.activateWindow()
            if reply != QMessageBox.StandardButton.Yes:
                return

            self.sound_manager.play("delete")
            self.del_silo()
            return

    def _delete_file_container(self, cat, text):
        """Retire a silo's file folder when the silo is cleared/deleted.

        Never destroys user assets: the folder is MOVED to
        data/files/_trash/<slug>-<n>/ so it survives an accidental clear
        (silo text is undoable via Ctrl+Z; files must not be less safe)."""
        import os
        import shutil
        import time

        from fastprompter.ui.file_container import silo_files_dir
        if not hasattr(self, "_files_root"):
            return
        d = silo_files_dir(self._files_root(), cat, text)
        try:
            if not os.path.isdir(d) or not os.listdir(d):
                if os.path.isdir(d):
                    os.rmdir(d)  # empty folder: no assets to keep
                return
            trash = os.path.join(self._files_root(), "_trash")
            os.makedirs(trash, exist_ok=True)
            dest = os.path.join(trash, f"{os.path.basename(d)}-{int(time.time())}")
            n = 2
            while os.path.exists(dest):
                dest = os.path.join(trash, f"{os.path.basename(d)}-{int(time.time())}-{n}")
                n += 1
            shutil.move(d, dest)
        except OSError as e:
            logger.warning(f"Could not retire file container {d}: {e}")

    def delete_preset_by_index(self, cat, global_idx):
        """Delete a snippet at the given category and index."""
        if self.data["categories"][cat][global_idx] is not None:
            self.add_data_undo_state("Delete snippet")
            target_item = self.data["categories"][cat][global_idx]
            if self.data.get("trash_vision", "False") == "True" and cat != "Trash":
                if "Trash" not in self.data["categories"]:
                    self.data["categories"]["Trash"] = []
                if "Trash" not in self.data["cats_order"]:
                    self.data["cats_order"].append("Trash")
                self.data["categories"]["Trash"].append(target_item)
            else:
                self._delete_file_container(cat, target_item["text"])
        if getattr(self, "editing_snippet", None) == (cat, global_idx):
            self.editing_snippet = None
            self.btn_save.setText(tr("Save", getattr(self, "_current_lang", "EN")))
            self._refresh_theme_cache()
            self.btn_save.setStyleSheet(self._theme_cache.get("btn_save", ""))
            # Stop the debounce timer before touching the editor to prevent it from
            # writing "" to temp_presets[active_slot] after _suspend_cache is released
            self._cache_timer.stop()
            self._suspend_cache = True
            try:
                self.text_area.blockSignals(True)
                # Restore the active silo/archive document (don't blank the editor)
                if not getattr(self, "active_is_archive", False):
                    slot = self.active_temp_slot
                    if 0 <= slot < len(self.silo_docs):
                        self.text_area.set_active_document(self.silo_docs[slot])
                else:
                    slot = self.active_temp_slot
                    if 0 <= slot < len(self.archive_docs):
                        self.text_area.set_active_document(self.archive_docs[slot])
            finally:
                self.text_area.blockSignals(False)
                self._suspend_cache = False
        snippet_key = f"{cat}_{global_idx}"
        if snippet_key in getattr(self, "snippet_docs", {}):
            del self.snippet_docs[snippet_key]
        self.data["categories"][cat][global_idx] = None
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_archive_panel()

    def trash_silo(self, idx=None, is_archive=False):
        """Move a silo to the trash: its text lands as a .md file in
        data/files/_trash/ (next to any files it owned) and the slot is
        removed. Nothing is destroyed — the trash folder is a plain dir."""
        import datetime

        from fastprompter.ui.file_container import silo_slug
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if idx is None:
            idx = self.active_temp_slot
        if not (0 <= idx < len(presets)):
            return
        if idx == self.active_temp_slot and is_archive == getattr(self, "active_is_archive", False):
            presets[idx] = self.text_area.toPlainText()
        text = presets[idx]
        if text.strip():
            trash = os.path.join(self._files_root(), "_trash")
            try:
                os.makedirs(trash, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%d.%m.%y-%H%M%S")
                name = f"{silo_slug(text)}-{stamp}.md"
                with open(os.path.join(trash, name), "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                logger.warning(f"Trash write failed, silo NOT deleted: {e}")
                return
        self.del_silo(idx)

    def open_trash_folder(self):
        trash = os.path.join(self._files_root(), "_trash")
        os.makedirs(trash, exist_ok=True)
        try:
            os.startfile(trash)
        except OSError as e:
            logger.error(f"Open trash failed: {e}")

    def del_silo(self, idx=None):
        """Delete a silo at the given index, or the active one."""
        self.sound_manager.play("delete")
        is_arc = getattr(self, "active_is_archive", False)
        presets = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
        docs = self.archive_docs if is_arc else self.silo_docs
        if len(presets) > 1:
            if idx is None:
                idx = self.active_temp_slot

            if not (0 <= idx < len(presets)):
                return

            if idx == self.active_temp_slot:
                presets[idx] = self.text_area.toPlainText()
            self.add_data_undo_state("Delete silo")

            old_text = presets[idx]
            self._delete_file_container(self.get_current_category(), old_text)

            presets.pop(idx)
            if idx < len(docs):
                docs.pop(idx)

            if not is_arc:
                self.silo_last_edited.pop(idx, None)
                pinned = self.data.get("pinned_silos", [])
                if isinstance(pinned, list) and idx in pinned:
                    pinned.remove(idx)
                ticked = self.data.get("silo_ticked", [])
                if isinstance(ticked, list) and idx in ticked:
                    ticked.remove(idx)
                cmap = self.data.get("silo_children", {})
                if isinstance(cmap, dict):
                    cmap.pop(idx, None)  # deleting a parent promotes its children
                    for kids in cmap.values():
                        if idx in kids:
                            kids.remove(idx)
                collapsed = self.data.get("silo_collapsed", [])
                if isinstance(collapsed, list) and idx in collapsed:
                    collapsed.remove(idx)
                if hasattr(self, "_remap_silo_indices"):
                    self._remap_silo_indices(lambda i: i - 1 if i > idx else i)

            if idx < self.active_temp_slot:
                self.active_temp_slot -= 1
            elif self.active_temp_slot >= len(presets):
                self.active_temp_slot = len(presets) - 1

            self.silo_page = self.active_temp_slot // max(1, self._visible_silos)
            self._switch_to_slot(self.active_temp_slot, initial=True)
            self.mark_dirty()
            self.cancel_editing()
            self.refresh_temp_presets()

    def select_empty_silo(self):
        """Insert a new empty silo at the top."""
        self.sound_manager.play("new")
        if getattr(self, "editing_snippet", None):
            self.save_snippet(silent=True)
        else:
            target = (
                self.data["archive_temp_presets"]
                if getattr(self, "active_is_archive", False)
                else self.data["temp_presets"]
            )
            if 0 <= self.active_temp_slot < len(target):
                target[self.active_temp_slot] = self.text_area.toPlainText()

        presets = (
            self.data["archive_temp_presets"]
            if getattr(self, "active_is_archive", False)
            else self.data["temp_presets"]
        )
        docs = self.archive_docs if getattr(self, "active_is_archive", False) else self.silo_docs

        # Cap empty silos at 5: jump to the first existing empty one instead
        # of letting the user spam unlimited blanks.
        if sum(1 for p in presets if not p.strip()) >= 5:
            for i, p in enumerate(presets):
                if not p.strip():
                    self.silo_page = i // max(1, self._visible_silos)
                    self._switch_to_slot(
                        i, initial=True, is_archive=getattr(self, "active_is_archive", False)
                    )
                    self.refresh_temp_presets()
                    return
            return

        self.add_data_undo_state("New silo (top)")
        if len(presets) >= 100:
            presets.pop()
            if len(docs) >= 100:
                docs.pop()

        presets.insert(0, "")

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        docs.insert(0, doc)

        # Shift silo_last_edited and pinned indices down (insert-at-top).
        # In-place: both containers are aliases into per-category stores.
        if not getattr(self, "active_is_archive", False) and hasattr(self, "silo_last_edited"):
            new_edited = {k + 1: v for k, v in self.silo_last_edited.items() if k + 1 < 100}
            self.silo_last_edited.clear()
            self.silo_last_edited.update(new_edited)
            pinned = self.data.get("pinned_silos", [])
            if isinstance(pinned, list):
                pinned[:] = [p + 1 for p in pinned if p + 1 < 100]

        self.silo_page = 0
        self.active_temp_slot = 0
        self._switch_to_slot(0, initial=True)
        self.mark_dirty()
        self.refresh_temp_presets()

    def append_empty_silo(self, pos=None):
        """Insert a new empty silo at the end or first empty slot."""
        self.sound_manager.play("new")
        if getattr(self, "editing_snippet", None):
            self.save_snippet(silent=True)
        else:
            target = (
                self.data["archive_temp_presets"]
                if getattr(self, "active_is_archive", False)
                else self.data["temp_presets"]
            )
            if 0 <= self.active_temp_slot < len(target):
                target[self.active_temp_slot] = self.text_area.toPlainText()
        self.add_data_undo_state("New silo (end)")

        presets = (
            self.data["archive_temp_presets"]
            if getattr(self, "active_is_archive", False)
            else self.data["temp_presets"]
        )
        docs = self.archive_docs if getattr(self, "active_is_archive", False) else self.silo_docs

        for i, content_val in enumerate(presets):
            if not content_val.strip():
                self.silo_page = i // max(1, self._visible_silos)
                self._switch_to_slot(i, initial=True)
                return
        if len(presets) < 100:
            i = len(presets)
            presets.append("")

            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            docs.append(doc)

            self.silo_page = i // max(1, self._visible_silos)
            self._switch_to_slot(i, initial=True)
            self.mark_dirty()
            self.refresh_temp_presets()

    def archive_active_item(self):
        """Archive the current snippet or silo."""
        if getattr(self, "editing_snippet", None):
            self.archive_active_snippet()
        else:
            self.archive_active_silo()

    def archive_active_snippet(self):
        """Move the current snippet to archive."""
        self.add_data_undo_state("Archive snippet")
        cat = self.get_current_category()
        if not cat:
            return

        text = self.text_area.toPlainText().strip()
        if not text:
            return

        if getattr(self, "active_is_archive", False):
            return

        editing_idx = self.editing_snippet[1] if self.editing_snippet else -1

        if self.editing_snippet:
            self.save_snippet(silent=True)

        slots = self.data["categories"].get(cat, [])
        found_idx = (
            editing_idx
            if (
                0 <= editing_idx < len(slots)
                and slots[editing_idx]
                and slots[editing_idx]["text"] == text
            )
            else -1
        )
        if found_idx == -1:
            for i, s in enumerate(slots):
                if s and s["text"] == text:
                    found_idx = i
                    break

        if found_idx == -1:
            return

        item = slots[found_idx]
        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []

        self.data["archive_temp_presets"].insert(0, item["text"])

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(item["text"])
        self.archive_docs.insert(0, doc)

        slots[found_idx] = None

        self._trim_archive()
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_archive_panel()
        self.cancel_editing()

    def archive_active_silo(self):
        """Move the current silo to archive."""
        idx = self.active_temp_slot

        if getattr(self, "active_is_archive", False):
            return
        if not (0 <= idx < len(self.data.get("temp_presets", []))):
            return

        text = self.text_area.toPlainText().strip()
        if not text:
            return

        self.data["temp_presets"][idx] = text
        self.add_data_undo_state("Archive silo")

        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []

        self.data["archive_temp_presets"].insert(0, text)

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(text)
        self.archive_docs.insert(0, doc)

        self.data["temp_presets"][idx] = ""
        self._set_plain_text_clean(self.silo_docs[idx], "")
        self.clear_text(internal=True)

        self._trim_archive()
        self.mark_dirty()
        self.refresh_archive_panel()
        self.refresh_temp_presets()

    def convert_to_snippet(self):
        """Convert the active silo to a snippet in the current category."""
        text = self.text_area.toPlainText().strip()
        if not text:
            return

        cat = self.get_current_category()
        if not cat:
            return

        slots = self.data["categories"][cat]
        if None not in slots:
            return

        self.add_data_undo_state("Convert silo to snippet")
        empty_idx = slots.index(None)

        name = text.replace("\n", " ")[:22]
        if len(text) > 22:
            name += "..."

        slots[empty_idx] = {"name": name, "text": text, "last_edited": int(time.time())}

        idx = self.active_temp_slot
        if 0 <= idx < len(self.data["temp_presets"]):
            self.data["temp_presets"][idx] = ""
        self.clear_text(internal=True)

        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
