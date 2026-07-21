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
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.translations import tr
from fastprompter.core.watcher.queue import (
    DETACHED,
    FAILED,
    PENDING,
    SENT,
    SKIPPED,
    all_items,
    move_between,
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs)
        # currentChanged is connected at the END of __init__: adding the very
        # first tab fires it, and a refresh() that early reaches for widgets
        # this constructor has not built yet. The exception lands inside a Qt
        # slot, which takes the process down without a traceback.

        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)
        self.tabs.addTab(page, tr("This silo", self.lang))

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

        self._build_master_tab()
        self.refresh()
        self.tabs.currentChanged.connect(lambda _i: self.refresh())

    # ------------------------------------------------------------------
    def _build_master_tab(self):
        """Every queue in the category at once, and a way to move items."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        self.lbl_master = QLabel("")
        lay.addWidget(self.lbl_master)

        self.master_list = QListWidget()
        self.master_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.master_list.setToolTip(tr(
            "Every silo's queue in this category. The silo each prompt came\n"
            "from is named on the left.", self.lang))
        lay.addWidget(self.master_list, 1)

        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel(tr("Move to:", self.lang)))
        self.cb_target = QComboBox()
        self.cb_target.setToolTip(tr("Which silo's queue to move it into", self.lang))
        row.addWidget(self.cb_target, 1)

        self.btn_move = QPushButton(tr("Move", self.lang))
        self.btn_move.clicked.connect(self.move_selected_to_target)
        row.addWidget(self.btn_move)

        self.btn_master_front = QPushButton(tr("Send next", self.lang))
        self.btn_master_front.setToolTip(tr(
            "Move to the front of its own queue. Still waits for the agent.",
            self.lang))
        self.btn_master_front.clicked.connect(self.master_to_front)
        row.addWidget(self.btn_master_front)

        self.btn_master_remove = QPushButton(tr("Remove", self.lang))
        self.btn_master_remove.clicked.connect(self.master_remove)
        row.addWidget(self.btn_master_remove)
        row.addStretch(1)
        lay.addLayout(row)

        self.tabs.addTab(page, tr("All silos", self.lang))

    # ---- master view --------------------------------------------------
    def _master_selected(self):
        row = self.master_list.currentItem()
        if row is None:
            return None, None
        slot, item_id = row.data(Qt.ItemDataRole.UserRole)
        queue = self.main_win.prompt_queues.get(slot)
        return slot, (queue.find(item_id) if queue else None)

    def refresh_master(self):
        queues = self.main_win.prompt_queues
        labels = self.main_win.silo_queue_labels()

        keep = None
        current = self.master_list.currentItem()
        if current is not None:
            keep = current.data(Qt.ItemDataRole.UserRole)

        self.master_list.clear()
        total = 0
        for slot, label, item in all_items(queues, labels):
            text, detached = self.main_win.queue_item_live_text(slot, item)
            if detached and item.state == PENDING:
                item.mark_detached()
            elif not detached and item.state == DETACHED:
                item.state, item.reason = PENDING, ""
            if text and text != item.text and item.state not in (SENT, FAILED, SKIPPED):
                item.text = text

            lamp, hint = _LAMPS.get(item.state, ("?", item.state))
            skill = f"/{item.skill} " if item.skill else ""
            row = QListWidgetItem(f"{lamp}  [{label}]  {skill}{item.text}")
            row.setData(Qt.ItemDataRole.UserRole, (slot, item.id))
            tip = [hint]
            if item.reason:
                tip.append(item.reason)
            row.setToolTip("\n".join(tip))
            from PyQt6.QtGui import QColor
            row.setForeground(QColor(_LAMP_COLORS.get(item.state, "#c0c0c0")))
            self.master_list.addItem(row)
            if keep == (slot, item.id):
                self.master_list.setCurrentItem(row)
            total += 1

        self.lbl_master.setText(
            f"{total} " + tr("prompts across", self.lang)
            + f" {len(queues)} " + tr("silos", self.lang))

        self.cb_target.clear()
        presets = self.main_win.data.get("temp_presets") or []
        for index in range(len(presets)):
            slot = str(index)
            self.cb_target.addItem(
                f"{index + 1}: {self.main_win.silo_queue_label(slot)}", slot)

        for btn in (self.btn_move, self.btn_master_front, self.btn_master_remove):
            btn.setEnabled(total > 0)

    def move_selected_to_target(self):
        slot, item = self._master_selected()
        if item is None:
            return
        target = self.cb_target.currentData()
        if target is None or str(target) == str(slot):
            return
        # the anchor belongs to the old silo's document; moving the item to
        # another silo leaves it pointing at a line that is not there, so the
        # mark goes and the item carries its text from here on
        editor = getattr(self.main_win, "text_area", None)
        if editor is not None and str(slot) == self.main_win._queue_slot_key():
            editor.clear_queue_marks(item.id)
        move_between(self.main_win.prompt_queues, item.id, slot, target)
        self.main_win.save_prompt_queues()
        self.refresh()

    def master_to_front(self):
        slot, item = self._master_selected()
        if item is None:
            return
        self.main_win.prompt_queues[slot].to_front(item.id)
        self.main_win.save_prompt_queues()
        self.refresh()

    def master_remove(self):
        slot, item = self._master_selected()
        if item is None:
            return
        editor = getattr(self.main_win, "text_area", None)
        if editor is not None and str(slot) == self.main_win._queue_slot_key():
            editor.clear_queue_marks(item.id)
        self.main_win.prompt_queues[slot].remove(item.id)
        self.main_win.save_prompt_queues()
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
        if getattr(self, "master_list", None) is not None:
            self.refresh_master()
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
