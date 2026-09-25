"""Minecraft-chest look for the silo file container.

The container's "Chest" view is the ordinary QListWidget icon grid painted as
a chest inventory: a light-grey panel of bevelled 36px slots, a fixed number
of slots (64 / 128) that are drawn even while empty, a stack-count badge in
the corner of folders, the white hover wash, and -- instead of a native
tooltip -- the dark-purple item card that follows the cursor.

The empty slots are real, disabled placeholder items (``PLACEHOLDER_ROLE``)
appended after the files. That keeps Qt in charge of the grid: the slots
line up with the files at every width and the scroll range covers the whole
chest, with no hand-maintained geometry to drift out of sync.

Nothing here does disk I/O on a timer. The card builds its text once per
hovered item (cached by path + mtime) from a single stat, plus a bounded
image-header read or a short text head for the preview.
"""

from __future__ import annotations

import datetime
import html
import os

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

SLOT = 36            # Minecraft 18px slot at GUI scale 2
ICON = 32            # 16px item sprite at GUI scale 2
CHEST_SLOT_CHOICES = ("dynamic", 64, 128)
DEFAULT_CHEST_SLOTS = "dynamic"

PLACEHOLDER_ROLE = Qt.ItemDataRole.UserRole + 7
BADGE_ROLE = Qt.ItemDataRole.UserRole + 8

# Minecraft GUI palette
PANEL_BG = QColor("#C6C6C6")
SLOT_BG = QColor("#8B8B8B")
SLOT_DARK = QColor("#373737")
SLOT_LIGHT = QColor("#FFFFFF")
HOVER_WASH = QColor(255, 255, 255, 128)
SELECT_FRAME = QColor("#FFFFA0")
BADGE_FG = QColor("#FFFFFF")
BADGE_SHADOW = QColor("#3F3F3F")


def chest_palette(main_win=None):
    """Derive chest palette from active theme, falling back to classic Minecraft."""
    if main_win is None:
        return {
            "panel_bg": PANEL_BG,
            "slot_bg": SLOT_BG,
            "slot_dark": SLOT_DARK,
            "slot_light": SLOT_LIGHT,
            "hover_wash": HOVER_WASH,
            "select_frame": SELECT_FRAME,
            "badge_fg": BADGE_FG,
            "badge_shadow": BADGE_SHADOW,
        }
    try:
        from fastprompter.theme.themes import theme_raw_colors
        raw = theme_raw_colors(main_win, fallback=None)
    except Exception:
        raw = None
    if not raw or not isinstance(raw, dict):
        return {
            "panel_bg": PANEL_BG,
            "slot_bg": SLOT_BG,
            "slot_dark": SLOT_DARK,
            "slot_light": SLOT_LIGHT,
            "hover_wash": HOVER_WASH,
            "select_frame": SELECT_FRAME,
            "badge_fg": BADGE_FG,
            "badge_shadow": BADGE_SHADOW,
        }
    panel_bg = QColor(raw.get("bg_main", "#C6C6C6"))
    slot_bg = QColor(raw.get("bg_text", "#8B8B8B"))
    slot_dark = QColor(raw.get("border_dark", "#373737"))
    slot_light = QColor(raw.get("border_light", "#FFFFFF"))
    accent = QColor(raw.get("accent", "#FFFFA0"))
    text_main = QColor(raw.get("text_main", "#FFFFFF"))

    hover = QColor(accent.red(), accent.green(), accent.blue(), 60) if accent.isValid() else HOVER_WASH

    return {
        "panel_bg": panel_bg,
        "slot_bg": slot_bg,
        "slot_dark": slot_dark,
        "slot_light": slot_light,
        "hover_wash": hover,
        "select_frame": accent if accent.isValid() else SELECT_FRAME,
        "badge_fg": text_main if text_main.isValid() else BADGE_FG,
        "badge_shadow": slot_dark if slot_dark.isValid() else BADGE_SHADOW,
    }


# Item-name "rarity" colours, as Minecraft tints item names
RARITY_COMMON = "#FFFFFF"
RARITY_UNCOMMON = "#FFFF55"
RARITY_RARE = "#55FFFF"
RARITY_EPIC = "#FF55FF"
TEXT_GRAY = "#AAAAAA"
TEXT_DARK = "#555555"
TEXT_BLUE = "#5555FF"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}
_ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"}
_EPIC_EXTS = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".lnk", ".url"}
_MEDIA_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".mp4", ".mkv", ".mov",
               ".avi", ".webm", ".m4a"}
_TEXT_EXTS = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".toml",
              ".ini", ".cfg", ".csv", ".log", ".js", ".ts", ".html", ".css",
              ".xml", ".bat", ".cmd", ".ps1", ".sh", ".c", ".cpp", ".h",
              ".rs", ".go", ".java", ".lua", ".sql"}
_TEXT_PREVIEW_LINES = 6
_TEXT_PREVIEW_BYTES = 4096
_TEXT_PREVIEW_MAX_FILE = 8 * 1024 * 1024
_PREVIEW_PX = 128
_PREVIEW_MAX_FILE = 40 * 1024 * 1024
_PREVIEW_MAX_PIXELS = 40_000_000


def pixel_font(px=11, bold=True):
    font = QFont("Verdana")
    font.setPixelSize(px)
    font.setBold(bold)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def chest_slots(data):
    """Configured slot count ('dynamic', 64, 128), tolerant of junk in the profile."""
    raw = (data or {}).get("silo_chest_slots", DEFAULT_CHEST_SLOTS)
    if isinstance(raw, str) and raw.strip().lower() in ("dynamic", "auto"):
        return "dynamic"
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return DEFAULT_CHEST_SLOTS
    return value if value in (64, 128) else DEFAULT_CHEST_SLOTS


def slot_total(file_count, capacity, columns=8):
    """Slots to draw: the capacity, or whole extra rows once it overflows.

    Files are never refused because the chest is "full" -- the grid just
    grows by full rows so the overflow still sits in proper slots.
    """
    if isinstance(capacity, str):
        capacity = 128
    if file_count <= capacity:
        return capacity
    columns = max(1, columns)
    return ((file_count + columns - 1) // columns) * columns


def paint_slot(p: QPainter, r: QRect, pal: dict | None = None):
    """One recessed inventory slot: dark top-left, white bottom-right."""
    slot_bg = pal["slot_bg"] if pal else SLOT_BG
    slot_dark = pal["slot_dark"] if pal else SLOT_DARK
    slot_light = pal["slot_light"] if pal else SLOT_LIGHT

    p.fillRect(r, slot_bg)
    p.fillRect(QRect(r.left(), r.top(), r.width(), 2), slot_dark)
    p.fillRect(QRect(r.left(), r.top(), 2, r.height()), slot_dark)
    p.fillRect(QRect(r.left(), r.bottom() - 1, r.width(), 2), slot_light)
    p.fillRect(QRect(r.right() - 1, r.top(), 2, r.height()), slot_light)
    # the two corners where light meets dark are the slot colour in MC
    p.fillRect(QRect(r.right() - 1, r.top(), 2, 2), slot_bg)
    p.fillRect(QRect(r.left(), r.bottom() - 1, 2, 2), slot_bg)


class ChestSlotDelegate(QStyledItemDelegate):
    """Paints every item -- file or empty placeholder -- as a chest slot."""

    def sizeHint(self, option, index):  # noqa: N802 (Qt naming)
        return QSize(SLOT, SLOT)

    def paint(self, p, option, index):
        win = getattr(self.parent(), "main_win", None)
        if win is None and hasattr(self.parent(), "_panel"):
            win = getattr(self.parent()._panel, "main_win", None)
        pal = chest_palette(win)
        cell = option.rect
        r = QRect(0, 0, SLOT, SLOT)
        r.moveCenter(cell.center())
        p.save()
        paint_slot(p, r, pal)
        inner = r.adjusted(2, 2, -2, -2)
        if not index.data(PLACEHOLDER_ROLE):
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon is not None and not icon.isNull():
                pix = icon.pixmap(QSize(ICON, ICON))
                if not pix.isNull():
                    size = pix.deviceIndependentSize().toSize()
                    size.scale(ICON, ICON, Qt.AspectRatioMode.KeepAspectRatio)
                    target = QRect(QPoint(0, 0), size)
                    target.moveCenter(inner.center())
                    p.drawPixmap(target, pix)
            badge = index.data(BADGE_ROLE)
            if badge:
                p.setFont(pixel_font(11))
                text_rect = inner.adjusted(0, 0, 0, 1)
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
                p.setPen(pal["badge_shadow"])
                p.drawText(text_rect.translated(1, 1), align, str(badge))
                p.setPen(pal["badge_fg"])
                p.drawText(text_rect, align, str(badge))
            if option.state & QStyle.StateFlag.State_Selected:
                p.setPen(pal["select_frame"])
                p.drawRect(inner.adjusted(0, 0, -1, -1))
                p.drawRect(inner.adjusted(1, 1, -2, -2))
        is_drag_hover = False
        lw = self.parent()
        if hasattr(lw, "_drag_hover_item") and lw._drag_hover_item is not None:
            if hasattr(lw, "itemFromIndex"):
                is_drag_hover = (lw.itemFromIndex(index) is lw._drag_hover_item)
        if (option.state & QStyle.StateFlag.State_MouseOver) or is_drag_hover:
            p.fillRect(inner, pal["hover_wash"])
        p.restore()


def make_placeholder():
    item = QListWidgetItem("")
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    item.setData(PLACEHOLDER_ROLE, True)
    item.setSizeHint(QSize(SLOT, SLOT))
    return item


def is_placeholder(item):
    return item is not None and bool(item.data(PLACEHOLDER_ROLE))


def folder_badge(path):
    """Stack count for a folder slot (entries inside), capped like a stack."""
    try:
        with os.scandir(path) as it:
            n = 0
            for _ in it:
                n += 1
                if n > 999:
                    break
    except OSError:
        return ""
    if n <= 1:
        return ""          # Minecraft never shows a count of 1
    return "999+" if n > 999 else str(n)


# ---- item card (the Minecraft tooltip) -----------------------------------

def _rarity(path, is_dir):
    ext = os.path.splitext(path)[1].lower()
    if is_dir:
        return RARITY_UNCOMMON
    if ext in IMAGE_EXTS or ext in _MEDIA_EXTS:
        return RARITY_RARE
    if ext in _ARCHIVE_EXTS or ext in _EPIC_EXTS:
        return RARITY_EPIC
    return RARITY_COMMON


def _fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024 / 1024 / 1024:.2f} GB"


def _fmt_time(ts):
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except (OverflowError, OSError, ValueError):
        return "?"


def _kind(path, is_dir, tr_fn, lang):
    if is_dir:
        return tr_fn("Folder", lang)
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return tr_fn("{} image", lang).format(ext[1:].upper())
    if ext:
        return tr_fn("{} file", lang).format(ext[1:].upper())
    return tr_fn("File", lang)


def image_preview(path, max_px=_PREVIEW_PX):
    """Bounded scaled decode for the card, or (None, None) if unsafe/invalid."""
    try:
        if os.path.getsize(path) > _PREVIEW_MAX_FILE:
            return None, None
    except OSError:
        return None, None
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > _PREVIEW_MAX_PIXELS:
        return None, size if size.isValid() else None
    scaled = QSize(size)
    if scaled.width() > max_px or scaled.height() > max_px:
        scaled.scale(max_px, max_px, Qt.AspectRatioMode.KeepAspectRatio)
    reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return None, size
    return QPixmap.fromImage(img), size


def _text_head(path):
    try:
        if os.path.getsize(path) > _TEXT_PREVIEW_MAX_FILE:
            return []
        with open(path, "rb") as fh:
            raw = fh.read(_TEXT_PREVIEW_BYTES)
    except OSError:
        return []
    if b"\x00" in raw:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if len(line) > 56:
            line = line[:55] + "…"
        lines.append(line)
        if len(lines) >= _TEXT_PREVIEW_LINES:
            break
    return lines


def build_item_card(path, tr_fn, lang="EN", summary_fn=None):
    """(html, preview_pixmap_or_None) for one container entry."""
    name = os.path.basename(path.rstrip("\\/")) or path
    try:
        st = os.stat(path)
    except OSError:
        body = (f"<div style='color:{RARITY_COMMON};'>{html.escape(name)}</div>"
                f"<div style='color:#FF5555;'>"
                f"{html.escape(tr_fn('File is gone', lang))}</div>")
        return _wrap(body), None
    is_dir = os.path.isdir(path)
    color = _rarity(path, is_dir)
    rows = [
        f"<div style='color:{color}; font-size:12px;'>{html.escape(name)}</div>",
        f"<div style='color:{TEXT_GRAY};'>{html.escape(_kind(path, is_dir, tr_fn, lang))}</div>",
    ]
    preview = None
    ext = os.path.splitext(path)[1].lower()
    if is_dir:
        if summary_fn is not None:
            try:
                summary = summary_fn(path, lang)
            except Exception:
                summary = ""
            for line in str(summary).splitlines()[:8]:
                rows.append(f"<div style='color:{TEXT_GRAY}; white-space:pre;'>"
                            f"{html.escape(line)}</div>")
    else:
        rows.append(f"<div style='color:{TEXT_GRAY};'>"
                    f"{html.escape(tr_fn('Size', lang))}: "
                    f"<span style='color:#FFFFFF;'>{_fmt_size(st.st_size)}</span></div>")
        if ext in IMAGE_EXTS:
            preview, dims = image_preview(path)
            if dims is not None:
                rows.append(f"<div style='color:{TEXT_GRAY};'>"
                            f"{dims.width()} × {dims.height()} px</div>")
        elif ext in _TEXT_EXTS:
            head = _text_head(path)
            if head:
                lines = "<br>".join(html.escape(line) for line in head)
                rows.append(f"<div style='color:{TEXT_DARK}; font-family:Consolas, monospace;"
                            f" font-size:10px; margin-top:3px;'>{lines}</div>")
    rows.append(f"<div style='color:{TEXT_GRAY}; margin-top:3px;'>"
                f"{html.escape(tr_fn('Modified', lang))}: {_fmt_time(st.st_mtime)}</div>")
    created = getattr(st, "st_birthtime", None) or st.st_ctime
    rows.append(f"<div style='color:{TEXT_GRAY};'>"
                f"{html.escape(tr_fn('Created', lang))}: {_fmt_time(created)}</div>")
    shown = path if len(path) <= 60 else path[:24] + "…" + path[-35:]
    rows.append(f"<div style='color:{TEXT_DARK}; font-size:10px; margin-top:3px;'>"
                f"{html.escape(shown)}</div>")
    if ext in IMAGE_EXTS:
        hints = (tr_fn("Double-click: open in viewer", lang),
                 tr_fn("Ctrl+C: copy image • Ctrl+Shift+C: copy path", lang))
    else:
        hints = (tr_fn("Double-click: open", lang),
                 tr_fn("Ctrl+C: copy • Ctrl+Shift+C: copy path", lang))
    rows.append(f"<div style='color:{TEXT_BLUE}; font-style:italic; font-size:10px;"
                f" margin-top:4px;'>{'<br>'.join(html.escape(h) for h in hints)}</div>")
    return _wrap("".join(rows)), preview


def _wrap(body):
    return ("<html><body style='font-family:Verdana, sans-serif; font-size:11px;'>"
            f"{body}</body></html>")


class ChestItemCard(QWidget):
    """The Minecraft item tooltip: near-black purple box that follows the
    cursor. Transparent to the mouse, never takes focus."""

    BG = QColor(16, 0, 16, 240)
    BORDER_TOP = QColor(80, 0, 255, 200)
    BORDER_BOTTOM = QColor(40, 0, 127, 200)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 9, 7)
        layout.setSpacing(8)
        self._pic = QLabel(self)
        self._pic.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._pic.hide()
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(False)
        self._label.setFont(pixel_font(11, bold=False))
        self._label.setStyleSheet("background: transparent;")
        col.addWidget(self._label)
        col.addStretch(1)
        layout.addWidget(self._pic)
        layout.addLayout(col)
        self.path = None

    def set_content(self, path, html_text, pixmap=None):
        self.path = path
        self._label.setText(html_text)
        if pixmap is not None and not pixmap.isNull():
            self._pic.setPixmap(pixmap)
            self._pic.show()
        else:
            self._pic.clear()
            self._pic.hide()
        self.adjustSize()

    def follow(self, global_pos):
        """Minecraft places the card up-right of the cursor, on screen."""
        x, y = global_pos.x() + 12, global_pos.y() - 12
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            if x + self.width() > area.right():
                x = global_pos.x() - 12 - self.width()
            if y + self.height() > area.bottom():
                y = area.bottom() - self.height()
            x = max(area.left(), x)
            y = max(area.top(), y)
        self.move(x, y)

    def paintEvent(self, _event):  # noqa: N802 (Qt naming)
        p = QPainter(self)
        r = self.rect()
        # outer 1px frame in the background colour, with notched corners
        p.fillRect(r.adjusted(1, 0, -1, 0), self.BG)
        p.fillRect(r.adjusted(0, 1, 0, -1), self.BG)
        inner = r.adjusted(1, 1, -1, -1)
        h = inner.height()
        for i in range(2, h - 2):
            t = i / max(1, h - 1)
            c = QColor(
                int(self.BORDER_TOP.red() + (self.BORDER_BOTTOM.red() - self.BORDER_TOP.red()) * t),
                int(self.BORDER_TOP.green() + (self.BORDER_BOTTOM.green() - self.BORDER_TOP.green()) * t),
                int(self.BORDER_TOP.blue() + (self.BORDER_BOTTOM.blue() - self.BORDER_TOP.blue()) * t),
                200)
            p.fillRect(inner.left() + 1, inner.top() + i, 1, 1, c)
            p.fillRect(inner.right() - 1, inner.top() + i, 1, 1, c)
        p.fillRect(inner.left() + 1, inner.top() + 1, inner.width() - 2, 1, self.BORDER_TOP)
        p.fillRect(inner.left() + 1, inner.bottom() - 1, inner.width() - 2, 1, self.BORDER_BOTTOM)
        p.end()
