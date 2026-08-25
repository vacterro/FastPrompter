import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class TrashDialog(QDialog):
    def __init__(self, main_win, trash_dir):
        super().__init__(main_win)
        self.main_win = main_win
        self.trash_dir = trash_dir
        self.setWindowTitle(self.tr("Manage Trash"))
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        lbl = QLabel(self.tr("Deleted silos and snippet texts are saved here."))
        layout.addWidget(lbl)
        
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        
        self.btn_restore = QPushButton(self.tr("Restore Selected"))
        self.btn_restore.clicked.connect(self._restore_selected)
        btn_layout.addWidget(self.btn_restore)
        
        self.btn_empty = QPushButton(self.tr("Empty Trash"))
        self.btn_empty.clicked.connect(self._empty_trash)
        btn_layout.addWidget(self.btn_empty)
        
        btn_close = QPushButton(self.tr("Close"))
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        self._load_trash()

    def tr(self, text):
        if hasattr(self.main_win, "tr"):
            return self.main_win.tr(text, getattr(self.main_win, "_current_lang", "EN"))
        return text

    def _load_trash(self):
        self.list_widget.clear()
        if not os.path.isdir(self.trash_dir):
            return
            
        for f in sorted(os.listdir(self.trash_dir), reverse=True):
            if f.endswith(".md"):
                item = QListWidgetItem(f)
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(self.trash_dir, f))
                self.list_widget.addItem(item)

    def _restore_selected(self):
        items = self.list_widget.selectedItems()
        if not items:
            return

        item = items[0]
        filepath = item.data(Qt.ItemDataRole.UserRole)
        md_basename = os.path.basename(filepath)

        try:
            with open(filepath, encoding="utf-8") as f:
                text = f.read()

            # Restore through the canonical silo insertion primitive so the
            # new slot shifts every slot-indexed store, docs stay aligned
            # with presets, and undo sees one action (T-755). The old fallback
            # was a bare temp_presets.insert(0, ...) that bypassed all of it.
            if hasattr(self.main_win, "insert_silo_at"):
                inserted = self.main_win.insert_silo_at(text)
            else:
                self.main_win.data["temp_presets"].insert(0, text)
                self.main_win.mark_dirty()
                if hasattr(self.main_win, "refresh_temp_presets"):
                    self.main_win.refresh_temp_presets()
                inserted = 0

            # The trash source is deleted ONLY when the insertion actually
            # succeeded. insert_silo_at returns the slot on success and None
            # when every slot is occupied, so a full workspace must keep the
            # only trash copy instead of destroying it while restoring nothing.
            if inserted is None:
                QMessageBox.warning(
                    self, self.tr("Restore failed"),
                    self.tr("Could not restore the silo: the workspace is full."))
                return

            # CORE-006: restore the File Container folder using the EXACT
            # delete-time association, not a slug guess. This survives
            # duplicate titles, collision-suffixed folders and cross-category
            # restores. Returns the allocated folder name, or None when there
            # is no recoverable folder (a real no-folder state, NOT success).
            folder_restored = False
            allocated = None
            if hasattr(self.main_win, "_restore_trash_file_container"):
                try:
                    allocated = self.main_win._restore_trash_file_container(
                        md_basename, text, inserted)
                    folder_restored = allocated is not None
                except Exception:
                    folder_restored = False

            # CORE-002: the trash source is destroyed as the FINAL commit step.
            # The restored silo text and its File Container state must be
            # durably persisted before the recovery source is removed; if the
            # save fails the .md is kept so nothing is lost (recoverable
            # failure). The delete happens exactly once here.
            saved = True
            if hasattr(self.main_win, "save_data_to_db"):
                try:
                    saved = bool(self.main_win.save_data_to_db(force=True))
                except Exception:
                    saved = False
            else:
                self.main_win.mark_dirty()

            if not saved:
                QMessageBox.warning(
                    self, self.tr("Restore incomplete"),
                    self.tr("The silo was restored but could not be saved "
                            "persistently. The trash copy was kept so you can "
                            "try again."))
                self._load_trash()
                return

            # FINAL commit step: delete the recovery source exactly once.
            try:
                os.remove(filepath)
            except OSError:
                # The restore already landed durably; a missing source file is
                # not a failure of the restore itself.
                pass

            if folder_restored:
                QMessageBox.information(
                    self, self.tr("Success"),
                    self.tr("Silo restored successfully."))
            else:
                QMessageBox.warning(
                    self, self.tr("Partial restore"),
                    self.tr("Text restored, but the File Container folder could "
                            "not be restored. You can find the files in the "
                            "trash folder."))
            self._load_trash()

        except Exception as e:
            QMessageBox.warning(self, self.tr("Error"), f"{self.tr('Failed to restore:')}\n{e}")

    def _empty_trash(self):
        reply = QMessageBox.question(
            self,
            self.tr("Empty Trash"),
            self.tr("Do you want to delete ALL trash?\n\nYes: Delete text and files.\nNo: Delete text only, keep files."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        
        if reply == QMessageBox.StandardButton.Cancel:
            return
            
        if not os.path.isdir(self.trash_dir):
            return
            
        delete_all = (reply == QMessageBox.StandardButton.Yes)
        
        try:
            changed_log = False
            for f in os.listdir(self.trash_dir):
                path = os.path.join(self.trash_dir, f)
                if os.path.isfile(path) and f.endswith(".md"):
                    os.remove(path)
                elif delete_all and os.path.isdir(path):
                    try:
                        shutil.rmtree(path)
                    except Exception as rm_err:
                        from fastprompter.core.logging import logger
                        logger.warning(
                            "Empty Trash: could not remove %s: %s", path, rm_err)
                        # keep the recovery record: the directory still exists
                        continue
                    # P1: the directory was genuinely destroyed, so drop only
                    # the recovery records whose trashed path equals it. Keep
                    # every other entry (other silos, or one we failed to
                    # delete) — an impossible original->trash mapping must not
                    # survive a real deletion.
                    log = self.main_win.data.get("folder_trash_log", [])
                    if log:
                        norm = os.path.normcase(os.path.abspath(path))
                        kept = [
                            e for e in log
                            if not (isinstance(e, (list, tuple)) and len(e) >= 2
                                    and os.path.normcase(os.path.abspath(e[1])) == norm)
                        ]
                        if len(kept) != len(log):
                            self.main_win.data["folder_trash_log"] = kept
                            changed_log = True
            if changed_log:
                self.main_win.mark_dirty()
            self._load_trash()
            QMessageBox.information(self, self.tr("Success"), self.tr("Trash emptied."))
        except Exception as e:
            QMessageBox.warning(self, self.tr("Error"), f"{self.tr('Failed to empty trash:')}\n{e}")
