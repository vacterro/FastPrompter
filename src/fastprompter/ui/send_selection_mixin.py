"""Send the selected text somewhere else.

Until now a piece of text could only leave a silo whole: archive the silo,
convert the silo, duplicate the silo. Keeping one paragraph out of a long
note meant cutting it, making a silo by hand, pasting, and going back.

Five destinations, all working on the selection only and all leaving the
source untouched — this copies, it never cuts, because a "save this
elsewhere" that also deletes is how notes get lost:

    new child silo      nested under the silo you are in
    new silo            a fresh top-level one at the end
    append to silo…     onto the end of one you pick
    new archive entry   straight into the archive
    append to archive…  onto the end of an archived entry you pick

Every one of them writes through the same _append_text/_new_silo_with, so
the undo step, the dirty flag and the panel refresh cannot be forgotten in
one path and remembered in another.
"""

from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QInputDialog

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr

# What a destination is called in the picker: its slot number and enough of
# its first real line to recognise it.
_LABEL_CHARS = 44


def silo_label(idx, text, lang="EN"):
    """"3 — Design notes" for a picker row."""
    first = ""
    for line in (text or "").split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            first = stripped
            break
    if not first:
        first = tr("(empty)", lang)
    if len(first) > _LABEL_CHARS:
        first = first[:_LABEL_CHARS - 1] + "…"
    return f"{idx + 1} — {first}"


class SendSelectionMixin:
    # ── the text being sent ──
    def selected_text(self):
        """The selection, trimmed. Empty string when there is none."""
        cursor = self.text_area.textCursor()
        if not cursor.hasSelection():
            return ""
        # Qt gives U+2029 for the paragraph breaks inside a selection; left
        # alone it lands in the target as one unbroken line
        return cursor.selectedText().replace(chr(0x2029), chr(10)).strip()

    # ── shared writers ──
    def _append_text(self, target_list, idx, text, docs, undo_label):
        """Append `text` to the entry at `idx`, keeping its document in step.

        The document cache is what the editor actually shows, so writing only
        the string list leaves the change invisible until the silo is
        reopened - and then the stale document overwrites it back.
        """
        if not (0 <= idx < len(target_list)):
            return False
        self.add_data_undo_state(undo_label)
        existing = target_list[idx] or ""
        joined = (existing.rstrip() + "\n\n" + text) if existing.strip() else text
        target_list[idx] = joined
        if docs is not None and idx < len(docs):
            self._set_plain_text_clean(docs[idx], joined)
        # the open editor is showing a document we may have just replaced
        if idx == getattr(self, "active_temp_slot", -1) and \
                bool(getattr(self, "active_is_archive", False)) == (docs is self.archive_docs):
            self._switch_to_slot(idx, initial=True)
        self.mark_dirty()
        return True

    # ── destinations ──
    def selection_to_new_child_silo(self):
        """A new silo holding the selection, nested under the current one."""
        text = self.selected_text()
        if not text:
            return False
        if getattr(self, "active_is_archive", False):
            # the archive has no hierarchy to nest into
            return self.selection_to_new_archive()
        idx = getattr(self, "active_temp_slot", 0)
        before = len(self.data.get("temp_presets", []))
        self.new_child_silo(idx)
        after = len(self.data.get("temp_presets", []))
        if after <= before:
            # refused - nesting limit, or a bad index. Do not silently drop
            # the text: put it in a top-level silo instead and say so.
            logger.info("child silo refused at %s; sending to a new silo", idx)
            return self.selection_to_new_silo()
        new_idx = getattr(self, "active_temp_slot", idx + 1)
        self._append_text(self.data["temp_presets"], new_idx, text,
                          self.silo_docs, "Selection to new child silo")
        self.refresh_temp_presets()
        return True

    def selection_to_new_silo(self):
        """A new top-level silo holding the selection."""
        text = self.selected_text()
        if not text:
            return False
        presets = self.data.get("temp_presets", [])
        new_idx = self._insert_silo_at(len(presets), text)
        self.mark_dirty()
        self.refresh_temp_presets()
        self._switch_to_slot(new_idx)
        return True

    def selection_to_silo(self, idx):
        """Append the selection to an existing silo."""
        text = self.selected_text()
        if not text:
            return False
        ok = self._append_text(self.data.get("temp_presets", []), idx, text,
                               self.silo_docs, "Selection appended to silo")
        if ok:
            self.refresh_temp_presets()
        return ok

    def selection_to_new_archive(self):
        """A new archive entry holding the selection."""
        text = self.selected_text()
        if not text:
            return False
        self.add_data_undo_state("Selection to new archive entry")
        archive = self.data.setdefault("archive_temp_presets", [])
        archive.insert(0, text)
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        self._set_plain_text_clean(doc, text)
        self.archive_docs.insert(0, doc)
        self._trim_archive()
        self.mark_dirty()
        self.refresh_archive_panel()
        return True

    def selection_to_archive(self, idx):
        """Append the selection to an existing archive entry."""
        text = self.selected_text()
        if not text:
            return False
        ok = self._append_text(self.data.get("archive_temp_presets", []), idx,
                               text, self.archive_docs,
                               "Selection appended to archive")
        if ok:
            self.refresh_archive_panel()
        return ok

    # ── pickers ──
    def _pick_target(self, title, entries):
        """Ask which entry to append to. Returns its index, or None."""
        lang = getattr(self, "_current_lang", "EN")
        if not entries:
            return None
        labels = [silo_label(i, t, lang) for i, t in entries]
        self.ignore_focus_loss = True
        try:
            choice, ok = QInputDialog.getItem(
                self, tr(title, lang), tr("Append to:", lang), labels, 0, False)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if not ok or not choice:
            return None
        return entries[labels.index(choice)][0]

    def ask_selection_to_silo(self):
        presets = self.data.get("temp_presets", [])
        # an empty slot is not a destination anybody means to pick
        entries = [(i, t) for i, t in enumerate(presets) if (t or "").strip()]
        idx = self._pick_target("Append selection to silo", entries)
        if idx is None:
            return False
        return self.selection_to_silo(idx)

    def ask_selection_to_archive(self):
        archive = self.data.get("archive_temp_presets", [])
        entries = [(i, t) for i, t in enumerate(archive) if (t or "").strip()]
        idx = self._pick_target("Append selection to archive", entries)
        if idx is None:
            return False
        return self.selection_to_archive(idx)

    # ── menu ──
    def build_send_selection_menu(self, menu):
        """Add the "Send selection" submenu. Disabled with no selection."""
        lang = getattr(self, "_current_lang", "EN")
        has = bool(self.selected_text())
        sub = menu.addMenu(tr("Send Selection To", lang))
        sub.setEnabled(has)
        sub.setToolTip(tr(
            "Copy the selected text into another silo or the archive.\n"
            "The selection stays where it is - nothing is cut.", lang))
        sub.addAction(tr("New Child Silo", lang), self.selection_to_new_child_silo)
        sub.addAction(tr("New Silo", lang), self.selection_to_new_silo)
        sub.addAction(tr("Existing Silo…", lang), self.ask_selection_to_silo)
        sub.addSeparator()
        sub.addAction(tr("New Archive Entry", lang), self.selection_to_new_archive)
        sub.addAction(tr("Existing Archive Entry…", lang), self.ask_selection_to_archive)
        return sub
