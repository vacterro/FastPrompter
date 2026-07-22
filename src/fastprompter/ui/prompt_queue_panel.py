"""Queue panel widget that lives in the sidebar.

Shows queued prompts with status, allows reorder/delete/clear,
and provides start/stop control for the watcher.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.prompt_queue import PromptEntry, QueueManager
from fastprompter.core.translations import tr


# Map entry status to a short label + colour hint
_STATUS_MARK = {
    "queued": "○ ",
    "sent": "◉ ",
    "completed": "✓ ",
    "failed": "✗ ",
}


class PromptQueuePanel(QWidget):
    """Collapsible sidebar panel listing queued prompts."""

    def __init__(self, main_win, queue_manager: QueueManager):
        super().__init__()
        self.main_win = main_win
        self._qm = queue_manager
        self._qm.set_on_change(self._on_queue_changed)

        self.setObjectName("PromptQueuePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Header row: title + clear + close
        hdr = QHBoxLayout()
        hdr.setSpacing(2)
        title = QLabel(tr("Queue", getattr(main_win, "_current_lang", "EN")))
        title.setStyleSheet("font-weight: bold; padding: 2px 4px;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._btn_start = QPushButton("▶")
        self._btn_start.setToolTip(tr("Start watcher", getattr(main_win, "_current_lang", "EN")))
        self._btn_start.setFixedSize(20, 20)
        self._btn_start.clicked.connect(self._toggle_watcher)
        hdr.addWidget(self._btn_start)

        self._btn_clear = QPushButton("✕")
        self._btn_clear.setToolTip(tr("Clear queue", getattr(main_win, "_current_lang", "EN")))
        self._btn_clear.setFixedSize(20, 20)
        self._btn_clear.clicked.connect(self._clear_queue)
        hdr.addWidget(self._btn_clear)

        self._btn_close = QPushButton("▸")
        self._btn_close.setToolTip(tr("Close panel", getattr(main_win, "_current_lang", "EN")))
        self._btn_close.setFixedSize(20, 20)
        self._btn_close.clicked.connect(self._close_panel)
        hdr.addWidget(self._btn_close)

        layout.addLayout(hdr)

        # List of queued entries
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.itemDoubleClicked.connect(self._remove_item)
        layout.addWidget(self._list)

        # Empty state label
        self._empty_lbl = QLabel(tr("Queue empty.\nPress hotkey to queue a line.",
                                     getattr(main_win, "_current_lang", "EN")))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #888; padding: 20px;")
        self._empty_lbl.setWordWrap(True)
        layout.addWidget(self._empty_lbl)

        # Bottom: count label
        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet("padding: 1px 4px; color: #888;")
        layout.addWidget(self._count_lbl)

        self._refresh()

    # ---- public helpers ----

    def add_entry(self, entry: PromptEntry) -> None:
        """Called from outside to append a newly-captured entry."""
        self._qm.append(entry)

    def refresh(self) -> None:
        """Rebuild list from queue manager state."""
        self._refresh()

    # ---- internal ----

    def _refresh(self) -> None:
        self._list.clear()
        count = len(self._qm)
        self._empty_lbl.setVisible(count == 0)
        self._count_lbl.setText(str(count))

        # Toggle button label
        self._btn_start.setText("■" if self._qm.running else "▶")

        for entry in self._qm:
            mark = _STATUS_MARK.get(entry.status, "○ ")
            preview = entry.text[:60].replace("\n", " ")
            label = f"{mark}{preview}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(
                f"[{entry.status}] silo {entry.silo_index}:{entry.line_number}\n"
                f"{entry.text[:200]}"
            )
            self._list.addItem(item)

    def _on_queue_changed(self) -> None:
        self._refresh()
        # Also update the header indicator if available
        ind = getattr(self.main_win, "queue_indicator", None)
        if ind is not None:
            ind.refresh()

    def _toggle_watcher(self) -> None:
        self._qm.running = not self._qm.running
        self._refresh()

    def _clear_queue(self) -> None:
        self._qm.clear()
        self._refresh()

    def _remove_item(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        if entry_id:
            self._qm.remove(entry_id)
            self._refresh()

    def _close_panel(self) -> None:
        self.setVisible(False)
        # Sync the header indicator
        ind = getattr(self.main_win, "queue_indicator", None)
        if ind is not None:
            ind.set_active(False)
