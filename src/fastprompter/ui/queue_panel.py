"""The prompt queue for the current silo.

Shows what Alt+C has collected, in the order it will go out. Reordering,
editing and deleting live here; sending does not — there is deliberately no
control in this dialog that types into an agent.

Rows show the text read back from the line the item is anchored to, so what
is listed is what would actually be sent.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr
from fastprompter.core.watcher.queue import (
    DETACHED,
    FAILED,
    PENDING,
    SENT,
    SKIPPED,
    queue_for,
)

# state -> (lamp, tooltip). The lamp is text, not an icon, so it survives
# every theme without a second asset to keep in step.
_LAMPS = {
    PENDING: ("●", "waiting to be sent"),
    SENT: ("✓", "sent"),
    FAILED: ("✗", "failed"),
    SKIPPED: ("–", "skipped"),
    DETACHED: ("⚠", "its line was deleted"),
}
_LAMP_COLORS = {
    PENDING: "#6aa9ff",
    SENT: "#46b98a",
    FAILED: "#e05555",
    SKIPPED: "#888888",
    DETACHED: "#e0a03c",
}


class QueueDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")

        self.setWindowTitle(tr("Prompt queue", self.lang))
        self.setMinimumSize(520, 380)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.lbl_head = QLabel("")
        root.addWidget(self.lbl_head)

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        # dragging is the natural way to reorder, and the order IS the
        # sending order - so the drop has to be written back to the queue
        self.list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.list.model().rowsMoved.connect(lambda *_: self._apply_row_order())
        self.list.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setSpacing(4)

        self.btn_next = QPushButton(tr("Send next", self.lang))
        self.btn_next.setToolTip(tr(
            "Move to the front of the queue.\n"
            "It still waits for the agent to be idle - nothing here types\n"
            "into a running agent.", self.lang))
        self.btn_next.clicked.connect(self.to_front_selected)
        row.addWidget(self.btn_next)

        self.btn_up = QPushButton("▲")
        self.btn_up.setToolTip(tr("Move up", self.lang))
        self.btn_up.clicked.connect(lambda: self.nudge(-1))
        row.addWidget(self.btn_up)

        self.btn_down = QPushButton("▼")
        self.btn_down.setToolTip(tr("Move down", self.lang))
        self.btn_down.clicked.connect(lambda: self.nudge(1))
        row.addWidget(self.btn_down)

        self.btn_edit = QPushButton(tr("Edit", self.lang))
        self.btn_edit.setToolTip(tr(
            "Edit the queued text. The note itself is not touched.", self.lang))
        self.btn_edit.clicked.connect(self.edit_selected)
        row.addWidget(self.btn_edit)

        self.btn_remove = QPushButton(tr("Remove", self.lang))
        self.btn_remove.clicked.connect(self.remove_selected)
        row.addWidget(self.btn_remove)

        row.addStretch(1)
        self.btn_clear_done = QPushButton(tr("Clear finished", self.lang))
        self.btn_clear_done.setToolTip(tr(
            "Drop everything that has been sent, failed or skipped.", self.lang))
        self.btn_clear_done.clicked.connect(self.clear_finished)
        row.addWidget(self.btn_clear_done)

        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        root.addLayout(row)

        self.refresh()

    # ------------------------------------------------------------------
    def _queue(self):
        return queue_for(self.main_win.prompt_queues,
                         self.main_win._queue_slot_key())

    def _selected(self):
        item = self.list.currentItem()
        if item is None:
            return None
        return self._queue().find(item.data(Qt.ItemDataRole.UserRole))

    # ---- keeping the rows honest --------------------------------------
    def refresh_from_document(self):
        """Read each item's text back from the line it is anchored to.

        Items are references, not copies: this is what makes an edit in the
        note show up here. An anchor that no longer resolves means the line
        was deleted, which is what `detached` records - the last known text
        is kept rather than thrown away.
        """
        editor = getattr(self.main_win, "text_area", None)
        if editor is None:
            return
        for item in self._queue():
            if item.state in (SENT, FAILED, SKIPPED):
                continue          # it has had its turn; freeze what it said
            block = editor.block_for_queue_item(item.id)
            if block is None:
                if item.state != DETACHED:
                    item.mark_detached()
                continue
            text = block.text().strip()
            if text and text != item.text:
                item.text = text
            if item.state == DETACHED:
                item.state = PENDING      # the line came back (undo)
                item.reason = ""

    def refresh(self):
        self.refresh_from_document()
        queue = self._queue()
        selected = self.list.currentItem()
        keep = selected.data(Qt.ItemDataRole.UserRole) if selected else None

        self.list.blockSignals(True)
        self.list.clear()
        for item in queue:
            lamp, hint = _LAMPS.get(item.state, ("?", item.state))
            skill = f"/{item.skill} " if item.skill else ""
            row = QListWidgetItem(f"{lamp}  {skill}{item.text}")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            tip = [hint]
            if item.reason:
                tip.append(item.reason)
            if item.line:
                tip.append(tr("from line {}", self.lang).format(item.line)
                           if "{}" in tr("from line {}", self.lang)
                           else f"line {item.line}")
            row.setToolTip("\n".join(tip))
            from PyQt6.QtGui import QColor
            row.setForeground(QColor(_LAMP_COLORS.get(item.state, "#c0c0c0")))
            self.list.addItem(row)
            if item.id == keep:
                self.list.setCurrentItem(row)
        self.list.blockSignals(False)

        pending = len(queue.pending())
        self.lbl_head.setText(
            f"{self._silo_label()} — {pending}/{len(queue)} "
            + tr("waiting", self.lang))
        for btn in (self.btn_next, self.btn_up, self.btn_down,
                    self.btn_edit, self.btn_remove):
            btn.setEnabled(bool(len(queue)))

    def _silo_label(self):
        """The silo's name: its first non-empty line, minus a leading `#`.

        The sidebar flattens the first 100 CHARACTERS, which suits a narrow
        button but reads as run-on text in a header — notes open with a
        title, so the first line is the name.
        """
        try:
            raw = self.main_win.text_area.toPlainText()
        except Exception:
            raw = ""
        first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        if first.startswith("#"):
            first = first.lstrip("#").lstrip()
        return first[:48] or tr("This silo", self.lang)

    # ---- actions ------------------------------------------------------
    def _apply_row_order(self):
        """A drag reordered the rows; the queue is the thing that matters."""
        queue = self._queue()
        by_id = {i.id: i for i in queue}
        ordered = []
        for row in range(self.list.count()):
            item_id = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            if item_id in by_id:
                ordered.append(by_id.pop(item_id))
        ordered.extend(by_id.values())     # anything unmatched keeps its place
        queue.items[:] = ordered
        self.main_win.save_prompt_queues()

    def nudge(self, delta):
        item = self._selected()
        if item is None:
            return
        queue = self._queue()
        index = queue.items.index(item)
        queue.move(item.id, index + delta)
        self.main_win.save_prompt_queues()
        self.refresh()

    def to_front_selected(self):
        item = self._selected()
        if item is None:
            return
        self._queue().to_front(item.id)
        self.main_win.save_prompt_queues()
        self.refresh()

    def edit_selected(self):
        item = self._selected()
        if item is None:
            return
        text, ok = QInputDialog.getText(
            self, tr("Edit prompt", self.lang),
            tr("Text to send:", self.lang), text=item.text)
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        item.text = text
        # the note keeps its own text: editing here changes what is sent,
        # not what is written down
        self.main_win.save_prompt_queues()
        self.refresh()

    def remove_selected(self):
        item = self._selected()
        if item is None:
            return
        editor = getattr(self.main_win, "text_area", None)
        if editor is not None:
            editor.clear_queue_marks(item.id)
        self._queue().remove(item.id)
        self.main_win.save_prompt_queues()
        self.refresh()

    def clear_finished(self):
        queue = self._queue()
        editor = getattr(self.main_win, "text_area", None)
        for item in list(queue):
            if item.state in (SENT, FAILED, SKIPPED):
                if editor is not None:
                    editor.clear_queue_marks(item.id)
                queue.remove(item.id)
        self.main_win.save_prompt_queues()
        self.refresh()
