"""A stable, readable hover card for the AI-limit top-bar gauge (T-1242).

Why this exists
---------------
``LimitGauges`` used to drive a native ``QToolTip``: ``Enter``/``ToolTip``
called ``QToolTip.showText`` and ``Leave`` called ``QToolTip.hideText``.
The gauge is a few pixels tall, so the moment the pointer moved OFF the
gauge and TOWARDS the tooltip it wanted to read, ``Leave`` fired and the
tooltip vanished.  The panel was structurally unreadable -- no tooltip
delay, font or HTML tweak can fix that, because a native tooltip is not
something the pointer is allowed to enter.

So the interaction model changes instead: an application-owned frameless
widget that the pointer may enter, with a small grace interval so travelling
between the gauge and the card never closes it.

The card renders the CURRENT service snapshot that the caller hands it.  It
performs no I/O of its own and never triggers a provider request.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

#: Milliseconds the card stays open after the pointer leaves BOTH surfaces.
#: Long enough to cross the gap between a 12px gauge and the card below it,
#: short enough that the card never feels stuck.
HIDE_GRACE_MS = 300

#: Hard cap on the rendered width.  Freebuff contributes many model names;
#: without this the panel grows into a 1200px horizontal banner.
MAX_WIDTH = 660

#: The card may never eat more than this much vertical space; beyond it the
#: content scrolls inside the card instead of running off the screen.
MAX_HEIGHT = 620


class LimitHoverCard(QFrame):
    """Frameless, non-focus-stealing panel anchored under an anchor widget."""

    def __init__(self, anchor: QWidget) -> None:
        # Tool + Frameless: no taskbar entry, no title bar, and -- unlike
        # Qt.WindowType.ToolTip -- it still receives enter/leave events, which
        # is the entire point.
        super().__init__(None, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self._anchor = anchor
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("LimitHoverCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)

        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(False)
        self._label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction)

        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._scroll)

        #: While the card is OPEN its width may only GROW.  The panel is
        #: re-rendered every second (live reset countdown), and a countdown
        #: that goes "1h 2m" -> "1h 1m" changes the measured text advance by
        #: a pixel or two.  Re-fitting to that made the open card twitch
        #: horizontally once per second.  Growing-only keeps the geometry
        #: still; the floor is dropped when the card closes.
        self._width_floor = 0
        #: Session geometry (T-1242 spec 18/21): pinned at SHOW, never moved
        #: by a content/countdown refresh.  ``_session_anchor_global`` is the
        #: anchor's mapped origin at show time; the card only re-anchors
        #: when the anchor's top-level WINDOW actually moves (a real user
        #: action), never because a per-second re-render re-fitted the
        #: gauge by a pixel.
        self._session_x: int | None = None
        self._session_y: int | None = None
        self._session_anchor_global: QPoint | None = None

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(HIDE_GRACE_MS)
        self._hide_timer.timeout.connect(self._maybe_hide)

        self._install_filters()

    # -- lifecycle ---------------------------------------------------------

    def _install_filters(self) -> None:
        """Close with the window that owns the gauge; never outlive it."""
        anchor = self._anchor
        if anchor is None:
            return
        try:
            anchor.installEventFilter(self)
            window = anchor.window()
            if window is not None and window is not anchor:
                window.installEventFilter(self)
        except (RuntimeError, TypeError):
            pass

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        # Hide/Close only.  WindowDeactivate is NOT a close trigger: showing
        # this frameless Tool window deactivates the owner on Windows, so
        # reacting to it made the card close itself the instant it appeared.
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.hide_now()
        elif event.type() == QEvent.Type.Move and self.isVisible():
            # Re-anchor ONLY on a real window move.  A per-second re-render
            # re-fits the gauge's own geometry, which fires Move on the
            # gauge widget too -- chasing that re-introduced the exact
            # one-pixel-per-tick jump this card exists to prevent.
            if self._window_moved_since_session():
                self.reposition()
        return False

    def _window_moved_since_session(self) -> bool:
        """True when the anchor's top-level window moved after the show."""
        recorded = self._session_anchor_global
        if recorded is None or self._anchor is None:
            return False
        try:
            window = self._anchor.window()
            if window is None:
                return False
            current = window.mapToGlobal(QPoint(0, 0))
        except (RuntimeError, TypeError):
            return False
        return (current.x() != recorded.x() or current.y() != recorded.y())

    # -- content -----------------------------------------------------------

    def set_html(self, html: str) -> None:
        """Render a fresh snapshot; safe while the card is open."""
        self._label.setText(html or "")
        self._label.adjustSize()
        self._resize_to_content()

    def _resize_to_content(self) -> None:
        """Fit the content, and never clip a column behind a scrollbar.

        The first version added a flat 26 px of chrome, so as soon as a
        scrollbar appeared it ate that margin and the right-hand column was
        cut off (reported against the reset times).  The bars are measured
        instead of guessed.

        Session contract (T-1242 spec 18/20): while the card is open its
        width NEVER shrinks -- ``width = max(initial, later required)`` -- so
        a countdown that gains/loses a digit cannot move the right edge once
        per second.  Height follows the content freely; the position is
        corrected once, deterministically, if a taller card would leave the
        screen.
        """
        hint = self._label.sizeHint()
        margins = self.layout().contentsMargins()
        chrome_w = margins.left() + margins.right() + 4
        chrome_h = margins.top() + margins.bottom() + 4
        bar_w = self._scroll.verticalScrollBar().sizeHint().width()
        bar_h = self._scroll.horizontalScrollBar().sizeHint().height()

        height = hint.height() + chrome_h
        width = hint.width() + chrome_w
        if height > MAX_HEIGHT:
            height = MAX_HEIGHT
            width += bar_w              # room for the vertical scrollbar
        if width > MAX_WIDTH:
            width = MAX_WIDTH
            height = min(MAX_HEIGHT, height + bar_h)
        width = max(160, width)
        previous_height = self.height()
        if self.isVisible():
            # Open card: never shrink under a per-second re-render.
            width = max(width, self._width_floor)
        self._width_floor = width
        self.setFixedSize(width, max(40, height))
        if self.isVisible() and self._session_y is not None:
            self._keep_session_card_on_screen(previous_height)

    # -- placement ---------------------------------------------------------

    def _keep_session_card_on_screen(self, previous_height: int) -> None:
        """One deterministic vertical correction for a taller card.

        Content refreshes may change HEIGHT (spec 19) but never move X.  If
        the card no longer fits below the anchor it flips ONCE above and
        stays there for the rest of the session -- no flicker per tick.
        """
        x = self.x()
        y = self.y()
        if self._session_x is not None:
            x = self._session_x
        screen = QApplication.screenAt(QPoint(x, y)) \
            or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        # Growing width on a right-clamped card keeps its LEFT edge: moving
        # X is forbidden mid-session, so only a genuinely off-screen card is
        # pulled back once.
        if x + self.width() > area.right() - 2:
            x = area.right() - self.width() - 2
            self._session_x = x
        if y + self.height() > area.bottom():
            if (previous_height <= self.height()
                    and self._session_y is not None
                    and y > area.top() + 2):
                return                  # already flipped above: stay put
            try:
                above = self._anchor.mapToGlobal(QPoint(0, 0)).y()
            except (RuntimeError, TypeError):
                above = y
            y = max(area.top() + 2, above - self.height() - 2)
            self._session_y = y
        if x != self.x() or y != self.y():
            self.move(x, y)

    def reposition(self) -> None:
        """Anchor below the gauge, kept inside the screen it is shown on."""
        anchor = self._anchor
        if anchor is None:
            return
        try:
            origin = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        except (RuntimeError, TypeError):
            return
        x, y = origin.x(), origin.y()
        screen = QApplication.screenAt(origin) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 2, min(x, area.right() - self.width() - 2))
            if y + self.height() > area.bottom():
                # Not enough room below: flip above the gauge.
                try:
                    above = anchor.mapToGlobal(QPoint(0, 0)).y()
                except (RuntimeError, TypeError):
                    above = y
                y = max(area.top() + 2, above - self.height() - 2)
        self.move(x, y)
        # Pin the session geometry at the moment of the initial show.
        self._session_x = x
        self._session_y = y
        try:
            window = anchor.window()
            self._session_anchor_global = (
                window.mapToGlobal(QPoint(0, 0)) if window is not None
                else None)
        except (RuntimeError, TypeError):
            self._session_anchor_global = None

    # -- show / hide with grace -------------------------------------------

    def show_card(self, html: str) -> None:
        """Show (or refresh) the card without stealing focus."""
        self._hide_timer.stop()
        if not self.isVisible():
            self._width_floor = 0     # fresh hover: fit the content again
            self._session_x = None
            self._session_y = None
            self._session_anchor_global = None
        self.set_html(html)
        if not self.isVisible():
            self.reposition()         # ONE placement for the whole session
            self._session_x = self.x()
            self._session_y = self.y()
            try:
                window = self._anchor.window() if self._anchor else None
                self._session_anchor_global = (
                    window.mapToGlobal(QPoint(0, 0)) if window is not None
                    else None)
            except (RuntimeError, TypeError):
                self._session_anchor_global = None
            self.show()
            self.raise_()
            # T-1245: card hidden/nonexistent -> visible. The refresh path
            # (set_html / reposition while already visible) never reaches
            # this branch: it is guarded by the isVisible() probe above, so
            # geometry changes on an open card stay silent.
            try:
                from fastprompter.ui.appearance_sounds import (
                    emit_hover_card_show,
                )
                emit_hover_card_show(
                    self._anchor.window() if self._anchor else None)
            except Exception:
                pass

    def schedule_hide(self) -> None:
        """Start the grace interval; entering either surface cancels it."""
        if self.isVisible():
            self._hide_timer.start()

    def cancel_hide(self) -> None:
        self._hide_timer.stop()

    def hide_now(self) -> None:
        self._hide_timer.stop()
        self._width_floor = 0
        self._session_x = None
        self._session_y = None
        self._session_anchor_global = None
        if self.isVisible():
            self.hide()

    def _pointer_inside(self) -> bool:
        """True while the cursor is over the card OR its anchor gauge."""
        position = QCursor.pos()
        for widget in (self, self._anchor):
            if widget is None:
                continue
            try:
                if not widget.isVisible():
                    continue
                top_left = widget.mapToGlobal(QPoint(0, 0))
            except (RuntimeError, TypeError):
                continue
            if (top_left.x() <= position.x() <= top_left.x() + widget.width()
                    and top_left.y() <= position.y()
                    <= top_left.y() + widget.height()):
                return True
        return False

    def _maybe_hide(self) -> None:
        if self._pointer_inside():
            return          # came back before the grace expired
        self.hide()

    # -- Qt events ---------------------------------------------------------

    def enterEvent(self, event):  # noqa: N802 (Qt naming)
        self.cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt naming)
        self.schedule_hide()
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Escape:
            self.hide_now()
            event.accept()
            return
        super().keyPressEvent(event)
