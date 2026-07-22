"""Header indicator widget — compact queue status badge.

Lives in the toolbar between the timer and pin-top button.
Shows: queue icon, entry count badge, colour-coded status.
Click toggles the queue sidebar panel.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from fastprompter.core.translations import tr


class PromptQueueIndicator(QPushButton):
    """Compact header button showing queue state.

    Appearance:
      idle (0 entries)    ─ grey  "📋"
      queued (1+ entries) ─ gold  "📋 N"
      running             ─ green "📋 N"
      error               ─ red   "📋 !"
    """

    def __init__(self, main_win):
        super().__init__("📋")
        self.main_win = main_win
        self.setObjectName("btn_queue_indicator")
        self.setToolTip(tr("Prompt Queue — click to toggle panel",
                           getattr(main_win, "_current_lang", "EN")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._active = False
        self.clicked.connect(self._toggle_panel)

    def set_active(self, on: bool) -> None:
        """Mirror the panel's visibility without fighting the click toggle."""
        self._active = on
        self._update_style()

    def refresh(self) -> None:
        """Read current queue state from the manager and update appearance."""
        self._update_style()

    def _toggle_panel(self) -> None:
        panel = getattr(self.main_win, "queue_panel", None)
        if panel is None:
            return
        visible = not panel.isVisible()
        panel.setVisible(visible)
        self._active = visible
        self._update_style()

    def _update_style(self) -> None:
        qm = getattr(self.main_win, "queue_manager", None)
        if qm is None:
            count = 0
            running = False
        else:
            count = len(qm)
            running = qm.running

        # Build label
        if count > 0:
            self.setText(f"📋{count}")
        else:
            self.setText("📋")

        # Colour by state
        if count == 0:
            colour = "#888888"
        elif running:
            colour = "#44aa44"  # green
        elif any(e.status == "failed" for e in qm):
            colour = "#dd4444"  # red
        else:
            colour = "#d4b84c"  # gold/queued

        # Active (panel open) gets a sunken look
        if self._active:
            self.setStyleSheet(
                f"padding: 0 2px; font-weight: bold; color: {colour};"
                f" background-color: #2a2a2a; border: 1px inset #555;"
            )
        else:
            self.setStyleSheet(
                f"padding: 0 2px; font-weight: bold; color: {colour};"
                f" background: transparent; border: none;"
            )
