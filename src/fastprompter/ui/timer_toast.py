from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.translations import tr
from fastprompter.theme.themes import blend_hex

_MARGIN = 18
_AUTO_CLOSE_MS = 30000
_SNOOZE_CHOICES = (5, 10, 30)


def _get_toast_palette(main_win):
    """Derive palette from the active theme's notification tokens.

    Every theme carries a dedicated notif_* token set; a theme that predates
    them falls back to its generic colours. Win95 dark-golden fallbacks cover
    a theme cache that isn't reachable yet (very early paint).
    """
    raw = {}
    try:
        if main_win is not None:
            cache = getattr(main_win, "_theme_cache", None) or {}
            raw = cache.get("raw_colors", {}) or {}
    except Exception:
        pass

    bg = raw.get("notif_bg", raw.get("bg_main", "#1A0F05"))
    header = raw.get("notif_header", raw.get("btn_bg", "#362812"))
    header_text = raw.get("notif_header_text", raw.get("notif_accent", raw.get("accent", "#D9B340")))
    title = raw.get("notif_title", raw.get("accent", "#D9B340"))
    text = raw.get("notif_text", raw.get("text_main", "#D4B87A"))
    accent = raw.get("notif_accent", raw.get("accent", "#D9B340"))
    border = raw.get("notif_border", raw.get("border_light", "#C0A060"))
    border_dark = raw.get("notif_border_dark", raw.get("border_dark", "#0E0803"))
    info = raw.get("notif_info", blend_hex(text, border, 0.30))
    btn_bg = raw.get("notif_btn_bg", header)
    btn_text = raw.get("notif_btn_text", accent)
    btn_pressed = raw.get("notif_btn_pressed", blend_hex(header, border, 0.45))

    return {
        "bg": bg,
        "header": header,
        "header_text": header_text,
        "title": title,
        "text": text,
        "accent": accent,
        "border": border,
        "border_dark": border_dark,
        "info": info,
        "btn_bg": btn_bg,
        "btn_text": btn_text,
        "btn_pressed": btn_pressed,
    }


class TimerToast(QWidget):
    """One popup per fired timer. Stacks upward if several land at once.
    Styled with classic Vintage Win95 3D bevels & active theme colors.
    """

    _open: list[TimerToast] = []

    def __init__(self, main_win, timer, on_snooze=None, on_dismiss=None):
        super().__init__(None)
        self.main_win = main_win
        self.timer_obj = timer
        self.on_snooze = on_snooze
        self.on_dismiss = on_dismiss
        lang = getattr(main_win, "_current_lang", "EN")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        p = _get_toast_palette(main_win)
        accent = timer.display_color() if hasattr(timer, "display_color") else p["title"]

        self.setObjectName("TimerToast")
        self.setStyleSheet(f"""
            QWidget#TimerToast {{
                background-color: {p['bg']};
                color: {p['text']};
                border-top: 2px solid {p['border']};
                border-left: 2px solid {p['border']};
                border-right: 2px solid {p['border_dark']};
                border-bottom: 2px solid {p['border_dark']};
            }}
            QWidget#HeaderBar {{
                background-color: {p['header']};
                border-bottom: 1px solid {p['border_dark']};
            }}
            QLabel#HeaderTitle {{
                color: {p['header_text']};
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton#CloseBtn {{
                background-color: {p['btn_bg']};
                color: {p['btn_text']};
                border-top: 1px solid {p['border']};
                border-left: 1px solid {p['border']};
                border-right: 1px solid {p['border_dark']};
                border-bottom: 1px solid {p['border_dark']};
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                border-radius: 0px;
            }}
            QPushButton#CloseBtn:pressed {{
                border-top: 1px solid {p['border_dark']};
                border-left: 1px solid {p['border_dark']};
                border-right: 1px solid {p['border']};
                border-bottom: 1px solid {p['border']};
                background-color: {p['btn_pressed']};
            }}
            QLabel#TitleLbl {{
                color: {p['title']};
                font-weight: bold;
                font-size: 12px;
            }}
            QLabel#DescLbl {{
                color: {p['text']};
                font-size: 11px;
            }}
            QLabel#InfoLbl {{
                color: {p['info']};
                font-size: 10px;
            }}
            QPushButton.toast-btn {{
                background-color: {p['btn_bg']};
                color: {p['btn_text']};
                border-top: 2px solid {p['border']};
                border-left: 2px solid {p['border']};
                border-right: 2px solid {p['border_dark']};
                border-bottom: 2px solid {p['border_dark']};
                padding: 2px 7px;
                font-size: 11px;
                border-radius: 0px;
            }}
            QPushButton.toast-btn:hover {{
                background-color: {blend_hex(p['btn_bg'], p['border'], 0.18)};
            }}
            QPushButton.toast-btn:pressed {{
                border-top: 2px solid {p['border_dark']};
                border-left: 2px solid {p['border_dark']};
                border-right: 2px solid {p['border']};
                border-bottom: 2px solid {p['border']};
                background-color: {p['btn_pressed']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Win95 Vintage Header Bar ---
        header = QWidget()
        header.setObjectName("HeaderBar")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(6, 2, 4, 2)
        h_lay.setSpacing(4)

        hdr_title = QLabel(tr("Timer Notification", lang))
        hdr_title.setObjectName("HeaderTitle")
        h_lay.addWidget(hdr_title, 1)

        btn_close_x = QPushButton("✕")
        btn_close_x.setObjectName("CloseBtn")
        btn_close_x.setFixedSize(16, 16)
        btn_close_x.setToolTip(tr("Dismiss", lang))
        btn_close_x.clicked.connect(self.close)
        h_lay.addWidget(btn_close_x)

        root.addWidget(header)

        # --- Body Area ---
        body = QWidget()
        b_lay = QHBoxLayout(body)
        b_lay.setContentsMargins(0, 0, 0, 0)
        b_lay.setSpacing(0)

        # Urgency Indicator
        ind = QWidget()
        ind.setFixedWidth(6)
        ind.setStyleSheet(f"background-color: {accent}; border-right: 1px solid {p['border_dark']};")
        b_lay.addWidget(ind)

        main_body = QWidget()
        mb_lay = QVBoxLayout(main_body)
        mb_lay.setContentsMargins(10, 8, 10, 8)
        mb_lay.setSpacing(4)

        title = QLabel(timer.name)
        title.setObjectName("TitleLbl")
        mb_lay.addWidget(title)

        if timer.description:
            desc = QLabel(timer.description)
            desc.setObjectName("DescLbl")
            desc.setWordWrap(True)
            desc.setMaximumWidth(320)
            mb_lay.addWidget(desc)

        when = QLabel(tr("Time's up", lang))
        when.setObjectName("InfoLbl")
        when.setStyleSheet(f"color: {p['accent']};")
        mb_lay.addWidget(when)

        row = QHBoxLayout()
        row.setSpacing(4)
        # W2-006: a Snooze button is only honest when the owner gave us a
        # callback that will actually accept the object. Test probes and
        # delete-after-fire timers get no Snooze controls at all.
        if callable(self.on_snooze):
            for mins in _SNOOZE_CHOICES:
                b = QPushButton(f"+{mins}m")
                b.setProperty("class", "toast-btn")
                b.setToolTip(tr("Snooze", lang))
                b.clicked.connect(lambda _c, m=mins: self._snooze(m))
                row.addWidget(b)
        row.addStretch(1)
        btn_ok = QPushButton(tr("Dismiss", lang))
        btn_ok.setProperty("class", "toast-btn")
        btn_ok.setToolTip(tr(
            "Acknowledge the passed event — the red passed-event alert clears.",
            lang))
        btn_ok.clicked.connect(self._dismiss)
        row.addWidget(btn_ok)
        mb_lay.addLayout(row)
        b_lay.addWidget(main_body)

        root.addWidget(body)

        # Apply non-antialiased crisp rendering for Vintage look
        strat = QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias
        for w in self.findChildren((QLabel, QPushButton)):
            f = w.font()
            f.setStyleStrategy(strat)
            w.setFont(f)

        self.adjustSize()
        self._place()

        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.timeout.connect(self.close)
        self._auto.start(_AUTO_CLOSE_MS)

        TimerToast._open.append(self)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        """Click the toast to dismiss it.

        Reported as "the test notification is not clickable and removable":
        the ✕ and OK buttons existed, but nothing happened when the body
        itself was clicked, which is what everyone tries first on a toast.
        Child widgets get the event before this, so the buttons keep their
        own behaviour — only the background dismisses.
        """
        self.close()
        event.accept()

    @classmethod
    def _live_toasts(cls):
        """Open toasts that still exist.

        A toast destroyed without its closeEvent leaves a dangling entry, and
        the stack offset below is a SUM over this list: a few stale entries
        push the next toast up and off the screen, where it can be neither
        seen nor clicked nor closed.
        """
        alive = []
        for t in cls._open:
            try:
                if not sip.isdeleted(t) and not t.isHidden():
                    alive.append(t)
            except RuntimeError:
                continue
        cls._open[:] = [t for t in cls._open if not sip.isdeleted(t)]
        return alive

    @classmethod
    def close_for_main(cls, main_win):
        """Close every open toast owned by ``main_win`` (profile switch).

        An old profile's toast must not stay up mutating the new profile's
        data when its Snooze button is clicked.
        """
        for t in list(cls._open):
            try:
                if not sip.isdeleted(t) and t.main_win is main_win:
                    t.close()
            except RuntimeError:
                continue

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
        # Bound the stack: once the toasts would exceed the screen height,
        # retire the OLDEST first — overlapping toasts hide each other's
        # Snooze/Dismiss controls and become impossible to dismiss.
        live = self._live_toasts()
        need = self.height() + 8
        available = area.height() - 2 * _MARGIN
        while live and sum(t.height() + 8 for t in live) + need > available:
            oldest = live.pop(0)
            oldest.close()
        # Collapse: surviving toasts shift DOWN to fill the retired slots, so
        # the new toast lands above the one below it instead of on top of it.
        y_cursor = area.bottom() - _MARGIN
        for t in reversed(live):
            y_cursor -= t.height()
            t.move(t.x(), max(area.top(), y_cursor))
            y_cursor -= 8
        x = area.right() - self.width() - _MARGIN
        y = area.bottom() - self.height() - _MARGIN \
            - sum(t.height() + 8 for t in live)
        # Never off-screen: a toast the user cannot reach is a toast they
        # cannot dismiss, and the stack offset is unbounded by nature.
        x = max(area.left(), min(x, area.right() - self.width()))
        y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)

    def _dismiss(self):
        """The explicit Dismiss button: acknowledge, then close.

        Deliberately different from the ✕ / body-click / auto-close paths:
        those only remove the popup, while the passed-event red alert on the
        date label keeps nagging ("do not forget"). Dismiss is the
        acknowledgement that clears it — wired through ``on_dismiss``.
        """
        try:
            if self.on_dismiss:
                self.on_dismiss(self.timer_obj)
        finally:
            self.close()

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


def show_toast(main_win, timer, on_snooze=None, on_dismiss=None):
    """Create and show a toast; returns it (or None if the UI can't)."""
    try:
        toast = TimerToast(main_win, timer, on_snooze=on_snooze,
                           on_dismiss=on_dismiss)
        toast.show()
        toast.raise_()
        return toast
    except Exception:
        from fastprompter.core.logging import logger
        logger.debug("timer toast failed to show")
        return None

