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

    def _consumed_map(self):
        return self.main_win.data.setdefault("trash_consumed", {})

    def _load_trash(self):
        """List restorable .md sources.

        W2-005: a source whose consumed identity was already durably
        committed is NEVER offered again — the restore it belongs to lives
        in SQLite, and re-listing the .md would let a second click insert a
        duplicate without its folder. The stale file (left behind by a
        source-delete permission error or a crash before removal) is removed
        opportunistically; if deletion keeps failing it simply stays
        invisible."""
        self.list_widget.clear()
        consumed = self.main_win.data.get("trash_consumed") or {}
        if not os.path.isdir(self.trash_dir):
            return

        for f in sorted(os.listdir(self.trash_dir), reverse=True):
            if not f.endswith(".md"):
                continue
            if consumed.get(f):
                # already durably restored: retry the physical cleanup once
                try:
                    os.remove(os.path.join(self.trash_dir, f))
                except OSError:
                    pass
                continue
            item = QListWidgetItem(f)
            item.setData(Qt.ItemDataRole.UserRole,
                         os.path.join(self.trash_dir, f))
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

            mw = self.main_win
            data = mw.data
            # CORE-003/W2-001: capture the COMPLETE pre-restore state through
            # the canonical snapshot primitive — every slot-indexed store
            # (watcher queues, colours, pins, ticks, children, gaps, project
            # paths, links, Sync-Project mappings, view state) plus docs and
            # navigation — so a failed durable save can roll back to an
            # identity-equivalent runtime instead of a hand-picked subset.
            pre_snapshot = mw._snapshot_current() \
                if hasattr(mw, "_snapshot_current") else None
            pre_undo = list(getattr(mw, "data_undo_stack", []) or [])
            pre_redo = list(getattr(mw, "data_redo_stack", []) or [])
            from fastprompter.ui.snippet_ops_mixin import resolve_trash_link
            pre_link_val = (data.get("trash_text_folder") or {}).get(md_basename)
            pre_log = list(data.get("folder_trash_log") or [])
            _sel, _rem = resolve_trash_link(pre_link_val, pre_log)
            pre_trashed = _sel[1] if _sel else None
            pre_consumed = dict(data.get("trash_consumed") or {})

            # W2-005: the consumed identity is recorded BEFORE the durable
            # save and committed IN THE SAME SQLite transaction as the
            # inserted silo — there is never a restart interval where both
            # "restored durably" and "actionable .md" are true.
            self._consumed_map()[md_basename] = True

            # Restore through the canonical silo insertion primitive so the
            # new slot shifts every slot-indexed store, docs stay aligned
            # with presets, and undo sees one action (T-755). The old fallback
            # was a bare temp_presets.insert(0, ...) that bypassed all of it.
            if hasattr(mw, "insert_silo_at"):
                inserted = mw.insert_silo_at(text)
            else:
                data["temp_presets"].insert(0, text)
                mw.mark_dirty()
                if hasattr(mw, "refresh_temp_presets"):
                    mw.refresh_temp_presets()
                inserted = 0

            # The trash source is deleted ONLY when the insertion actually
            # succeeded. insert_silo_at returns the slot on success and None
            # when every slot is occupied, so a full workspace must keep the
            # only trash copy instead of destroying it while restoring nothing.
            if inserted is None:
                self._consumed_map().pop(md_basename, None)
                QMessageBox.warning(
                    self, self.tr("Restore failed"),
                    self.tr("Could not restore the silo: the workspace is full."))
                return

            # CORE-006: restore the File Container folder using the EXACT
            # delete-time association, not a slug guess. Returns the allocated
            # folder name, or None when there is no recoverable folder.
            folder_restored = False
            allocated = None
            if hasattr(mw, "_restore_trash_file_container"):
                try:
                    allocated = mw._restore_trash_file_container(
                        md_basename, text, inserted)
                    folder_restored = allocated is not None
                except Exception:
                    folder_restored = False

            # CORE-004: attempt the durable commit BEFORE deleting the recovery
            # source. On failure, roll EVERY mutation back — logical state via
            # the canonical snapshot apply, undo/redo stacks by truncation,
            # physical container by moving it back to its exact trash path —
            # and keep the .md so a retry reproduces the same transaction.
            saved = True
            if hasattr(mw, "save_data_to_db"):
                try:
                    saved = bool(mw.save_data_to_db(force=True))
                except Exception:
                    saved = False
            else:
                mw.mark_dirty()

            if not saved:
                # ---- compensating rollback ---------------------------------
                if allocated and pre_trashed:
                    cat = mw.get_current_category() if hasattr(
                        mw, "get_current_category") else ""
                    comp = (mw._category_files_dir(cat)
                            if hasattr(mw, "_category_files_dir") else None)
                    if comp:
                        dest = os.path.join(mw._files_root(), comp, allocated)
                        if os.path.isdir(dest):
                            try:
                                os.rename(dest, pre_trashed)
                            except OSError:
                                pass
                # complete logical state back to the pre-insertion boundary
                if pre_snapshot is not None and hasattr(mw, "_apply_data_state"):
                    try:
                        mw._apply_data_state(pre_snapshot)
                    except Exception:
                        pass
                    # the insertion pushed ONE undo entry ("Restore silo");
                    # restore both stacks to their exact pre-operation shape
                    # so Ctrl+Z cannot replay a transaction that never committed.
                    stack = getattr(mw, "data_undo_stack", None)
                    if isinstance(stack, list):
                        del stack[len(pre_undo):]
                    rstack = getattr(mw, "data_redo_stack", None)
                    if isinstance(rstack, list):
                        rstack[:] = pre_redo
                    if hasattr(mw, "_save_undo_state"):
                        mw._save_undo_state()
                # restore the recovery records exactly as they were
                data["folder_trash_log"] = pre_log
                ttf = data.setdefault("trash_text_folder", {})
                if pre_link_val is not None:
                    ttf[md_basename] = pre_link_val
                else:
                    ttf.pop(md_basename, None)
                data["trash_consumed"] = pre_consumed
                mw.mark_dirty()
                QMessageBox.warning(
                    self, self.tr("Restore incomplete"),
                    self.tr("The restore could not be saved persistently. "
                            "Everything was rolled back and the trash copy "
                            "was kept so you can try again."))
                self._load_trash()
                return

            # FINAL commit step: delete the recovery source exactly once.
            # W2-005: failure here is harmless by construction — the consumed
            # identity committed above already hides this .md from every later
            # listing, so the restore can never replay.
            try:
                os.remove(filepath)
            except OSError:
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
            link = self.main_win.data.get("trash_text_folder") or {}
            # W2-005: consumed identities die with their sources.
            consumed = self.main_win.data.get("trash_consumed") or {}
            for f in os.listdir(self.trash_dir):
                path = os.path.join(self.trash_dir, f)
                if os.path.isfile(path) and f.endswith(".md"):
                    os.remove(path)
                    # CORE-003: the text->folder association is stale once the
                    # text is gone — drop it so it can't mislink a later restore.
                    link.pop(f, None)
                    if consumed.pop(f, None) is not None:
                        self.main_win.mark_dirty()
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
