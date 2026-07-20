"""Timer notification popup.

A tray balloon is easy to miss and can't be acted on. This is a small
frameless panel in the corner of the screen showing the timer's name and
description, with Snooze and Dismiss right there.

It deliberately does NOT steal focus (WA_ShowWithoutActivating): a limit
reset should not yank the caret out of whatever the user is typing.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.translations import tr

_MARGIN = 18
_AUTO_CLOSE_MS = 30000
_SNOOZE_CHOICES = (5, 10, 30)


class TimerToast(QWidget):
    """One popup per fired timer. Stacks upward if several land at once."""

    _open: list[TimerToast] = []

    def __init__(self, main_win, timer, on_snooze=None):
        super().__init__(None)
        self.main_win = main_win
        self.timer_obj = timer
        self.on_snooze = on_snooze
        lang = getattr(main_win, "_current_lang", "EN")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        accent = timer.display_color()
        self.setStyleSheet(f"""
            QWidget {{ background-color: #1a1a1a; color: #d0d0d0; }}
            QLabel#TitleLbl {{ color: {accent}; font-weight: bold; font-size: 13px; }}
            QLabel#DescLbl  {{ color: #a0a0a0; }}
            QPushButton {{
                background-color: #2e2e2e; color: #d0d0d0;
                border: 1px solid #0a0a0a; padding: 3px 8px;
            }}
            QPushButton:hover {{ background-color: #3a3a3a; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)

        title = QLabel(timer.name)
        title.setObjectName("TitleLbl")
        root.addWidget(title)

        if timer.description:
            desc = QLabel(timer.description)
            desc.setObjectName("DescLbl")
            desc.setWordWrap(True)
            desc.setMaximumWidth(300)
            root.addWidget(desc)

        when = QLabel(tr("Time's up", lang))
        when.setObjectName("DescLbl")
        root.addWidget(when)

        row = QHBoxLayout()
        row.setSpacing(4)
        for mins in _SNOOZE_CHOICES:
            b = QPushButton(f"+{mins}m")
            b.setToolTip(tr("Snooze", lang))
            b.clicked.connect(lambda _c, m=mins: self._snooze(m))
            row.addWidget(b)
        row.addStretch(1)
        btn_ok = QPushButton(tr("Dismiss", lang))
        btn_ok.clicked.connect(self.close)
        row.addWidget(btn_ok)
        root.addLayout(row)

        self.adjustSize()
        self._place()

        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.timeout.connect(self.close)
        self._auto.start(_AUTO_CLOSE_MS)

        TimerToast._open.append(self)

    # ------------------------------------------------------------------
    def _place(self):
        """Bottom-right of the screen, stacked above any toast already up."""
        screen = QApplication.primaryScreen()
        try:
            if self.main_win is not None:
                screen = QApplication.screenAt(
                    self.main_win.geometry().center()) or screen
        except Exception:
            pass
        if screen is None:
            return
        area = screen.availableGeometry()
        offset = sum(t.height() + 8 for t in TimerToast._open if not t.isHidden())
        self.move(area.right() - self.width() - _MARGIN,
                  area.bottom() - self.height() - _MARGIN - offset)

    def _snooze(self, minutes):
        try:
            if self.on_snooze:
                self.on_snooze(self.timer_obj, minutes)
        finally:
            self.close()

    def closeEvent(self, event):
        try:
            TimerToast._open.remove(self)
        except ValueError:
            pass
        super().closeEvent(event)


def show_toast(main_win, timer, on_snooze=None):
    """Create and show a toast; returns it (or None if the UI can't)."""
    try:
        toast = TimerToast(main_win, timer, on_snooze=on_snooze)
        toast.show()
        toast.raise_()
        return toast
    except Exception:
        from fastprompter.core.logging import logger
        logger.debug("timer toast failed to show")
        return None
