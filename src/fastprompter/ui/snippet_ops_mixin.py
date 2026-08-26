"""Snippet operations mixin for FastPrompter — CRUD, archive, clipboard, and import/export.

Extracted from main.py Phase 2c of the modularization plan.
Provides SnippetOpsMixin class for use as a mixin with FastPrompter QMainWindow.
"""

import os
import time

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr

_is_deleted = sip.isdeleted

# folder_trash_log retention (P2-23). The log is the physical recovery
# mapping for undoable retirements. _restore_trashed_folders only restores
# an entry whose original folder is referenced by the CURRENT per-slot maps
# (undo restores the maps from the snapshot BEFORE folders), so an entry is
# restorable exactly while its folder name appears in a live undo snapshot
# or the current maps — referenced entries are therefore ALWAYS kept. The
# numeric floor only sweeps UNREFERENCED orphans (failed-restore leftovers
# would otherwise re-accumulate forever). It is DERIVED, not magic: undo
# capacity (50 actions, main.py) times the per-category slot model
# (10 normal + 10 archive), never an arbitrary 500 that could prune the
# recovery mapping of an action the user can still undo.
_UNDO_MAX_ACTIONS = 50
_MAX_FOLDERS_PER_CATEGORY = 20   # 10 normal + 10 archive slots
_FOLDER_TRASH_LOG_FLOOR = _UNDO_MAX_ACTIONS * _MAX_FOLDERS_PER_CATEGORY
# W2-006: journal file name for crash-consistent folder retirement.
_RETIREMENT_JOURNAL = ".retirement_journal.json"


def _journal_path(root):
    return os.path.join(root, "_trash", _RETIREMENT_JOURNAL)


def _journal_load_records(root):
    """Load every outstanding retirement record from the journal.

    Returns a list of dicts with at least ``original``/``trashed`` keys.
    A legacy v1 journal (a single overwrite slot holding one dict, CORE-002)
    is migrated transparently so old crash leftovers stay recoverable.
    Unreadable/corrupt payloads yield an empty list — callers then behave
    exactly as if no journal existed (the physical layout is untouched).
    """
    import json
    jp = _journal_path(root)
    if not os.path.isfile(jp):
        return []
    try:
        with open(jp, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    records = []
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        for r in payload["records"]:
            if isinstance(r, dict) and r.get("original") and r.get("trashed"):
                records.append(r)
    elif isinstance(payload, dict) and payload.get("original") \
            and payload.get("trashed"):
        records.append({
            "id": str(payload.get("ts") or "legacy"),
            "original": payload["original"],
            "trashed": payload["trashed"],
            "ts": str(payload.get("ts") or ""),
            "merged": True,
        })
    return records


def _journal_store_records(root, records):
    """Durably rewrite the journal with exactly ``records`` (atomic).

    A multi-record model (CORE-002/W2-001): one retirement must never
    overwrite another uncommitted record, so every mutation rewrites the
    FULL outstanding set through temp + os.replace.
    """
    import json
    try:
        jp = _journal_path(root)
        os.makedirs(os.path.dirname(jp), exist_ok=True)
        tmp = jp + f".tmp{int(time.time() * 1000)}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "records": list(records)}, f)
        os.replace(tmp, jp)
        return True
    except OSError as e:
        from fastprompter.core.logging import logger
        logger.warning("retirement journal write failed: %s", e)
        return False


def _write_retirement_journal(root, entry):
    """Append ONE planned retirement record before the physical move.

    Kept as the single-record entry point (existing tests monkeypatch this
    symbol): under the v2 multi-record model it appends to the outstanding
    set instead of overwriting it, so repeated retirements inside one
    uncommitted transaction each keep their own durable recovery record.

    Returns True on success, False on OSError (CORE-002: the caller MUST
    treat a False result as a fatal precondition and refuse the physical
    move — the journal is the only thing that can reconstruct the
    original->trash ownership after a crash)."""
    records = _journal_load_records(root)
    record = {
        "id": f"{entry.get('ts', '')}-{len(records)}-{int(time.time() * 1000)}",
        "original": entry.get("original"),
        "trashed": entry.get("trashed"),
        "ts": entry.get("ts", ""),
    }
    if not record["original"] or not record["trashed"]:
        return False
    records.append(record)
    return _journal_store_records(root, records)


def _clear_retirement_journal(root):
    """Remove the journal once every record it held is durably acknowledged."""
    try:
        jp = _journal_path(root)
        if os.path.isfile(jp):
            os.remove(jp)
    except OSError as e:
        from fastprompter.core.logging import logger
        logger.warning("retirement journal clear failed: %s", e)


def _norm_pair(original, trashed):
    return (os.path.normcase(os.path.abspath(str(original))),
            os.path.normcase(os.path.abspath(str(trashed))))


def _reconcile_retirement_journal(root, data, owner_is_live=None):
    """Startup reconciliation (CORE-002 / W2-001), transaction-aware.

    The journal records that a PHYSICAL retirement happened, but the logical
    deletion may never have been durably committed (the mutator only calls
    ``mark_dirty``; SQLite lags). For every outstanding record:

    * the durable state still maps the original path to a LIVE silo/category
      (``owner_is_live`` truthy) — the logical deletion was NOT committed, so
      the physical side effect is rolled back and the record is retired;
    * the logical deletion IS durably committed (or the owner cannot be
      resolved) — the ``(original, trashed)`` recovery pair merges into the
      in-memory log, and the record STAYS in the journal flagged ``merged``
      until ``_ack_retirement_journal`` observes the pair in a SUCCESSFUL
      SQLite save (never acknowledge durability that does not exist yet).

    Idempotent by construction: repeated runs dedup on the normalised pair
    and never resurrect a rolled-back retirement. Paths outside the current
    files root are left untouched (unknowable ownership context) and retried
    on a later startup instead of being guessed about.
    """
    records = _journal_load_records(root)
    if not records:
        return
    root_abs = os.path.abspath(root)
    log = data.setdefault("folder_trash_log", [])
    existing = {_norm_pair(e[0], e[1]) for e in log
                if isinstance(e, (tuple, list)) and len(e) >= 2}
    remaining = []
    for rec in records:
        orig, trashed = rec.get("original"), rec.get("trashed")
        if not (orig and trashed):
            continue
        try:
            inside = os.path.abspath(str(orig)).startswith(
                root_abs + os.sep)
        except Exception:
            inside = False
        if not inside:
            # different/unreachable storage context: do not guess, retry later
            remaining.append(rec)
            continue
        live = False
        if owner_is_live is not None:
            try:
                live = bool(owner_is_live(orig))
            except Exception:
                live = False
        if live:
            # COMMIT/ROLLBACK arbitration: the DB still owns this folder, so
            # the physical rename must be undone before the workspace shows.
            if not os.path.exists(orig) and os.path.isdir(trashed):
                try:
                    os.makedirs(os.path.dirname(orig), exist_ok=True)
                    os.rename(trashed, orig)
                    # fully reversed: retire journal record and remove stale
                    # recovery mapping from the in-memory log
                    _pair = _norm_pair(orig, trashed)
                    log[:] = [e for e in log
                              if isinstance(e, (tuple, list)) and len(e) >= 2
                              and _norm_pair(e[0], e[1]) != _pair]
                    existing.discard(_pair)
                    continue          # fully reversed: retire the record
                except OSError as e:
                    from fastprompter.core.logging import logger
                    logger.warning(
                        "retirement rollback %s -> %s failed: %s",
                        trashed, orig, e)
            elif os.path.exists(orig):
                # already home (prior partial run): ensure stale mapping is
                # cleared from the log and retire the journal record
                _pair = _norm_pair(orig, trashed)
                log[:] = [e for e in log
                          if isinstance(e, (tuple, list)) and len(e) >= 2
                          and _norm_pair(e[0], e[1]) != _pair]
                existing.discard(_pair)
                continue              # already home (prior partial run)
            # could not reverse: keep BOTH the journal record and the
            # recovery mapping so nothing is lost
            pair = _norm_pair(orig, trashed)
            if pair not in existing:
                log.append((os.path.abspath(orig), os.path.abspath(trashed)))
                existing.add(pair)
            remaining.append(rec)
        else:
            # logical deletion committed (or unknowable): adopt the record
            pair = _norm_pair(orig, trashed)
            if pair not in existing:
                log.append((os.path.abspath(orig), os.path.abspath(trashed)))
                existing.add(pair)
            rec["merged"] = True
            remaining.append(rec)
    if remaining:
        _journal_store_records(root, remaining)
    else:
        _clear_retirement_journal(root)


def _ack_retirement_journal(root, data):
    """Retire journal records whose recovery pairs are now DURABLE.

    Called after a successful SQLite commit (main.save_data_to_db): a
    ``merged`` record may be dropped ONLY once the same pair exists in the
    state that just committed — closing W2-001's second crash window where
    the old reconciliation deleted the journal before the log was persisted.
    Records whose trashed folder is gone AND whose original is back were
    rolled back and are equally done."""
    records = _journal_load_records(root)
    if not records:
        return
    log_pairs = {_norm_pair(e[0], e[1]) for e in
                 (data.get("folder_trash_log") or [])
                 if isinstance(e, (tuple, list)) and len(e) >= 2}
    kept = []
    for rec in records:
        orig, trashed = rec.get("original"), rec.get("trashed")
        if not (orig and trashed):
            continue
        pair = _norm_pair(orig, trashed)
        if pair in log_pairs:
            continue                  # durably represented: acknowledged
        if os.path.exists(orig) and not os.path.exists(trashed):
            continue                  # rolled back physically: done
        kept.append(rec)
    if kept:
        _journal_store_records(root, kept)
    else:
        _clear_retirement_journal(root)


def resolve_trash_link(val, log):
    """CORE-001: the ONE canonical ``trash_text_folder`` resolver.

    ``val`` is what ``data["trash_text_folder"][md_basename]`` holds:

    * NEW format — the exact absolute original folder path recorded at
      delete time. Matched against ``folder_trash_log`` originals by exact
      (case-normalised, absolute) path equality;
    * LEGACY format — a bare folder basename from older builds. Matched by
      basename equality ONLY when no exact interpretation applies.

    Exactly ONE deterministic recoverable record is selected (first match
    whose trashed directory still exists); EVERY other entry survives in
    ``remaining``, so duplicate basenames across categories can never steal
    each other's recovery records. ``log`` itself is not mutated.

    Returns ``(selected, remaining)``; ``selected`` is None when nothing
    recoverable matches.
    """
    entries = list(log or [])
    if not val:
        return None, entries
    val_s = str(val)
    want_exact = os.path.isabs(val_s)
    picked = -1
    if want_exact:
        target = os.path.normcase(os.path.abspath(val_s))
        for i, e in enumerate(entries):
            if not (isinstance(e, (tuple, list)) and len(e) >= 2):
                continue
            if not os.path.isdir(e[1]):
                continue
            if os.path.normcase(os.path.abspath(str(e[0]))) == target:
                picked = i
                break
    else:
        base = os.path.basename(val_s)
        for i, e in enumerate(entries):
            if not (isinstance(e, (tuple, list)) and len(e) >= 2):
                continue
            if not os.path.isdir(e[1]):
                continue
            if os.path.basename(str(e[0])) == base:
                picked = i
                break
    if picked < 0:
        return None, entries
    selected = entries[picked]
    return selected, [e for j, e in enumerate(entries) if j != picked]


def _purge_retirement_record(root, trashed_path):
    """Drop the journal record(s) for a retirement that was rolled back.

    W2-001: a rolled-back move must never be resurrected by a later startup
    reconciliation, so its durable claim is retired together with the
    in-memory log entry."""
    records = _journal_load_records(root)
    if not records:
        return
    norm = os.path.normcase(os.path.abspath(str(trashed_path)))
    kept = [r for r in records
            if os.path.normcase(os.path.abspath(str(r.get("trashed")))) != norm]
    if len(kept) != len(records):
        if kept:
            _journal_store_records(root, kept)
        else:
            _clear_retirement_journal(root)


def _trash_stamp():
    """Readable timestamp for a trash filename, ``dd.mm.yy-HHMMSS``.

    Module-level so tests can freeze it deterministically (the trash
    no-clobber regression pins two writes in the SAME second)."""
    import datetime
    return datetime.datetime.now().strftime("%d.%m.%y-%H%M%S")


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

    def _write_backup_file(self, folder, name, text):
        """Publish ``text`` as ``name`` inside ``folder`` (container-owned).

        The name must pass the shared component validator (single component,
        no separators / ``..`` / drive / UNC / device / trailing dot-space),
        the destination is unique no-clobber, and publication goes through the
        container's atomic ``_write_text_atomic`` — never a raw ``open()``.
        Returns (dest_path, "") or (None, error_reason).
        """
        from fastprompter.ui.file_container import (
            _unique_dest,
            _write_text_atomic,
            capture_resolved_root,
        )
        from fastprompter.utils.path_safety import validate_component
        clean, reason = validate_component(name)
        if clean is None:
            return None, reason
        try:
            os.makedirs(folder, exist_ok=True)
            root_identity = capture_resolved_root(folder)
            dest = _unique_dest(folder, clean)
            _write_text_atomic(dest, text, folder, root_identity)
            return dest, ""
        except OSError as e:
            return None, str(e)

    def backup_silo_to_files(self, idx, is_archive=False):
        """Save the current silo text as a file in its own file container.

        The folder is resolved ONLY through the canonical per-slot helper
        (``_silo_folder_dir``), never by string-building a path from the raw
        category/silo names — a hostile name could otherwise escape the
        container. The user filename goes through the shared validator and is
        published atomically without clobbering an existing file.
        """
        import datetime

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

        folder = self._silo_folder_dir(idx, is_archive=False)

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

                dest, err = self._write_backup_file(folder, name, silo_text)
                if dest is None:
                    QMessageBox.warning(self, tr("Error", getattr(self, "_current_lang", "EN")), tr("Failed to save backup:\n{}", getattr(self, "_current_lang", "EN")).format(err))
                    return

                if result[0] == "clear":
                    if is_archive == getattr(self, "active_is_archive", False) and idx == getattr(self, "active_temp_slot", -1):
                        self.clear_text(internal=False)
                    else:
                        # Canonical non-active silo clear: update data + doc,
                        # mark dirty, push undo, refresh — never bypass the
                        # shared path (CORE-001 / W2-008).
                        self.clear_silo(idx, is_archive=is_archive)
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
                self._restore_centered_blocks()
                self._restore_aligned_blocks()

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
        le = getattr(self, "_current_lang", "EN")
        try:
            title = tr("Delete Snippet", le) if cat != "Trash" else tr("Delete Permanently", le)
            msg = tr("Delete this snippet?", le) if cat != "Trash" else tr("Delete this snippet permanently?", le)
            reply = QMessageBox.question(
                self, title, msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_preset_by_index(cat, global_idx)

    def restore_snippet(self, global_idx):
        if "Trash" not in self.data.get("categories", {}):
            return
        item = self.data["categories"]["Trash"][global_idx]
        if not item:
            return

        self.add_data_undo_state("Restore snippet")

        target_cat = "Default"
        for c in self.data.get("cats_order", []):
            if c != "Trash":
                target_cat = c
                break

        if target_cat not in self.data["categories"]:
            self.data["categories"][target_cat] = []
            if target_cat not in self.data.get("cats_order", []):
                self.data.setdefault("cats_order", []).insert(0, target_cat)

        target_slots = self.data["categories"][target_cat]
        # W2-002: the snippet model is fixed at 100 slots. Restore into a
        # free (None) slot and refuse atomically when the destination is
        # full -- never grow the list (a 101st slot is silently dropped by
        # the loader on restart). The undo snapshot already pushed above is
        # withdrawn on refusal so Ctrl+Z cannot replay a non-event.
        if None not in target_slots:
            if getattr(self, "data_undo_stack", None):
                self.data_undo_stack.pop()
            self._save_undo_state()
            return
        free = target_slots.index(None)
        target_slots[free] = item
        self.data["categories"]["Trash"][global_idx] = None

        self.mark_dirty()
        self.refresh_snippets_panel()

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
        # resolved by the row's own name, not by assuming the combo row
        # index equals the cats_order index (see _cat_at)
        if hasattr(self, "_cat_at"):
            return self._cat_at(self.cat_combo.currentIndex())
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
        (silo text is undoable via Ctrl+Z; files must not be less safe).

        Returns an explicit status so callers can decide whether the
        per-slot ownership mapping may be dropped:

        "MOVED_TO_TRASH"   folder had assets and was moved to _trash
        "EMPTY_REMOVED"    folder existed but was empty; removed
        "CONFIRMED_ABSENT" no folder exists at the resolved path (root
                           was reachable, so absence is a real fact)
        "FAILED"           filesystem error; the folder is exactly where
                           it was — the caller must keep ownership
        "ROOT_UNAVAILABLE" a configured custom root is unreachable, so
                           "isdir -> False" proves NOTHING; assets may
                           still be on the share — keep ownership
        """
        import os
        import time

        if not hasattr(self, "_files_root"):
            return "FAILED"
        # A configured custom root that is temporarily unreachable must not be
        # read as "the folder is gone": on a dead share isdir() returns False
        # while the assets still exist on the NAS. Fail closed instead of
        # dropping the ownership mapping.
        custom = (self.data.get("files_root") or "").strip()
        if custom and not self._custom_files_root_usable(custom):
            from fastprompter.core.logging import logger as _lg
            _lg.warning("file retirement skipped: custom files root %r is "
                        "unreachable; ownership mapping preserved", custom)
            return "ROOT_UNAVAILABLE"
        # `text` may be an already-resolved folder path (silos, via the
        # per-slot map) or a silo/snippet title (fallback, title-slug). The
        # title fallback resolves through the category's PERSISTENT physical
        # component, not a lossy slug of the raw name.
        from fastprompter.ui.file_container import silo_slug
        if isinstance(text, str) and os.path.isabs(text):
            d = text
        else:
            comp = self._category_files_dir(cat)
            if comp is None:
                # P1-4: a category with no persisted component on an
                # unreachable root resolves to NOTHING — a title-slug guess
                # could point at another category's real folder.
                from fastprompter.core.logging import logger as _lg
                _lg.warning("file retirement skipped: no physical component "
                            "resolvable for %r (root unreachable); ownership "
                            "mapping preserved", cat)
                return "ROOT_UNAVAILABLE"
            d = os.path.join(self._files_root(), comp, silo_slug(text))
        try:
            if not os.path.isdir(d):
                return "CONFIRMED_ABSENT"
            if not os.listdir(d):
                os.rmdir(d)  # empty folder: no assets to keep
                return "EMPTY_REMOVED"
            trash = os.path.join(self._files_root(), "_trash")
            os.makedirs(trash, exist_ok=True)
            dest = os.path.join(trash, f"{os.path.basename(d)}-{int(time.time())}")
            n = 2
            while os.path.exists(dest):
                dest = os.path.join(trash, f"{os.path.basename(d)}-{int(time.time())}-{n}")
                n += 1
            # W2-006: journal the retirement BEFORE the physical move so a
            # crash between the rename and the in-memory log append can be
            # reconciled on the next startup (the log entry is the recovery
            # record that links the trashed path to the original owner).
            from fastprompter.ui.file_container import _move_into_container, capture_resolved_root
            root = self._files_root()
            _journal_entry = {
                "original": os.path.abspath(d),
                "trashed": os.path.abspath(dest),
                "ts": _trash_stamp(),
            }
            # CORE-002: the journal is a MANDATORY precondition. If it cannot
            # be written durably, refuse the physical move entirely — moving
            # the folder without a recovery record would orphan the assets on
            # a crash. The caller sees "FAILED" and keeps the silo intact.
            if not _write_retirement_journal(root, _journal_entry):
                return "FAILED"
            _move_into_container(d, dest, root, capture_resolved_root(root))
            # remember original->trash so undoing the delete/clear can bring
            # the files back to where they belong (files never vanish: they're
            # in _trash even if the restore ever misses)
            log = self.data.setdefault("folder_trash_log", [])
            log.append((os.path.abspath(d), os.path.abspath(dest)))
            self._prune_folder_trash_log(log)
            # CORE-002: DO NOT clear the journal here. The in-memory log is
            # not yet durably persisted to SQLite, so deleting the journal now
            # would reopen the crash window it was meant to close. The journal
            # survives until startup reconciliation commits the record (the
            # reconciliation is idempotent and de-duplicates), which is the
            # only correct moment to retire it.
            return "MOVED_TO_TRASH"
        except OSError as e:
            logger.warning(f"Could not retire file container {d}: {e}")
            return "FAILED"

    def _prune_folder_trash_log(self, log):
        """Retention contract (P2-23): a recovery entry survives exactly
        while some still-restorable action can use it.

        ``_restore_trashed_folders`` only restores an entry whose original
        folder is referenced by the CURRENT per-slot maps, and undo restores
        the maps from the snapshot before it restores folders — so an entry
        whose folder name appears in no live undo snapshot and no current
        map can never be restored and is dead weight. Referenced entries are
        ALWAYS kept (above the floor they are the reason the log exists);
        the derived floor only sweeps unreferenced orphans so the log cannot
        grow without bound. See the module constants for the derivation.
        """
        if len(log) <= _FOLDER_TRASH_LOG_FLOOR:
            return
        names = set()
        for key in ("silo_folders_all", "archive_silo_folders_all"):
            stores = self.data.get(key) or {}
            if not isinstance(stores, dict):
                continue
            for m in stores.values():
                if isinstance(m, dict):
                    for v in m.values():
                        if isinstance(v, str) and v:
                            names.add(v)
        for snap in (getattr(self, "data_undo_stack", None) or []):
            if not isinstance(snap, dict):
                continue
            for key in ("silo_folders_all", "archive_silo_folders_all"):
                stores = snap.get(key) or {}
                if not isinstance(stores, dict):
                    continue
                for m in stores.values():
                    if isinstance(m, dict):
                        for v in m.values():
                            if isinstance(v, str) and v:
                                names.add(v)
        kept = [(o, t) for (o, t) in log if os.path.basename(o) in names]
        if len(kept) != len(log):
            log[:] = kept
            self.mark_dirty()

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
            # W2-002: the snippet model is fixed at 100 slots and the Trash
            # category persists through that same model (the loader drops
            # slot 100+ on read). A full Trash refuses the snippet append --
            # the item is then PERMANENTLY deleted instead of being written
            # to a slot that would silently vanish on restart.
            if len(self.data["categories"]["Trash"]) < 100:
                self.data["categories"]["Trash"].append(target_item)
            # else: permanent snippet deletion mutates SNIPPET state only
            # (W2-003). Snippets carry no File Container attachment
            # ownership; retiring a folder here would alias an unrelated
            # silo's assets by index/title-slug coincidence.
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
                self._restore_centered_blocks()
                self._restore_aligned_blocks()
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

    def trash_silo(self, idx=None, is_archive=False, *args, **kwargs):
        """Move a silo to the trash (called from context menu).
        Just calls del_silo which now handles the trashing of text.
        Returns the explicit success/failure result from del_silo so batch
        callers can tell a real deletion from an aborted one (P1-6)."""
        return self.del_silo(idx, *args, is_archive=is_archive, **kwargs)

    def silo_text_at(self, idx, is_archive=False):
        """The stored text of silo ``idx``, or "" when the slot is empty."""
        key = "archive_temp_presets" if is_archive else "temp_presets"
        presets = self.data.get(key) or []
        if 0 <= idx < len(presets):
            return presets[idx] or ""
        return ""

    def clear_silo(self, idx=None, is_archive=False):
        """Empty a silo's text without deleting the slot or touching its files.

        Shift+middle-click on a silo clears it (a pure wipe) instead of
        trash_silo, which retires both text AND files into _trash. The slot,
        its colours, gaps, children and any on-disk files are left untouched;
        only the in-memory text becomes empty. Recoverable via undo."""
        if idx is None:
            idx = self.active_temp_slot
        key = "archive_temp_presets" if is_archive else "temp_presets"
        presets = self.data.get(key) or []
        if not (0 <= idx < len(presets)):
            return False
        self.add_data_undo_state("Clear silo")
        presets[idx] = ""
        docs = self.archive_docs if is_archive else self.silo_docs
        if idx < len(docs) and docs[idx] is not None:
            self._set_plain_text_clean(docs[idx], "")
        if (
            idx == getattr(self, "active_temp_slot", None)
            and is_archive == getattr(self, "active_is_archive", False)
        ):
            # the live editor shows this slot — reload it to the wiped doc
            self._switch_to_slot(idx, initial=True, is_archive=is_archive)
        else:
            if is_archive:
                self.refresh_archive_panel()
            else:
                self.refresh_temp_presets()
        
        # If this silo was ticked, un-tick it
        ticked = self.data.get("silo_ticked", [])
        if not is_archive and isinstance(ticked, list) and idx in ticked:
            ticked.remove(idx)
            self.refresh_temp_presets()
        
        self.mark_dirty()
        try:
            self.play_sound("clear")
        except Exception:
            pass
        return True

    def prompt_delete_silo(self, idx=None, is_archive=False):
        """Delete a silo from the UI, asking first when it holds text.

        The menu entry used to appear only on a silo that already had
        content, which left an empty one with no delete anywhere — so the
        gate moved here, where it belongs: an empty slot goes without a
        dialog (there is nothing to lose), a written one has to be
        confirmed. Both land in the same `del_silo`, so the undo snapshot
        and the slot-keyed remap stay one code path.
        """
        if idx is None:
            idx = self.active_temp_slot
        lang = getattr(self, "_current_lang", "EN")
        text = self.silo_text_at(idx, is_archive)
        if not is_archive and idx == getattr(self, "active_temp_slot", None):
            # the live editor is ahead of the stored copy for the open silo
            text = self.text_area.toPlainText() or text
        if text.strip():
            # ignore_focus_loss around the dialog: without it the modal takes
            # focus and close_on_focus_loss hides the whole window behind it.
            self.ignore_focus_loss = True
            try:
                reply = QMessageBox.question(
                    self,
                    tr("Delete Silo", lang),
                    tr("Are you sure you want to delete this silo and its content?", lang),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
            finally:
                self.ignore_focus_loss = False
            self.activateWindow()
            if reply != QMessageBox.StandardButton.Yes:
                return False
        # P1: propagate the real deletion outcome. trash_silo returns
        # del_silo's boolean — a physical-retirement failure must surface as
        # False, not as a "delete succeeded" while the silo intentionally
        # remains.
        return self.trash_silo(idx, is_archive)

    def _trash_silo_content(self, text, folder_name=None):
        """Write text to _trash as a durable recovery copy.

        P1-10 no-clobber: the destination name keeps the readable
        ``<slug>-<timestamp>`` form, but the FINAL path is allocated via the
        shared ``_unique_dest`` allocator and published through
        ``_write_text_atomic`` (temp + no-clobber rename). Two deletes in the
        same second with the same or colliding slug each get their OWN file;
        no deleted text is ever silently overwritten.

        ``folder_name`` (CORE-006) is the EXACT File Container folder name that
        was retired alongside this text. When supplied it is recorded against
        the trashed .md's basename so restore can recover the right assets
        without rediscovering ownership from a lossy ``silo_slug`` guess
        (which collapses duplicate titles and collision-suffixed folders).

        Returns (CORE-001 fail-closed contract):
          * ``True``  — blank text: a successful no-op, nothing written.
          * ``str``   — the written ``.md`` path: the durable copy exists.
          * ``False`` — the durable write FAILED. Callers must NOT proceed
            with the destructive delete/clear; the live silo must stay intact.
        """
        if not text.strip():
            return True

        from fastprompter.ui.file_container import (
            _unique_dest,
            _write_text_atomic,
            capture_resolved_root,
            silo_slug,
        )
        root = self._files_root()
        trash = os.path.join(root, "_trash")
        dest = None
        try:
            os.makedirs(trash, exist_ok=True)
            stamp = _trash_stamp()
            wanted = f"{silo_slug(text)}-{stamp}.md"
            dest = _unique_dest(trash, wanted)
            _write_text_atomic(dest, text, root, capture_resolved_root(root))
            # CORE-003: bind this exact .md to the EXACT retired folder
            # identity (its full original path), NOT merely the folder
            # basename. Category-local File Container names can repeat across
            # categories, so a basename key would alias distinct retirements
            # and let one silo's restore steal another's assets. The full
            # original path is unique per retirement and matches the
            # folder_trash_log entry one-to-one on restore.
            if folder_name:
                link = self.data.setdefault("trash_text_folder", {})
                link[os.path.basename(dest)] = os.path.abspath(folder_name)
        except OSError as e:
            logger.warning(f"Trash write failed: {e}")
            return False

        if self.data.get("trash_vision", "False") == "True":
            if "Trash" not in self.data.get("categories", {}):
                self.data.setdefault("categories", {})["Trash"] = []
            if "Trash" not in self.data.get("cats_order", []):
                self.data.setdefault("cats_order", []).append("Trash")

            title = text.strip().split('\n')[0][:40].strip()
            if not title:
                title = "Untitled"
            # Must match the snippet schema (name/text/last_edited) — this
            # list is rendered by the normal snippet panel, which crashes
            # with KeyError: 'name' on any other shape.
            # W2-002: the Trash category persists through the fixed 100-slot
            # snippet model; a slot 100+ row is silently dropped by the loader
            # on restart, so a full Trash refuses the append (the physical
            # text already landed in the _trash folder above).
            if len(self.data["categories"]["Trash"]) < 100:
                self.data["categories"]["Trash"].append({
                    "name": title,
                    "text": text,
                    "last_edited": int(time.time()),
                })
            if hasattr(self, "get_current_category") and self.get_current_category() == "Trash":
                self.refresh_snippets_panel()
        return dest

    def open_trash_folder(self):
        trash = os.path.join(self._files_root(), "_trash")
        os.makedirs(trash, exist_ok=True)
        try:
            from fastprompter.ui.trash_dialog import TrashDialog
            dialog = TrashDialog(self, trash)
            dialog.exec()
        except Exception as e:
            logger.error(f"Open trash dialog failed: {e}")

    def del_silo(self, idx=None, skip_undo=False, is_archive=None):
        """Delete a silo at the given index, or the active one.

        `is_archive` names the target space EXPLICITLY when the caller knows
        it (context menu, Delete key); None falls back to the active space so
        a bare `del_silo(idx)` keeps its old meaning. trash_silo forwards it —
        deleting an archive row while a normal silo is active must not delete
        the normal silo at the same index (T-754).
        """
        self.sound_manager.play("delete")
        is_arc = getattr(self, "active_is_archive", False) if is_archive is None else is_archive
        presets = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
        docs = self.archive_docs if is_arc else self.silo_docs
        if len(presets) > 1:
            if idx is None:
                idx = self.active_temp_slot

            if not (0 <= idx < len(presets)):
                return False

            # Snapshot BEFORE any mutation — undo must represent the exact
            # state the user saw before pressing delete. _live_text_into
            # folds the live editor text into the snapshot, so the order here
            # does not need a separate flush step.
            pushed_undo = None
            if not skip_undo:
                pushed_undo = self.add_data_undo_state("Delete silo")

            # Flush the live editor text only when deleting from the space the
            # editor is actually showing; a non-active-space delete must not
            # touch the active document.
            active_in_space = is_arc == getattr(self, "active_is_archive", False)
            if active_in_space and idx == self.active_temp_slot:
                presets[idx] = self.text_area.toPlainText()

            # CORE-001: stage the durable text recovery copy FIRST, then retire
            # the physical assets, then mutate. A recovery-write failure must
            # NOT proceed to any destructive step — the live silo stays intact.
            folder = self._silo_folder_dir(idx, is_archive=is_arc)
            # CORE-003: pass the EXACT original folder path so the trashed .md
            # can be bound to a unique retirement identity.
            folder_path = os.path.abspath(folder) if folder else None
            staged = self._trash_silo_content(
                presets[idx], folder_name=folder_path)
            if staged is False:
                # P0-6: the recovery copy could not be written durably, so the
                # destructive delete is REFUSED. The text, assets, maps and
                # undo snapshot are all left untouched.
                from fastprompter.core.logging import logger as _lg
                _lg.warning(
                    "silo delete ABORTED (slot %d, archive=%s): trash write "
                    "failed; live silo kept intact", idx, is_arc)
                if pushed_undo is not None and self.data_undo_stack and \
                        self.data_undo_stack[-1] is pushed_undo:
                    self.data_undo_stack.pop()
                self._save_undo_state()
                return False
            # NOW retire the physical assets. A silo whose assets cannot be
            # secured is not deleted at all; the staged recovery copy is
            # redundant and removed so trash does not lie about what was lost.
            if folder is None:
                retire = "ROOT_UNAVAILABLE"
            else:
                retire = self._delete_file_container(
                    self.get_current_category(), folder)
            if retire in ("FAILED", "ROOT_UNAVAILABLE"):
                # P0-6: ABORT. Remove the staged recovery copy (it records a
                # delete that did not happen) and keep the silo exactly as it
                # was. The just-pushed undo snapshot is popped.
                if isinstance(staged, str):
                    try:
                        os.remove(staged)
                        self.data.get("trash_text_folder", {}).pop(
                            os.path.basename(staged), None)
                    except OSError:
                        pass
                from fastprompter.core.logging import logger as _lg
                _lg.warning("silo delete ABORTED (slot %d, archive=%s): "
                            "folder retirement %s; nothing was removed",
                            idx, is_arc, retire)
                if pushed_undo is not None and self.data_undo_stack and \
                        self.data_undo_stack[-1] is pushed_undo:
                    self.data_undo_stack.pop()
                self._save_undo_state()
                return False
            # P1-9: the ownership mapping is dropped ONLY for a confirmed
            # retirement. By the time we are here the retirement is confirmed,
            # so the map entries are dropped unconditionally.
            if not is_arc:
                self.data.get("silo_folders", {}).pop(str(idx), None)
                self.data.get("silo_project_paths", {}).pop(str(idx), None)
            else:
                self.data.get("archive_silo_folders", {}).pop(str(idx), None)
                self.data.get("archive_project_paths", {}).pop(str(idx), None)

            # W2-002: a File Container drawer still bound to this retired
            # folder loses its mutation lease here — its next import must
            # never _ensure_folder the deleted path back into existence.
            if hasattr(self, "_detach_file_container_for"):
                try:
                    self._detach_file_container_for(folder)
                except Exception:
                    pass

            # Assets are secured; NOW the logical delete proceeds: the slot is
            # popped and the state remapped. The recovery copy is already in
            # _trash (CORE-006 link recorded inside _trash_silo_content).
            presets.pop(idx)
            if idx < len(docs):
                docs.pop(idx)

            if not is_arc:
                self.silo_last_edited.pop(idx, None)

            # One canonical remap for BOTH spaces (T-754). The archive used to
            # pop text/doc and never remap, so its folders, project paths and
            # queues stayed on the old slot and the next archived silo
            # inherited them. drop_silo_state skips the normal-only lists
            # (pins/ticks/children/gaps) for the archive half.
            self.drop_silo_state(idx, is_archive=is_arc)

            if active_in_space:
                if idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif self.active_temp_slot >= len(presets):
                    self.active_temp_slot = len(presets) - 1
                self.silo_page = self.active_temp_slot // max(1, self._visible_silos)
                self._switch_to_slot(self.active_temp_slot, initial=True, is_archive=is_arc)

            self.mark_dirty()
            self.cancel_editing()
            self.refresh_temp_presets()
            if is_arc:
                self.refresh_archive_panel()
            return True
        # guard not met (only one silo left, or nothing to delete): no-op
        return False

    def select_empty_silo(self, insertion="top"):
        """Insert a new empty silo.

        ``insertion`` is the EXPLICIT intent and must be passed by every
        keyboard route (the canonical NEW = "top"). When omitted/None the
        position is derived from the pointer's own event modifiers (the mouse
        path): plain -> top, Shift -> above the selected silo, Ctrl -> below.
        CORE-013: inferring intent from ambient ``QApplication.keyboardModifiers()``
        is wrong for ``Ctrl+N`` — the modifier that triggers the shortcut is
        mistaken for a gesture modifier, so a canonical NEW landed BELOW instead
        of at the top. Keyboard callers therefore pass intent explicitly.
        """
        is_arc = bool(getattr(self, "active_is_archive", False))
        self.sound_manager.play("new")
        if getattr(self, "editing_snippet", None):
            self.save_snippet(silent=True)
        else:
            target = (
                self.data["archive_temp_presets"]
                if is_arc
                else self.data["temp_presets"]
            )
            if 0 <= self.active_temp_slot < len(target):
                target[self.active_temp_slot] = self.text_area.toPlainText()

        presets = (
            self.data["archive_temp_presets"]
            if is_arc
            else self.data["temp_presets"]
        )
        docs = self.archive_docs if is_arc else self.silo_docs

        # Where to drop the new empty silo. Keyboard routes pass ``insertion``
        # explicitly (canonical = "top"). Mouse paths that omit it derive the
        # position from the live event modifiers.
        if insertion is None:
            mods = QApplication.keyboardModifiers()
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            if shift:
                insertion = "above"
            elif ctrl:
                insertion = "below"
            else:
                insertion = "top"
        else:
            # A keyboard route names the insertion point explicitly; the cap
            # check below must still know whether this is an explicit
            # above/below request (which bypasses the empty-silo cap).
            shift = insertion == "above"
            ctrl = insertion == "below"
        if insertion == "above":
            pos = max(0, min(self.active_temp_slot, len(presets)))
        elif insertion == "below":
            pos = max(0, min(self.active_temp_slot + 1, len(presets)))
        else:
            pos = 0

        # The silo we are inserting relative to, before any mutation. Used to
        # detect a gap hugging it on the insert side (see gap relocation below),
        # and to preserve child hierarchy if a child silo was selected.
        orig_sel = self.active_temp_slot
        orig_parent = self.silo_parent_of(orig_sel) if hasattr(self, "silo_parent_of") else None

        # Cap empty silos at 5: jump to the first existing empty one instead
        # of letting the user spam unlimited blanks. This is navigation, not a
        # data action, so it must not push an undo entry.
        if not (shift or ctrl) and sum(1 for p in presets if not p.strip()) >= 5:
            for i, p in enumerate(presets):
                if not p.strip():
                    self.silo_page = i // max(1, self._visible_silos)
                    self._switch_to_slot(i, initial=True, is_archive=is_arc)
                    self.refresh_temp_presets()
                    return
            return

        # canonical capacity boundary: never evict another silo implicitly. If
        # the space is full of content, refuse BEFORE any mutation (lose nothing).
        if self._silo_at_capacity(is_arc):
            return

        self.add_data_undo_state("New silo")
        presets.insert(pos, "")

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        docs.insert(pos, doc)

        # Insert at `pos` shifts every slot index >= pos down by one. This used
        # to be a hand-rolled copy of that shift, which drifted from the
        # canonical table twice: it wrote str() children keys (orphaning whole
        # subtrees, so a child silo vanished from the sidebar) and it never
        # shifted watcher_queues at all (every queue moved to the wrong silo).
        # One remap through _SILO_INDEX_STATE keeps all nine stores in step.
        # silo_gaps IS in that table since T-704 — a gap belongs to the silo
        # it was placed under, so it rides along with the shift. The archive
        # half is the same structural mutation and gets the same remap (T-754).
        if hasattr(self, "_remap_silo_indices"):
            self._remap_silo_indices(
                lambda i: i + 1 if i >= pos else i, is_archive=is_arc)

        # If inserting above/below a child silo, keep the new silo within the
        # hierarchy as a child of the same parent at the target position.
        if (shift or ctrl) and orig_parent is not None and not is_arc:
            remapped_parent = orig_parent + 1 if orig_parent >= pos else orig_parent
            cmap = self.data.setdefault("silo_children", {})
            if isinstance(cmap, dict):
                parent_key = next((k for k in cmap if str(k) == str(remapped_parent)), remapped_parent)
                kids = cmap.setdefault(parent_key, [])
                if isinstance(kids, list):
                    target_sibling = orig_sel + 1 if shift else orig_sel
                    if target_sibling in kids:
                        insert_idx = kids.index(target_sibling) + (0 if shift else 1)
                        kids.insert(insert_idx, pos)
                    elif pos not in kids:
                        kids.append(pos)

        # Gap that hugs the selected silo on the insert side must ride to the
        # FAR side of the new silo, else the new silo lands BEYOND the divider
        # ("jumped over" it). Shift (above) already keeps the new silo below an
        # above-gap; the only crossing case is Ctrl (below) with a gap directly
        # under the selected: relocate that gap to sit under the new silo, name
        # included, so the group stays intact and shifts cleanly.
        if ctrl and not is_arc:
            gaps = self.data.get("silo_gaps") or []
            if orig_sel in gaps:
                gaps[gaps.index(orig_sel)] = pos
                names = self.data.setdefault(
                    "silo_gap_names_all", {}).setdefault(
                    self.get_current_category(), {})
                old_key = str(orig_sel)
                if old_key in names:
                    names[str(pos)] = names.pop(old_key)
                self.data["silo_gap_names"] = names

        self.silo_page = pos // max(1, self._visible_silos)
        self.active_temp_slot = pos
        self._switch_to_slot(pos, initial=True, is_archive=is_arc)
        self.mark_dirty()
        self.refresh_temp_presets()

    def insert_silo_at(self, text, pos=0, is_archive=False):
        """Insert a silo holding ``text`` at ``pos`` — the canonical insertion
        primitive (T-755). Every slot-indexed store shifts down with the
        insert, docs stay aligned with presets, and undo sees ONE action.

        The trash restore used to be a bare ``temp_presets.insert(0, ...)``
        that left docs, colours, queues and the undo stack all behind.

        Honours the 100-slot capacity boundary: a full space is refused before
        any mutation (the 101st restore loses nothing); a blank slot, if one
        exists, is reused in place rather than growing the list past the
        persistence contract.

        Return contract: the inserted slot index on success, or ``None`` when
        every slot is occupied (refused). Callers MUST treat ``None`` as
        failure and preserve the source.
        """
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        has_pristine = getattr(self, "_slot_is_pristine", None)
        def _is_pristine(idx):
            return has_pristine(idx, is_archive) if has_pristine else True
        blank = next((i for i, p in enumerate(presets) if not (p or "").strip() and _is_pristine(i)), None)
        if len(presets) >= self.MAX_SILOS_PER_CATEGORY and blank is None:
            return  # full of content or no pristine blank: refuse, lose nothing
        if blank is not None and len(presets) >= self.MAX_SILOS_PER_CATEGORY:
            # reuse the blank rather than grow past the 100-slot contract
            self.add_data_undo_state("Restore silo")
            presets[blank] = text
            from PyQt6.QtGui import QTextDocument
            while len(docs) <= blank:
                d = QTextDocument()
                d.setDefaultFont(self.text_area.font())
                docs.append(d)
            if docs[blank] is None:
                d = QTextDocument()
                d.setDefaultFont(self.text_area.font())
                d.setPlainText(text)
                docs[blank] = d
            else:
                docs[blank].setPlainText(text)
            self.mark_dirty()
            self._switch_to_slot(blank, initial=True, is_archive=is_archive)
            self.refresh_temp_presets()
            if is_archive:
                self.refresh_archive_panel()
            return blank
        pos = max(0, min(pos, len(presets)))
        self.add_data_undo_state("Restore silo")
        presets.insert(pos, text)
        from PyQt6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(text)
        docs.insert(pos, doc)
        # docs is grown lazily elsewhere, so it can be shorter than presets;
        # keep the invariant "docs count == preset count" (T-755). A topped-up
        # tail doc is blank and self-heals from presets on load.
        while len(docs) < len(presets):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            docs.append(d)
        if hasattr(self, "open_silo_slot"):
            self.open_silo_slot(pos, is_archive=is_archive)
        self.mark_dirty()
        self._switch_to_slot(pos, initial=True, is_archive=is_archive)
        self.refresh_temp_presets()
        if is_archive:
            self.refresh_archive_panel()
        # Success contract: return the slot index. A full workspace refuses and
        # returns None (P0), so callers can tell a real restore from a no-op.
        return pos

    def append_empty_silo(self, pos=None):
        """Insert a new empty silo at the end or first empty slot."""
        is_arc = bool(getattr(self, "active_is_archive", False))
        self.sound_manager.play("new")
        if getattr(self, "editing_snippet", None):
            self.save_snippet(silent=True)
        else:
            target = (
                self.data["archive_temp_presets"]
                if is_arc
                else self.data["temp_presets"]
            )
            if 0 <= self.active_temp_slot < len(target):
                target[self.active_temp_slot] = self.text_area.toPlainText()

        presets = (
            self.data["archive_temp_presets"]
            if is_arc
            else self.data["temp_presets"]
        )
        docs = self.archive_docs if is_arc else self.silo_docs

        # Navigate to an existing empty slot first: that is navigation, not a
        # data action, so it must not push an undo entry and the editor must
        # stay in the SAME index space (archive stays archive).
        for i, content_val in enumerate(presets):
            if not content_val.strip():
                self.silo_page = i // max(1, self._visible_silos)
                self._switch_to_slot(i, initial=True, is_archive=is_arc)
                return

        # Only a real insertion is a data action, and only if capacity allows.
        # A full space is refused before any mutation (lose nothing).
        if self._silo_at_capacity(is_arc):
            return
        self.add_data_undo_state("New silo (end)")

        i = len(presets)
        presets.append("")

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        docs.append(doc)

        self.silo_page = i // max(1, self._visible_silos)
        self._switch_to_slot(i, initial=True, is_archive=is_arc)
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_arc:
            self.refresh_archive_panel()

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

        # canonical archive capacity: refuse to exceed the 100-slot contract
        if self._silo_at_capacity(True):
            return
        self.data["archive_temp_presets"].insert(0, item["text"])

        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(item["text"])
        self.archive_docs.insert(0, doc)

        # The archive insert-at-0 is a structural mutation: its slot-keyed
        # state (folders, project paths, queues) must shift with it (T-754).
        self.open_silo_slot(0, is_archive=True)

        slots[found_idx] = None

        self._trim_archive()
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_archive_panel()
        self.cancel_editing()

    def _archive_silo(self, idx):
        """Move silo ``idx`` from the normal space to the archive as ONE
        transaction, shared by the hover-button and the active-silo paths
        (T-754).

        The text, its document, its files folder, its project path and its
        queued references move together, and the archive's insert-at-0 index
        shift goes through the canonical remap. The normal slot stays behind,
        emptied — the silo was archived, not deleted.
        """
        if getattr(self, "active_is_archive", False):
            return
        presets = self.data.get("temp_presets", [])
        if not (0 <= idx < len(presets)):
            return

        if idx == self.active_temp_slot:
            text = self.text_area.toPlainText()
        else:
            text = presets[idx] or ""
        if not text.strip():
            return
        if idx == self.active_temp_slot:
            presets[idx] = text

        # canonical archive capacity: refuse to exceed the 100-slot contract
        if self._silo_at_capacity(True):
            return
        self.add_data_undo_state("Archive silo")

        if "archive_temp_presets" not in self.data:
            self.data["archive_temp_presets"] = []
        self.data["archive_temp_presets"].insert(0, text)

        from PyQt6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        doc.setPlainText(text)
        self.archive_docs.insert(0, doc)

        # the archive insert-at-0 is a structural mutation: shift its slot state
        self.open_silo_slot(0, is_archive=True)

        # identity-owned state travels with the text
        old_k = str(idx)
        folders = self.data.get("silo_folders", {})
        if isinstance(folders, dict) and old_k in folders:
            self.data.setdefault("archive_silo_folders", {})["0"] = folders.pop(old_k)
        paths = self.data.get("silo_project_paths", {})
        if isinstance(paths, dict) and old_k in paths:
            self.data.setdefault("archive_project_paths", {})["0"] = paths.pop(old_k)
        queues = self.data.get("watcher_queues", {})
        if isinstance(queues, dict) and old_k in queues:
            queues["a0"] = queues.pop(old_k)

        # the normal slot stays, emptied
        presets[idx] = ""
        if idx < len(self.silo_docs) and self.silo_docs[idx] is not None:
            self._set_plain_text_clean(self.silo_docs[idx], "")
        if idx == self.active_temp_slot:
            self.clear_text(internal=True)

        self._trim_archive()
        self.mark_dirty()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def archive_active_silo(self):
        """Move the current silo to archive."""
        self._archive_silo(self.active_temp_slot)

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
