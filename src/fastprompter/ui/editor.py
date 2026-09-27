import os
import random
import re
import subprocess
import sys

from PyQt6 import sip
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QTextBlockUserData,
    QTextCursor,
    QTextFormat,
)
from PyQt6.QtWidgets import QApplication, QTextEdit, QWidget

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr
from fastprompter.ui.edit_guard import edit_block
from fastprompter.ui.markdown_highlighter import QUEUED_BIT, SENT_BIT
from fastprompter.ui.qt_lifetime import weak_qt_callback
from fastprompter.utils.paths import exists_within

# Matches every stamp shape Ctrl+E ever wrote: "17.07 - 04:19",
# "17 Jul - 04:19", optional seconds, optional day-part word prefix.
# The refresh glyph lives on this regex — a stamp format added in
# main.py MUST be reflected here or the glyph silently disappears.
TS_STAMP_LINE_RE = re.compile(
    r"(?:Morning |Day |Evening |Night )?"
    r"(?:\d{2}\.\d{2}|\d{1,2} [A-Za-z]{3}) - \d{2}:\d{2}(?::\d{2})?(?: [AP]M)?"
)
MD_IMAGE_RE = re.compile(r'!\[.*?\]\((.*?)\)')

# File types the editor can meaningfully load as plain text
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".xml", ".yaml", ".yml", ".csv", ".ini", ".cfg", ".conf",
    ".log", ".bat", ".sh", ".ps1", ".sql", ".rb", ".php", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".swift",
    ".kt", ".scala", ".pl", ".lua", ".r", ".m", ".mm", ".tex",
    ".rst", ".toml", ".lock", ".env", ".gitignore", ".editorconfig",
    ".properties", ".gradle", ".sln", ".csproj", ".vcxproj",
}


def _read_text_file(path):
    """Read a file as UTF-8 text for pasting into the editor."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def describe_clipboard_mime(mime):
    """Bounded metadata about one clipboard payload — never its CONTENT.

    T-1269C append. NEW seeds a silo through
    ``SnippetOpsMixin._clipboard_text_for_new_silo`` (``clipboard.text()``),
    while Ctrl+V goes through ``insertFromMimeData``, which selects its branch
    from the FORMATS present. A clipboard carrying text PLUS an image or URL
    payload can therefore seed a new silo and still paste nothing, so the
    moment of failure needs this shape recorded: which representations exist,
    how long the text is, and how many URLs are local — lengths, flags and
    counts only, never the text itself.
    """
    info = {
        "has_text": False,
        "text_length": 0,
        "text_stripped_length": 0,
        "has_urls": False,
        "url_count": 0,
        "local_url_count": 0,
        "any_url_is_local": False,
        "has_image": False,
        "formats": [],
    }
    if mime is None:
        return info
    try:
        info["has_text"] = bool(mime.hasText())
        if info["has_text"]:
            text = mime.text() or ""
            info["text_length"] = len(text)
            info["text_stripped_length"] = len(text.strip())
    except Exception:
        pass
    try:
        info["has_urls"] = bool(mime.hasUrls())
        if info["has_urls"]:
            urls = mime.urls() or []
            info["url_count"] = len(urls)
            info["local_url_count"] = sum(1 for u in urls if u.isLocalFile())
            info["any_url_is_local"] = bool(info["local_url_count"])
    except Exception:
        pass
    try:
        info["has_image"] = bool(mime.hasImage())
    except Exception:
        pass
    try:
        # Bounded: some providers expose dozens of platform formats.
        info["formats"] = [str(f) for f in (mime.formats() or [])][:12]
    except Exception:
        pass
    return info


def _mime_urls(mime):
    """Return a safe URL snapshot for malformed/custom MIME providers."""
    try:
        return list(mime.urls() or [])
    except Exception:
        return []


def _mime_text(mime):
    """Return MIME text without allowing a broken provider to abort paste."""
    try:
        return mime.text() or ""
    except Exception:
        return ""


def _paste_record(branch, mime_info, before, after, fallback):
    """One paste attempt, as the evidence the acceptance asks for.

    Carries the branch that ran, whether the KEY path reached the editor and
    called ``self.paste()``, whether ``insertFromMimeData`` ran at all, and
    the document revision on both sides of the attempt — so "sound played and
    nothing appeared" is decided by the document, not by the cue.
    """
    record = dict(after)
    record.update({
        "branch": branch,
        "document_changed": (before.get("document_revision")
                             != after.get("document_revision")),
        "document_revision_before": before.get("document_revision"),
        "document_revision_after": after.get("document_revision"),
        "text_fallback_used": bool(fallback),
        "mime": mime_info,
    })
    for key in (
        "document_id", "silo_document_id", "cursor_position",
        "has_selection", "editor_visible", "editor_enabled",
        "editor_read_only", "focus_widget", "focus_widget_id",
        "preview_mode", "silo_view_page",
        "document_owned_by_active_silo",
    ):
        record[f"{key}_before"] = before.get(key)
    return record


def classify_paste_failure(record):
    """Name which of the three observed failure classes a record belongs to.

    T-1269 append A1 asks the diagnostics to DISTINGUISH the classes, not to
    guess at them:

    * ``key_routing``             the Ctrl+V key never reached this editor's
                                  paste route -- no ``paste()`` call to blame,
                                  so the failure is outside the app (another
                                  window, a shortcut owner, an external tool);
    * ``clipboard_ownership_race`` the key arrived, but the OS clipboard
                                  GENERATION moved while the paste ran, so the
                                  payload consumed may be an older item the
                                  operator never copied last;
    * ``fastprompter_paste_route`` the key arrived, the route ran, and the
                                  document still did not change;
    * ``None``                    no failure evidence: the document changed, or
                                  a branch deliberately consumed the payload.

    Every answer comes from the record itself, so the working attempt and the
    failing one stay comparable field for field.
    """
    if not record.get("key_path_reached"):
        return "key_routing"
    if record.get("clipboard_changed_during_paste"):
        return "clipboard_ownership_race"
    if record.get("document_changed") or record.get("branch_settled"):
        return None
    if not record.get("paste_called"):
        return "key_routing"
    return "fastprompter_paste_route"


def _draw_horizontal_rule(painter, hr_color, y_pos, width):
    """Draw a horizontal rule line at the given y position."""
    margin = 4
    painter.setPen(QColor(hr_color))
    painter.drawLine(margin, y_pos, width - margin, y_pos)
    painter.setPen(QColor(0, 0, 0, 30))
    painter.drawLine(margin, y_pos + 2, width - margin, y_pos + 2)


def _task_checkbox_rect(marker_rect):
    marker = marker_rect.toRect() if isinstance(marker_rect, QRectF) else QRect(marker_rect)
    size = max(9, min(14, round(marker.height() * 0.72)))
    size = min(size, marker.width(), marker.height())
    return QRect(
        marker.x() + (marker.width() - size) // 2,
        marker.y() + (marker.height() - size) // 2,
        size,
        size,
    )


def _paint_task_checkbox(painter, rect, checked):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.fillRect(rect, QColor("#4a9a4a" if checked else "#222222"))
    painter.setPen(QPen(QColor("#202020"), 1))
    painter.drawLine(rect.topLeft(), rect.topRight())
    painter.drawLine(rect.topLeft(), rect.bottomLeft())
    painter.setPen(QPen(QColor("#75c475" if checked else "#666666"), 1))
    painter.drawLine(rect.bottomLeft(), rect.bottomRight())
    painter.drawLine(rect.topRight(), rect.bottomRight())
    if checked:
        inset = max(2, rect.width() // 5)
        check_left = rect.left() + inset + 1
        mid_x = rect.left() + max(4, rect.width() * 2 // 5 + 1)
        mid_y = rect.top() + rect.height() * 2 // 3
        check_pen = QPen(QColor("#ffffff"), 2 if rect.width() >= 12 else 1)
        check_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        check_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(check_pen)
        painter.drawLine(check_left, rect.center().y(), mid_x, mid_y)
        painter.drawLine(mid_x, mid_y, rect.right() - inset, rect.top() + inset)
    painter.restore()


# How much of the gutter belongs to the mark widget. Left of this a click
# cycles the line mark; right of it the margin behaves like Word's, where
# the cursor mirrors and a click takes the whole line. Widenended 16 -> 24
# so the mark column is an easy target rather than a pixel hunt (the painted
# square is allowed to be smaller than the hit zone).
MARK_ZONE_PX = 24

# The curated mark palette. IDs are persistent (they ride in userState and in
# saved view metadata), so old saved marks keep loading; the SHAPES were
# retired -- every mark now paints as the same object, a plain filled square
# box, and only the colour carries the distinction. Colours are fixed
# high-contrast hexes hand-checked against both light and dark gutter
# backgrounds (Win95 crisp fill, no alpha, no antialiasing), not generated
# from the theme.
MARK_PALETTE = {
    1: ("#3DA43D", "green"),    # strong leaf green, clear on light and dark
    2: ("#D9483B", "red"),      # solid brick red
    3: ("#E0A400", "yellow"),   # amber/yellow, dark enough to read on white
    4: ("#3D6FD9", "blue"),     # medium blue
    5: ("#A26FD9", "purple"),   # violet
}

# Marks with the mixed shapes/dots of the old presentation map onto the
# same-ID colour square: 1 was already a green box, 2 (red dot) and 3
# (yellow rhombus) keep their colour, 4 (blue square) keeps its colour, and
# 5 is the new slot. No saved id changes meaning.
_RANDOM_MARK_IDS = tuple(MARK_PALETTE)

_MARGIN_CURSOR = None


def reset_margin_cursor():
    """Drop the cached shape, so a changed cursor set is picked up."""
    global _MARGIN_CURSOR
    _MARGIN_CURSOR = None


def margin_cursor():
    """Word's mirrored margin arrow.

    The whole point of the shape is that it is the ordinary arrow flipped -
    that is the signal people already read as "click here takes the entire
    line" - so it is the user's OWN arrow, mirrored, whenever the cursor set
    can supply one. Drawing a polygon instead put a heavier, differently
    shaped arrow next to theirs, which read as a foreign cursor rather than
    a reversed one.

    The hand-drawn shape is only the fallback for when there is no set to
    borrow from: Qt has no stock cursor pointing up and to the right.
    """
    global _MARGIN_CURSOR
    if _MARGIN_CURSOR is not None:
        return _MARGIN_CURSOR

    try:
        from fastprompter.ui.cursor_theme import mirrored_arrow
        borrowed = mirrored_arrow()
    except Exception:
        from fastprompter.core.logging import logger
        logger.debug("could not mirror the set's arrow", exc_info=True)
        borrowed = None
    if borrowed is not None:
        _MARGIN_CURSOR = borrowed
        return _MARGIN_CURSOR

    w = h = 20
    pix = QPixmap(w, h)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    try:
        # no antialiasing: UI.md wants crisp Win95 edges everywhere
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        body = [
            QPoint(18, 2), QPoint(18, 14), QPoint(14, 11), QPoint(11, 17),
            QPoint(7, 15), QPoint(10, 9), QPoint(5, 8),
        ]
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(body)
    finally:
        painter.end()
    # hot spot at the tip, so the click lands on the line being pointed at
    _MARGIN_CURSOR = QCursor(pix, 18, 2)
    return _MARGIN_CURSOR


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setMouseTracking(True)
        self.hover_y = -1

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def _in_margin(self, x):
        """Marks own the left strip only while marks are actually on."""
        if self.editor.main_win.data.get("line_marks", "False") != "True":
            return True
        return x >= MARK_ZONE_PX

    def mouseReleaseEvent(self, event):
        self.editor._gutter_anchor_block = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event):
        if (self._in_margin(event.pos().x())
                and event.button() == Qt.MouseButton.LeftButton):
            self.editor.margin_select_line(event.pos().y(), extend=False)
            return
        self.editor.line_number_area_mouse_press_event(event)

    def mouseMoveEvent(self, event):
        self.hover_y = event.pos().y()
        self.setCursor(margin_cursor() if self._in_margin(event.pos().x())
                       else Qt.CursorShape.ArrowCursor)
        # dragging down the margin sweeps whole lines, as in Word
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self.editor._gutter_anchor_block is not None:
                self.editor.margin_select_line(event.pos().y(), extend=True)
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_y = -1
        self.update()
        super().leaveEvent(event)


class _BlockData(QTextBlockUserData):
    """Everything carried BY a block rather than by its line number.

    Storing this against line NUMBERS would smear it across the wrong lines
    the moment anything is inserted or deleted above. Qt moves a block's
    userData with the block, so a mark stays on the text the user actually
    touched.

    A block has exactly ONE userData slot, so everything that wants to ride
    along has to share this object. Edit heat was here first; the watcher
    queue anchor joined it. Replacing the object wholesale - which is what
    `setUserData(_LineHeat(ts))` used to do - would silently drop whichever
    field the caller did not know about.
    """

    __slots__ = ("ts", "queue_id", "fold_count", "word_count")

    def __init__(self, ts=None, queue_id=""):
        super().__init__()
        self.ts = ts
        self.queue_id = queue_id
        self.fold_count = 0
        self.word_count = -1


# Kept so existing callers and tests can still say _LineHeat(ts).
_LineHeat = _BlockData


# Windows set-1 scan codes for the letter and digit rows. A scan code is the
# PHYSICAL key: it does not change with the keyboard layout, while
# QKeyEvent.key() does. Without this, Ctrl+B on a Russian layout reports
# Key_I and fired italic instead of bold - the wrong command, with nothing
# logged. Only these two rows are mapped because only they carry shortcuts;
# anything else falls back to whatever Qt reported.
_SCAN_TO_KEY = {}
if sys.platform == "win32":
    _SCAN_TO_KEY = {
        0x1E: Qt.Key.Key_A, 0x30: Qt.Key.Key_B, 0x2E: Qt.Key.Key_C,
        0x20: Qt.Key.Key_D, 0x12: Qt.Key.Key_E, 0x21: Qt.Key.Key_F,
        0x22: Qt.Key.Key_G, 0x23: Qt.Key.Key_H, 0x17: Qt.Key.Key_I,
        0x24: Qt.Key.Key_J, 0x25: Qt.Key.Key_K, 0x26: Qt.Key.Key_L,
        0x32: Qt.Key.Key_M, 0x31: Qt.Key.Key_N, 0x18: Qt.Key.Key_O,
        0x19: Qt.Key.Key_P, 0x10: Qt.Key.Key_Q, 0x13: Qt.Key.Key_R,
        0x1F: Qt.Key.Key_S, 0x14: Qt.Key.Key_T, 0x16: Qt.Key.Key_U,
        0x2F: Qt.Key.Key_V, 0x11: Qt.Key.Key_W, 0x2D: Qt.Key.Key_X,
        0x15: Qt.Key.Key_Y, 0x2C: Qt.Key.Key_Z,
        0x02: Qt.Key.Key_1, 0x03: Qt.Key.Key_2, 0x04: Qt.Key.Key_3,
        0x05: Qt.Key.Key_4, 0x06: Qt.Key.Key_5, 0x07: Qt.Key.Key_6,
        0x08: Qt.Key.Key_7, 0x09: Qt.Key.Key_8, 0x0A: Qt.Key.Key_9,
        0x0B: Qt.Key.Key_0,
    }


def block_data(block, create=False):
    """The block's payload, optionally creating it.

    Always go through this rather than setUserData(): it preserves the
    fields the caller is not interested in.
    """
    data = block.userData()
    if isinstance(data, _BlockData):
        return data
    if not create:
        return None
    data = _BlockData()
    block.setUserData(data)
    return data


def stamp_heat(block, ts):
    """Set the edit timestamp without disturbing the queue anchor."""
    data = block_data(block, create=True)
    if data is not None:
        data.ts = ts
    return data


# T-1269C append: chords the EDITOR owns because Qt's own editing machinery
# binds them (Select All / Copy / Paste / Cut). A profile may map one of these
# to a FastPrompter command; `keyPressEvent` runs the configurable hotkeys
# BEFORE the editing four, so a user mapping silently stole the key and the
# symptom was "Ctrl+V does nothing" with no sound and nothing logged. The
# editing keys win deterministically and the conflict is reported once.
_RESERVED_EDITING_SEQUENCES = ("Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X")


class VaultTextEdit(QTextEdit):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.setTabChangesFocus(False)
        self.document().setUndoRedoEnabled(True)
        self._right_drag_start = None
        self._dragged = False
        # T-1269C: explicit state for one synchronous Ctrl+V attempt. These
        # flags keep route evidence separate from sound playback and from
        # insertFromMimeData calls caused by drag/drop.
        self._paste_key_path = False
        self._paste_paste_called = False
        self._paste_insert_reached = False
        self._paste_diagnostics_active = False

        self.line_number_area = LineNumberArea(self)
        self.document().documentLayout().documentSizeChanged.connect(self.update_line_number_area_width)
        self.verticalScrollBar().valueChanged.connect(self.line_number_area.update)
        self._last_scroll_value = 0
        self.verticalScrollBar().valueChanged.connect(self._watch_scroll_reset)
        # the text moves under a stationary mouse, so the hovered line has to
        # be re-derived on scroll as well as on mouse move
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.rehover_from_pointer())
        self.document().contentsChange.connect(self._stamp_edited_blocks)
        self.textChanged.connect(self.refresh_extra_selections)
        self.textChanged.connect(self.line_number_area.update)
        self.cursorPositionChanged.connect(self.line_number_area.update)
        self.cursorPositionChanged.connect(self._sync_conceal_reveal)
        self._last_hover_pos = QPoint(-10000, -10000)
        self._hover_block = None
        self._gutter_anchor_block = None
        self._doc_has_checkbox = False
        self._doc_has_code = False
        self._code_sel_dirty = True  # code-panel selections need a (re)build
        self._code_selections_cache = []  # last code-panel build, reused until dirty
        self._opener_cache = None  # set of opener block numbers, invalidated on text change
        self._pending_link = None  # (QUrl, QPoint) recorded on press in Live Preview
        # Persistent Ctrl+click word selections: list of QTextCursor objects.
        # Toggle with Ctrl+click; clear all with Ctrl+triple-click on any
        # word. Cursors track their own document and stay valid across edits
        # and silo switches (each silo keeps its own pins).
        self._pinned_cursors = []
        # consecutive Ctrl+left clicks within the double-click interval (for
        # triple-click detection — Qt never delivers a "triple click" event).
        self._ctrl_click_ts = None
        self._ctrl_click_pos = None
        self._ctrl_click_count = 0
        # T-815: instead of invalidating the whole opener cache on EVERY
        # keystroke (which forces a full rescan on the next fence query),
        # reconcile edits incrementally and only drop the cache when a fence
        # line is actually touched.
        self.document().contentsChange.connect(self._reconcile_edits)
        QTimer.singleShot(0, weak_qt_callback(
            self, type(self)._refresh_checkbox_flag))

        # Debounced state capture: scroll-only browsing (no typing) also
        # persists the view position, cursor, and marks. Fires 2 s after
        # the last scroll or resize event.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(2000)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        self.verticalScrollBar().valueChanged.connect(self._kick_idle_timer)

    def _first_visible_block(self):
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return None
        cursor = self.cursorForPosition(QPoint(0, 0))
        if cursor.isNull():
            return None
        blk = cursor.block()
        return blk if blk.isValid() else None

    def _refresh_checkbox_flag(self, first=None, last=None):
        """Update checkbox/code flags. Early-exit when both already True.

        These flags control gutter auto-show for code blocks. Once a
        document has a checkbox or code fence there is nothing new to discover — the
        flags stay True. Deleting the last such line leaves the gutter
        marginally wider than needed until reload, which is invisible in
        practice and saves scanning ~200 blocks on every keystroke for the
        lifetime of the edit session.

        T-815: when ``first``/``last`` block numbers are supplied (from the
        incremental ``_reconcile_edits`` path) only that changed range is
        scanned — an ordinary keystroke no longer walks O(total blocks). A
        full scan still runs on document attach (the no-arg SingleShot(0)).
        """
        # Guard SELF first: this runs from QTimer.singleShot(0, ...) and from
        # the contentsChange reconcile, so the editor can be gone by the time
        # it fires and self.document() would then touch a dead C++ object.
        if sip.isdeleted(self):
            return
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return

        # Both flags already set — nothing to find. This is the steady-state
        # for any document that contains a checkbox or code fence.
        if self._doc_has_checkbox and self._doc_has_code:
            return

        if first is None or last is None:
            first = 0
            last = doc.blockCount() - 1
            # Attaching a huge document is navigation, not a license to scan
            # every block synchronously.  Inspect only the first viewport-ish
            # chunk; later edits reconcile their own ranges incrementally.
            try:
                threshold = int(getattr(self.main_win, "_LARGE_DOC_THRESHOLD", 500000))
                block_threshold = int(getattr(
                    self.main_win, "_LARGE_DOC_BLOCK_THRESHOLD", 2000))
            except (AttributeError, TypeError, ValueError):
                threshold = 500000
                block_threshold = 2000
            if (doc.characterCount() >= threshold
                    or doc.blockCount() >= block_threshold):
                last = min(last, 200)
        else:
            last = min(last, doc.blockCount() - 1)

        has_cb = self._doc_has_checkbox  # continue from current state
        has_code = self._doc_has_code

        for i in range(first, last + 1):
            if i >= doc.blockCount():
                break
            txt = doc.findBlockByNumber(i).text()
            if not has_cb and "[" in txt:
                has_cb = True
            if not has_code and txt.lstrip().startswith("```"):
                has_code = True
            if has_cb and has_code:
                break

        changed = False
        if has_cb != self._doc_has_checkbox:
            self._doc_has_checkbox = has_cb
            changed = True
        if has_code != self._doc_has_code:
            self._doc_has_code = has_code
            changed = True
        if changed:
            self.update_line_number_area_width()
        # Store derived flags on the QTextDocument wrapper itself.  The
        # revision makes this a per-document/per-generation cache, and the
        # document owns its metadata without a global id() table that can leak
        # or collide after a wrapper is destroyed.
        try:
            doc._fastprompter_feature_revision = doc.revision()
            doc._fastprompter_has_checkbox = self._doc_has_checkbox
            doc._fastprompter_has_code = self._doc_has_code
        except (AttributeError, RuntimeError):
            pass

    def _reconcile_edits(self, position, removed, added):
        """T-815: incrementally maintain derived block metadata.

        ``contentsChange`` already reports the affected character range
        (``position``/``removed``/``added``), so only the touched blocks need
        re-derivation — not the whole document. A plain edit inside a line
        updates the checkbox/code flags for its block and leaves the opener
        cache and code-panel selections untouched."""
        if sip.isdeleted(self):
            return
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return
        first = doc.findBlock(position)
        last = doc.findBlock(max(position, position + added))
        self._refresh_checkbox_flag(first.blockNumber(), last.blockNumber())

        # A fence line (```` ``` ````) is the only edit that can change code
        # membership or opener parity, so only a fence-touching edit must
        # invalidate them. Everything else keeps the cached state valid.
        fb = first.blockNumber()
        lb = min(last.blockNumber(), doc.blockCount() - 1)
        fence_touched = False
        for i in range(fb, lb + 1):
            if doc.findBlockByNumber(i).text().lstrip().startswith("```"):
                fence_touched = True
                break
        if fence_touched:
            self._opener_cache = None
            self._code_sel_dirty = True

    def _sync_conceal_reveal(self):
        """Tell the highlighter which block the caret is on, so Obsidian-style
        preview can un-hide the markup on just that line."""
        hl = getattr(self.main_win, "highlighter", None) if hasattr(self, "main_win") else None
        if hl is None or sip.isdeleted(hl) or not getattr(hl, "conceal", False):
            return
        if hl.document() is not self.document():
            return                  # highlighter is attached to another silo
        hl.set_reveal_block(self.textCursor().blockNumber())

    def _gutter_active(self):
        """The line-number gutter follows the user's toggle alone — a reliable
        master on/off. (It used to force itself on whenever the document held
        a code block, which made the # toggle appear dead on code silos.)
        Code auto-numbering is opt-in via the 'code_auto_gutter' setting."""
        if not hasattr(self, 'main_win'):
            return False
        if self.main_win.data.get("show_line_numbers", "False") == "True":
            return True
        if (self.main_win.data.get("code_auto_gutter", "False") == "True"
                and self._doc_has_code):
            return True
        return False

    def set_active_document(self, doc):
        hl = getattr(self.main_win, 'highlighter', None)
        if hl and not sip.isdeleted(hl) and hl.document() != doc:
            hl.setDocument(None)
        cur_doc = self.document()
        if cur_doc and not sip.isdeleted(cur_doc):
            try:
                cur_doc.documentLayout().documentSizeChanged.disconnect(self.update_line_number_area_width)
            except Exception:
                pass
            try:
                cur_doc.contentsChange.disconnect(self._stamp_edited_blocks)
            except Exception:
                pass
            try:
                cur_doc.contentsChange.disconnect(self._on_contents_change)
            except Exception:
                pass
            try:
                cur_doc.contentsChange.disconnect(self._reconcile_edits)
            except Exception:
                pass
        self.setDocument(doc)
        self.document().setUndoRedoEnabled(True)
        self._words_dirty = True
        self._aggregate_word_count = None
        # PERF-005: the metadata cache belongs to the new document
        self._invalidate_view_metadata()
        # Each silo is its own QTextDocument, so the heat hook has to follow
        # the swap — connecting once in __init__ only ever stamped the very
        # first document.
        self.document().contentsChange.connect(self._stamp_edited_blocks)
        # NOT a lambda: this used to be `lambda *_a: self.refresh_extra_selections()`,
        # which nothing could ever disconnect. Documents outlive the swap (one
        # per silo), so every switch BACK to a silo stacked another copy on the
        # same document — after N switches one paste fired N identical handlers,
        # and the connection also outlived the editor itself (a dead C++ object
        # reached from a document signal is an access violation, H-406 class).
        self.document().contentsChange.connect(self._on_contents_change)
        # T-815: the incremental reconcile must follow the swap too, and a
        # swapped-in document needs a fresh code-panel rebuild.
        self.document().contentsChange.connect(self._reconcile_edits)
        self._code_sel_dirty = True
        self.refresh_extra_selections()
        self.document().documentLayout().documentSizeChanged.connect(self.update_line_number_area_width)
        self.update_line_number_area_width()
        # The persisted global setting is the authority.  ``self.font()`` can
        # still hold the font of the document we just left (or a style-polish
        # default), which made returning to a silo sporadically render at 11pt
        # while Settings correctly continued to show the user's chosen size.
        configured_font = getattr(self.main_win, "configured_font", None)
        font = configured_font() if callable(configured_font) else self.font()
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        self.setFont(font)
        self.document().setDefaultFont(font)
        # T-1008: every silo swap must resynchronise the highlighter state
        # (large-doc degradation + reveal block) for THIS document, or a big
        # document inherits the previous one's skip state and loses headers.
        # This helper is also the only code allowed to attach the highlighter:
        # attaching here first can make Qt rehighlight a huge document before
        # the helper gets a chance to apply the huge-document guard.
        if hl and not sip.isdeleted(hl):
            sync = getattr(self.main_win, "_sync_live_preview_highlighter", None)
            if callable(sync):
                sync()
        self._opener_cache = None
        cached_revision = getattr(
            doc, "_fastprompter_feature_revision", None)
        if cached_revision == doc.revision():
            self._doc_has_checkbox = bool(getattr(
                doc, "_fastprompter_has_checkbox", False))
            self._doc_has_code = bool(getattr(
                doc, "_fastprompter_has_code", False))
            self.update_line_number_area_width()
        else:
            # Sticky-True flags are only valid for the document they were
            # found on.  A changed document gets one bounded scan; an
            # unchanged warm document reuses the metadata above.
            self._doc_has_checkbox = False
            self._doc_has_code = False
            self._refresh_checkbox_flag()

    def line_number_area_width(self):
        if not self._gutter_active():
            return 0
        digits = 1
        m = max(1, self.document().blockCount())
        while m >= 10:
            m /= 10
            digits += 1
        width = 3 + self.fontMetrics().horizontalAdvance('9') * digits + 10
        if self.main_win.data.get("line_marks", "False") == "True":
            # the mark widget owns the left strip; without this the margin
            # left for Word-style whole-line clicks is only a few pixels
            width = max(width, MARK_ZONE_PX + 14)
        return width

    def update_line_number_area_width(self):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self._kick_idle_timer()

    def _gutter_colors(self):
        """Gutter background and number colour, taken from the theme.

        These used to be hardcoded per theme NAME, and the test was
        `"vintage" in name` - so "Vintage Dark", whose editor background is
        #181818, got the golden-vintage brown #2A1C0A with gold numbers. Any
        theme not named in the chain fell back to a flat grey. Deriving both
        from the active palette means new themes are handled for free.
        """
        from fastprompter.theme.themes import blend_hex

        raw = {}
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache:
                raw = cache.get("raw_colors") or {}
            custom = self.main_win._get_custom_colors()
            if isinstance(custom, dict):
                raw = {**raw, **custom}
        except Exception:
            logger.debug("gutter colours: theme lookup failed", exc_info=True)

        editor_bg = raw.get("bg_text") or raw.get("bg_main")
        text_main = raw.get("text_main")
        if not editor_bg:
            base = self.palette().base().color()
            editor_bg = base.name()
        if not text_main:
            text_main = self.palette().text().color().name()

        # the gutter sits just off the page: a touch lighter on dark themes,
        # a touch darker on light ones, so it reads as a margin either way
        toward = "#ffffff" if QColor(editor_bg).lightness() < 128 else "#000000"
        bg = QColor(blend_hex(editor_bg, toward, 0.08))
        # numbers are deliberately quieter than body text
        numbers = QColor(blend_hex(text_main, editor_bg, 0.45))
        if not bg.isValid():
            bg = self.palette().base().color()
        if not numbers.isValid():
            numbers = QColor("#808080")
        return bg, numbers

    def gutter_rows(self, limit=200):
        """Which blocks get a number, and how tall their row really is.

        Yields ``(block, top, row_height)``. Split out of the paint loop so
        the anti-overlap rule is testable without rendering: numbers used to
        be drawn at every block's top in a box a full font-height tall
        whatever the block's REAL height was, and a block the highlighter
        collapses to 1pt (a `---` rule, an image ref, concealed markup) is
        only ~2px, so its digits landed on top of the next line's. A block
        whose top falls inside the band the previous number already occupies
        is skipped — a 1pt filler row carries no visible text anyway.
        """
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return
        first = self._first_visible_block()
        if not first:
            return
        first_number = first.blockNumber()
        last_number = min(doc.blockCount(), first_number + limit)
        fm_height = self.fontMetrics().height()
        last_bottom = -1
        for block_number in range(first_number, last_number):
            block = doc.findBlockByNumber(block_number)
            if not block.isValid():
                break
            if not block.isVisible():       # folded away
                continue
            rect = self.cursorRect(QTextCursor(block))
            top = int(rect.top())
            if top < last_bottom:
                continue
            last_bottom = top + fm_height
            yield block, top, max(2, min(fm_height, int(rect.height()) or fm_height))

    def line_number_area_paint_event(self, event):
        if not self._gutter_active():
            return
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return
        # Deliberately NO blockCount() bail here: the gutter rows are found by
        # _first_visible_block()/cursorRect over the visible region only, so
        # cost is O(visible), and the old `> 2000 -> return` left large
        # documents with numbers but no marks and no queue stripes.
        painter = QPainter(self.line_number_area)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setFont(self.font())
            bg, text_color = self._gutter_colors()
            painter.fillRect(event.rect(), bg)

            for block, top, row_height in self.gutter_rows():
                block_number = block.blockNumber()
                mark = max(0, block.userState()) & 0xFF
                hover_y = getattr(self.line_number_area, "hover_y", -1)
                is_hovered = hover_y != -1 and top <= hover_y <= top + row_height

                # Fold count badge: when a header is folded, replace the line
                # number with the hidden line count — more useful at a glance.
                fold_bit = max(0, block.userState()) & self.FOLD_BIT
                fc_data = block_data(block) if fold_bit else None
                fold_count = fc_data.fold_count if fc_data else 0
                if fold_count > 0:
                    label = f"{fold_count}L"
                    old_font = painter.font()
                    smaller = QFont(old_font)
                    smaller.setPixelSize(max(7, old_font.pixelSize() - 3))
                    painter.setFont(smaller)
                    painter.setPen(text_color)
                    painter.drawText(
                        2, top, self.line_number_area.width() - 4,
                        self.fontMetrics().height(),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        label)
                    painter.setFont(old_font)
                else:
                    painter.setPen(text_color)
                    painter.drawText(0, top, self.line_number_area.width() - 4,
                                     self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight,
                                     str(block_number + 1))

                marks_enabled = self.main_win.data.get("line_marks", "False") == "True"

                if marks_enabled and (mark > 0 or is_hovered):
                    h = row_height
                    cx = 9
                    cy = top + h // 2
                    # A real box: ~12-14px where the row allows, clamped for
                    # small/collapsed rows. Every mark paints as the SAME
                    # object -- a filled square -- and the colour carries the
                    # distinction, never the shape.
                    size = max(6, min(h - 4, 14))

                    if is_hovered and not mark:
                        # empty-slot affordance: crisp 1px outline of the box
                        # that would appear, no fill
                        painter.setPen(QPen(text_color, 1))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(cx - size//2, cy - size//2, size, size)
                    else:
                        color, _name = MARK_PALETTE.get(mark, MARK_PALETTE[1])
                        painter.setPen(QPen(QColor("#000000"), 1))
                        painter.setBrush(QColor(color))
                        # filled square + crisp dark border, no antialiasing
                        # (Win95 box; drawRect insets by the pen width)
                        painter.drawRect(cx - size//2, cy - size//2, size, size)

                # Queue state, drawn as a stripe down the gutter's right edge
                # rather than a glyph beside the user's mark. Two reasons: it
                # cannot collide with a mark or a digit however wide the
                # gutter gets, and it does not read as a fifth kind of user
                # mark - these are the watcher's, not the user's.
                #
                # Deliberately NOT gated on marks_enabled: that setting is
                # about the user's own margin marks. Hiding queue state with
                # it would leave a silo whose lines are queued looking
                # identical to one that is not.
                queue_state = max(0, block.userState()) & (QUEUED_BIT | SENT_BIT)
                if queue_state:
                    stripe = QColor("#46b98a") if queue_state & SENT_BIT \
                        else QColor("#6aa9ff")
                    h = row_height
                    width = self.line_number_area.width()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(stripe)
                    painter.drawRect(width - 3, top + 1, 2, max(1, h - 2))

        finally:
            painter.end()

    def _block_at_y(self, y):
        """Which block is under this gutter y, or None past the last one.

        PERF-010: gutter drag fires on every pointermove, so the lookup
        must NOT walk from doc.begin() through an arbitrary document prefix.
        Qt's direct position lookup maps the viewport y to the block under
        it in O(visible region); the visible-block walk below is only a
        fallback."""
        doc = self.document()
        try:
            cursor = self.cursorForPosition(QPoint(0, int(y)))
            block = cursor.block()
            if block.isValid() and block.isVisible():
                # cursorForPosition CLAMPS an out-of-range y to the last
                # block; verify the point is actually within this block's
                # viewport band before accepting it (PERF-010 guardrail:
                # a Y below the last line must still read as "no block").
                rect = self.cursorRect(QTextCursor(block))
                if rect.top() <= y <= rect.top() + max(1, rect.height()):
                    return block
        except Exception:
            pass
        block = doc.firstBlock()
        while block.isValid():
            if block.isVisible():
                rect = self.cursorRect(QTextCursor(block))
                height = doc.documentLayout().blockBoundingRect(block).height()
                if rect.top() <= y <= rect.top() + height:
                    return block
            block = block.next()
        return None

    def margin_select_line(self, y, extend=False):
        """Select whole lines from the margin, Word-style.

        A plain click takes the line under the pointer; dragging sweeps from
        wherever the drag started, in either direction.
        """
        block = self._block_at_y(y)
        if block is None or not block.isValid():
            return False

        if not extend or self._gutter_anchor_block is None:
            self._gutter_anchor_block = block.blockNumber()

        doc = self.document()
        anchor = doc.findBlockByNumber(self._gutter_anchor_block)
        if not anchor.isValid():
            anchor = block

        first, last = (anchor, block)
        if block.blockNumber() < anchor.blockNumber():
            first, last = (block, anchor)

        cursor = QTextCursor(doc)
        cursor.setPosition(first.position())
        end = last.position() + last.length() - 1
        # include the newline so a swept range reads as whole lines, the way
        # dragging the margin does in a word processor
        if last.next().isValid():
            end += 1
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.setFocus()
        return True

    def line_number_area_mouse_press_event(self, event):
        if self.main_win.data.get("line_marks", "False") != "True":
            return
        # PERF: resolve ONLY the block under the pointer via _block_at_y
        # (O(visible region)). The old implementation bailed on documents
        # above 2000 blocks and then walked from doc.begin() -- a full-
        # document prefix scan -- so big documents had a dead gutter. There
        # is no size bail any more: marks work in any document and cost
        # nothing extra on click.
        step = 1 if event.button() == Qt.MouseButton.LeftButton else -1
        block = self._block_at_y(event.pos().y())
        if block is None or not block.isValid():
            return
        state = max(0, block.userState())
        mark = state & 0xFF
        # cycle through the curated palette, OFF included: left forward,
        # right backward (so overshooting doesn't mean clicking around)
        new_mark = (mark + step) % (len(MARK_PALETTE) + 1)
        block.setUserState((state & ~0xFF) | new_mark)
        self.line_number_area.update()
        self._invalidate_view_metadata()
        self.main_win.save_line_marks()

    # ---- margin marks: persistence ------------------------------------
    def _invalidate_view_metadata(self):
        """PERF-005: the cached view metadata is stale -- the next
        collect_view_metadata rebuilds from scratch."""
        self._view_metadata_cache = None
        self._view_metadata_dirty = True

    def collect_view_metadata(self):
        """Collect marks, heat and folded anchors in one pass for view-state
        persistence. PERF-005: the result is cached and invalidated only when
        marks/folds/heat actually change, so a scroll-idle capture reuses the
        cached data instead of walking the full document again."""
        if not getattr(self, "_view_metadata_dirty", True):
            cached = getattr(self, "_view_metadata_cache", None)
            if cached is not None:
                return cached
        import time as _t
        marks = {}
        heat = {}
        folded = []
        
        try:
            span = self._heat_window()
        except Exception:
            span = 24 * 3600
        now = _t.time()
        
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            # Marks
            state = max(0, block.userState())
            mark = state & 0xFF
            if mark:
                marks[block.blockNumber()] = mark
                
            # Heat
            ts = getattr(block.userData(), "ts", None)
            if ts is not None and (now - ts) < span:
                heat[block.blockNumber()] = round(float(ts), 1)
                
            # Folded anchors
            if state & self.FOLD_BIT:
                text = block.text().strip()
                if text:
                    folded.append(text)
                    
            block = block.next()
        
        self._view_metadata_cache = (marks, heat, folded)
        self._view_metadata_dirty = False
        return marks, heat, folded

    def apply_line_heat(self, heat):
        """Restore saved edit timestamps onto their blocks."""
        if not heat:
            return
        doc = self.document()
        for num, ts in heat.items():
            try:
                num, ts = int(num), float(ts)
            except (TypeError, ValueError):
                continue
            block = doc.findBlockByNumber(num)
            if block.isValid():
                stamp_heat(block, ts)
        self.viewport().update()

    def apply_line_marks(self, marks):
        """Restore saved marks, preserving the code/fold bits already set."""
        if not marks:
            return
        doc = self.document()
        for num, mark in marks.items():
            try:
                num, mark = int(num), int(mark) & 0xFF
            except (TypeError, ValueError):
                continue
            block = doc.findBlockByNumber(num)
            if block.isValid():
                state = max(0, block.userState())
                block.setUserState((state & ~0xFF) | mark)
        self.line_number_area.update()

    def _ts_glyph_rect(self, block):
        """Rect of the inline timestamp-refresh glyph for a stamped line."""
        if not TS_STAMP_LINE_RE.search(block.text()):
            return None
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        r = self.cursorRect(cur)
        size = max(16, r.height())
        return QRect(r.right() + 8, r.top() + (r.height() - size) // 2, size + 2, size)

    def _ts_glyph_block_at(self, pos):
        """Return the block whose refresh glyph contains pos, else None."""
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            g = self._ts_glyph_rect(block)
            if g is not None and g.contains(pos):
                return block
            block = block.next()
        return None

    def _invalidate_opener_cache(self):
        """Drop the fence-opener cache on any text change — lazy rebuild on next access."""
        self._opener_cache = None

    def _rebuild_opener_cache(self):
        """Scan all blocks and cache which ``` lines open a code block.

        Called lazily on first _fence_is_opener call after an edit. The
        cache is then O(1) for every subsequent call until the next edit.

        A closing fence is bare ``` (no info string after the backticks).
        A ```lang line can only OPEN a block, never close one.  The old
        code toggled on any ``` line, so a nested ```python inside a
        block would flip the state and desync every fence after it.
        """
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            self._opener_cache = set()
            return
        cache = set()
        in_code = False
        b = doc.firstBlock()
        while b.isValid():
            stripped = b.text().strip()
            if stripped.startswith("```"):
                if not in_code:
                    # any ``` line outside code opens a block
                    cache.add(b.blockNumber())
                    in_code = True
                elif stripped.rstrip("`") == "":
                    # bare ``` inside code closes it
                    in_code = False
                # else: ```lang inside code — ignore (stays in code)
            b = b.next()
        self._opener_cache = cache

    def _fence_is_opener(self, block):
        """True when this ``` line OPENS a code block (cached, O(1) after first call).

        Uses a lazily-built cache: on first call after any edit, scans the
        whole document once and caches opener block numbers. Subsequent calls
        are a set lookup. Avoids stale highlighter state AND repeated O(N)
        scans on every mouse move over ``` lines.
        """
        if not block.text().strip().startswith("```"):
            return False
        prev = block.previous()
        if not prev.isValid():
            return True
        if self._opener_cache is None:
            self._rebuild_opener_cache()
        return block.blockNumber() in self._opener_cache

    # ---- prompt queue (Alt+C) ---------------------------------------------

    def queue_current_line(self):
        """Alt+C: hand the current line (or the selection) to the queue.

        Returns (text, block) for the caller to enqueue, or (None, None) when
        there is nothing worth queuing. The block is what the queue anchors
        to - see block_data(): line NUMBERS shift under any edit above, so
        they cannot be the anchor.
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", " ").strip()
            block = self.document().findBlock(cursor.selectionStart())
        else:
            block = cursor.block()
            text = block.text().strip()

        if not text:
            return None, None            # an empty line is not a prompt

        # the payload itself is created by set_queue_anchor once the caller
        # has an item id to put in it
        state = max(0, block.userState())
        block.setUserState(state | QUEUED_BIT)

        # to the next line, so ten follow-ups are ten keystrokes
        move = QTextCursor(block)
        move.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        if block.next().isValid():
            move = QTextCursor(block.next())
        else:
            move.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setTextCursor(move)
        self.line_number_area.update()
        return text, block

    def set_queue_anchor(self, block, item_id):
        """Tie a queued item to the block it came from.

        Memory-only by contract: the persistence API (collect_queue_marks /
        apply_queue_marks) was retired with the T-1183 watcher subsystem, and
        no production route writes anchors into a save file. Anchors live as
        long as the document does.
        """
        data = block_data(block, create=True)
        if data is not None:
            data.queue_id = item_id or ""
        # PERF-004: populate the per-document anchor index so periodic
        # watcher ticks do not repeatedly scan from doc.begin().
        if not hasattr(self, "_queue_anchor_index"):
            self._queue_anchor_index = {}
        if item_id:
            self._queue_anchor_index[item_id] = block
        return data

    def block_for_queue_item(self, item_id):
        """The block still carrying this item's anchor, or None if the line
        was deleted - which is what makes an item `detached`."""
        if not item_id:
            return None
        # PERF-004: consult the index first; validate the cached block
        idx = getattr(self, "_queue_anchor_index", None)
        if idx is not None and item_id in idx:
            block = idx[item_id]
            if block.isValid() and block.blockNumber() >= 0:
                data = block.userData()
                if getattr(data, "queue_id", "") == item_id:
                    return block
            del idx[item_id]  # stale: remove from index
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            data = block.userData()
            if getattr(data, "queue_id", "") == item_id:
                return block
            block = block.next()
        return None

    def blocks_for_queue_items(self, item_ids):
        """Find the blocks for multiple queue items in one pass.

        PERF-004: consult the index first; fall back to a full scan only
        for any remaining items the index did not resolve."""
        if not item_ids:
            return {}
        ids = set(item_ids)
        result = {}
        idx = getattr(self, "_queue_anchor_index", None)
        if idx is not None:
            for item_id in list(ids):
                block = idx.get(item_id)
                if block is not None and block.isValid() and block.blockNumber() >= 0:
                    data = block.userData()
                    if getattr(data, "queue_id", "") == item_id:
                        result[item_id] = block
                        ids.discard(item_id)
                        continue
                if item_id in idx:
                    del idx[item_id]  # stale
            if not ids:
                return result
        doc = self.document()
        block = doc.begin()
        while block.isValid() and ids:
            data = block.userData()
            qid = getattr(data, "queue_id", "")
            if qid in ids:
                result[qid] = block
                ids.discard(qid)
            block = block.next()
        return result

    def mark_queue_sent(self, item_id):
        """Tick the gutter for a line whose prompt has gone out."""
        block = self.block_for_queue_item(item_id)
        if block is None:
            return False
        # PERF-004: remove from the index; a sent anchor is no longer
        # needed by the periodic watcher scans.
        idx = getattr(self, "_queue_anchor_index", None)
        if idx is not None:
            idx.pop(item_id, None)
        state = max(0, block.userState())
        block.setUserState((state | SENT_BIT) & ~QUEUED_BIT)
        self.line_number_area.update()
        return True

    def clear_queue_marks(self, item_id=None):
        """Drop the queue bits, for one item or for the whole document."""
        doc = self.document()
        block = doc.begin()
        cleared = 0
        while block.isValid():
            data = block.userData()
            if item_id is None or getattr(data, "queue_id", "") == item_id:
                state = max(0, block.userState())
                if state & (QUEUED_BIT | SENT_BIT):
                    block.setUserState(state & ~(QUEUED_BIT | SENT_BIT))
                    cleared += 1
                if data is not None and hasattr(data, "queue_id"):
                    data.queue_id = ""
            block = block.next()
        if cleared:
            self.line_number_area.update()
        return cleared

    def prune_queue_marks(self):
        """Drop queue bits from blocks that carry no anchor.

        Deleting a line makes Qt merge blocks, and the surviving block can
        inherit the userState bits while the userData does NOT come with
        them - measured. The anchor is the truth and the bits are a cache,
        so a bit without an anchor is stale and would otherwise paint a tick
        beside a line that was never sent.
        """
        doc = self.document()
        block = doc.begin()
        pruned = 0
        while block.isValid():
            state = max(0, block.userState())
            if (state & (QUEUED_BIT | SENT_BIT)
                    and not getattr(block.userData(), "queue_id", "")):
                block.setUserState(state & ~(QUEUED_BIT | SENT_BIT))
                pruned += 1
            block = block.next()
        if pruned:
            self.line_number_area.update()
        return pruned

    # ---- folding (code fences + markdown headers) -------------------------

    FOLD_BIT = 1 << 9

    @staticmethod
    def _header_level(text):
        """1-6 for '# ...' .. '###### ...' lines, else 0."""
        stripped = text.lstrip()
        n = 0
        while n < len(stripped) and stripped[n] == "#":
            n += 1
        return n if 0 < n <= 6 and stripped[n:n + 1] == " " else 0

    @staticmethod
    def _is_divider_line(text):
        """A '---' / '***' / '___' horizontal rule: 3+ of one character.

        Deliberately not a regex: the backreference form of this pattern
        keeps getting mangled when the file is edited by a script, and it
        failed silently (matching a control character instead).
        """
        stripped = text.strip()
        if len(stripped) < 3 or stripped[0] not in "-*_":
            return False
        return set(stripped) == {stripped[0]}
    @staticmethod
    def _is_quote_line(text):
        return text.lstrip().startswith(">")

    def _is_quote_start(self, block):
        """First line of a quote run — that line carries the fold toggle.

        A one-line quote counts too: it still gets the toggle, it just has
        nothing to hide, so it stays a single wrapped line on screen.
        """
        if not self._is_quote_line(block.text()):
            return False
        prev = block.previous()
        return not (prev.isValid() and self._is_quote_line(prev.text()))

    def _is_fold_anchor(self, block):
        text = block.text()
        if self._header_level(text):
            return True
        if self._is_quote_start(block):
            return True
        return text.strip().startswith("```") and self._fence_is_opener(block)

    def _fold_range(self, block):
        """Blocks hidden when this anchor folds: (first, last) or None."""
        text = block.text()
        lvl = self._header_level(text)
        first = block.next()
        if not first.isValid():
            return None
        if self._is_quote_start(block):
            # collapse through the last consecutive '>' line, leaving the
            # quote showing as its own first line (like a footnote)
            last = None
            b = first
            while b.isValid() and self._is_quote_line(b.text()):
                last = b
                b = b.next()
            return (first, last) if last is not None else None
        if lvl:
            last = None
            b = first
            # If --- sits directly below the header, skip it — treat it
            # as header decoration, not a section boundary. The fold
            # still hides the --- line; it just looks past it for the
            # next real boundary.
            if self._is_divider_line(b.text()):
                b = b.next()
            while b.isValid():
                other = self._header_level(b.text())
                if other and other <= lvl:
                    break
                # a horizontal rule closes the section too — people use it as
                # an explicit "this part ends here" marker, and without it a
                # header swallowed everything up to the NEXT header
                if self._is_divider_line(b.text()):
                    break
                last = b
                b = b.next()
            return (first, last) if last is not None else None
        # fence opener: hide through the closing fence (bare ``` only)
        b = first
        last = None
        while b.isValid():
            last = b
            s = b.text().strip()
            if s.startswith("```") and s.rstrip("`") == "":
                break
            b = b.next()
        return (first, last) if last is not None else None

    def _fold_rect(self, block):
        """Rect of the fold toggle box on an anchor line."""
        if block.text().strip().startswith("```"):
            c = self._code_copy_rect(block)
            return QRect(c.right() + 6, c.top(), c.width(), c.height())
        ts = self._ts_glyph_rect(block)
        if ts is not None:
            size = ts.height()
            return QRect(ts.right() + 6, ts.top(), size, size)
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        r = self.cursorRect(cur)
        size = max(14, r.height() - 2)
        return QRect(r.right() + 6, r.top() + (r.height() - size) // 2, size, size)

    def _fold_block_at(self, pos):
        if self.document().blockCount() > 2000:
            return None
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if block.isVisible():
                r = self.cursorRect(QTextCursor(block))
                if r.top() > vp_h:
                    break
                if self._is_fold_anchor(block) and self._fold_rect(block).contains(pos):
                    return block
            block = block.next()
        return None

    def toggle_fold(self, anchor):
        """Collapse/expand the region under a header or code fence."""
        rng = self._fold_range(anchor)
        if rng is None:
            return
        first, last = rng
        state = max(0, anchor.userState())
        collapse = not (state & self.FOLD_BIT)
        b = first
        while b.isValid():
            b.setVisible(not collapse)
            if b.blockNumber() >= last.blockNumber():
                break
            b = b.next()
        anchor.setUserState(state | self.FOLD_BIT if collapse else state & ~self.FOLD_BIT)
        self._invalidate_view_metadata()
        # Store hidden line count on the anchor block for the gutter badge
        data = block_data(anchor, create=True)
        if data is not None:
            data.fold_count = (last.blockNumber() - first.blockNumber() + 1) if collapse else 0
        doc = self.document()
        doc.markContentsDirty(anchor.position(),
                              last.position() + last.length() - anchor.position())
        self.viewport().update()
        if hasattr(self, "line_number_area"):
            self.line_number_area.update()

    def expand_fold_at(self, block):
        """Expand the region under `block` if it is a collapsed anchor.

        Call this BEFORE any edit that could stop a line from being a fold
        anchor — otherwise the hidden lines stay hidden with nothing left to
        re-expand them, and the text looks destroyed even though it is all
        still in the document.
        """
        if not block.isValid():
            return False
        if not (max(0, block.userState()) & self.FOLD_BIT):
            return False
        self.toggle_fold(block)
        return True

    def rescue_orphan_folds(self):
        """Un-hide blocks whose collapsed anchor no longer exists.

        A last-resort net: any edit that removes a fold anchor while its
        region is collapsed would otherwise strand those lines invisible
        forever (no anchor left to click).
        """
        doc = self.document()
        anchors = []
        b = doc.firstBlock()
        while b.isValid():
            if self._is_fold_anchor(b) and (max(0, b.userState()) & self.FOLD_BIT):
                rng = self._fold_range(b)
                if rng is not None:
                    anchors.append((rng[0].blockNumber(), rng[1].blockNumber()))
            b = b.next()

        changed = False
        b = doc.firstBlock()
        while b.isValid():
            if not b.isVisible():
                n = b.blockNumber()
                if not any(first <= n <= last for first, last in anchors):
                    b.setVisible(True)
                    changed = True
            b = b.next()
        if changed:
            doc.markContentsDirty(0, doc.characterCount())
            self.viewport().update()
            if hasattr(self, "line_number_area"):
                self.line_number_area.update()
        return changed

    def undo(self):
        """Undo one step, then make sure no block is stranded invisible.

        The auto-collapse of a freshly quoted group hides blocks through
        visibility flags, which are not part of the document undo data: a
        plain Ctrl+Z could otherwise restore the text while the previously
        hidden blocks stay invisible with no anchor left to click.
        """
        super().undo()
        try:
            self.rescue_orphan_folds()
        except Exception:
            pass

    def redo(self):
        """Redo one step with the same no-stranded-hidden-blocks net."""
        super().redo()
        try:
            self.rescue_orphan_folds()
        except Exception:
            pass

    def unfold_all(self):
        """Safety hatch: show every block and clear all fold bits."""
        doc = self.document()
        b = doc.firstBlock()
        changed = False
        while b.isValid():
            if not b.isVisible():
                b.setVisible(True)
                changed = True
            state = max(0, b.userState())
            if state & self.FOLD_BIT:
                b.setUserState(state & ~self.FOLD_BIT)
            b = b.next()
        if changed:
            doc.markContentsDirty(0, doc.characterCount())
            self.viewport().update()
            if hasattr(self, "line_number_area"):
                self.line_number_area.update()

    def _code_copy_rect(self, block):
        """Rect of the inline copy button on an opening fence line."""
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        r = self.cursorRect(cur)
        size = max(14, r.height() - 2)
        return QRect(r.right() + 6, r.top() + (r.height() - size) // 2, size, size)

    def _image_pill_rect(self, block, match):
        """Screen rect of the collapsed image pill for one ![](...) match.

        Same geometry paintEvent draws, derived from cursor rects so the two
        cannot disagree: the pill runs from the start of the match to its end
        on the same visual line, and falls back to a fixed width when the
        match wraps.
        """
        start = QTextCursor(block)
        start.setPosition(block.position() + match.start())
        end = QTextCursor(block)
        end.setPosition(block.position() + match.end())
        r_start, r_end = self.cursorRect(start), self.cursorRect(end)
        height = max(18, r_start.height())
        width = (abs(r_end.left() - r_start.left())
                 if r_end.top() == r_start.top() else 150)
        top = r_start.top() + (r_start.height() - height) // 2
        return QRect(r_start.left(), top, max(40, width), height)

    @staticmethod
    def _image_copy_rect(pill):
        """Rect of the copy button, 6 px to the right of the image pill.

        It used to sit INSIDE the pill's right edge, drawn on top of the
        filename label -- two controls occupying the same pixels. It now
        clears the pill entirely, the same 6 px offset ``_code_copy_rect``
        uses, so neither button can overlap the thing it annotates.
        """
        size = max(14, pill.height() - 2)
        return QRect(pill.right() + 6,
                     pill.top() + (pill.height() - size) // 2, size, size)

    def _image_copy_at(self, pos):
        """(path, rect) for the image-copy button under `pos`, else None.

        Walks the pills the same way ``image_pill_at`` does, but answers for
        the BUTTON, and the button is checked first on every press: a click
        that lands on it must copy, never open the viewer.
        """
        doc = self.document()
        if doc.blockCount() > 2000:
            return None
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            if self.cursorRect(QTextCursor(block)).top() > vp_h:
                break
            for match in MD_IMAGE_RE.finditer(block.text()):
                pill = self._image_pill_rect(block, match)
                button = self._image_copy_rect(pill)
                if button.contains(pos):
                    url = self._image_url_for(match.group(1))
                    if url is None or not url.isLocalFile():
                        return None     # an http image has no local file
                    path = os.path.realpath(os.path.abspath(
                        url.toLocalFile()))
                    return path, button
            block = block.next()
        return None

    def image_pill_at(self, pos):
        """(block, match) for the image pill under `pos`, or None."""
        doc = self.document()
        if doc.blockCount() > 2000:
            return None            # the pills are not painted on huge docs
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            if self.cursorRect(QTextCursor(block)).top() > vp_h:
                break
            for match in MD_IMAGE_RE.finditer(block.text()):
                if self._image_pill_rect(block, match).contains(pos):
                    return block, match
            block = block.next()
        return None

    @staticmethod
    def _image_url_for(target):
        """``![](...)`` target or rendered path -> QUrl, or None if unusable."""
        raw = str(target or "").strip()
        if not raw:
            return None
        if raw.startswith("http"):
            return QUrl(raw)
        return QUrl.fromLocalFile(raw.replace("file:///", ""))

    def _markdown_image_for(self, path):
        """(block, match) whose image link resolves to ``path``, or None.

        A RENDERED image knows only where its bytes came from. Renaming needs
        the markdown link too, or the file would move and the document would
        keep pointing at the old name. Rather than keep a second geometry
        table in sync with the renderer, the link is recovered from the text.
        """
        wanted = os.path.normcase(os.path.abspath(
            str(path or "").replace("file:///", "")))
        if not wanted:
            return None
        doc = self.document()
        if doc.blockCount() > 2000:
            return None
        block = doc.firstBlock()
        while block.isValid():
            for match in MD_IMAGE_RE.finditer(block.text()):
                target = match.group(1)
                url = self._image_url_for(target)
                if url is None or not url.isLocalFile():
                    continue
                candidate = os.path.normcase(os.path.abspath(
                    url.toLocalFile()))
                if candidate == wanted:
                    return block, match
            block = block.next()
        return None

    def image_hit_at(self, pos):
        """THE image hit test: ``(block, match, url)`` under ``pos``, or None.

        One resolver for both worlds, on purpose. Source mode paints collapsed
        pills (``image_pill_at``); Live Preview and Reading mode paint the
        real raster and record its rect in ``_rendered_images``. Those used to
        be two independent click paths with two different gestures, which is
        how "click to view" ended up meaning Ctrl+click in one mode and
        double-click-to-rename in another.

        ``block``/``match`` are None when the visual could not be tied back to
        a markdown link. Such a hit can still be OPENED; it must never be
        renamed, because there would be no link to move with the file.
        """
        hit = self.image_pill_at(pos)
        if hit is not None:
            block, match = hit
            url = self._image_url_for(match.group(1))
            return None if url is None else (block, match, url)
        for rect, path in (getattr(self, "_rendered_images", None) or ()):
            try:
                if not rect.contains(pos):
                    continue
            except (TypeError, AttributeError):
                continue
            url = self._image_url_for(path)
            if url is None:
                return None
            found = self._markdown_image_for(path) if url.isLocalFile() else None
            if found is not None:
                return found[0], found[1], url
            return None, None, url
        return None

    @staticmethod
    def _image_hit_is_renameable(block, match, url):
        """Only a LOCAL file with a link behind it may be renamed.

        An http image is somebody else's file; a rendered visual with no
        recoverable link would leave the document pointing at a name that no
        longer exists.
        """
        return (block is not None and match is not None
                and url is not None and url.isLocalFile())

    def rename_image_at(self, block, match):
        """Rename the file a pill points at, and the link with it.

        The gesture is Ctrl+LEFT-CLICK (T-1265 C3). It used to be
        double-click, which collided with the one thing a user actually wants
        from an image - looking at it - and meant a plain double-click could
        pop a rename dialog nobody asked for. Plain click now opens the
        viewer; Ctrl+click renames.

        Renaming is worth a gesture at all because the file was written as
        `paste-20260730_140826.png`, which says when it arrived and nothing
        about what it is.
        """
        import os as _os

        from PyQt6.QtCore import QUrl
        from PyQt6.QtWidgets import QInputDialog

        target = match.group(1)
        path = QUrl(target).toLocalFile() if target.startswith("file:") else target
        path = _os.path.normpath(path) if path else ""
        old_name = _os.path.basename(path) or target
        stem, ext = _os.path.splitext(old_name)

        mw = self.main_win
        lang = getattr(mw, "_current_lang", "EN")
        if hasattr(mw, "_increment_focus_lock"):
            mw._increment_focus_lock()      # the window hides on focus loss
        try:
            new_stem, ok = QInputDialog.getText(
                self, tr("Rename image", lang), tr("New name:", lang),
                text=stem)
        finally:
            if hasattr(mw, "_decrement_focus_lock"):
                QTimer.singleShot(300, weak_qt_callback(
                    mw, type(mw)._decrement_focus_lock))
        new_stem = (new_stem or "").strip()
        if not ok or not new_stem or new_stem == stem:
            return False

        # keep the extension unless the user typed one themselves
        new_name = new_stem if _os.path.splitext(new_stem)[1] else new_stem + ext
        new_name = re.sub(r'[\\/:*?"<>|]+', "_", new_name)

        new_path = path
        if path and _os.path.isfile(path):
            from fastprompter.ui.file_container import _unique_dest
            new_path = _unique_dest(_os.path.dirname(path), new_name)
            try:
                _os.rename(path, new_path)
            except OSError:
                logger.exception("could not rename the pasted image")
                return False        # link untouched: it still points at a file

        # the link follows the file, in ONE undo step with it
        new_target = (QUrl.fromLocalFile(new_path).toString()
                      if target.startswith("file:") else new_path)
        cursor = self.textCursor()
        from fastprompter.ui.edit_guard import edit_block
        with edit_block(cursor, self):
            cursor.setPosition(block.position() + match.start(1))
            cursor.setPosition(block.position() + match.end(1),
                               QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(new_target)
        fc = getattr(mw, "_file_container", None)
        if fc is not None and not sip.isdeleted(fc):
            prev = getattr(mw, "ignore_focus_loss", False)
            mw.ignore_focus_loss = True
            try:
                fc.refresh()
            finally:
                mw.ignore_focus_loss = prev
        return True

    def _code_copy_block_at(self, pos):
        """Return the opening fence block whose copy button contains pos."""
        if self.document().blockCount() > 2000:
            return None
        block = self._first_visible_block()
        vp_h = self.viewport().height()
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            if block.text().strip().startswith("```") and self._fence_is_opener(block):
                if self._code_copy_rect(block).contains(pos):
                    return block
            block = block.next()
        return None

    def copy_code_block(self, opener_block):
        """Copy the fenced block's content (between the fences) to clipboard."""
        lines = []
        b = opener_block.next()
        while b.isValid():
            if b.text().strip().startswith("```"):
                break
            lines.append(b.text())
            b = b.next()
        QApplication.clipboard().setText("\n".join(lines))
        try:
            self.main_win.play_tick_sound()
        except Exception:
            pass

    def copy_image_at(self, path):
        """Put the image at ``path`` on the clipboard as pixels + a file URL.

        The same payload the file container's Ctrl+C produces, so a picture
        pasted out of the editor and one pasted out of the silo file list are
        indistinguishable on the receiving side.
        """
        from fastprompter.ui.image_viewer import copy_image_to_clipboard
        if not copy_image_to_clipboard(path):
            return False
        try:
            self.main_win.play_tick_sound()
        except Exception:
            pass
        return True

    def _interactive_target_at(self, pos):
        """W2-006/PERF-006: ONE visible-block walk answering every hover
        target. Returns True when ``pos`` hits a checkbox, timestamp glyph,
        fold anchor or code-copy button.

        The four features used to run four independent visible-region walks
        per qualifying pointer movement; the geometry question is the same,
        so it is answered once here. Click handlers keep their specific
        helpers (clicks are not high-frequency).
        """
        doc = self.document()
        if not doc or sip.isdeleted(doc):
            return False
        try:
            block = self._first_visible_block()
            vp_h = self.viewport().height()
        except Exception:
            return False
        if not block:
            return False
        big = doc.blockCount() > 2000
        check_cb = self._doc_has_checkbox
        while block is not None and block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            g = self._ts_glyph_rect(block)
            if g is not None and g.contains(pos):
                return True
            if check_cb and r.bottom() >= 0 and self._checkbox_hit_in_block(block, pos):
                return True
            if not big:
                if self._is_fold_anchor(block) and self._fold_rect(block).contains(pos):
                    return True
                if (block.text().strip().startswith("```")
                        and self._fence_is_opener(block)
                        and self._code_copy_rect(block).contains(pos)):
                    return True
                for m_img in MD_IMAGE_RE.finditer(block.text()):
                    if self._image_copy_rect(
                            self._image_pill_rect(block, m_img)).contains(pos):
                        return True
            block = block.next()
        return False

    def _checkbox_hit_in_block(self, block, pos):
        """W2-006 helper: does ``pos`` hit THIS block's task checkbox?

        The guard is PER BLOCK, not around the whole walk. It used to wrap
        the entire loop, so one block that upset the layout maths aborted
        the scan and every checkbox below it became unclickable - measured:
        a single raising block made the third checkbox in a three-line
        document impossible to hit. A bad block is skipped now; the ones
        after it still answer.
        """
        try:
            text = block.text()
            stripped = text.lstrip()
            indent = len(text) - len(stripped)
            if stripped.startswith(("[ ] ", "[x] ", "[X] ")):
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.Right,
                                    QTextCursor.MoveMode.MoveAnchor, indent)
                r_start = self.cursorRect(cursor)
                cursor.movePosition(QTextCursor.MoveOperation.Right,
                                    QTextCursor.MoveMode.MoveAnchor, 4)
                r_end = self.cursorRect(cursor)
                b_w = int(r_end.x() - r_start.x())
                # A wrapped line can put the closing bracket on the
                # next visual row, which makes the width negative and
                # QRect.contains() false for every point - the
                # checkbox would simply stop responding. Fall back to
                # the line height, which is close enough to the glyph
                # box to stay clickable.
                if b_w <= 0:
                    b_w = int(r_start.height())
                if QRect(int(r_start.x()), int(r_start.top()),
                         b_w, int(r_start.height())).contains(pos):
                    return True
        except Exception as exc:
            logger.debug("checkbox hit test skipped block %s: %s",
                         block.blockNumber(), exc)
        return False

    def _checkbox_at_pos(self, pos):
        """Which checkbox, if any, is under this viewport point."""
        if not self._doc_has_checkbox:
            return None
        doc = self.document()
        if not doc:
            return None
        try:
            vp_h = self.viewport().height()
            block = self._first_visible_block()
        except Exception as exc:
            logger.debug("checkbox hit test could not start: %s", exc)
            return None
        if not block:
            return None

        while block.isValid():
            r = self.cursorRect(QTextCursor(block))
            if r.top() > vp_h:
                break
            if r.bottom() >= 0 and self._checkbox_hit_in_block(block, pos):
                return block
            block = block.next()
        return None

    @staticmethod
    def strip_strike(text):
        """Remove every layer of ~~…~~ wrapping.

        Loops instead of stripping once: a naive wrap/unwrap pair can leave
        text like ``~~~~done~~~~`` behind, and one pass would only peel the
        outer layer, so the tildes accumulate a little more each toggle.
        """
        s = text
        while len(s) >= 4 and s.startswith("~~") and s.endswith("~~"):
            inner = s[2:-2]
            # Peel only when what's left is either clean, or itself a
            # well-formed wrapper (the "~~~~x~~~~" over-wrap case). Bail on
            # stray tildes — "~~a~~ and ~~b~~" is two spans, not one wrap,
            # and unwrapping it would corrupt the line.
            if "~~" in inner and not (
                len(inner) >= 4 and inner.startswith("~~") and inner.endswith("~~")
            ):
                break
            s = inner
        return s

    @classmethod
    def wrap_strike(cls, text):
        """Wrap in ~~…~~ exactly once, whatever state it starts in."""
        inner = cls.strip_strike(text)
        if not inner.strip():
            return inner  # never strike an empty line into "~~~~"
        # a stray unbalanced "~~" would fuse with ours into "~~~~"
        if "~~" in inner:
            return inner
        return f"~~{inner}~~"

    def _toggle_single_line(self, block):
        """Cycle one line: plain -> checked+struck -> unchecked -> plain."""
        try:
            text = block.text()
            stripped = text.lstrip()
            indent = text[:len(text) - len(stripped)]
            if stripped.startswith("[x] ") or stripped.startswith("[X] "):
                # checked -> unchecked, drop the strikethrough
                new_text = f"{indent}[ ] {self.strip_strike(stripped[4:])}"
            elif stripped.startswith("[ ] "):
                # unchecked -> no checkbox at all (3rd click returns to plain)
                new_text = f"{indent}{self.strip_strike(stripped[4:])}"
            elif stripped:
                # plain -> checked AND struck in one go
                new_text = f"{indent}[x] {self.wrap_strike(stripped)}"
            else:
                return
            bcursor = QTextCursor(block)
            bcursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            bcursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            bcursor.insertText(new_text)
            # Clicking a checkbox in the text made NO sound at all, and
            # everywhere that did make one asked for "tick" in both
            # directions — so un-ticking sounded exactly like ticking.
            mw = getattr(self, "main_win", None)
            if mw is not None and hasattr(mw, "play_tick_sound"):
                mw.play_tick_sound(new_text.lstrip().startswith(("[x] ", "[X] ")))
        except Exception as e:
            logger.debug(f"checkbox toggle error: {e}")

    _RE_ORDERED = re.compile(r"^(\s*)(\d+)\.(\s)")

    def _delete_line_smart(self, block):
        """Delete the line under the cursor, then keep any surrounding
        ordered list sequential. Bullet/checkbox lists need no renumber, so
        the plain block removal already leaves them well-formed."""
        try:
            doc = self.document()
            was_ordered = self._RE_ORDERED.match(block.text())
            # Anchor the renumber to the previous block: it survives the
            # deletion and its next sibling becomes the new run head.
            prev_no = block.previous().blockNumber() if block.previous().isValid() else -1
            start_pos = block.position()
            end_pos = start_pos + len(block.text())
            nxt, prev = block.next(), block.previous()
            cursor = QTextCursor(doc)
            with edit_block(cursor, self):
                # Take exactly one paragraph separator with the line so no
                # blank gap survives: the trailing one when a block follows,
                # otherwise the leading one (last block).
                if nxt.isValid():
                    cursor.setPosition(start_pos)
                    cursor.setPosition(nxt.position(), QTextCursor.MoveMode.KeepAnchor)
                elif prev.isValid():
                    cursor.setPosition(start_pos - 1)
                    cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
                else:
                    cursor.setPosition(start_pos)
                    cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                if was_ordered:
                    start = doc.findBlockByNumber(prev_no + 1) if prev_no >= 0 else doc.firstBlock()
                    self._renumber_ordered_run(start)
        except Exception as e:
            logger.debug(f"smart line delete error: {e}")

    def _renumber_ordered_run(self, start_block):
        """Rewrite the contiguous ordered-list run containing ``start_block``
        as 1., 2., 3., ... at each item's own indent. Walks back to the true
        head first so a mid-run start still fixes the whole run."""
        block = start_block
        if not block.isValid() or not self._RE_ORDERED.match(block.text()):
            return
        # rewind to the first item of the run
        while block.previous().isValid() and self._RE_ORDERED.match(block.previous().text()):
            block = block.previous()
        n = 1
        while block.isValid():
            m = self._RE_ORDERED.match(block.text())
            if not m:
                break
            want = f"{m.group(1)}{n}.{m.group(3)}"
            have = block.text()[:m.end()]
            if want != have:
                bc = QTextCursor(block)
                bc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                bc.setPosition(block.position() + m.end(),
                               QTextCursor.MoveMode.KeepAnchor)
                bc.insertText(want)
            n += 1
            block = block.next()

    def _set_line_mark(self, block):
        """Strict toggle of the colored line mark on ``block``.

        Unmarked -> a random palette colour; marked -> OFF. The second click
        NEVER re-rolls the colour (remove, then apply again for a new one).
        Marks ride in the low userState byte, so queue/fold bits survive;
        text is never touched. The caller decides whether to accept the
        mouse event.
        """
        if block is None or not block.isValid():
            return
        state = max(0, block.userState())
        mark = state & 0xFF
        if mark:
            new_mark = 0                       # marked -> remove, strict
        else:
            new_mark = random.choice(_RANDOM_MARK_IDS)
        block.setUserState((state & ~0xFF) | new_mark)
        self.line_number_area.update()
        self._invalidate_view_metadata()
        self.main_win.save_line_marks()

    def _ensure_line_marks_visible(self):
        """Turn line-mark visibility ON if it is currently off.

        An explicit mark request must never create an INVISIBLE mark: the
        toggle goes through the settings checkbox's own callback (blocked
        signal, we set the state and drive the callback directly) so the
        settings UI, gutter geometry and the persisted value all agree.
        Returns True when the setting was flipped here.
        """
        if self.main_win.data.get("line_marks", "False") == "True":
            return False
        self.main_win.data["line_marks"] = "True"
        cb = getattr(self.main_win, "cb_line_marks", None)
        if cb is not None:
            from PyQt6.QtCore import QSignalBlocker
            with QSignalBlocker(cb):
                cb.setChecked(True)          # UI mirrors without re-firing
            cb.toggled.emit(True)            # run the builder's own callback
        self.update_line_number_area_width()
        self.line_number_area.update()
        return True

    def mouseDoubleClickEvent(self, event):
        """Double-click an image pill to rename the file it points at.

        Anywhere else this is the normal word-select, so the gesture costs
        nothing: a pill is not text you would double-click to select.
        The second press of a Ctrl+triple-click arrives here, so the press
        counter is bumped here too (the third press lands in mousePressEvent).
        """
        if event.button() == Qt.MouseButton.MiddleButton:
            self.mousePressEvent(event)
            return
        if (not sip.isdeleted(self)
                and event.button() == Qt.MouseButton.LeftButton):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._ctrl_click_bump(event.pos())
            if self.image_hit_at(event.pos()) is not None:
                # T-1265 C3: SWALLOWED, not acted on. The first press of this
                # sequence already opened the viewer (or renamed, on Ctrl), so
                # doing anything here would open a second viewer or a second
                # rename dialog. Double-click is no longer a rename gesture.
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _handle_image_click(self, event, block, match, url):
        """Plain click -> view. Ctrl+click -> rename. Ctrl+Shift -> folder.

        Returns True when the click was consumed. Anything else (Shift alone,
        Alt, an unhandled combination) falls through to the normal handling
        rather than being silently eaten.
        """
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if alt or (shift and not ctrl):
            return False

        # Live Preview records a link under the press and opens it on RELEASE.
        # Leaving that armed would open the same image a second time.
        self._pending_link = None

        if ctrl and shift:
            if url.isLocalFile():
                self.open_containing_folder(url)
                self._suppress_context_menu = True
                return True
            return False
        if ctrl:
            if not self._image_hit_is_renameable(block, match, url):
                # An http image, or a visual with no recoverable link: there is
                # nothing local to rename, and inventing a target would be
                # worse than doing nothing.
                return True
            self.rename_image_at(block, match)
            return True
        VaultTextEdit.authorize_and_open_url(
            url, self, getattr(self.main_win, "_current_lang", "EN"))
        return True

    def mouseTripleClickEvent(self, event):
        """Ctrl+triple-click on a word clears all pinned selections."""
        if (not sip.isdeleted(self)
                and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and getattr(self, "_pinned_cursors", None)):
            self._clear_pinned_selections()
            event.accept()
            return
        # QTextEdit has no mouseTripleClickEvent — Qt reports the third press
        # as an ordinary press. The method is kept because the suite drives it
        # directly, so the super() call has to tolerate its absence.
        parent = getattr(super(), "mouseTripleClickEvent", None)
        if callable(parent):
            parent(event)
        else:
            event.accept()

    def mousePressEvent(self, event):
        if sip.isdeleted(self):
            return
        try:
            # Live Preview: remember a link under the press (open is deferred to
            # release, so a drag/selection that starts on a link still works).
            self._record_pending_link(event)
            if event.button() == Qt.MouseButton.LeftButton:
                # The image-copy button sits 6 px right of the pill, so it
                # must be asked BEFORE the pill: a press on it copies and
                # must never open the viewer.
                image_copy = self._image_copy_at(event.pos())
                if image_copy is not None:
                    self._image_copy_pressed = image_copy[0]
                    self.viewport().update()
                    event.accept()
                    return
                fold_block = self._fold_block_at(event.pos())
                if fold_block is not None:
                    self._fold_pressed_block = fold_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                code_block = self._code_copy_block_at(event.pos())
                if code_block is not None:
                    self._copy_pressed_block = code_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                ts_block = self._ts_glyph_block_at(event.pos())
                if ts_block is not None:
                    # show the pushed state; the action fires on release
                    self._ts_pressed_block = ts_block.blockNumber()
                    self.viewport().update()
                    event.accept()
                    return
                cb_block = self._checkbox_at_pos(event.pos())
                if cb_block:
                    self._toggle_single_line(cb_block)
                    event.accept()
                    return

                # T-1265 C3: an image is a VISUAL CONTROL, like the fold arrow
                # and the copy button above it, so it answers an ordinary
                # click. Ctrl+click renames it. This is deliberately an
                # exception to the Source-mode "links need Ctrl" rule: that
                # rule protects arbitrary hrefs, and it still does -- opening
                # goes through authorize_and_open_url, the ONE router, which
                # decodes rasters internally and still demands confirmation
                # before any local file reaches the shell.
                image_hit = self.image_hit_at(event.pos())
                if image_hit is not None:
                    handled = self._handle_image_click(event, *image_hit)
                    if handled:
                        event.accept()
                        return
            
            mods = event.modifiers()
            
            # Check for image stub clicks
            if mods & Qt.KeyboardModifier.ControlModifier:
                img_path = None
                for rect, path in getattr(self, "_rendered_images", []):
                    if rect.contains(event.pos()):
                        img_path = path
                        break
                
                if img_path:
                    url = QUrl(img_path) if img_path.startswith("http") else QUrl.fromLocalFile(img_path.replace("file:///", ""))
                    wants_folder = (event.button() == Qt.MouseButton.RightButton or bool(mods & Qt.KeyboardModifier.ShiftModifier))
                    if wants_folder and url.isLocalFile():
                        self.open_containing_folder(url)
                        self._suppress_context_menu = True
                    elif event.button() == Qt.MouseButton.LeftButton:
                        VaultTextEdit.authorize_and_open_url(url, self, getattr(self.main_win, '_current_lang', 'EN'))
                    else:
                        return
                    event.accept()
                    return
            if (mods & Qt.KeyboardModifier.ControlModifier
                    and event.button() == Qt.MouseButton.LeftButton):
                tag = self.hashtag_at(event.pos())
                if tag:
                    self.main_win.open_hashtag_dialog(tag)
                    event.accept()
                    return
            if mods & Qt.KeyboardModifier.ControlModifier:
                url = self._safe_link_url(self.anchor_url_at(event.pos()))
                if url is not None:
                    wants_folder = (
                        event.button() == Qt.MouseButton.RightButton
                        or bool(mods & Qt.KeyboardModifier.ShiftModifier))
                    if wants_folder and url.isLocalFile():
                        self.open_containing_folder(url)
                        self._suppress_context_menu = True
                    elif event.button() == Qt.MouseButton.LeftButton:
                        VaultTextEdit.authorize_and_open_url(url, self, getattr(self.main_win, '_current_lang', 'EN'))
                    else:
                        return      # Ctrl+right on a web link: let the menu open
                    event.accept()
                    return
        except Exception:
            self._fold_pressed_block = None
            self._copy_pressed_block = None
            self._image_copy_pressed = None
            self._ts_pressed_block = None
            logger.exception("mouse press handling failed at %s", event.pos())
        _line_drag_mods = (Qt.KeyboardModifier.ControlModifier
                           | Qt.KeyboardModifier.ShiftModifier)
        if (event.button() == Qt.MouseButton.LeftButton
                and (event.modifiers() & _line_drag_mods) == _line_drag_mods):
            self._cancel_line_drag()
            cursor = self.textCursor()
            click_pos = self.cursorForPosition(event.pos()).position()
            if cursor.hasSelection() and cursor.selectionStart() <= click_pos <= cursor.selectionEnd():
                start = self.document().findBlock(cursor.selectionStart()).blockNumber()
                end = self.document().findBlock(cursor.selectionEnd()).blockNumber()
                self._line_drag_source_block = (start, end)
            else:
                blk = self.cursorForPosition(event.pos()).block().blockNumber()
                self._line_drag_source_block = (blk, blk)
            self._line_drag_press_pos = event.pos()
            self._line_drag_active = False
            self._line_drag_hover_block = None
            event.accept()
            return
        # exact match, so Ctrl+Shift doesn't also fire the bullet toggle
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Plain Ctrl+click on a word pins it as a persistent selection
            # (toggle off with the same gesture). Bullet/list lines keep the
            # old Ctrl+click behaviour — toggling the bullet — so the two do
            # not fight over the same click.
            # Ctrl+triple-click on any word clears all pinned selections.
            blk = self.cursorForPosition(event.pos()).block()
            is_list_line = blk.isValid() and bool(
                re.match(r'^\s*(?:[-*•]|\d+[.)])\s+', blk.text()))
            if not is_list_line:
                count = self._ctrl_click_bump(event.pos())
                if count >= 3:
                    self._clear_pinned_selections()
                else:
                    self._toggle_pinned_selection(event.pos())
                event.accept()
                return
            super().mousePressEvent(event)
            cursor = self.textCursor()
            with edit_block(cursor, self):
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                line = cursor.selectedText()
                if re.match(r'^\s*\u2022\s*', line):
                    new_line = re.sub(r'^(\s*)\u2022\s*', r'\1- ', line)
                elif re.match(r'^\s*-\s+', line):
                    # NB: non-raw string \u2014 \u escapes are valid in a regex
                    # *pattern* but not in an re.sub *replacement template*,
                    # where they raise "bad escape \u" and crash the app.
                    new_line = re.sub(r'^(\s*)-\s+', '\\1\u2022 ', line)
                else:
                    new_line = None
                if new_line is not None:
                    cursor.insertText(new_line)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            if event.modifiers() == Qt.KeyboardModifier.AltModifier:
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    cursor.setPosition(self.cursorForPosition(event.pos()).position())
                
                with edit_block(cursor, self):
                    start_block = self.document().findBlock(cursor.selectionStart())
                    end_block = self.document().findBlock(cursor.selectionEnd())
                    
                    b = start_block
                    while b.isValid() and b.blockNumber() <= end_block.blockNumber():
                        text = b.text()
                        if text.strip():
                            if not re.match(r'^\s*[-*•]\s+', text):
                                c = QTextCursor(b)
                                c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                                m = re.match(r'^(\s*)', text)
                                ind = m.group(1) if m else ""
                                c.setPosition(b.position() + len(ind))
                                c.insertText("• ")
                        b = b.next()
                self.main_win.mark_dirty()
                event.accept()
                return

            block = self.cursorForPosition(event.pos()).block()
            if event.modifiers() == (Qt.KeyboardModifier.ControlModifier
                                     | Qt.KeyboardModifier.ShiftModifier):
                return                       # Ctrl+Shift+MB: unbound, no text change
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                # Ctrl+Middle toggles the colored line mark on the line under
                # the pointer -- anywhere on the line, the gutter box does not
                # have to be hit. It MUST NOT delete text (the old
                # _delete_line_smart binding is retired; one gesture, one
                # owner).
                self._ensure_line_marks_visible()
                self._set_line_mark(block)
                event.accept()
                return
            # Plain middle-click a line cycles it: plain -> checked+struck ->
            # unchecked -> plain. (This used to clear the whole silo, which
            # was a lot of destruction for a stray scroll-wheel press.)
            if block.isValid() and block.text().strip():
                self._toggle_single_line(block)
                self.main_win.mark_dirty()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._right_drag_start = event.globalPosition().toPoint()
            self._dragged = False
        super().mousePressEvent(event)

    def _move_lines(self, start_num, end_num, target_num):
        """Line-blocking drop: move a block of lines to a new position.

        The dragged range lands AFTER the drop line when dragged down and
        BEFORE it when dragged up, which is what the drop indicator draws.
        Rich content (bold, checkboxes, image pills) survives the trip: the
        lines travel as a QTextDocumentFragment, not as plain text.
        """
        if start_num > end_num:
            start_num, end_num = end_num, start_num
        if start_num <= target_num <= end_num:
            return  # target is inside the dragged range

        doc = self.document()
        if not (0 <= start_num and end_num < doc.blockCount() and 0 <= target_num < doc.blockCount()):
            return

        start_block = doc.findBlockByNumber(start_num)
        end_block = doc.findBlockByNumber(end_num)
        if not start_block.isValid() or not end_block.isValid():
            return

        count = end_num - start_num + 1
        last_num = doc.blockCount() - 1

        cursor = self.textCursor()
        with edit_block(cursor, self):
            cursor.setPosition(start_block.position())
            # length() counts the block separator, so -1 lands on end-of-block
            cursor.setPosition(end_block.position() + end_block.length() - 1,
                               QTextCursor.MoveMode.KeepAnchor)
            fragment = cursor.selection()

            # Swallow exactly ONE newline with the lines, or the move leaves a
            # blank line where they were. Prefer the one after; at the end of
            # the document there is none, so take the one before instead.
            if end_num < last_num:
                cursor.setPosition(cursor.position() + 1, QTextCursor.MoveMode.KeepAnchor)
            elif start_num > 0:
                sel_end = cursor.position()
                cursor.setPosition(start_block.position() - 1)
                cursor.setPosition(sel_end, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

            # Blocks after the removed range shifted down by `count`
            new_target = target_num if target_num < start_num else target_num - count
            target_block = doc.findBlockByNumber(new_target)
            if not target_block.isValid():
                target_block = doc.lastBlock()

            cursor.setPosition(target_block.position())
            if target_num > end_num:
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cursor.insertText("\n")
                cursor.insertFragment(fragment)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.insertFragment(fragment)
                cursor.insertText("\n")

    def mouseReleaseEvent(self, event):
        line_drag_source = getattr(self, "_line_drag_source_block", None)
        if line_drag_source is not None and event.button() == Qt.MouseButton.LeftButton:
            was_active = getattr(self, "_line_drag_active", False)
            hover = getattr(self, "_line_drag_hover_block", None)
            
            start_num, end_num = line_drag_source
            self._cancel_line_drag()
            
            if was_active and hover is not None and not (start_num <= hover <= end_num):
                self._move_lines(start_num, end_num, hover)
            event.accept()
            return
        pressed_fold = getattr(self, "_fold_pressed_block", None)
        if pressed_fold is not None and event.button() == Qt.MouseButton.LeftButton:
            self._fold_pressed_block = None
            self.viewport().update()
            block = self._fold_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed_fold:
                self.toggle_fold(block)
            event.accept()
            return
        pressed_img = getattr(self, "_image_copy_pressed", None)
        if pressed_img is not None:
            self._image_copy_pressed = None
            self.viewport().update()
            if event.button() == Qt.MouseButton.LeftButton:
                hit = self._image_copy_at(event.pos())
                if hit is not None and hit[0] == pressed_img:
                    self.copy_image_at(pressed_img)
                    event.accept()
                    return
            else:
                event.accept()
                return
        pressed_copy = getattr(self, "_copy_pressed_block", None)
        if pressed_copy is not None and event.button() == Qt.MouseButton.LeftButton:
            self._copy_pressed_block = None
            self.viewport().update()
            block = self._code_copy_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed_copy:
                self.copy_code_block(block)
            event.accept()
            return
        pressed = getattr(self, "_ts_pressed_block", None)
        if pressed is not None and event.button() == Qt.MouseButton.LeftButton:
            self._ts_pressed_block = None
            self.viewport().update()
            block = self._ts_glyph_block_at(event.pos())
            if block is not None and block.blockNumber() == pressed:
                self.main_win.refresh_timestamp_in_block(block)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        # Live Preview: a plain click that landed on a link (and didn't turn
        # into a drag/selection) opens it. Deferred from press so dragging
        # across a link still selects text.
        if self._open_pending_link_if_click(event):
            return

    def _open_pending_link_if_click(self, event):
        """Open a link recorded on press, but only if it was a real click.

        Guards (all required): left button, same link under press and release,
        the pointer barely moved (under the drag threshold), no text got
        selected by the press, and we are still in Live Preview. A drag that
        began on a link must select text, never launch a browser.
        """
        pending = getattr(self, "_pending_link", None)
        self._pending_link = None
        if pending is None:
            return False
        if self._preview_mode() != "Live Preview":
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        press_url, press_pos = pending
        if self.textCursor().hasSelection():
            return False  # a real selection was made — do not navigate
        if (event.pos() - press_pos).manhattanLength() > QApplication.startDragDistance():
            return False
        release_url = self._safe_link_url(self.anchor_url_at(event.pos()))
        if release_url != press_url:
            return False
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.AltModifier):
            return False
        wants_folder = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if wants_folder and release_url.isLocalFile():
            self.open_containing_folder(release_url)
        else:
            VaultTextEdit.authorize_and_open_url(release_url, self, getattr(self.main_win, '_current_lang', 'EN'))
        return True

    def leaveEvent(self, event):
        # otherwise the wash stays stuck on whatever line the mouse left from
        if getattr(self, "_hover_block", None) is not None:
            self._hover_block = None
            self.viewport().update()
        super().leaveEvent(event)

    def hashtag_at(self, pos):
        """The #tag under a viewport point, or None."""
        from fastprompter.core.hashtags import tag_at
        try:
            cursor = self.cursorForPosition(pos)
            return tag_at(cursor.block().text(), cursor.positionInBlock())
        except Exception:
            logger.debug("hashtag lookup failed", exc_info=True)
            return None

    def _cancel_line_drag(self):
        timer = getattr(self, "_line_drag_autoscroll_timer", None)
        if timer is not None:
            timer.stop()
        self._line_drag_source_block = None
        self._line_drag_active = False
        self._line_drag_hover_block = None
        self._line_drag_scroll_direction = 0
        self.viewport().update()

    def _update_line_drag_autoscroll(self, pos):
        self._line_drag_last_pos = QPoint(pos)
        height = self.viewport().height()
        edge = min(36, max(12, height // 4))
        distance = edge - pos.y() if pos.y() < edge else pos.y() - (height - edge)
        direction = -1 if pos.y() < edge else (1 if pos.y() > height - edge else 0)
        self._line_drag_scroll_direction = direction
        self._line_drag_scroll_speed = max(1, min(6, 1 + max(0, distance) // 8))
        timer = getattr(self, "_line_drag_autoscroll_timer", None)
        if timer is None:
            timer = self._line_drag_autoscroll_timer = QTimer(self)
            timer.setInterval(40)
            timer.timeout.connect(self._line_drag_autoscroll_tick)
        if direction:
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _line_drag_autoscroll_tick(self):
        if (not getattr(self, "_line_drag_active", False)
                or getattr(self, "_line_drag_source_block", None) is None
                or not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton)):
            self._cancel_line_drag()
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + self._line_drag_scroll_direction
                     * self._line_drag_scroll_speed * max(1, bar.singleStep()))
        pos = self._line_drag_last_pos
        rect = self.viewport().rect()
        probe = QPoint(max(0, min(pos.x(), rect.right())),
                       max(0, min(pos.y(), rect.bottom())))
        block = self.cursorForPosition(probe).block()
        self._line_drag_hover_block = block.blockNumber() if block.isValid() else None
        self.viewport().update()

    def anchor_url_at(self, pos):
        """The link under this viewport point, or None."""
        try:
            fmt = self.cursorForPosition(pos).charFormat()
            if not fmt.isAnchor():
                return None
            url = QUrl(fmt.anchorHref())
            return url if url.isValid() else None
        except Exception:
            logger.debug("anchor lookup failed", exc_info=True)
            return None

    # Only these schemes are ever handed to the OS. A markdown link can carry
    # anything from a `javascript:` exploit to a typo'd scheme; we never turn
    # those into a launch request.
    _SAFE_LINK_SCHEMES = ("http", "https", "ftp", "mailto", "file")

    # A local file handed to the OS shell is executed according to the user's
    # file-type associations: .py launches the interpreter, .cpl opens Control
    # Panel, .msi/.msp run installers, .js/.vbs/.wsf/.jse/.vbe run script hosts,
    # .lnk/.url resolve to whatever they point at, and so on. An extension
    # denylist is the wrong shape for this — every class left out silently
    # bypasses the prompt and is handed straight to the shell. The central
    # authorization below therefore fails CLOSED: ANY local file requires
    # explicit confirmation before the shell sees it, independent of suffix.

    @staticmethod
    def authorize_and_open_url(url, parent, lang="EN"):
        """Central target router: internal raster decoding or guarded shell open."""
        from fastprompter.ui.image_viewer import IMAGE_SUFFIXES, open_image_viewer

        raw = url.toString() if isinstance(url, QUrl) else str(url)
        if re.match(r"^[A-Za-z]:[/\\]", raw):
            url = QUrl.fromLocalFile(raw)
        elif not isinstance(url, QUrl):
            url = QUrl(raw)
        if VaultTextEdit._safe_link_url(url) is None:
            return False
        if not url.isLocalFile():
            return QDesktopServices.openUrl(url)

        from PyQt6.QtWidgets import QMessageBox

        from fastprompter.core.i18n import tr

        path = os.path.realpath(os.path.abspath(url.toLocalFile()))
        if os.path.isdir(path):
            return VaultTextEdit.open_containing_folder(parent, QUrl.fromLocalFile(path))
        if os.path.splitext(url.toLocalFile())[1].lower() in IMAGE_SUFFIXES:
            return open_image_viewer(path, parent, lang)
        msg = tr("This link points to a file on your computer:\n\n{}\n\n"
                 "Opening it may run a program. Are you sure you want to open it?",
                 lang).format(path)
        reply = QMessageBox.warning(
            parent, tr("Security Warning", lang), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return False

        return QDesktopServices.openUrl(url)

    @staticmethod
    def _safe_link_url(url):
        """Return ``url`` if its scheme is one we will actually open, else None."""
        if url is None or not isinstance(url, QUrl) or not url.isValid():
            return None
        if re.match(r"^[A-Za-z]:[/\\]", url.toString()):
            url = QUrl.fromLocalFile(url.toString())
        scheme = (url.scheme() or "").lower()
        if scheme not in VaultTextEdit._SAFE_LINK_SCHEMES:
            return None
        # A `file:` href with no path (or a bare `mailto:` with no address) is
        # not something we can usefully hand to the shell.
        if scheme in ("file", "mailto") and not url.path() and not url.encodedPath():
            return None
        return url

    def _preview_mode(self):
        """The current Source / Live Preview / Reading mode, or '' if unknown."""
        combo = getattr(getattr(self, "main_win", None), "preview_combo", None)
        if combo is None:
            return ""
        try:
            return combo.currentData() or combo.currentText()
        except Exception:
            return ""

    def _record_pending_link(self, event):
        """Live Preview only: remember a link under the press, but do NOT open.

        Opening is deferred to the release so a drag/selection that starts on a
        link still works. Plain Source-view clicks are never recorded here —
        there a link opens only on Ctrl+click (handled in mousePressEvent).
        """
        if self._preview_mode() != "Live Preview":
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                | Qt.KeyboardModifier.AltModifier):
            return
        url = self._safe_link_url(self.anchor_url_at(event.pos()))
        if url is None:
            self._pending_link = None
            return
        self._pending_link = (url, event.pos())

    def open_containing_folder(self, url):
        """Reveal a local file in the file manager.

        Was copy-pasted in three places (Ctrl+Shift+click, the context menu,
        and now Ctrl+right-click), which is two places too many for logic
        that shells out.
        """
        if url is None or not url.isLocalFile():
            return False
        path = os.path.normpath(url.toLocalFile())
        try:
            if os.name == "nt":
                # /select, needs the path as its own argument, and the comma
                # belongs to the switch - explorer is fussy about both.
                # Popen, not run: run() waits for explorer to exit, on the GUI
                # thread, with no timeout. Revealing a file on a share that has
                # gone away would freeze the window for as long as explorer
                # took to give up. Nothing here needs its exit code.
                subprocess.Popen(["explorer", "/select,", path])
            else:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(os.path.dirname(path)))
        except Exception:
            logger.debug("could not reveal %s", path, exc_info=True)
            return False
        return True

    def _watch_scroll_reset(self, value):
        """Record who threw the view back to the top.

        Reported symptom: clicking to type sometimes snaps the document to
        the very beginning. It has not been reproducible on demand, so this
        catches the moment it happens and writes the call stack to the log
        rather than guessing at a fix. Only fires on a real slam to zero
        from far down, so it cannot spam an ordinary scroll.
        """
        previous, self._last_scroll_value = self._last_scroll_value, value
        if value == 0 and previous > 200:
            import traceback
            logger.warning(
                "view jumped to the top from %s\n%s",
                previous, "".join(traceback.format_stack(limit=12)))

    def _kick_idle_timer(self):
        """Restart the 2 s idle timer — called on every scroll event."""
        self._idle_timer.start()

    def _on_idle_timeout(self):
        """Capture silo state after 2 s of inactivity (scroll-only browsing)."""
        mw = getattr(self, "main_win", None)
        if mw is not None:
            mw.capture_silo_state()
            # PERF-002: scroll-idle capture is view metadata (settings)
            mw.mark_dirty("settings")

    def rehover_from_pointer(self, point=None):
        """Re-derive the hovered line without the mouse having moved.

        Hover was only ever recomputed from mouseMoveEvent, so scrolling
        under a stationary pointer left the wash on the block number it
        started on while a different line sat under the cursor.
        """
        if self.main_win.data.get("hover_line", "True") != "True":
            return False
        if point is None:
            # Geometry, not underMouse(). `underMouse()` answers "has Qt seen
            # an enter event for me", which is False whenever the enter was
            # missed — an unfocused window, a cursor warped in by software, a
            # widget scrolled under a stationary pointer. Every one of those
            # is exactly when this method is worth calling, so it bailed out
            # in the cases it exists for. The rect test below already answers
            # the real question: is the pointer over my viewport.
            point = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(point):
            return False
        blk = self.cursorForPosition(point).block()
        new_hover = blk.blockNumber() if blk.isValid() else None
        if new_hover == getattr(self, "_hover_block", None):
            return False
        self._hover_block = new_hover
        self._last_hover_pos = point
        self.viewport().update()
        return True

    def mouseMoveEvent(self, event):
        if sip.isdeleted(self):
            return
        if (getattr(self, "_line_drag_source_block", None) is not None
                and (event.buttons() & Qt.MouseButton.LeftButton)):
            if not self._line_drag_active:
                delta = event.pos() - self._line_drag_press_pos
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self._line_drag_active = True
            if self._line_drag_active:
                self._update_line_drag_autoscroll(event.pos())
                block = self.cursorForPosition(event.pos()).block()
                new_hover = block.blockNumber() if block.isValid() else None
                if new_hover != getattr(self, "_line_drag_hover_block", None):
                    self._line_drag_hover_block = new_hover
                    self.viewport().update()
                event.accept()
                return
        if (getattr(self, "_line_drag_source_block", None) is not None
                and not (event.buttons() & Qt.MouseButton.LeftButton)):
            self._cancel_line_drag()
        try:
            if not event.buttons():
                p = event.pos()
                if (p - self._last_hover_pos).manhattanLength() > 3:
                    self._last_hover_pos = p
                    if self.main_win.data.get("hover_line", "True") == "True":
                        blk = self.cursorForPosition(p).block()
                        new_hover = blk.blockNumber() if blk.isValid() else None
                        if new_hover != getattr(self, "_hover_block", None):
                            self._hover_block = new_hover
                            # The wash is painted in paintEvent, NOT through
                            # extra selections, so asking for those to be
                            # rebuilt repainted nothing: the hover appeared
                            # to stick until some other event forced a paint
                            # (and over 2000 blocks that path bails out
                            # entirely, so it never repainted at all).
                            self.viewport().update()
                    over_target = self._interactive_target_at(p)
                    is_link = bool(self.anchorAt(p)) or bool(self.hashtag_at(p))
                    target = Qt.CursorShape.PointingHandCursor if (over_target or is_link) else Qt.CursorShape.IBeamCursor
                    cur = self.viewport().cursor()
                    if cur.shape() != target:
                        # through the main window so the user's own cursor
                        # set is honoured when that toggle is on
                        self.viewport().setCursor(
                            self.main_win.themed_cursor(target))
        except Exception as e:
            logger.debug(f"checkbox cursor error: {e}")
        if event.buttons() & Qt.MouseButton.RightButton and self._right_drag_start is not None:
            delta = event.globalPosition().toPoint() - self._right_drag_start
            if not self._dragged and delta.manhattanLength() > 3:
                self._dragged = True
            if self._dragged:
                self.main_win.move(self.main_win.pos() + delta)
                self._right_drag_start = event.globalPosition().toPoint()
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        if self._dragged:
            self._dragged = False
            event.ignore()
            return
        # Ctrl+right-click already revealed the folder on press; without this
        # the menu would still pop up over the file manager it just opened
        if getattr(self, "_suppress_context_menu", False):
            self._suppress_context_menu = False
            event.ignore()
            return
        menu = self.createStandardContextMenu()
        menu.addSeparator()

        # An image under the pointer: view it / grab it without opening
        # anything. Placed first - it is what the right-click was aimed at.
        hit = self.image_hit_at(event.pos())
        if hit is not None and hit[2].isLocalFile():
            from fastprompter.ui.image_viewer import (
                copy_image_path,
                copy_image_to_clipboard,
            )
            img_url = hit[2]
            img_path = os.path.realpath(os.path.abspath(img_url.toLocalFile()))
            img_lang = getattr(self.main_win, '_current_lang', 'EN')
            menu.addAction(
                tr("Open Image in Viewer", img_lang),
                lambda _c=False, u=img_url: VaultTextEdit.authorize_and_open_url(
                    u, self, img_lang))
            menu.addAction(
                tr("Copy Image", img_lang),
                lambda _c=False, p=img_path: copy_image_to_clipboard(p))
            menu.addAction(
                tr("Copy Image Path", img_lang),
                lambda _c=False, p=img_path: copy_image_path(p))
            menu.addSeparator()

        # Handle "Open Folder" for local file links
        url = self.anchor_url_at(event.pos())
        if url is not None and url.isLocalFile():
            path = os.path.normpath(url.toLocalFile())
            action = menu.addAction(
                f"Open folder containing {os.path.basename(path)}\tCtrl+RClick")
            action.triggered.connect(
                lambda _checked=False, u=url: self.open_containing_folder(u))
            menu.addSeparator()

        lang = getattr(self.main_win, '_current_lang', 'EN')
        # first, because it acts on what the user has just selected - the
        # reason they right-clicked - and it is disabled when nothing is
        # selected rather than hidden, so its existence is discoverable
        self.main_win.build_send_selection_menu(menu)
        menu.addSeparator()
        menu.addAction(tr("Expand All Folds", lang), self.unfold_all)
        # rare toolbar actions live here too (hidden from narrow headers)
        menu.addAction(tr("Clear Formatting", lang), self.main_win.clear_formatting)
        menu.addAction(tr("Insert Divider Line\tCtrl+W", lang), self.main_win.insert_divider_line)
        menu.addAction(tr("Insert Table", lang), self._insert_table)
        menu.addAction(tr("Insert Kanban", lang), self._insert_kanban)
        self._add_table_menu(menu, lang)
        self._add_kanban_menu(menu, lang)
        state = tr("ON", lang) if self.main_win.data.get("auto_bullet", "False") == "True" else tr("OFF", lang)
        menu.addAction(f"{tr('Auto-Bullet:', lang)} {state}", self._toggle_auto_bullet)
        # Typecheck: suggestions + "add to dictionary" for the flagged word
        # under the cursor. Built by main.py so the dictionary lives there.
        if hasattr(self.main_win, "build_spelling_menu"):
            try:
                self.main_win.build_spelling_menu(menu, event.pos())
            except Exception:
                pass
        menu.exec(event.globalPos())

    def _add_table_menu(self, menu, lang):
        """Table ops, shown only when the caret is actually in a table."""
        if not self.table_at_caret():
            return
        menu.addSeparator()
        sub = menu.addMenu(tr("SiloTable", lang))
        sub.addAction(tr("Row above", lang),
                      lambda: self.table_edit("row_above"))
        sub.addAction(tr("Row below	Enter", lang),
                      lambda: self.table_edit("row_below"))
        sub.addAction(tr("Delete row", lang),
                      lambda: self.table_edit("row_delete"))
        sub.addSeparator()
        sub.addAction(tr("Column left", lang),
                      lambda: self.table_edit("col_left"))
        sub.addAction(tr("Column right", lang),
                      lambda: self.table_edit("col_right"))
        sub.addAction(tr("Delete column", lang),
                      lambda: self.table_edit("col_delete"))
        sub.addSeparator()
        sub.addAction(tr("Align left", lang),
                      lambda: self.table_edit("align_left"))
        sub.addAction(tr("Align center", lang),
                      lambda: self.table_edit("align_center"))
        sub.addAction(tr("Align right", lang),
                      lambda: self.table_edit("align_right"))
        sub.addSeparator()
        sub.addAction(tr("Tidy up the pipes", lang), self.table_realign)

    def _add_kanban_menu(self, menu, lang):
        """Board ops, shown only when the caret is on a card."""
        if not self.in_kanban():
            return
        menu.addSeparator()
        sub = menu.addMenu(tr("SiloKanban", lang))
        sub.addAction(tr("Move card left	Alt+Left", lang),
                      lambda: self.kanban_move(dx=-1))
        sub.addAction(tr("Move card right	Alt+Right", lang),
                      lambda: self.kanban_move(dx=1))
        sub.addAction(tr("Move card up	Alt+Up", lang),
                      lambda: self.kanban_move(dy=-1))
        sub.addAction(tr("Move card down	Alt+Down", lang),
                      lambda: self.kanban_move(dy=1))
        sub.addSeparator()
        sub.addAction(tr("Tick / untick card", lang), self.kanban_toggle)
        sub.addAction(tr("New card in this column", lang), self.kanban_add_card)

    # ---- SiloTable / SiloKanban -------------------------------------------
    #
    # Both are markdown, not widgets. A silo is stored as plain text — that is
    # what the DB holds, what the disk mirror writes and what gets pasted into
    # an agent — so a QTextTable would look right until the first save and
    # then be gone. The text IS the table; these methods give it behaviour.

    def _doc_lines(self):
        return self.toPlainText().split("\n")

    def _replace_lines(self, first, last, new_lines, caret_line=None,
                       caret_col=0, select_to=None):
        """Swap lines [first, last] for `new_lines` as ONE undo step."""
        doc = self.document()
        start_block = doc.findBlockByNumber(first)
        end_block = doc.findBlockByNumber(last)
        if not start_block.isValid() or not end_block.isValid():
            return False
        from fastprompter.ui.edit_guard import edit_block

        # A QTextBlock carries the margin mark for its line, and replacing
        # text destroys every block it spans. Remember marks by POSITION
        # first (same text at same position = exact match), then by CONTENT
        # as fallback so a moved card keeps its mark. Two-level: position
        # match avoids the duplicate-text bug (two identical lines trading
        # states when one is rewritten), content fallback preserves marks
        # across kanban reorder where lines genuinely move.
        old_state_by_pos = {}
        old_state_by_text = {}
        for n in range(first, last + 1):
            blk = doc.findBlockByNumber(n)
            if blk.isValid() and blk.userState() > 0:
                old_state_by_pos[(blk.text(), n - first)] = blk.userState()
                old_state_by_text.setdefault(blk.text(), []).append(blk.userState())

        cursor = self.textCursor()
        # guarded: an exception between begin and end leaves the document
        # stuck inside an edit block forever, which is the whole history of
        # "the app froze after formatting" in this codebase
        with edit_block(cursor, self):
            cursor.setPosition(start_block.position())
            cursor.setPosition(end_block.position() + len(end_block.text()),
                               QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText("\n".join(new_lines))

        for offset, text in enumerate(new_lines):
            blk = doc.findBlockByNumber(first + offset)
            if not blk.isValid():
                continue
            # Exact (text, position) match wins — handles unchanged lines
            key = (text, offset)
            if key in old_state_by_pos:
                blk.setUserState(old_state_by_pos[key])
                continue
            # Fallback: text match for reordered lines (kanban move)
            states = old_state_by_text.get(text)
            if states:
                blk.setUserState(states.pop(0))

        if caret_line is not None:
            target = doc.findBlockByNumber(caret_line)
            if target.isValid():
                cursor.setPosition(target.position() + min(caret_col, len(target.text())))
                if select_to is not None:
                    cursor.setPosition(
                        target.position() + min(select_to, len(target.text())),
                        QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def table_at_caret(self):
        """(Table, line index, column index) for the caret, or None."""
        from fastprompter.ui import silo_table as st
        cursor = self.textCursor()
        line = cursor.blockNumber()
        lines = self._doc_lines()
        table = st.parse(lines, line)
        if table is None:
            return None
        col = st.cell_index(lines[line], cursor.positionInBlock())
        return table, line, col

    def _table_body_index(self, table, line):
        """Which BODY row a document line is, skipping the separator."""
        from fastprompter.ui import silo_table as st
        lines = self._doc_lines()
        idx = -1
        for i in range(table.first_block, min(line + 1, table.last_block + 1)):
            if st.is_separator_row(lines[i]) and i > table.first_block:
                continue
            if st.is_separator_row(lines[i]) and i == table.first_block:
                continue
            idx += 1
        return max(0, idx)

    def _table_line_of_body(self, table, body_index):
        """Inverse of _table_body_index, on the CURRENT text."""
        from fastprompter.ui import silo_table as st
        lines = self._doc_lines()
        idx = -1
        for i in range(table.first_block, table.last_block + 1):
            if i >= len(lines):
                break
            if st.is_separator_row(lines[i]):
                continue
            idx += 1
            if idx == body_index:
                return i
        return table.last_block

    def table_move_cell(self, forward=True):
        """Tab / Shift+Tab: next or previous cell, its content selected.

        Walks off the end of a row into the next one, and off the end of the
        table into a fresh row — the behaviour every table editor has and the
        reason a markdown table is otherwise miserable to fill in.
        """
        from fastprompter.ui import silo_table as st
        found = self.table_at_caret()
        if not found:
            return False
        table, line, col = found
        lines = self._doc_lines()
        width = max(table.columns, len(table.aligns))

        target_col = col + (1 if forward else -1)
        target_line = line
        if target_col >= width or target_col < 0:
            step = 1 if forward else -1
            target_line = line + step
            # the separator is not a cell the user can type in
            while (table.first_block <= target_line <= table.last_block
                   and st.is_separator_row(lines[target_line])):
                target_line += step
            target_col = 0 if forward else width - 1
            if target_line > table.last_block:
                if not forward:
                    return False
                body = self._table_body_index(table, table.last_block)
                grown = st.with_row(table, body)
                rendered = st.render(grown)
                if not self._replace_lines(table.first_block, table.last_block,
                                           rendered):
                    return False
                new_last = table.first_block + len(rendered) - 1
                span = st.cell_span(self._doc_lines()[new_last], 0)
                return self._place_caret(new_last, span)
            if target_line < table.first_block:
                return False

        span = st.cell_span(lines[target_line], target_col)
        return self._place_caret(target_line, span)

    def _place_caret(self, line, span):
        doc = self.document()
        block = doc.findBlockByNumber(line)
        if not block.isValid():
            return False
        cursor = self.textCursor()
        cursor.setPosition(block.position() + min(span[0], len(block.text())))
        if span[1] > span[0]:
            cursor.setPosition(block.position() + min(span[1], len(block.text())),
                               QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def table_new_row(self):
        """Enter inside a table: a fresh row under this one, caret in cell 1."""
        from fastprompter.ui import silo_table as st
        found = self.table_at_caret()
        if not found:
            return False
        table, line, _col = found
        body = self._table_body_index(table, line)
        grown = st.with_row(table, body)
        rendered = st.render(grown)
        if not self._replace_lines(table.first_block, table.last_block, rendered):
            return False
        new_line = self._table_line_of_body(
            st.Table(table.first_block, table.first_block + len(rendered) - 1,
                     grown.rows, grown.aligns, grown.has_header), body + 1)
        span = st.cell_span(self._doc_lines()[new_line], 0)
        return self._place_caret(new_line, span)

    def table_realign(self):
        """Re-render the table under the caret with every pipe lined up."""
        from fastprompter.ui import silo_table as st
        found = self.table_at_caret()
        if not found:
            return False
        table, line, col = found
        rendered = st.render(table)
        current = self._doc_lines()[table.first_block:table.last_block + 1]
        if current == rendered:
            return False                     # already tidy: no undo entry
        offset = line - table.first_block
        if not self._replace_lines(table.first_block, table.last_block, rendered):
            return False
        new_line = min(table.first_block + offset,
                       table.first_block + len(rendered) - 1)
        span = st.cell_span(self._doc_lines()[new_line], col)
        return self._place_caret(new_line, (span[0], span[0]))

    def table_edit(self, action):
        """Structural table ops, driven from the context menu."""
        from fastprompter.ui import silo_table as st
        found = self.table_at_caret()
        if not found:
            return False
        table, line, col = found
        body = self._table_body_index(table, line)
        ops = {
            "row_above": lambda t: st.with_row(t, body - 1),
            "row_below": lambda t: st.with_row(t, body),
            "row_delete": lambda t: st.without_row(t, body),
            "col_left": lambda t: st.with_column(t, col - 1),
            "col_right": lambda t: st.with_column(t, col),
            "col_delete": lambda t: st.without_column(t, col),
            "align_left": lambda t: st.set_align(t, col, st.ALIGN_LEFT),
            "align_center": lambda t: st.set_align(t, col, st.ALIGN_CENTER),
            "align_right": lambda t: st.set_align(t, col, st.ALIGN_RIGHT),
        }
        op = ops.get(action)
        if op is None:
            return False
        changed = op(table)
        rendered = st.render(changed)
        offset = min(line - table.first_block, len(rendered) - 1)
        if not self._replace_lines(table.first_block, table.last_block, rendered):
            return False
        new_line = table.first_block + max(0, offset)
        lines = self._doc_lines()
        if new_line < len(lines):
            span = st.cell_span(lines[new_line], min(col, changed.columns - 1))
            self._place_caret(new_line, (span[0], span[0]))
        return True

    def kanban_move(self, dx=0, dy=0):
        """Alt+arrows: move the card under the caret across the board."""
        from fastprompter.ui import silo_kanban as sk
        lines = self._doc_lines()
        line = self.textCursor().blockNumber()
        moved = sk.move_card(lines, line, dx, dy)
        if moved is None:
            return False
        new_lines, at = moved
        # Rewrite the BOARD, not the silo. A move only rearranges lines
        # inside the board, and rewriting everything threw away the blocks —
        # and the margin marks — of text that has nothing to do with it.
        span = sk.board_span(lines)
        if span is None:
            return False
        first, last = span
        if not self._replace_lines(first, last, new_lines[first:last + 1]):
            return False
        block = self.document().findBlockByNumber(at)
        if block.isValid():
            cursor = self.textCursor()
            cursor.setPosition(block.position() + len(block.text()))
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
        return True

    def kanban_toggle(self):
        from fastprompter.ui import silo_kanban as sk
        lines = self._doc_lines()
        line = self.textCursor().blockNumber()
        out = sk.toggle_card(lines, line)
        if out is None:
            return False
        col = self.textCursor().positionInBlock()
        # exactly one line changes: rewrite exactly that line
        return self._replace_lines(line, line, [out[line]], caret_line=line,
                                   caret_col=col)

    def kanban_add_card(self):
        from fastprompter.ui import silo_kanban as sk
        lines = self._doc_lines()
        line = self.textCursor().blockNumber()
        added = sk.add_card(lines, line)
        if added is None:
            return False
        out, at = added
        span = sk.board_span(lines)
        if span is None:
            return False
        first, last = span
        # one line longer than the span it replaces
        return self._replace_lines(first, last, out[first:last + 2],
                                   caret_line=at, caret_col=len(out[at]))

    def in_kanban(self):
        from fastprompter.ui import silo_kanban as sk
        lines = self._doc_lines()
        board = sk.parse(lines)
        return board.card_at(self.textCursor().blockNumber()) is not None

    def _insert_table(self):
        from PyQt6.QtWidgets import (
            QDialog,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
        )
        
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Insert Table", getattr(self.main_win, "_current_lang", "EN")))
        dlg.setStyleSheet(self.main_win.styleSheet())
        layout = QVBoxLayout(dlg)
        
        grid = QGridLayout()
        grid.addWidget(QLabel(tr("Rows:", getattr(self.main_win, "_current_lang", "EN"))), 0, 0)
        spin_rows = QSpinBox()
        spin_rows.setRange(1, 100)
        spin_rows.setValue(3)
        grid.addWidget(spin_rows, 0, 1)
        
        grid.addWidget(QLabel(tr("Columns:", getattr(self.main_win, "_current_lang", "EN"))), 1, 0)
        spin_cols = QSpinBox()
        spin_cols.setRange(1, 100)
        spin_cols.setValue(3)
        grid.addWidget(spin_cols, 1, 1)
        
        layout.addLayout(grid)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        if dlg.exec():
            r = spin_rows.value()
            c = spin_cols.value()
            
            from fastprompter.ui import silo_table as st
            table = st.new_table(r, c)
            lines = st.render(table)
            cursor = self.textCursor()
            cursor.insertText("\n".join(lines) + "\n")

    def _insert_kanban(self):
        from fastprompter.ui import silo_kanban as sb
        cursor = self.textCursor()
        cursor.insertText("\n".join(sb.new_board()) + "\n")

    def _toggle_auto_bullet(self):
        # goes through the main window so the change is saved and the
        # toolbar button/tooltip stay in step with it
        cur = self.main_win.data.get("auto_bullet", "False") == "True"
        self.main_win.set_auto_bullet(not cur)
        self.main_win.mark_dirty()

    def _ask_binary_drop_choice(self, name):
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self.main_win)
        lang = getattr(self.main_win, '_current_lang', 'EN')
        box.setWindowTitle(tr("Add dropped file", lang))
        box.setText(tr("How should '{}' be added?", lang).format(name))
        btn_file = box.addButton(tr("📥 Copy to Silo Files 📁", lang), QMessageBox.ButtonRole.AcceptRole)
        btn_files_link = box.addButton(tr("🔗 Link in Silo Files 📁", lang), QMessageBox.ButtonRole.ActionRole)
        btn_editor_link = box.addButton(tr("🔗 Link in Text", lang), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_file)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_file: return "file"
        if clicked is btn_files_link: return "files_link"
        if clicked is btn_editor_link: return "editor_link"
        return "cancel"

    def _drop_overlay(self):
        from fastprompter.ui.drop_overlay import DropOverlay
        if getattr(self, "_overlay", None) is None:
            self._overlay = DropOverlay(self)
        return self._overlay

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.isLocalFile() for u in event.mimeData().urls()
        ):
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            any_text = any(
                os.path.splitext(p)[1].lower() in TEXT_EXTENSIONS
                or not os.path.splitext(p)[1]
                for p in paths
            )
            self._drop_overlay().begin(has_text_option=any_text)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None and ov.isVisible():
            ov.track(event.position().toPoint())
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None:
            ov.end()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        ov = getattr(self, "_overlay", None)
        if ov is not None and ov.isVisible():
            zone = ov.zone_at(event.position().toPoint())
            ov.end()
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self._drop_paths(paths, zone)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _drop_paths(self, paths, zone):
        """Route dropped files according to the chosen zone."""
        to_files = []
        to_links = []
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            is_text = ext in TEXT_EXTENSIONS or not ext
            if zone == "text" and is_text:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        self.insertPlainText(f.read())
                except OSError:
                    import traceback
                    traceback.print_exc()
            elif zone == "editor_link":
                name = os.path.basename(path)
                clean_path = path.replace("\\", "/")
                self.insertPlainText(f"[{name}](file:///{clean_path})")
            elif zone == "files_link":
                to_links.append(path)
            else:
                to_files.append(path)

        if to_files:
            self.main_win.add_files_to_active_silo(to_files)
        if to_links:
            self.main_win.add_links_to_active_silo(to_links)

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp",
                        ".webp", ".ico", ".tif", ".tiff", ".svg"}

    def image_paste_markup(self, name, url):
        """How a pasted image should land in the text.

        `pill` — the default and what it always used to be — is `![](...)`,
        the only shape `MD_IMAGE_RE` matches and therefore the only one the
        painter collapses into the golden chip you can click to open. A
        pasted image PATH went in as `[name](...)` instead: a plain markdown
        link, no chip, and nothing to click, which is the regression.
        `link` keeps that plain link, `path` inserts the bare path.
        """
        url = QUrl(url).toString(QUrl.ComponentFormattingOption.FullyEncoded)
        url = url.replace("(", "%28").replace(")", "%29")
        try:
            style = self.main_win.data.get("image_paste_style", "pill")
        except Exception:
            style = "pill"
        if style == "path":
            return url
        if style == "link":
            return f"[{name}]({url})"
        return f"![]({url})"

    def _paste_image_inline(self, markup):
        """Insert pasted image markup at the caret, with no forced new line.

        Both image paste branches used to append ``"\\n"`` (and, mid-line,
        prefix one as well), so every pasted screenshot shoved the caret onto
        a fresh line whether the user wanted that or not — the single most
        common complaint about pasting a picture. A caret sitting in the
        middle of a word gets a separating space instead of a line break, so
        the markup never glues itself onto the neighbouring text.
        """
        cursor = self.textCursor()
        block = cursor.block()
        pos = cursor.positionInBlock()
        before = block.text()[:pos]
        prefix = "" if (pos == 0 and not before.strip()) or (
            not before or before[-1].isspace()) else " "
        self.insertPlainText(f"{prefix}{markup}")

    # ------------------------------------------------------------------
    # T-1269C append — the Ctrl+V LIVE route, made answerable
    # ------------------------------------------------------------------
    #
    # The operator's report is "the paste sound plays and no text appears",
    # intermittently, on the real window. ``keyPressEvent`` emits the cue
    # BEFORE the paste runs, so the sound proves only that the key path was
    # reached — never that the document changed. Two questions must be
    # answerable from evidence instead of from a green unit test:
    #
    #   1. was the key path reached, and did ``self.paste()`` run?
    #      -> ``_paste_from_keyboard`` / ``_paste_key_path``
    #   2. which insertFromMimeData branch ran, and did it change anything?
    #      -> ``_insert_from_mime_data`` returns a branch LABEL and
    #         ``_finish_paste`` compares the document revision around it
    #
    # A rich branch that yields NOTHING while the same clipboard also carries
    # usable plain text now falls back to the text representation. That is the
    # MIME differential the operator hit from the other side: NEW reads
    # ``clipboard.text()`` (``SnippetOpsMixin._clipboard_text_for_new_silo``)
    # and seeds a silo, while Ctrl+V picks its branch from the FORMATS present
    # and could return with neither a document change nor a file/link action.
    #
    # NOTHING here records clipboard CONTENT — lengths, flags, counts, object
    # identities only. The ring is bounded per editor, and a record is written
    # only by a paste attempt, so ordinary typing cannot grow it.
    _PASTE_DIAG_LIMIT = 20

    def paste_diagnostics(self):
        """The bounded Ctrl+V record ring, oldest first. No clipboard text."""
        return list(getattr(self, "_paste_diag", ()))

    def _paste_contract(self, record):
        """Add the three route questions every record must answer.

        The acceptance asks, for any attempted paste: was ``keyPressEvent``
        reached, was ``self.paste()`` called, and was ``insertFromMimeData``
        reached at all? A successful record answers yes to all three by
        construction -- stating it here keeps every record the same shape, so
        the failing one and the working one can be compared field for field.
        """
        record["key_path_reached"] = bool(getattr(self, "_paste_key_path", False))
        record["paste_called"] = bool(
            getattr(self, "_paste_paste_called", False))
        record["insert_reached"] = bool(
            getattr(self, "_paste_insert_reached", False))
        return record

    def _paste_state(self):
        """Metadata about the paste TARGET — not one byte of clipboard text.

        This is the "prove it at failure time" set: editor and document
        identity, the document the ACTIVE silo owns, caret/selection, the
        focus widget, the view page, and the writable/visible/enabled state
        of the editor. Recorded before and after every paste attempt.
        """
        mw = self.main_win
        slot = getattr(mw, "active_temp_slot", None)
        state = {
            "editor_id": id(self),
            "document_id": None,
            "document_revision": None,
            "silo_document_id": None,
            "active_category": None,
            "active_slot": slot,
            "active_is_archive": bool(getattr(mw, "active_is_archive", False)),
            "cursor_position": None,
            "has_selection": None,
            "editor_visible": None,
            "editor_enabled": None,
            "editor_read_only": None,
            "focus_widget": None,
            "focus_widget_id": None,
            "preview_mode": None,
            "silo_view_page": None,
            "document_owned_by_active_silo": None,
            "event_key": None,
            "event_modifiers": None,
            "native_scan_code": None,
        }
        event_meta = getattr(self, "_paste_event_meta", None) or {}
        state.update({key: event_meta.get(key) for key in (
            "event_key", "event_modifiers", "native_scan_code")})
        try:
            state["active_category"] = mw.get_current_category()
        except Exception:
            pass
        try:
            state["document_id"] = id(self.document())
            state["document_revision"] = self.document().revision()
        except Exception:
            pass
        docs = getattr(
            mw,
            "archive_docs" if bool(getattr(mw, "active_is_archive", False))
            else "silo_docs",
            None,
        )
        if (isinstance(docs, (list, tuple)) and isinstance(slot, int)
                and 0 <= slot < len(docs)):
            owner_doc = docs[slot]
            state["silo_document_id"] = id(owner_doc)
            state["document_owned_by_active_silo"] = (
                owner_doc is self.document())
        try:
            cursor = self.textCursor()
            state["cursor_position"] = cursor.position()
            state["has_selection"] = bool(cursor.hasSelection())
            state["editor_visible"] = bool(self.isVisible())
            state["editor_enabled"] = bool(self.isEnabled())
            state["editor_read_only"] = bool(self.isReadOnly())
        except Exception:
            pass
        focus = QApplication.focusWidget()
        state["focus_widget"] = type(focus).__name__ if focus is not None else None
        state["focus_widget_id"] = id(focus) if focus is not None else None
        try:
            state["preview_mode"] = self._preview_mode()
        except Exception:
            pass
        try:
            state["silo_view_page"] = mw.silo_view.currentIndex()
        except Exception:
            pass
        return state

    def _clipboard_generation_probe(self, label=""):
        """One bounded OS + Qt clipboard generation sample -- never content.

        T-1269 A2: the Windows clipboard sequence number (the OS's own
        generation counter), the process that owns the clipboard, and the
        Qt-side notification count are gathered together, because a paste
        failure can sit on EITHER side of that boundary. Nothing here reads,
        copies, stores or logs clipboard text: the record carries lengths,
        flags, counters and a process name only. Every lookup is optional -- an
        unavailable API or a protected owner leaves a None/UNKNOWN entry
        instead of breaking the paste it is observing.
        """
        from fastprompter.core.win_clipboard import clipboard_generation
        try:
            probe = clipboard_generation(label)
        except Exception:
            probe = {"label": label, "monotonic": None, "sequence": None,
                     "owner": {}}
        try:
            from fastprompter.ui.clipboard_watch import (
                clipboard_watch_snapshot,
            )
            probe["qclipboard"] = clipboard_watch_snapshot()
        except Exception:
            probe["qclipboard"] = {}
        return probe

    def _apply_paste_clipboard_contract(self, record):
        """Attach the clipboard GENERATION evidence to one paste record.

        T-1269 A3: the three samples of one attempt -- key entry, immediately
        before the MIME payload is read, immediately after the paste returns --
        are compared here. If the OS generation moved between them, then an
        external clipboard owner replaced the payload WHILE the paste ran, and
        the record says so (``clipboard_changed_during_paste`` plus
        ``failure_class: clipboard_ownership_race``) instead of quietly
        presenting an older payload as the operator's newest copy.
        """
        from fastprompter.core.win_clipboard import (
            UNKNOWN,
            clipboard_race_evidence,
        )
        key_entry = (record.get("clipboard_key_entry")
                     or getattr(self, "_paste_clip_key_entry", None))
        mime_read = (record.get("clipboard_at_mime_read")
                     or getattr(self, "_paste_clip_mime_read", None))
        after = (record.get("clipboard_after_paste")
                 or getattr(self, "_paste_clip_after_paste", None))
        record["clipboard_key_entry"] = key_entry
        record["clipboard_at_mime_read"] = mime_read
        record["clipboard_after_paste"] = after
        try:
            evidence = clipboard_race_evidence((
                ("key_entry", key_entry),
                ("mime_read", mime_read),
                ("after_paste", after),
            ))
        except Exception:
            evidence = {"evidence": "unknown", "changed": False,
                        "sequences": {}, "owner_processes": [], "owner": {}}
        record["clipboard_race"] = evidence
        record["clipboard_changed_during_paste"] = bool(evidence["changed"])
        owner = evidence.get("owner") or {}
        if not owner:
            # An unresolved owner is still a SHAPED owner: the acceptance says
            # an unresolvable lookup must read UNKNOWN, and a consumer that has
            # to guess whether a key is missing or a lookup failed cannot tell
            # "no owner" from "this record is older than the field" (measured:
            # a paste on a machine whose clipboard had no live owner produced a
            # record with NO clipboard_owner key at all).
            owner = {"status": "unknown", "hwnd": None, "pid": None,
                     "process": UNKNOWN, "is_self": None}
        record["clipboard_owner"] = owner
        record["clipboard_owner_process"] = owner.get("process")
        record["failure_class"] = classify_paste_failure(record)
        return record

    def _close_paste_record(self):
        """Re-score the newest record now that the whole attempt has ended.

        The record is written while ``self.paste()`` runs -- that is, BEFORE
        the post-paste clipboard sample exists. Closing it here is what lets
        the third sample prove (or disprove) a race that began mid-paste.
        """
        record = getattr(self, "_paste_last_record", None)
        if isinstance(record, dict):
            self._apply_paste_clipboard_contract(record)

    def _log_clipboard_race(self, record):
        """One attributable warning when the OS clipboard moved mid-paste.

        Emitted at most once per record, and never containing clipboard text:
        generation numbers and the owning process name are the whole payload,
        so the operator can name the competing owner (ClipDiary, a clipboard+
        script, the OS clipboard history) instead of being told "try again".
        """
        if not record.get("clipboard_changed_during_paste"):
            return
        if record.get("clipboard_race_logged"):
            return
        record["clipboard_race_logged"] = True
        race = record.get("clipboard_race") or {}
        logger.warning(
            "Ctrl+V: the Windows clipboard generation changed DURING this "
            "paste (sequences=%s, owner processes=%s). The payload this paste "
            "consumed may not be the item that was copied last; the owner "
            "processes above identify the competing writer. record=%s",
            race.get("sequences"), race.get("owner_processes"), record)

    def paste_key_router_evidence(self):
        """Class-1 (key routing) evidence for the intermittent report.

        A Ctrl+V that never reaches FastPrompter writes no record, so "nothing
        was inserted" and "the key never arrived" would be indistinguishable
        from the ring alone. This heartbeat separates them: the counter moves
        only when a real Ctrl+V key event reaches this editor.
        """
        records = list(getattr(self, "_paste_diag", ()) or ())
        return {
            "key_events_seen": int(getattr(self, "_paste_key_events_seen", 0)),
            "last_key_monotonic": getattr(
                self, "_paste_last_key_monotonic", None),
            "record_count": len(records),
            "records_without_key_path": sum(
                1 for r in records if not r.get("key_path_reached")),
            "failure_classes": [r.get("failure_class") for r in records],
        }

    def _record_paste_diag(self, record):
        """Append to the bounded ring and hand the record back."""
        ring = getattr(self, "_paste_diag", None)
        if ring is None:
            ring = self._paste_diag = []
        # T-1269 A2/A3: every paste record leaves through this one door, so the
        # clipboard-generation contract and the failure classification are
        # applied uniformly -- the refusal, the no-callback and the ordinary
        # records all end up the same shape.
        record = self._apply_paste_clipboard_contract(record)
        ring.append(record)
        limit = self._PASTE_DIAG_LIMIT
        if len(ring) > limit:
            del ring[:-limit]
        self._paste_last_record = record
        self._log_clipboard_race(record)
        return record

    def _paste_block_reason(self):
        """Why the Ctrl+V cue AND the paste must be declined, or None.

        Read-only is the one state a real key event still reaches: Qt delivers
        the key, this handler runs, and an unconditional ``self.paste()`` is
        swallowed by ``insertFromMimeData``'s read-only guard — so the cue
        that ``keyPressEvent`` already played was a lie. Suppressing the cue
        exactly when the paste is refused is the fix; forcing the insertion
        would be the bug.

        A hidden or disabled widget never receives the key in the first place,
        so those two states are RECORDED by ``_paste_state`` (the contract
        requires proving them at failure time) but do not block the handler:
        programmatic and QTest routes to a not-yet-shown editor must keep
        working, and "no cue" there is already guaranteed by Qt.
        """
        try:
            if self.isReadOnly():
                return "read_only"
            if not self.isEnabled():
                return "disabled"
        except RuntimeError:      # underlying C++ object already gone
            return "deleted"
        return None

    def _paste_from_keyboard(self, event=None):
        """Ctrl+V's single entry point — the live key route, instrumented.

        Keeping the refusal here (and not inside ``insertFromMimeData``) is
        what lets the diagnostics separate the two failure classes the
        operator's report cannot distinguish on its own:

        * "key path reached, then the MIME/paste step produced nothing" — an
          in-app defect, which the records below name exactly;
        * "key path never reached" — which would point outside the app
          (another window, a shortcut owner, an external tool) and is
          recorded as ``paste_called: False``.
        """
        if event is not None:
            try:
                self._paste_event_meta = {
                    "event_key": int(event.key()),
                    "event_modifiers": int(event.modifiers().value),
                    "native_scan_code": int(event.nativeScanCode()),
                }
            except Exception:
                self._paste_event_meta = {}
        # T-1269 A1: the key-path heartbeat. A Ctrl+V that never reaches
        # FastPrompter writes NO record at all, so "nothing was inserted" and
        # "the app never saw the key" would look identical in the ring. These
        # counters move only when a real Ctrl+V key event arrives here, which
        # is what makes class 1 (key routing) decidable from evidence.
        self._paste_key_events_seen = (
            getattr(self, "_paste_key_events_seen", 0) + 1)
        # T-1269 A3: the OS clipboard GENERATION at the key entry. Two more
        # samples follow -- immediately before the MIME payload is read, and
        # immediately after the paste returns. A generation that moves between
        # them means an external clipboard owner (ClipDiary, a clipboard+
        # script, the OS clipboard history) rewrote the payload mid-paste.
        self._paste_last_record = None
        self._paste_clip_key_entry = self._clipboard_generation_probe(
            "key_entry")
        self._paste_clip_mime_read = None
        self._paste_clip_after_paste = None
        self._paste_last_key_monotonic = (
            self._paste_clip_key_entry or {}).get("monotonic")
        # The key DID reach this route, refusal or not: that is the class-1 /
        # class-2 boundary, and every record has to state it.
        self._paste_key_path = True
        self._paste_paste_called = False
        self._paste_insert_reached = False
        reason = self._paste_block_reason()
        if reason is not None:
            before = self._paste_state()
            mime_info = describe_clipboard_mime(
                QApplication.clipboard().mimeData())
            after = self._paste_state()
            record = self._paste_contract(_paste_record(
                "refused:" + reason, mime_info, before, after, False))
            self._record_paste_diag(record)
            logger.debug(
                "Ctrl+V declined in the editor (%s); no paste cue played and "
                "nothing was inserted: %s", reason, record)
            self._paste_event_meta = None
            self._paste_key_path = False
            return
        self._paste_paste_called = True
        self._paste_insert_reached = False
        self._paste_diagnostics_active = True
        before = self._paste_state()
        paste_error = False
        try:
            self.paste()
        except Exception:
            paste_error = True
            logger.exception("Ctrl+V paste call failed")
        finally:
            # A3: the third generation sample -- taken once the paste returned.
            self._paste_clip_after_paste = self._clipboard_generation_probe(
                "after_paste")
            # The attempt is over, so the record written while `paste()` ran
            # can be judged with all three clipboard samples in hand.
            self._close_paste_record()
            self._paste_diagnostics_active = False
        if not self._paste_insert_reached:
            after = self._paste_state()
            record = self._paste_contract(_paste_record(
                "paste_error" if paste_error else "paste_no_insert_callback",
                describe_clipboard_mime(QApplication.clipboard().mimeData()),
                before, after, False))
            self._record_paste_diag(record)
            logger.warning(
                "Ctrl+V reached the editor but insertFromMimeData was not "
                "reached: record=%s", record)
        self._paste_key_path = False
        self._paste_event_meta = None

    def insertFromMimeData(self, source):
        self._paste_insert_reached = True
        if self._paste_diagnostics_active:
            # A3: the second generation sample -- immediately before the MIME
            # payload is read by the branch below.
            self._paste_clip_mime_read = self._clipboard_generation_probe(
                "mime_read")
        if self.isReadOnly():
            if not self._paste_diagnostics_active:
                return
            before = self._paste_state()
            after = self._paste_state()
            record = self._paste_contract(_paste_record(
                "refused:read_only", describe_clipboard_mime(source),
                before, after, False))
            self._record_paste_diag(record)
            return

        before = self._paste_state()
        mime_info = describe_clipboard_mime(source)
        branch = self._insert_from_mime_data(source)
        self._finish_paste(branch, source, mime_info, before)

    def _finish_paste(self, branch, source, mime_info, before):
        """The paste RESULT contract, checked against the document itself.

        For a writable editor holding a text-capable clipboard, a paste that
        reached a branch and changed NOTHING is a real failure — unless the
        branch deliberately did something else (attached a file, recorded a
        link, read a file whose content is empty). Those cases are settled
        branches; everything else falls back to the plain text the same
        clipboard already carries, so no branch can silently do nothing while
        usable text is available.
        """
        settled = bool(getattr(self, "_paste_settled", False))
        changed = (before.get("document_revision") is not None
                   and before.get("document_revision")
                   != self._document_revision())
        text = (_mime_text(source) if source is not None
                and mime_info.get("has_text") else "")
        if not changed and text and not settled:
            self.insertPlainText(text)
            branch += "+text_fallback"
            after = self._paste_state()
            if self._paste_diagnostics_active:
                record = _paste_record(branch, mime_info, before, after,
                                       fallback=True)
                record["branch_settled"] = settled
                record = self._paste_contract(record)
                self._record_paste_diag(record)
                logger.warning(
                    "Ctrl+V: MIME branch produced no document change; the "
                    "plain-text representation was inserted instead. "
                    "clipboard=%s record=%s", mime_info, record)
            return
        after = self._paste_state()
        if not self._paste_diagnostics_active:
            return
        record = _paste_record(branch, mime_info, before, after,
                               fallback=False)
        record["branch_settled"] = settled
        record = self._paste_contract(record)
        self._record_paste_diag(record)
        if (not changed and not settled
                and mime_info.get("text_stripped_length")):
            logger.warning(
                "Ctrl+V produced NO document change and no file/link action "
                "although the clipboard carries usable text. clipboard=%s "
                "record=%s", mime_info, record)

    def _document_revision(self):
        try:
            return self.document().revision()
        except Exception:
            return None

    def _insert_from_mime_data(self, source):
        """The MIME-aware insert, returning the BRANCH it took.

        Behaviour is unchanged; the label is what turns "nothing appeared"
        into a named cause, and `self._paste_settled` records whether the
        branch deliberately consumed the paste even with no text inserted
        (file attached, dialog answered, empty file read).
        """
        self._paste_settled = False
        try:
            has_urls = bool(source.hasUrls())
        except Exception:
            has_urls = False
        try:
            has_image = bool(source.hasImage())
        except Exception:
            has_image = False
        urls = _mime_urls(source) if has_urls else []
        if has_urls and (not has_image or any(u.isLocalFile() for u in urls)):
            # Paste of copied files (Ctrl+V from Explorer) — no drag overlay.
            # A text-based file lands as its CONTENT, no dialog (T-752): the
            # user asked the silo to read files, so a copied .md/.py/.txt
            # pastes what it holds. Binary files keep the file/link choice.
            labels = []
            for url in urls:
                if url.isLocalFile():
                    path = url.toLocalFile()
                    ext = os.path.splitext(path)[1].lower()
                    if ext in self.IMAGE_EXTENSIONS:
                        labels.append("urls_image")
                        self._paste_settled = True
                        # T-1330: no forced line break. The image lands where
                        # the caret is; the user decides what follows it.
                        self._paste_image_inline(self.image_paste_markup(
                            os.path.basename(path), url.toString(QUrl.ComponentFormattingOption.FullyEncoded)))
                    elif ext in TEXT_EXTENSIONS or not ext:
                        try:
                            text_to_insert = _read_text_file(path)
                            labels.append("urls_file_text")
                            if text_to_insert:
                                self._paste_settled = True
                                self.insertPlainText(text_to_insert)
                            else:
                                labels.append("urls_file_empty")
                        except Exception:
                            # The read itself failed: NOT settled, so usable
                            # text on the same clipboard still reaches the
                            # caret instead of the paste vanishing
                            # (T-1269C append).
                            labels.append("urls_file_unreadable")
                            logger.debug(
                                "Ctrl+V local text-file URL read failed "
                                "(URL count=%s)", len(urls), exc_info=True)
                    else:
                        choice = self._ask_binary_drop_choice(os.path.basename(path))
                        if choice == "file":
                            labels.append("urls_binary_file")
                            self._paste_settled = True
                            self.main_win.add_files_to_active_silo([path])
                        elif choice == "files_link":
                            labels.append("urls_binary_link")
                            self._paste_settled = True
                            self.main_win.add_links_to_active_silo([path])
                        elif choice == "editor_link":
                            labels.append("urls_editor_link")
                            self._paste_settled = True
                            name = os.path.basename(path)
                            clean_path = path.replace("\\", "/")
                            text_to_insert = f"[{name}](file:///{clean_path})"
                            self.insertPlainText(text_to_insert)
                        else:
                            # Dismissed / unusable answer: deliberately NOT
                            # settled, so plain text (when present) is used.
                            labels.append("urls_binary_cancelled")
                else:
                    labels.append("urls_remote")
                    url_text = url.toString()
                    if url_text:
                        self._paste_settled = True
                        self.insertPlainText(url_text + "\n")
                    else:
                        labels.append("urls_remote_unusable")
            if not labels:
                # hasUrls() with an EMPTY list: the old code returned here with
                # nothing done at all.
                return "urls_empty"
            return "|".join(labels)
        if has_image:
            # Paste image from clipboard (FastCapture, screenshot, etc.)
            # Save to the silo's file folder and insert a markdown image ref
            try:
                image = source.imageData()
                image_invalid = image is None or image.isNull()
            except Exception:
                image = None
                image_invalid = True
            if image_invalid:
                # A payload that CLAIMS an image but decodes to nothing is the
                # silent-no-op shape this wave is about: returned unsettled, so
                # text on the same clipboard is used instead of the paste
                # disappearing (T-1269C append).
                return "image_no_payload"
            import datetime

            from fastprompter.ui.file_container import _unique_dest
            try:
                folder = self.main_win._silo_folder_dir(
                    getattr(self.main_win, "active_temp_slot", 0),
                    getattr(self.main_win, "active_is_archive", False))
                os.makedirs(folder, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                name = _unique_dest(folder, f"paste-{stamp}.png")
                if image.save(name, "PNG"):
                    markup = self.image_paste_markup(
                        os.path.basename(name), QUrl.fromLocalFile(name).toString())
                    self._paste_image_inline(markup)
                    # Refresh file container if open.
                    # Guard with ignore_focus_loss: the file container
                    # is a Qt.Tool window when undocked, and touching
                    # it can fire WindowDeactivate on the main window,
                    # which hides it via changeEvent (T-732).
                    try:
                        fc = getattr(self.main_win, "_file_container", None)
                        if fc is not None:
                            prev = getattr(self.main_win, "ignore_focus_loss", False)
                            self.main_win.ignore_focus_loss = True
                            try:
                                fc.refresh()
                            finally:
                                self.main_win.ignore_focus_loss = prev
                    except Exception:
                        pass
                    self._paste_settled = True
                    return "image_saved"
                # The save itself failed: no file, no insertion -> unsettled,
                # so plain text still lands (T-1269C append).
                return "image_save_failed"
            except Exception:
                logger.exception("paste image failed")
                return "image_error"
        try:
            has_text = bool(source.hasText())
        except Exception:
            has_text = False
        if has_text:
            text = _mime_text(source).strip().strip('\"')
            # Selected text + a URL on the clipboard -> wrap the selection as
            # a markdown link instead of replacing it with the raw URL
            cursor = self.textCursor()
            if cursor.hasSelection() and text and "\n" not in text:
                url = QUrl(text)
                if url.isValid() and url.scheme() in ("http", "https", "ftp", "file"):
                    selected = cursor.selectedText().replace(" ", "\n")
                    text_to_insert = f"[{selected}]({text})"
                    self.textCursor().insertText(text_to_insert)
                    self._paste_settled = True
                    return "text_selection_url"
            # Plain text file path — insert as markdown link, or READ the file
            # when it is a text file (T-752). The link branch below stays for
            # binary/image files; a text file path pastes its content.
            # exists_within, not os.path.exists: this runs on the GUI thread for
            # every short paste, and an unreachable UNC path froze the window for
            # a measured 93 seconds. See fastprompter.utils.paths.
            if text and len(text) < 260 and "\n" not in text:
                if QUrl(text).isLocalFile():
                    text = QUrl(text).toLocalFile()
                normalized = os.path.normpath(text)
                if exists_within(normalized):
                    name = os.path.basename(normalized)
                    url = QUrl.fromLocalFile(normalized).toString(
                        QUrl.ComponentFormattingOption.FullyEncoded)
                    if os.path.splitext(name)[1].lower() in self.IMAGE_EXTENSIONS:
                        # An image path pasted as a plain link is the whole
                        # T-724 regression: it rendered as raw `[name](...)`
                        # text and could not be clicked.
                        text_to_insert = self.image_paste_markup(name, url)
                        self.insertPlainText(text_to_insert)
                        self._paste_settled = True
                        return "text_path_image"
                    elif os.path.splitext(name)[1].lower() in TEXT_EXTENSIONS \
                            or not os.path.splitext(name)[1]:
                        try:
                            text_to_insert = _read_text_file(normalized)
                            self.insertPlainText(text_to_insert)
                            self._paste_settled = True
                            return "text_path_content"
                        except Exception:
                            # An unreadable path is NOT settled: the raw text on
                            # the clipboard still lands instead of the paste
                            # doing nothing at all (T-1269C append).
                            logger.debug(
                                "Ctrl+V plain text file path read failed",
                                exc_info=True)
                            return "text_path_read_error"
                    else:
                        text_to_insert = f"[{name}]({url})"
                        self.insertPlainText(text_to_insert)
                        self._paste_settled = True
                        return "text_path_link"
            text_to_insert = _mime_text(source)
            self.insertPlainText(text_to_insert)
            self._paste_settled = True
            return "text_plain"
        return "empty_mime"

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Some trackpads report only pixelDelta (angleDelta stays 0),
            # which made Ctrl+wheel zoom silently do nothing on them
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.main_win.adjust_font_size(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    # Alt+arrow moves a SiloKanban card. Alt is free in the editor, and the
    # gesture matches what the arrows already mean: direction.
    _KANBAN_ARROWS = None      # built lazily; Qt enums are not module-level

    # Editing keys Qt handles itself. `hotkey` is the generic event, the same
    # one every unnamed registered shortcut uses, so these are re-mappable in
    # the Sound Settings dialog like everything else.
    _BUILTIN_KEY_SOUNDS = {
        Qt.Key.Key_A: "select_all",
        Qt.Key.Key_C: "copy",
        Qt.Key.Key_V: "paste",
        Qt.Key.Key_X: "cut",
    }

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and getattr(self, "_line_drag_source_block", None) is not None:
            self._cancel_line_drag()
            event.accept()
            return
        mods = event.modifiers()

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle_checkboxes()
            event.accept()
            return

        if mods == Qt.KeyboardModifier.AltModifier:
            if self._KANBAN_ARROWS is None:
                type(self)._KANBAN_ARROWS = {
                    Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                    Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
                }
            step = self._KANBAN_ARROWS.get(event.key())
            # only swallow the key when a card really moved: Alt+arrow has to
            # stay inert in ordinary prose
            if step and self.kanban_move(*step):
                event.accept()
                return
            
        mw = self.main_win
        
        if mods == Qt.KeyboardModifier.NoModifier and event.key() == Qt.Key.Key_Delete:
            if not self.toPlainText().strip():
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self,
                    tr("Trash, not delete", getattr(mw, "_current_lang", "EN")),
                    tr("Delete this silo and move it to trash?", getattr(mw, "_current_lang", "EN")),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    is_archive = getattr(mw, "active_is_archive", False)
                    mw.trash_silo(mw.active_temp_slot, is_archive)
                event.accept()
                return

        from PyQt6.QtGui import QKeySequence
        key_val = event.key()
        # event.key() follows the ACTIVE LAYOUT, so on a Russian keyboard the
        # physical B key reports Key_I - and Ctrl+B fired italic instead of
        # bold. Not a miss: the wrong command, silently. The scan code is the
        # physical position and does not move with the layout, so it decides
        # when it is one we know.
        physical = _SCAN_TO_KEY.get(event.nativeScanCode())
        if physical is not None:
            key_val = physical
        if key_val > 0 and key_val != Qt.Key.Key_unknown:
            # Need to handle Qt's quirk where Shift+Ctrl+S can parse strangely if we don't use exact match
            # But QKeySequence(key_val | mods.value) is standard.
            seq_str = QKeySequence(key_val | mods.value).toString()

            def matches(name, default):
                configured = mw.data.get(name, default)
                canonical = QKeySequence(configured).toString() if configured else ""
                if canonical in _RESERVED_EDITING_SEQUENCES:
                    # Reserved for the editor's own editing keys (see
                    # _RESERVED_EDITING_SEQUENCES): the configured command does
                    # not get to steal Ctrl+V, and the collision is reported
                    # instead of leaving two silent owners of one chord.
                    self._note_reserved_hotkey_conflict(name, canonical)
                    return False
                return bool(seq_str) and seq_str == canonical

            if matches("hk_header", "Ctrl+E"):
                mw.apply_header_timestamp(); event.accept(); return
            if matches("hk_bold", "Ctrl+B"):
                mw.apply_bold_smart(); event.accept(); return
            if matches("hk_italic", "Ctrl+I"):
                mw.apply_format("italic"); event.accept(); return
            if matches("hk_underline", "Ctrl+U"):
                mw.apply_format("underline"); event.accept(); return
            if matches("hk_undo", "Ctrl+Z"):
                if hasattr(mw, "_smart_undo"): mw._smart_undo()
                event.accept(); return
            if matches("hk_new_snippet", "Ctrl+N"):
                mw.select_empty_silo(insertion="top"); event.accept(); return
            if matches("hk_save_snippet", "Ctrl+S"):
                mw.save_snippet(); event.accept(); return
            if matches("hk_export_silo", "Ctrl+Shift+S"):
                mw.save_silo_to_file(); event.accept(); return
            if matches("hk_find", "Ctrl+F"):
                mw.toggle_find(); event.accept(); return
            if matches("hk_replace", "Ctrl+H"):
                mw.show_replace(); event.accept(); return
            if matches("hk_focus", "Ctrl+D"):
                mw.cycle_focus_mode(); event.accept(); return
            if matches("hk_divider", "Ctrl+W"):
                mw.insert_divider_line(); event.accept(); return
            if matches("hk_snap", "Ctrl+Q"):
                mw.cycle_snap_corner(); event.accept(); return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_T:
            # Strikethrough is non-configurable (not in hotkey settings)
            try:
                if hasattr(mw, "play_sound"):
                    mw.play_sound("strike")
            except Exception:
                pass
            mw.apply_format("strike")
            event.accept()
            return

        # Qt's own editing shortcuts never pass through add_shortcut, so the
        # T-735 wrapper could not reach them and Ctrl+A was silent while every
        # registered hotkey had a sound. Play and fall through — the event is
        # NOT accepted here, Qt still does the editing.
        #
        # T-1269C: `key_val` here, not `event.key()`. The configurable
        # hotkeys were normalized to the PHYSICAL key by T-735, but the
        # standard editing four were left on the raw layout-dependent key,
        # so on a Russian layout Ctrl+A/C/V/X were silently dead: no sound,
        # no editing, nothing logged. Sound and action must agree on ONE key
        # identity, or "the paste sound played" stops being evidence about
        # the paste.
        std_key = key_val
        if mods == Qt.KeyboardModifier.ControlModifier:
            event_name = self._BUILTIN_KEY_SOUNDS.get(std_key)
            # T-1269C append: the cue must not outlive the ability to paste.
            # `_paste_block_reason()` is the SAME predicate `_paste_from_keyboard`
            # consults, so "paste sound played, nothing inserted" can never
            # again be produced by a read-only/hidden/disabled editor: the cue
            # is suppressed exactly when the paste would be refused, and the
            # refusal is recorded with its reason instead.
            if event_name and not (std_key == Qt.Key.Key_V
                                   and self._paste_block_reason()):
                try:
                    mw.play_sound(event_name)
                except Exception:
                    pass
            # Qt matches its own Cut/SelectAll shortcuts on the raw key too,
            # so under a non-Latin layout they never fire. Only that case is
            # intercepted — on a Latin layout the event still falls through
            # to Qt exactly as before.
            if std_key != event.key():
                if std_key == Qt.Key.Key_A:
                    self.selectAll()
                    event.accept()
                    return
                if std_key == Qt.Key.Key_X and not self.isReadOnly():
                    self.cut()
                    event.accept()
                    return

        if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
            if event.key() == Qt.Key.Key_Z:
                if hasattr(mw, "_smart_undo"): mw._smart_undo()
            else:
                if hasattr(mw, "_smart_redo"): mw._smart_redo()
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if event.key() == Qt.Key.Key_Home else QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and event.key() in (
                Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            zoom_in = event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal)
            try:
                if hasattr(mw, "play_sound"):
                    mw.play_sound("zoom_in" if zoom_in else "zoom_out")
            except Exception:
                pass
            self.main_win.adjust_ui_scale(0.05 if zoom_in else -0.05)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Home:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        if event.key() == Qt.Key.Key_End:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            event.accept()
            return

        # T-1269C: std_key, so the copy contract holds on every layout.
        if std_key == Qt.Key.Key_C and mods == Qt.KeyboardModifier.ControlModifier:
            # Copy-All is the toolbar contract ("Copy all text (Ctrl+C)"), so
            # with no selection copy the WHOLE document straight to the
            # clipboard. Selecting the document first (the old route) left the
            # editor fully highlighted, and the next keystroke wiped the prompt.
            if self.textCursor().hasSelection():
                if std_key == event.key():
                    super().keyPressEvent(event)
                else:
                    # Non-Latin layout: Qt's own Copy shortcut matches the raw
                    # key and would never fire, so the selection is copied
                    # directly. Same action, reached by the physical key.
                    self.copy()
            else:
                QApplication.clipboard().setText(self.toPlainText())
            cb_ctrl_c = getattr(self.main_win, "cb_ctrl_c", None)
            ctrl_c_hides = (
                cb_ctrl_c.isChecked() if cb_ctrl_c is not None
                else self.main_win.data.get("ctrl_c_closes", "True") == "True"
            )
            if ctrl_c_hides:
                QTimer.singleShot(10, weak_qt_callback(
                    self.main_win, lambda window: window.hide_and_save()))
            return

        # T-1269C: std_key. `self.paste()` is the MIME-aware route
        # (insertFromMimeData), so image, file/URL and selection+URL pastes
        # keep their behaviour — this only decides WHICH key reaches it.
        if std_key == Qt.Key.Key_V and mods == Qt.KeyboardModifier.ControlModifier:
            self._paste_from_keyboard(event)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            # Inside a SiloTable, Tab walks the cells. Checked before the
            # indent path because four spaces inside a table row is never
            # what Tab was meant to do there.
            if not self.textCursor().hasSelection():
                forward = (event.key() == Qt.Key.Key_Tab
                           and mods == Qt.KeyboardModifier.NoModifier)
                if self.table_move_cell(forward=forward):
                    event.accept()
                    return
            cursor = self.textCursor()
            if cursor.hasSelection():
                # Block indentation
                start_block = self.document().findBlock(cursor.selectionStart()).blockNumber()
                end_block = self.document().findBlock(cursor.selectionEnd()).blockNumber()
                
                # if selection ends exactly at the start of a block, don't indent that block
                if cursor.selectionEnd() == self.document().findBlockByNumber(end_block).position() and end_block > start_block:
                    end_block -= 1
                
                edit_cursor = QTextCursor(self.document())
                edit_cursor.beginEditBlock()
                for b in range(start_block, end_block + 1):
                    edit_cursor.setPosition(self.document().findBlockByNumber(b).position())
                    if event.key() == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
                        edit_cursor.insertText("    ")
                    elif event.key() == Qt.Key.Key_Backtab or mods == Qt.KeyboardModifier.ShiftModifier:
                        edit_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                        text = edit_cursor.selectedText()
                        if text.startswith("    "):
                            edit_cursor.insertText(text[4:])
                        elif text.startswith("\t"):
                            edit_cursor.insertText(text[1:])
                edit_cursor.endEditBlock()
                event.accept()
                return
            else:
                # Single line Tab handling: "shift the cursor with the • accordingly"
                block = cursor.block()
                text = block.text()
                pos = cursor.positionInBlock()
                if text.lstrip().startswith("• "):
                    indent = len(text) - len(text.lstrip())
                    if pos <= indent + 2:
                        edit_cursor = QTextCursor(self.document())
                        edit_cursor.beginEditBlock()
                        edit_cursor.setPosition(block.position())
                        if event.key() == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
                            edit_cursor.insertText("    ")
                        elif event.key() == Qt.Key.Key_Backtab or mods == Qt.KeyboardModifier.ShiftModifier:
                            if text.startswith("    "):
                                edit_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 4)
                                edit_cursor.removeSelectedText()
                            elif text.startswith("\t"):
                                edit_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                                edit_cursor.removeSelectedText()
                        edit_cursor.endEditBlock()
                        event.accept()
                        return


        if event.key() == Qt.Key.Key_Backspace and (mods & Qt.KeyboardModifier.AltModifier):
            try:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.PreviousWord, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                self.setTextCursor(cursor)
            except Exception:
                pass
            event.accept()
            return

        if event.key() == Qt.Key.Key_Space and mods == Qt.KeyboardModifier.NoModifier:
            if self.main_win.data.get("auto_bullet", "False") == "True":
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    block = cursor.block()
                    text_in_block = block.text()
                    pos_in_block = cursor.positionInBlock()
                    text_before = text_in_block[:pos_in_block]
                    stripped = text_before.lstrip()
                    if stripped in ("-", "*", "+"):
                        cursor.movePosition(QTextCursor.MoveOperation.Left,
                                            QTextCursor.MoveMode.KeepAnchor, len(text_before))
                        cursor.insertText(text_before[:len(text_before) - len(stripped)] + "\u2022 ")
                        self.setTextCursor(cursor)
                        event.accept()
                        return

        # Auto-bullet continuation: Enter on a bullet line starts the next
        # line with the same bullet (blank line between them if
        # bullet_double_line is on); Enter on an empty bullet removes it.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                # Enter in a table adds a ROW rather than splitting the row in
                # half, which is what a bare newline does to markdown.
                if self.table_at_caret() and self.table_new_row():
                    event.accept()
                    return
                block_text = cursor.block().text()
                stripped = block_text.lstrip()

                if stripped == "---":
                    before, after = self.main_win.divider_counts()
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.insertText("\n" * before + "---" + "\n" * after + "\u2022 ")
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    event.accept()
                    return

                indent = block_text[:len(block_text) - len(stripped)]
                m = re.match(r'^([\u2022\-\*\+])[ \t]+(.*)$', stripped)

                # The user requested double line to work independently of the 'auto_bullet' check if toggled,
                # or just ensure double lines append correctly. We will allow auto-continuation if either
                # auto_bullet is True OR bullet_double_line is True.
                wants_auto_bullet = self.main_win.data.get("auto_bullet", "False") == "True"
                double = self.main_win.data.get("bullet_double_line", "False") == "True"

                if m and cursor.positionInBlock() >= len(block_text) - len(m.group(2)) and (wants_auto_bullet or double):
                    if m.group(2).strip():
                        sep = "\n\n" if double else "\n"
                        cursor.insertText(sep + indent + m.group(1) + " ")
                        self.setTextCursor(cursor)
                        self.ensureCursorVisible()
                        event.accept()
                        return
                    # Empty bullet: Enter clears the marker instead of continuing
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                        QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    event.accept()
                    return

        pre_key = event.key()
        pre_cursor = self.textCursor()
        pre_had_selection = pre_cursor.hasSelection()
        pre_revision = self.document().revision()

        try:
            # Swallow native Ctrl+B/I/U so user rebinding works fully
            if mods == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U):
                event.accept()
                return

            if getattr(self, "_undo_boundary_pending", False) and event.text():
                # First keystroke after a formatting command. Qt would merge
                # this insertion into that command's undo entry, so one
                # Ctrl+Z would revert BOTH — wrap it in its own edit block to
                # force a separate undo step. Only the first keystroke needs
                # it; the rest coalesce into normal typing as usual.
                self._undo_boundary_pending = False
                guard = self.textCursor()
                guard.beginEditBlock()
                try:
                    super().keyPressEvent(event)
                finally:
                    guard.endEditBlock()
            else:
                super().keyPressEvent(event)
        except Exception:
            logger.exception("keyPressEvent handling failed")
            event.accept()
            return

        # Typewriter / delete sounds (T-709, T-1242 append D1-D8).  The
        # selection was captured in pre_* BEFORE super() ran, so a Delete over a
        # selection is still classified as delete_selection (D3).  A keystroke
        # that edits nothing (caret at doc start/end, read-only) leaves the
        # document revision unchanged, so no sound is emitted (D4).
        txt = event.text()
        if txt and txt.isprintable() and not (
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            try:
                self.main_win.play_sound("type")
            except Exception:
                pass
        elif pre_key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            # Family semantics (D5/D6): Backspace stays its own event even over
            # a selection; Delete splits into forward vs selected-text.
            if pre_key == Qt.Key.Key_Backspace:
                event_name = "backspace"
            elif pre_had_selection:
                event_name = "delete_selection"
            else:
                event_name = "delete_forward"
            if self.document().revision() != pre_revision:
                try:
                    self.main_win.play_sound(event_name)
                except Exception:
                    pass

    @staticmethod
    def _whole_block_cursor(block):
        """Cursor spanning the ENTIRE block, wrapped lines included.

        A bare caret plus FullWidthSelection only tints the visual line the
        caret sits on, so a long wrapped paragraph got one stripe and the
        continuation lines stayed untinted. Selecting the block makes the
        tint cover every visual row it occupies.
        """
        return QTextCursor(block)

    def _theme_accent(self, fallback):
        """Accent colour of the active theme, for 'auto' colour settings."""
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache and cache.get("raw_colors"):
                return cache["raw_colors"].get("accent", fallback)
        except Exception:
            pass
        return fallback

    # ---- line temperature: show where you have recently been -----------
    def _heat_enabled(self):
        try:
            return self.main_win.data.get("line_heat", "False") == "True"
        except Exception:
            return False

    def invalidate_word_count(self):
        self._words_dirty = True
        self._aggregate_word_count = None
        
    def document_word_count(self):
        """O(1) total word count, or O(B) fallback if dirty."""
        doc = self.document()
        if not doc:
            return 0
        if getattr(self, "_words_dirty", True) or getattr(self, "_aggregate_word_count", None) is None:
            total = 0
            block = doc.begin()
            while block.isValid():
                data = block.userData()
                if data is None:
                    data = _BlockData()
                    block.setUserData(data)
                wc = getattr(data, 'word_count', -1)
                if wc == -1:
                    wc = len(block.text().split())
                    data.word_count = wc
                total += wc
                block = block.next()
            self._aggregate_word_count = total
            self._words_dirty = False
            return total
        return self._aggregate_word_count

    def _on_contents_change(self, position, removed, added):
        """Document changed — rebuild the background tints and word count."""
        if sip.isdeleted(self):
            return
        doc = self.document()
        if doc and not sip.isdeleted(doc):
            first = doc.findBlock(position)
            last = doc.findBlock(max(position, position + added))
            
            # Fast path: single-block edit
            if first == last and not getattr(self, "_words_dirty", False):
                data = first.userData()
                if data:
                    old_wc = getattr(data, 'word_count', -1)
                    if old_wc != -1:
                        new_wc = len(first.text().split())
                        data.word_count = new_wc
                        if hasattr(self, "_aggregate_word_count") and self._aggregate_word_count is not None:
                            self._aggregate_word_count += (new_wc - old_wc)
                    else:
                        self._words_dirty = True
                else:
                    self._words_dirty = True
            else:
                self._words_dirty = True
                block = first
                while block.isValid():
                    data = block.userData()
                    if hasattr(data, 'word_count'):
                        data.word_count = -1
                    if block == last:
                        break
                    block = block.next()
        self.refresh_extra_selections()

    def _stamp_edited_blocks(self, position, removed, added):
        """Timestamp every block the change touched."""
        # same reason as _on_contents_change: the document can outlive us, and
        # self.document() on a dead editor is an access violation
        if sip.isdeleted(self):
            return
        if not self._heat_enabled():
            return
        doc = self.document()
        if doc is None or sip.isdeleted(doc):
            return
        if doc.blockCount() > 2000:      # same ceiling as the other per-block work
            return
        import time as _t

        now = _t.time()
        try:
            first = doc.findBlock(position)
            last = doc.findBlock(max(position, position + added))
            block = first
            while block.isValid():
                stamp_heat(block, now)
                if block.blockNumber() >= last.blockNumber():
                    break
                block = block.next()
        except Exception:
            logger.debug("line heat stamp failed")

    # age -> (settings key, fallback colour). Same buckets and the same
    # custom-colour keys the silo recency tint uses, so the two read as one
    # system rather than two unrelated colour schemes.
    _HEAT_BUCKETS = (
        (60, "overlay_new", "#6a5555"),
        (3600, "overlay_recent", "#6a5a40"),
        (86400, "overlay_day", "#5a5a30"),
    )

    def _heat_window(self):
        """How long a line stays warm, in minutes (user-settable)."""
        try:
            minutes = int(self.main_win.data.get("line_heat_minutes", "1440"))
        except (TypeError, ValueError):
            minutes = 1440
        return max(1, min(60 * 24 * 30, minutes)) * 60

    def _heat_colour_for(self, age, span, custom):
        """Colour for a line of this age, over the user's chosen window.

        Rescales the shared overlay palette onto whatever window length the
        user picked, so a 10-minute window still runs the full spectrum
        rather than sitting on one colour.
        """
        ratio = max(0.0, min(1.0, age / span if span else 1.0))
        mode = (self.main_win.data.get("line_heat_palette", "warm") or "warm").lower()
        if mode == "accent":
            return QColor(self._theme_accent("#6a5555"))
        stops = [custom.get(key, fallback) for _lim, key, fallback in self._HEAT_BUCKETS]
        if mode == "cool":
            stops = list(reversed(stops))
        pos = ratio * (len(stops) - 1)
        low = int(pos)
        high = min(low + 1, len(stops) - 1)
        from fastprompter.theme.themes import blend_hex
        return QColor(blend_hex(stops[low], stops[high], pos - low))

    def _line_heat_selections(self, doc):
        if not self._heat_enabled():
            return []
        import time as _t

        now = _t.time()
        try:
            strength = int(self.main_win.data.get("line_heat_strength", "18"))
        except (TypeError, ValueError):
            strength = 18
        strength = max(2, min(60, strength))

        try:
            custom = self.main_win._get_custom_colors()
        except Exception:
            custom = {}

        out = []
        block = self._first_visible_block() or doc.firstBlock()
        vp_bottom = self.viewport().height()
        doc_layout = doc.documentLayout()
        y_off = -self.verticalScrollBar().value()
        while block.isValid():
            # only paint what's on screen; heat is decoration, not data
            top = doc_layout.blockBoundingRect(block).translated(0, y_off).top()
            if top > vp_bottom:
                break
            data = block.userData()
            ts = getattr(data, "ts", None)
            if ts is not None:
                age = now - ts
                span = self._heat_window()
                if age < span:
                    colour = self._heat_colour_for(age, span, custom)
                    if colour.isValid():
                        # fade across the whole window so it cools gradually
                        fade = 1.0 - (age / span) * 0.75
                        colour.setAlpha(round(255 * strength / 100 * fade))
                        sel = QTextEdit.ExtraSelection()
                        sel.format.setBackground(colour)
                        sel.format.setProperty(
                            QTextFormat.Property.FullWidthSelection, True)
                        sel.cursor = self._whole_block_cursor(block)
                        out.append(sel)
            block = block.next()
        return out

    def _hover_line_selection(self, doc):
        """A faint wash over the line under the mouse.

        Just enough to say "this is the line you're pointing at" without
        competing with the caret's own line or the text itself.
        """
        if self.main_win.data.get("hover_line", "True") != "True":
            return []
        num = getattr(self, "_hover_block", None)
        if num is None:
            return []
        block = doc.findBlockByNumber(num)
        if not block.isValid() or not block.isVisible():
            return []
        try:
            pct = int(self.main_win.data.get("hover_line_opacity", "10"))
        except (TypeError, ValueError):
            pct = 10
        pct = max(1, min(60, pct))
        # "auto" (the default) tracks the active theme's accent, so the
        # highlight belongs to whatever skin the user is on; an explicit
        # colour overrides it.
        chosen = (self.main_win.data.get("hover_line_color", "auto") or "auto").strip()
        if chosen.lower() in ("", "auto", "theme"):
            chosen = self._theme_accent("#6aa9ff")
        color = QColor(chosen)
        if not color.isValid():
            color = QColor(self._theme_accent("#6aa9ff"))
        color.setAlpha(round(255 * pct / 100))
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(color)
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self._whole_block_cursor(block)
        return [sel]

    def _code_block_selections(self, doc):
        """Full-width backgrounds for code fence/content lines, drawn behind
        the text by Qt itself (a manual fillRect in paintEvent would land
        after the text is drawn and hide it)."""
        selections = []
        block = doc.firstBlock()
        while block.isValid():
            stripped = block.text().lstrip()
            is_code = (max(0, block.userState()) & 256) or stripped.startswith("```")
            if is_code:
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor("#161616"))
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.cursor = self._whole_block_cursor(block)
                selections.append(sel)
            block = block.next()
        return selections

    def _paint_line_tints(self, painter, doc, doc_layout, y_off, vp_rect):
        """Hover highlight and edit-heat, drawn over whole block rectangles.

        blockBoundingRect covers every visual row a wrapped paragraph
        occupies, so the tint no longer stops after the first line. Drawn
        translucent (like the zebra stripes) so the text stays readable even
        though this lands after the text is painted.
        """
        import time as _t

        heat_on = self._heat_enabled()
        hover_on = self.main_win.data.get("hover_line", "True") == "True"
        hover_block = getattr(self, "_hover_block", None)
        if not heat_on and not (hover_on and hover_block is not None):
            return

        now = _t.time()
        span = self._heat_window() if heat_on else 0
        try:
            heat_pct = int(self.main_win.data.get("line_heat_strength", "18"))
        except (TypeError, ValueError):
            heat_pct = 18
        heat_pct = max(2, min(60, heat_pct))
        try:
            custom = self.main_win._get_custom_colors()
        except Exception:
            custom = {}

        hover_colour = None
        if hover_on and hover_block is not None:
            try:
                pct = int(self.main_win.data.get("hover_line_opacity", "10"))
            except (TypeError, ValueError):
                pct = 10
            chosen = (self.main_win.data.get("hover_line_color", "auto") or "auto").strip()
            if chosen.lower() in ("", "auto", "theme"):
                chosen = self._theme_accent("#6aa9ff")
            hover_colour = QColor(chosen)
            if not hover_colour.isValid():
                hover_colour = QColor(self._theme_accent("#6aa9ff"))
            hover_colour.setAlpha(round(255 * max(1, min(60, pct)) / 100))

        block = self._first_visible_block() or doc.firstBlock()
        while block.isValid():
            rect = doc_layout.blockBoundingRect(block).translated(0, y_off)
            if rect.top() > vp_rect.height():
                break
            if rect.bottom() >= 0 and block.isVisible():
                full = QRectF(0, rect.top(), vp_rect.width(), rect.height())
                if heat_on:
                    ts = getattr(block.userData(), "ts", None)
                    if ts is not None:
                        age = now - ts
                        if age < span:
                            colour = self._heat_colour_for(age, span, custom)
                            if colour.isValid():
                                fade = 1.0 - (age / span) * 0.75
                                colour.setAlpha(round(255 * heat_pct / 100 * fade))
                                painter.fillRect(full, colour)
                if hover_colour is not None and block.blockNumber() == hover_block:
                    painter.fillRect(full, hover_colour)
            block = block.next()

    def _live_pinned(self):
        """Prune pins whose document is gone, then return the survivors.

        A QTextCursor is a value type, so it is never "deleted" — when its
        document dies it simply goes null and reports -1 positions. Left in
        the list those would render nothing forever and grow without bound.
        """
        pins = getattr(self, "_pinned_cursors", None)
        if pins is None:
            pins = self._pinned_cursors = []
        alive = [c for c in pins if not c.isNull() and c.document() is not None]
        if len(alive) != len(pins):
            pins[:] = alive
        return pins

    def _pinned_extra_selections(self, doc):
        """ExtraSelections for the persistent Ctrl+click word highlights."""
        sels = []
        accent = QColor(self._theme_accent("#D9B340"))
        accent.setAlpha(110)
        for c in self._live_pinned():
            if c.document() is not doc:
                continue        # another silo's pin — not painted here
            start, end = c.selectionStart(), c.selectionEnd()
            if start >= end:
                continue
            cur = QTextCursor(doc)
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(accent)
            sel.cursor = cur
            sels.append(sel)
        return sels

    @property
    def _pinned_selections(self):
        """(start, end) of every live pin — a read-only view."""
        return [(c.selectionStart(), c.selectionEnd())
                for c in self._live_pinned()]

    def _toggle_pinned_selection(self, pos):
        """Pin/unpin the word under a Ctrl+click.

        Unpinning matches by OVERLAP, not by exact range: the pin is a live
        cursor that moves with edits, so the word's offsets are no longer the
        ones it was created with and an equality test would never release it.
        """
        cur = self.cursorForPosition(pos)
        if cur is None or cur.isNull():
            return
        if not cur.hasSelection():
            cur.select(QTextCursor.SelectionType.WordUnderCursor)
        if not cur.hasSelection():
            return
        start, end = cur.selectionStart(), cur.selectionEnd()
        pins = self._live_pinned()
        for c in list(pins):
            if c.document() is not cur.document():
                continue
            if start < c.selectionEnd() and c.selectionStart() < end:
                pins.remove(c)
                self.refresh_extra_selections()
                return
        pins.append(QTextCursor(cur))
        self.refresh_extra_selections()

    def _clear_pinned_selections(self):
        """Release every pin (Ctrl+triple-click)."""
        if not getattr(self, "_pinned_cursors", None):
            return
        self._pinned_cursors.clear()
        self.refresh_extra_selections()

    def _ctrl_click_bump(self, pos):
        """Count consecutive Ctrl+left clicks within the double-click
        interval and near the same position. Returns the running count;
        3 means a triple-click, which clears every pin."""
        import time as _t
        now = _t.monotonic()
        last_ts = getattr(self, "_ctrl_click_ts", None)
        last_pos = getattr(self, "_ctrl_click_pos", None)
        if (last_ts is not None
                and (now - last_ts) * 1000 <= QApplication.doubleClickInterval()
                and last_pos is not None
                and (last_pos - QPointF(pos)).manhattanLength() < 20):
            count = getattr(self, "_ctrl_click_count", 0) + 1
        else:
            count = 1
        self._ctrl_click_ts = now
        self._ctrl_click_pos = QPointF(pos)
        self._ctrl_click_count = count
        return count

    def refresh_extra_selections(self):
        """Ask for the background tints (code panels, heat, hover) to be rebuilt.

        Always DEFERRED to the event loop, never run inline, because
        setExtraSelections() schedules a layout pass and a repaint. Running
        that while Qt is mid-paint or mid-document-swap is re-entrant and
        faults inside Qt — an access violation with no Python traceback,
        and the bigger the document the likelier it is. Deferring also
        coalesces the burst of calls a single edit produces.
        """
        if sip.isdeleted(self):
            return
        if getattr(self, "_sel_refresh_pending", False):
            return
        self._sel_refresh_pending = True
        QTimer.singleShot(0, weak_qt_callback(
            self, type(self)._apply_extra_selections))

    def _apply_extra_selections(self):
        self._sel_refresh_pending = False
        if sip.isdeleted(self):
            return
        doc = self.document()
        if doc is None or sip.isdeleted(doc) or doc.blockCount() > 2000:
            return
        try:
            # T-815: the code-panel scan walks every block. It only needs to
            # run when code-region membership actually changed (a fence edit
            # or a document (re)attach) — `_reconcile_edits` and
            # `set_active_document` set the dirty flag for exactly those
            # moments. An ordinary keystroke leaves the flag clear, so a
            # 2000-line plain document never rescan. Pinned Ctrl+click
            # highlights are cheap and always rebuilt; code panels reuse the
            # last build until the dirty flag is set again.
            if getattr(self, "_code_sel_dirty", True):
                self._code_selections_cache = self._code_block_selections(doc)
            selections = self._pinned_extra_selections(doc)
            selections.extend(getattr(self, "_code_selections_cache", ()))
            self.setExtraSelections(selections)
        except Exception:
            logger.debug("failed to refresh extra selections")
        finally:
            self._code_sel_dirty = False

    def paintEvent(self, event):
        doc = self.document()
        super().paintEvent(event)
        if not doc:
            return
        block_count = doc.blockCount()
        is_large = block_count > 2000
        vp_rect = self.viewport().rect()
        painter = QPainter(self.viewport())
        try:
            # Zebra striping: skip for large docs (>2000 blocks)
            zebra_enabled = not is_large and self.main_win.data.get("zebra_lines", "False") == "True"
            try:
                zebra_alpha = min(90, max(2, int(self.main_win.data.get("zebra_opacity", "32"))))
            except Exception:
                zebra_alpha = 32
            zebra_odd = QColor(self.main_win.data.get("zebra_stripe_color", "#000000"))
            if not zebra_odd.isValid():
                zebra_odd = QColor(0, 0, 0)
            zebra_odd.setAlpha(zebra_alpha)

            # --- visual lines color
            try:
                hr_color = QColor(self.main_win.data.get("zebra_color", "#5a4a2a"))
            except Exception:
                hr_color = QColor("#5a4a2a")
            hr_drawn = set()

            # Checkbox rendering bg
            bg_color = self.viewport().palette().window().color()

            doc_layout = doc.documentLayout()
            y_off = -self.verticalScrollBar().value()
            self._rendered_images = []
            block = self._first_visible_block()
            if block:
                while block.isValid():
                    if not block.isVisible():  # folded away
                        block = block.next()
                        continue
                    # Full block geometry (covers wrapped lines), viewport coords
                    br = doc_layout.blockBoundingRect(block).translated(0, y_off)
                    block_layout = block.layout()
                    if block_layout.lineCount() > 0:
                        first_line = block_layout.lineAt(0)
                        r = first_line.rect().translated(br.topLeft())
                    else:
                        r = br
                    if br.top() > vp_rect.height():
                        break
                    if br.bottom() >= 0:
                        bnum = block.blockNumber()
                        text = block.text()
                        stripped = text.lstrip()

                        # Code fence / code content background is drawn behind the
                        # text via setExtraSelections() in paintEvent (a fillRect
                        # here lands AFTER super().paintEvent() has already drawn
                        # the text, hiding it completely).
                        is_code_block = not is_large and (
                            (max(0, block.userState()) & 256)  # CODE_BIT = 1 << 8
                            or stripped.startswith("```")
                        )

                        # Zebra background — skip for code blocks (have own bg)
                        if zebra_enabled and bnum % 2 == 1 and not is_code_block:
                            line_rect = QRectF(0, br.top(), vp_rect.width(), br.height())
                            painter.fillRect(line_rect, zebra_odd)

                        # Inline copy button on opening code fences:
                        # click copies the block's content to the clipboard
                        if not is_large and stripped.startswith("```") and self._fence_is_opener(block):
                            gc = QRectF(self._code_copy_rect(block))
                            pressed_c = getattr(self, "_copy_pressed_block", -1) == bnum
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                            painter.fillRect(gc, QColor("#1e1e1e"))
                            light = QColor("#3a3a3a")
                            dark = QColor("#0a0a0a")
                            painter.setPen(dark if pressed_c else light)
                            painter.drawLine(gc.topLeft(), gc.topRight())
                            painter.drawLine(gc.topLeft(), gc.bottomLeft())
                            painter.setPen(light if pressed_c else dark)
                            painter.drawLine(gc.bottomLeft(), gc.bottomRight())
                            painter.drawLine(gc.topRight(), gc.bottomRight())
                            painter.setPen(QColor("#D9B340"))
                            gfc = self.font()
                            gfc.setPointSizeF(max(8.0, gfc.pointSizeF() * 0.95))
                            painter.setFont(gfc)
                            tgc = gc.adjusted(2, 2, 2, 2) if pressed_c else gc
                            painter.drawText(tgc, Qt.AlignmentFlag.AlignCenter, "\u2398")
                            painter.setFont(self.font())

                        # Fold toggle box on headers and code fences:
                        # ▾ expanded, ▸ collapsed (hides the section)
                        if not is_large and self._is_fold_anchor(block):
                            fr = QRectF(self._fold_rect(block))
                            collapsed = bool(max(0, block.userState()) & self.FOLD_BIT)
                            pressed_f = getattr(self, "_fold_pressed_block", -1) == bnum
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                            painter.fillRect(fr, QColor("#1e1e1e"))
                            light = QColor("#3a3a3a")
                            dark = QColor("#0a0a0a")
                            painter.setPen(dark if pressed_f else light)
                            painter.drawLine(fr.topLeft(), fr.topRight())
                            painter.drawLine(fr.topLeft(), fr.bottomLeft())
                            painter.setPen(light if pressed_f else dark)
                            painter.drawLine(fr.bottomLeft(), fr.bottomRight())
                            painter.drawLine(fr.topRight(), fr.bottomRight())
                            painter.setPen(QColor("#D9B340"))
                            ff = self.font()
                            ff.setPointSizeF(max(8.0, ff.pointSizeF() * 0.9))
                            painter.setFont(ff)
                            tf = fr.adjusted(2, 2, 2, 2) if pressed_f else fr
                            painter.drawText(tf, Qt.AlignmentFlag.AlignCenter,
                                             "▸" if collapsed else "▾")
                            painter.setFont(self.font())
                            if collapsed:
                                painter.setPen(QColor("#808080"))
                                painter.drawText(
                                    int(fr.right()) + 6, int(fr.bottom()) - 2, "…")

                        # Inline refresh button after lines ending with a
                        # Ctrl+E timestamp: a small 3D box (pushes when
                        # clicked) that re-stamps the line to now
                        m_ts = TS_STAMP_LINE_RE.search(text)
                        if m_ts:
                            g_rect = self._ts_glyph_rect(block)
                            if g_rect is not None:
                                g = QRectF(g_rect)
                                pressed = getattr(self, "_ts_pressed_block", -1) == bnum
                                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

                                painter.fillRect(g, QColor("#1e1e1e"))

                                light = QColor("#3a3a3a")
                                dark = QColor("#0a0a0a")
                                top_left = dark if pressed else light
                                bottom_right = light if pressed else dark

                                painter.setPen(top_left)
                                painter.drawLine(g.topLeft(), g.topRight())
                                painter.drawLine(g.topLeft(), g.bottomLeft())

                                painter.setPen(bottom_right)
                                painter.drawLine(g.bottomLeft(), g.bottomRight())
                                painter.drawLine(g.topRight(), g.bottomRight())

                                painter.setPen(QColor("#a0a0a0"))
                                gf = self.font()
                                gf.setPointSizeF(max(8.0, gf.pointSizeF() * 1.1))
                                painter.setFont(gf)
                                tg = g.adjusted(2, 2, 2, 2) if pressed else g
                                painter.drawText(tg, Qt.AlignmentFlag.AlignCenter, "\u27f3")
                                painter.setFont(self.font())

                        # --- horizontal rule visual line (skip for large docs)
                        hr_visual = getattr(self.main_win, "data", {}).get("hr_visual_line", "True") == "True"
                        if not is_large and hr_visual and re.match(r'^[-*_]{3,}$', text.strip()):
                            mid_y = int(r.top() + r.height() // 2)
                            if mid_y not in hr_drawn:
                                hr_drawn.add(mid_y)
                                _draw_horizontal_rule(painter, hr_color, mid_y, vp_rect.width())

                        # Render collapsed markdown image stubs
                        if not is_large:
                            for m_img in MD_IMAGE_RE.finditer(text):
                                img_path = m_img.group(1)

                                # ONE geometry for paint AND hit test. Painting
                                # forced a 150 px minimum width that
                                # ``_image_pill_rect`` never applied, so the
                                # drawn pill ran over whatever followed the
                                # markup on that line while the clickable pill
                                # stayed narrow -- pointer and pixels disagreed
                                # about where the button was. Asking the hit
                                # test for its own rect is the whole fix.
                                btn_rect = QRectF(self._image_pill_rect(block, m_img))
                                
                                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                                painter.setBrush(QColor("#1e1e1e"))
                                painter.setPen(QColor("#5a4a2a"))
                                painter.drawRoundedRect(btn_rect, 4, 4)
                                
                                # Draw icon and text
                                painter.setPen(QColor("#D9B340"))
                                btn_text_rect = btn_rect.adjusted(4, 0, -4, 0)
                                painter.setFont(self.font())
                                
                                # Get the basename or fallback
                                display_name = os.path.basename(img_path)
                                if not display_name:
                                    display_name = img_path
                                # if file:/// protocol, decode it for display
                                if display_name.startswith("file:///"):
                                    display_name = display_name[8:]
                                
                                fm = painter.fontMetrics()
                                elided = fm.elidedText("🖼️ " + display_name, Qt.TextElideMode.ElideRight, int(btn_text_rect.width()))
                                painter.drawText(btn_text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
                                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                                
                                self._rendered_images.append((btn_rect, img_path))

                                # Copy-to-clipboard button, right of the pill.
                                # Drawn from the SAME geometry the hit test
                                # uses, so what the pointer can click is
                                # exactly what is on screen.
                                copy_rect = QRectF(self._image_copy_rect(
                                    btn_rect.toRect()))
                                pressed_img = (
                                    getattr(self, "_image_copy_pressed", None)
                                    and os.path.normcase(
                                        os.path.realpath(os.path.abspath(
                                            str(img_path).replace(
                                                "file:///", ""))))
                                    == os.path.normcase(
                                        os.path.realpath(os.path.abspath(
                                            str(self._image_copy_pressed)))))
                                painter.setRenderHint(
                                    QPainter.RenderHint.Antialiasing, False)
                                painter.fillRect(copy_rect, QColor("#1e1e1e"))
                                light = QColor("#3a3a3a")
                                dark = QColor("#0a0a0a")
                                painter.setPen(dark if pressed_img else light)
                                painter.drawLine(copy_rect.topLeft(),
                                                copy_rect.topRight())
                                painter.drawLine(copy_rect.topLeft(),
                                                copy_rect.bottomLeft())
                                painter.setPen(light if pressed_img else dark)
                                painter.drawLine(copy_rect.bottomLeft(),
                                                copy_rect.bottomRight())
                                painter.drawLine(copy_rect.topRight(),
                                                copy_rect.bottomRight())
                                painter.setPen(QColor("#D9B340"))
                                gcf = self.font()
                                gcf.setPointSizeF(
                                    max(8.0, gcf.pointSizeF() * 0.95))
                                painter.setFont(gcf)
                                tcf = (copy_rect.adjusted(2, 2, 2, 2)
                                       if pressed_img else copy_rect)
                                painter.drawText(tcf, Qt.AlignmentFlag.AlignCenter,
                                                "\u2398")
                                painter.setFont(self.font())

                        # Checkbox rendering
                        if self._doc_has_checkbox:
                            indent = len(text) - len(stripped)
                            if stripped.startswith("[ ] "):
                                checked = False
                            elif stripped.startswith("[x] ") or stripped.startswith("[X] "):
                                checked = True
                            else:
                                block = block.next()
                                continue

                            cursor = QTextCursor(block)
                            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                                QTextCursor.MoveMode.MoveAnchor, indent)
                            r_start = self.cursorRect(cursor)
                            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                                QTextCursor.MoveMode.MoveAnchor, 4)
                            r_end = self.cursorRect(cursor)
                            bg_left = int(r_start.x())
                            bg_top = int(r_start.top())
                            bg_w = int(r_end.x() - r_start.x())
                            bg_h = int(r_start.height())

                            marker_rect = QRect(bg_left, bg_top, bg_w, bg_h)
                            painter.fillRect(marker_rect, bg_color)
                            _paint_task_checkbox(
                                painter,
                                _task_checkbox_rect(marker_rect),
                                checked,
                            )
                    block = block.next()

            self._paint_typo_underlines(painter, doc, y_off)

            self._paint_line_tints(painter, doc, doc_layout, y_off, vp_rect)

            # Line-blocking drag: translucent box over the candidate drop
            # target so the interaction reads as interactive (PureRef-style).
            hover_num = getattr(self, "_line_drag_hover_block", None)
            if hover_num is not None:
                hover_block = doc.findBlockByNumber(hover_num)
                if hover_block.isValid():
                    hbr = doc_layout.blockBoundingRect(hover_block).translated(0, y_off)
                    accent = "#D9B340"
                    try:
                        cached = getattr(self.main_win, "_theme_cache", None)
                        if cached and cached.get("raw_colors"):
                            accent = cached["raw_colors"].get("accent", accent)
                    except Exception:
                        pass
                    hover_color = QColor(accent)
                    hover_color.setAlpha(128)  # 50% — translucent, never hides text
                    painter.fillRect(
                        QRectF(0, hbr.top(), vp_rect.width(), hbr.height()), hover_color)

        finally:
            painter.end()

    def _paint_typo_underlines(self, painter, doc, y_off):
        """Wavy underlines under flagged words (painted directly).

        Deliberately NOT routed through setExtraSelections: that channel is
        owned by the code-panel tinting path (``_apply_extra_selections``),
        which skips its pass unless the fence membership changed. Sharing it
        would couple the two features and re-enter the layout pass from the
        checker. Drawing here is independent — no recursion, no conflicts
        (this is the checker's "never recursive" contract, kept on the paint
        side as well).

        ``_typo_spans`` is ``[(start, end)]`` in ABSOLUTE document offsets,
        set by main.py after each debounced check; ``_typo_color`` is the
        user-chosen underline colour.

        PERF-005: the absolute->block-local grouping is cached and reused
        across paints of an unchanged document. Rebuilding it on every
        paintEvent would re-run up to 2,000 findBlock lookups per repaint
        (scrolling, hover, selection) for analysis that did not change.
        """
        spans = getattr(self, "_typo_spans", None)
        if not spans:
            self._typo_blocks_cache = None
            return
        color = getattr(self, "_typo_color", None)
        if not color:
            return
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        rev = doc.revision()
        cache_key = (id(spans), tuple(spans), rev)
        cached = getattr(self, "_typo_blocks_cache", None)
        if cached and cached[0] == cache_key:
            by_block = cached[1]
        else:
            by_block: dict[int, list[tuple[int, int]]] = {}
            for start, end in spans:
                block = doc.findBlock(start)
                if block.isValid():
                    by_block.setdefault(block.blockNumber(), []).append(
                        (start - block.position(), end - block.position()))
            self._typo_blocks_cache = (cache_key, by_block)
        block = self._first_visible_block()
        if not block:
            return
        painter.save()
        painter.setPen(QPen(qcolor, 1))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        doc_layout = doc.documentLayout()
        vp_h = self.viewport().height()
        while block.isValid():
            br = doc_layout.blockBoundingRect(block).translated(0, y_off)
            if br.top() > vp_h:
                break
            spans_b = by_block.get(block.blockNumber())
            if spans_b and br.bottom() >= 0:
                layout = block.layout()
                for local_s, local_e in spans_b:
                    line = layout.lineForTextPosition(local_s)
                    if not line.isValid():
                        continue
                    ts = line.textStart()
                    ls = max(local_s, ts)
                    le = min(local_e, ts + line.textLength())
                    if le <= ls:
                        continue
                    x = br.left() + line.x() + line.cursorToX(ls - ts)[0]
                    w = line.cursorToX(le - ts)[0] - line.cursorToX(ls - ts)[0]
                    y = br.top() + line.y() + line.ascent() + 1
                    segs = max(2, int(w / 5))
                    for k in range(segs):
                        sx = x + w * k / segs
                        ex = x + w * (k + 1) / segs
                        if k % 2 == 0:
                            painter.drawLine(QPointF(sx, y - 1), QPointF(ex, y + 1))
                        else:
                            painter.drawLine(QPointF(sx, y + 1), QPointF(ex, y - 1))
            block = block.next()
        painter.restore()

    def _toggle_checkboxes(self):
        doc = self.document()
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        if has_sel:
            start_block = doc.findBlock(cursor.selectionStart())
            end_block = doc.findBlock(cursor.selectionEnd())
        else:
            start_block = end_block = cursor.block()
        block = start_block
        with edit_block(cursor, self):
            self._toggle_checkbox_run(block, end_block)

    def _toggle_checkbox_run(self, block, end_block):
        while True:
            text = block.text()
            stripped = text.lstrip()
            if not stripped:
                # empty lines never become checkboxes
                if block == end_block:
                    break
                block = block.next()
                continue
            indent = text[:len(text) - len(stripped)]
            if stripped.startswith("[x] ") or stripped.startswith("[X] "):
                new_text = f"{indent}{self.strip_strike(stripped[4:])}"
            elif stripped.startswith("[ ] "):
                new_text = f"{indent}[x] {self.wrap_strike(stripped[4:])}"
            else:
                new_text = f"{indent}[ ] {stripped}"
            if new_text != text:
                bcursor = QTextCursor(block)
                bcursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                bcursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                bcursor.insertText(new_text)
            if block == end_block:
                break
            block = block.next()
