"""Where a tag appears, across every silo.

Opened by Ctrl+clicking a #tag. Deliberately a finder, not a manager: there
is nothing here to rename, delete or organise, because a tag only exists
while it is written somewhere.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.hashtags import collect_all, find_occurrences
from fastprompter.core.translations import tr


class HashtagDialog(QDialog):
    def __init__(self, main_win, tag=None):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")

        self.setWindowTitle(tr("Tags", self.lang))
        self.setMinimumSize(560, 360)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(6)

        left = QVBoxLayout()
        left.setSpacing(3)
        left.addWidget(QLabel(tr("Tags in use", self.lang)))
        self.tag_list = QListWidget()
        self.tag_list.setMaximumWidth(180)
        self.tag_list.setToolTip(tr(
            "Every tag written anywhere, with how many lines carry it",
            self.lang))
        self.tag_list.currentItemChanged.connect(self._tag_selected)
        left.addWidget(self.tag_list, 1)
        body.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(3)
        self.lbl_hits = QLabel("")
        right.addWidget(self.lbl_hits)
        self.hit_list = QListWidget()
        self.hit_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.hit_list.setToolTip(tr(
            "Double-click a line to open the silo it lives in", self.lang))
        self.hit_list.itemActivated.connect(self._go_to)
        self.hit_list.itemDoubleClicked.connect(self._go_to)
        right.addWidget(self.hit_list, 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_go = QPushButton(tr("Go to line", self.lang))
        self.btn_go.clicked.connect(lambda: self._go_to(self.hit_list.currentItem()))
        actions.addWidget(self.btn_go)
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        actions.addWidget(btn_close)
        root.addLayout(actions)

        self.reload(select=tag)

    # ------------------------------------------------------------------
    def _silo_texts(self):
        """Silo bodies, with the LIVE editor text for the open one.

        Reading straight from `data` would show a stale copy of whatever is
        being typed right now, which is usually the very thing being tagged.
        """
        texts = list(self.main_win.data.get("temp_presets") or [])
        slot = getattr(self.main_win, "active_temp_slot", 0)
        if (not getattr(self.main_win, "active_is_archive", False)
                and 0 <= slot < len(texts)):
            try:
                texts[slot] = self.main_win.text_area.toPlainText()
            except Exception:
                pass
        return texts

    @staticmethod
    def _silo_label(text):
        """Silos have no separate name: the sidebar shows the start of the
        text, so the same rule is used here."""
        first = (text or "").strip().splitlines()[:1]
        label = (first[0] if first else "").lstrip("#").strip()
        return label[:34] or ""

    def reload(self, select=None):
        self._texts = self._silo_texts()
        counts = collect_all(self._texts)
        self.tag_list.clear()
        for tag in sorted(counts, key=lambda t: (-counts[t], t)):
            item = QListWidgetItem(f"#{tag}  ({counts[tag]})")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.tag_list.addItem(item)

        wanted = (select or "").lstrip("#").lower()
        for row in range(self.tag_list.count()):
            item = self.tag_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == wanted:
                self.tag_list.setCurrentRow(row)
                return
        if self.tag_list.count():
            self.tag_list.setCurrentRow(0)
        else:
            self.lbl_hits.setText(tr("No tags written yet", self.lang))

    def _tag_selected(self, item, _prev=None):
        self.hit_list.clear()
        if item is None:
            return
        tag = item.data(Qt.ItemDataRole.UserRole)
        hits = find_occurrences(tag, self._texts,
                                [self._silo_label(t) for t in self._texts])
        self.lbl_hits.setText(f"#{tag} — {len(hits)} {tr('lines', self.lang)}")
        for hit in hits:
            row = QListWidgetItem(
                f"{hit['name']}:{hit['line']}   {hit['text'][:90]}")
            row.setData(Qt.ItemDataRole.UserRole, hit)
            self.hit_list.addItem(row)
        if hits:
            self.hit_list.setCurrentRow(0)

    def _go_to(self, item):
        if item is None:
            return
        hit = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(hit, dict):
            return
        if self.main_win.jump_to_silo_line(hit["silo"], hit["line"]):
            self.accept()
