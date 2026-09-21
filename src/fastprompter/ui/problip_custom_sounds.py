"""Custom Problip sounds manager (T-1242).

One compact dialog owned by the Problip settings page.  It reuses the
managed sound library -- files are COPIED under ``<data>/sound_library/``
and the pool persists ``user:<rel>`` refs, so the runtime never depends on
the original external path.  Removing a sound that is still referenced
anywhere (pool, event, preset, ambience, voice) shows the references and
requires explicit confirmation; broken references stay visibly broken
instead of silently falling back to Original Blip.
"""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core import sound_library
from fastprompter.core.problip import DEFAULT_SOUND_ID
from fastprompter.core.translations import tr


class ProblipCustomDialog(QDialog):
    """Import / select / preview / remove managed custom Problip WAVs."""

    def __init__(self, parent, lang: str, controller) -> None:
        super().__init__(parent)
        self.lang = lang
        self.controller = controller
        self.setWindowTitle(tr("Custom Problip sounds", lang))
        self._loading = False
        self._build()
        self.reload()

    # -- construction ---------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.lbl_info = QLabel(tr(
            "Imported WAVs are copied into the managed sound library. "
            "Tick the ones the Problip pool may play.", self.lang))
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.list = QListWidget()
        # CORE-003 (audit/10): ticking/unticking a managed WAV is the advertised
        # primary interaction, so it MUST persist -- previously _persist_pool()
        # had no call site and every selection was discarded on reload.
        # reload() sets _loading so programmatic check-state population never
        # recurses back into a settings write.
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list, 1)

        actions = QHBoxLayout()
        self.btn_add = QPushButton(tr("Add WAV...", self.lang))
        self.btn_folder = QPushButton(tr("Add folder...", self.lang))
        self.btn_preview = QPushButton(tr("Preview", self.lang))
        self.btn_remove = QPushButton(tr("Remove imported file", self.lang))
        self.btn_add.clicked.connect(self._add_wav)
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_preview.clicked.connect(self._preview)
        self.btn_remove.clicked.connect(self._remove)
        for widget in (self.btn_add, self.btn_folder, self.btn_preview,
                       self.btn_remove):
            actions.addWidget(widget)
        actions.addStretch(1)
        host = QWidget()
        host.setLayout(actions)
        layout.addWidget(host)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(tr("Close", self.lang))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    # -- data -------------------------------------------------------------------

    def reload(self) -> None:
        self._loading = True
        try:
            pooled = set(self.controller.settings.selected_sound_ids)
            self.list.clear()
            for ref in sound_library.list_managed_sounds():
                item = QListWidgetItem(ref[len(sound_library.USER_PREFIX):])
                item.setData(Qt_ItemRole, ref)
                item.setFlags(item.flags() | ITEM_IS_USER_CHECKABLE)
                missing = sound_library.resolve_sound_ref(ref) is None
                item.setCheckState(
                    CHECKED if ref in pooled else UNCHECKED)
                if missing:
                    item.setText(f"{item.text()} ({tr('missing', self.lang)})")
                self.list.addItem(item)
        finally:
            self._loading = False

    def _current_ref(self) -> str:
        item = self.list.currentItem()
        return "" if item is None else str(item.data(Qt_ItemRole))

    # -- actions -----------------------------------------------------------------

    def _selected_refs(self) -> list[str]:
        pooled = [t for t in self.controller.settings.selected_sound_ids
                  if not t.startswith(sound_library.USER_PREFIX)]
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == CHECKED:
                pooled.append(str(item.data(Qt_ItemRole)))
        # Order-insensitive pool: dedupe, keep stable order.
        seen: list[str] = []
        for token in pooled:
            if token not in seen:
                seen.append(token)
        return seen

    def _on_item_changed(self, _item) -> None:
        """Persist a user checkbox change; ignore reload's programmatic fill."""
        if self._loading:
            return
        self._persist_pool()

    def _persist_pool(self) -> None:
        tokens = self._selected_refs()
        # The playable pool must never silently disappear: at least one
        # entry always remains selected.
        if tokens:
            self.controller.update_settings(selected_sound_ids=tokens)

    def _add_wav(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, tr("Add WAV", self.lang), "", "WAV (*.wav)")
        added = False
        for path in paths:
            if sound_library.import_file(path, subdir="problip"):
                added = True
        if added:
            self.reload()

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("Add folder", self.lang))
        if not folder:
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(sound_library.ALLOWED_SUFFIXES):
                if sound_library.import_file(os.path.join(folder, name),
                                             subdir="problip"):
                    added += 1
        if added:
            self.reload()

    def _preview(self) -> None:
        """Explicit user preview: exactly one, on the PREVIEW bus."""
        ref = self._current_ref()
        if not ref:
            return
        path = sound_library.resolve_sound_ref(ref)
        if not path:
            QMessageBox.information(
                self, tr("Preview", self.lang),
                tr("This file is missing from the managed library.",
                   self.lang))
            return
        self.controller.test_path(path)

    def _remove(self) -> None:
        ref = self._current_ref()
        if not ref:
            return
        references = self._references_to(ref)
        message = tr(
            "Remove this file from the managed sound library?", self.lang)
        if references:
            message += "\n" + tr("Still referenced by", self.lang) + ": " \
                + ", ".join(references)
        confirm = QMessageBox.question(
            self, tr("Remove imported file", self.lang), message)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        # CORE-003 (audit/10): deletion is transactional and never leaves a
        # dangling pool token. Delete the file FIRST; only on confirmed success
        # rewrite the pool, and if this was the sole selected custom sound the
        # canonical fallback (Original) is restored deliberately instead of
        # silently keeping a now-missing ref.
        if not sound_library.remove_managed_sound(ref):
            QMessageBox.warning(
                self, tr("Remove imported file", self.lang),
                tr("The file could not be removed; nothing was changed.",
                   self.lang))
            return
        self._drop_from_pool(ref)
        self.reload()

    def _references_to(self, ref: str) -> list[str]:
        """Typed cross-store consumers, rendered for the confirmation text.

        CORE-004 (audit/10): delegates to the ONE canonical enumerator so the
        Problip dialog and the Audio Hub report the identical dependency set
        (pool, events, saved presets, saved ambience rules). An unreadable
        store is reported as unknown, never as "no references".
        """
        from fastprompter.core.sound_dependencies import dependencies_for_ref

        main_win = getattr(self.parent(), "main_win", None) or self.parent()
        state = getattr(main_win, "state", None)
        data = getattr(state, "data", None) if state is not None else None
        deps = dependencies_for_ref(
            ref, data=data if isinstance(data, dict) else None,
            problip_sound_ids=list(
                self.controller.settings.selected_sound_ids))
        references: list[str] = []
        if deps.problip_pool:
            references.append(tr("Problip pool", self.lang))
        for event in deps.events:
            references.append(f"{tr('Event', self.lang)}: {event}")
        for preset_id in deps.presets:
            references.append(f"{tr('Preset', self.lang)}: {preset_id}")
        for rule_id in deps.ambience_rules:
            references.append(f"{tr('Ambience rule', self.lang)}: {rule_id}")
        for store in deps.impact_unknown:
            references.append(
                tr("Unknown impact", self.lang) + f": {store}")
        return references

    def _drop_from_pool(self, ref: str) -> None:
        tokens = [t for t in self.controller.settings.selected_sound_ids
                  if t != ref]
        # Never leave the pool semantically empty: if the removed ref was the
        # only selection, restore the canonical default rather than persisting
        # a dangling token (normalize_sound_ids would drop it and fall back to
        # Original anyway -- do it explicitly and visibly here).
        if not tokens:
            tokens = [DEFAULT_SOUND_ID]
        self.controller.update_settings(selected_sound_ids=tokens)


# Shorthands kept at module bottom so the import above stays tidy.
from PyQt6.QtCore import Qt  # noqa: E402

Qt_ItemRole = Qt.ItemDataRole.UserRole
ITEM_IS_USER_CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
CHECKED = Qt.CheckState.Checked
UNCHECKED = Qt.CheckState.Unchecked
