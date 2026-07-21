"""Arming the watcher: pick a window, pick an agent, say go.

The dialog owns no logic. It shows what the engine thinks, and offers the
three controls that matter — arm, disarm, and stop everything.

Two deliberate absences:

* **No confirm-before-each-send.** The feature exists so the queue drains
  while the user is doing something else; a prompt per send would defeat it.
  The protections are the dry run, the rate limit, the identity check and
  the panic key, none of which interrupt anything.
* **No focus-stealing option.** It exists in the sender for a caller that
  asks, and nothing here asks.

Closing this dialog does NOT disarm. A run outlives the window that started
it, which is the whole point of a watcher.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr
from fastprompter.core.watcher import win32
from fastprompter.core.watcher.engine import ARMED, DISARMED, SENDING, WATCHING
from fastprompter.core.watcher.queue import queue_for

_STATE_COLORS = {
    DISARMED: "#888888",
    ARMED: "#6aa9ff",
    WATCHING: "#e0a03c",
    SENDING: "#46b98a",
}


class WatcherDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "en")
        self.setWindowTitle(tr("Watcher", self.lang))
        self.resize(560, 520)

        self._adapters, self._limits, self._errors = main_win.watcher_adapters()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.lbl_state = QLabel()
        self.lbl_state.setWordWrap(True)
        root.addWidget(self.lbl_state)

        root.addWidget(QLabel(tr("Agent", self.lang)))
        self.cmb_agent = QComboBox()
        root.addWidget(self.cmb_agent)
        self.lbl_agent_why = QLabel()
        self.lbl_agent_why.setWordWrap(True)
        self.lbl_agent_why.setStyleSheet("color: #b08040;")
        root.addWidget(self.lbl_agent_why)

        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Target window", self.lang)))
        head.addStretch(1)
        btn_rescan = QPushButton(tr("Rescan", self.lang))
        btn_rescan.clicked.connect(self.refresh_windows)
        head.addWidget(btn_rescan)
        root.addLayout(head)

        self.lst_windows = QListWidget()
        self.lst_windows.setMinimumHeight(120)
        root.addWidget(self.lst_windows)

        self.chk_live = QCheckBox(
            tr("Actually send (otherwise it only records what it would send)",
               self.lang))
        root.addWidget(self.chk_live)

        row = QHBoxLayout()
        self.btn_arm = QPushButton()
        self.btn_arm.clicked.connect(self.toggle_arm)
        row.addWidget(self.btn_arm)
        self.btn_panic = QPushButton(tr("Stop everything", self.lang))
        self.btn_panic.clicked.connect(self.panic)
        row.addWidget(self.btn_panic)
        root.addLayout(row)

        # Watching is not arming with sending switched off: it builds no
        # target and no sender, so there is nothing in that mode that could
        # send. Safe to point at an agent mid-turn to learn its signal.
        self.btn_watch = QPushButton()
        self.btn_watch.clicked.connect(self.toggle_watch)
        root.addWidget(self.btn_watch)

        self.lst_trace = QListWidget()
        self.lst_trace.setMinimumHeight(96)
        self.lst_trace.setToolTip(tr(
            "Live signal from the agent. Only changes are listed.", self.lang))
        root.addWidget(self.lst_trace)

        root.addWidget(QLabel(tr("What has gone out", self.lang)))
        self.lst_log = QListWidget()
        self.lst_log.setMinimumHeight(110)
        root.addWidget(self.lst_log)

        self.cmb_agent.currentIndexChanged.connect(self.refresh_agent_note)

        self.refresh_agents()
        self.refresh_windows()
        self.refresh()
        main_win.watcher_listen(self.refresh)

    # ---- teardown -----------------------------------------------------
    def closeEvent(self, event):
        """Unsubscribe, but leave a run going.

        The listener list holds a bound method of a dialog Qt is about to
        delete; calling into it from the next tick would reach a dead C++
        object, and an exception in a Qt slot takes the process down with no
        traceback.
        """
        try:
            self.main_win.watcher_unlisten(self.refresh)
        except Exception:
            pass
        super().closeEvent(event)

    # ---- population ---------------------------------------------------
    def refresh_agents(self):
        self.cmb_agent.blockSignals(True)
        self.cmb_agent.clear()
        for adapter in self._adapters:
            ok, reason = (
                (False, tr("disabled in the config", self.lang))
                if not adapter.enabled else adapter.supported())
            label = adapter.name if ok else f"{adapter.name}  —  {reason}"
            self.cmb_agent.addItem(label, adapter)
            index = self.cmb_agent.count() - 1
            if not ok:
                item = self.cmb_agent.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        self.cmb_agent.blockSignals(False)

        for i in range(self.cmb_agent.count()):
            adapter = self.cmb_agent.itemData(i)
            if adapter is not None and adapter.enabled and adapter.supported()[0]:
                self.cmb_agent.setCurrentIndex(i)
                break
        self.refresh_agent_note()

    def refresh_agent_note(self):
        notes = list(self._errors)
        adapter = self.current_adapter()
        if adapter is not None and not adapter.supported()[0]:
            notes.append(adapter.supported()[1])
        if adapter is not None and adapter.skill_format is None:
            notes.append(tr(
                "This agent has no skills; queued items carrying one will be "
                "skipped rather than sent without it.", self.lang))
        self.lbl_agent_why.setText("\n".join(notes))
        self.lbl_agent_why.setVisible(bool(notes))

    def refresh_windows(self):
        import os

        self.lst_windows.clear()
        if not win32.available():
            self.lst_windows.addItem(
                tr("No window layer on this platform.", self.lang))
            return
        for win in win32.list_windows(own_pid=os.getpid()):
            item = QListWidgetItem(f"{win.title}    [{win.cls}]")
            item.setData(Qt.ItemDataRole.UserRole, win.hwnd)
            item.setToolTip(f"hwnd {win.hwnd} · pid {win.pid}")
            self.lst_windows.addItem(item)

    # ---- reading the controls -----------------------------------------
    def current_adapter(self):
        return self.cmb_agent.currentData()

    def current_hwnd(self):
        item = self.lst_windows.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # ---- actions ------------------------------------------------------
    def toggle_arm(self):
        engine = self.main_win.watcher_engine()
        if engine.armed:
            self.main_win.watcher_disarm(tr("stopped by hand", self.lang))
            return

        hwnd = self.current_hwnd()
        if hwnd is None:
            self.lbl_state.setText(tr("Pick the window to send to.", self.lang))
            return

        queue = queue_for(self.main_win.prompt_queues,
                          self.main_win._queue_slot_key())
        if not queue.pending():
            self.lbl_state.setText(
                tr("Nothing is queued in this silo yet — Alt+C adds a line.",
                   self.lang))
            return

        ok, reason = self.main_win.watcher_arm(
            hwnd, self.current_adapter(), live=self.chk_live.isChecked())
        if not ok:
            self.lbl_state.setText(reason)
        self.refresh()

    def panic(self):
        self.main_win.watcher_panic()
        self.refresh()

    def toggle_watch(self):
        if self.main_win.watcher_observing:
            self.main_win.watcher_stop_observing()
            return
        ok, reason = self.main_win.watcher_observe(self.current_adapter())
        if not ok:
            self.lbl_state.setText(reason)
        self.refresh()

    # ---- the live view ------------------------------------------------
    def refresh(self):
        engine = self.main_win.watcher_engine()
        colour = _STATE_COLORS.get(engine.state, "#888888")
        target = getattr(self.main_win, "_watcher_target", None)
        where = f" → {target.title}" if target is not None and engine.armed else ""

        queue = queue_for(self.main_win.prompt_queues,
                          engine.queue_key or self.main_win._queue_slot_key())
        left = len(queue.pending())

        self.lbl_state.setText(
            f"<b style='color:{colour}'>{engine.state}</b>{where}<br>"
            f"{engine.reason or ''}<br>"
            f"{tr('sent', self.lang)}: {engine.sent_count} · "
            f"{tr('still queued', self.lang)}: {left}")

        armed = engine.armed
        self.btn_arm.setText(
            tr("Disarm", self.lang) if armed else tr("Arm", self.lang))
        self.btn_panic.setEnabled(armed)
        # Locked while armed: both are pinned at arming, so letting them move
        # would show a target and a queue the run is not actually using.
        self.lst_windows.setEnabled(not armed)
        self.cmb_agent.setEnabled(not armed)
        self.chk_live.setEnabled(not armed)

        watching = self.main_win.watcher_observing
        self.btn_watch.setText(
            tr("Stop watching", self.lang) if watching
            else tr("Watch the agent (sends nothing)", self.lang))
        self.btn_watch.setEnabled(not armed)

        self.lst_trace.clear()
        for row in reversed(self.main_win.watcher_trace()[-30:]):
            grew = f"  +{row['delta']:,}b" if row["delta"] > 0 else ""
            mark = "▶" if row["state"] == "busy" else "■"
            note = ""
            if row["would_send"]:
                mark = "→"
                note = "   " + tr("a prompt would go out here", self.lang)
            item = QListWidgetItem(
                f"{mark}  {row['at']:6.1f}s  {row['state']}{grew}{note}")
            item.setToolTip(row["reason"])
            self.lst_trace.addItem(item)

        self.lst_log.clear()
        for entry in reversed(self.main_win.watcher_log().to_list()[-40:]):
            mark = "✓" if entry["ok"] else "✗"
            if entry["dry"]:
                mark = "·"
            row = QListWidgetItem(f"{mark}  {entry['text'][:70]}")
            row.setToolTip(f"{entry['at']} · {entry['reason']}")
            self.lst_log.addItem(row)
