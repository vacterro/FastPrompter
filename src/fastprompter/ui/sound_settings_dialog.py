"""The sound panel: every event, its file, its volume, on or off (T-707).

Nothing about WHICH sound plays is hardcoded here. The event list comes from
`sound_manager.EVENT_LABELS`, the file list from whatever WAVs are actually in
`sound/`, and every change is written straight into `data["sound_events"]`,
which is the same map the player reads.
"""

from typing import Any

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core import audio_level, sound_library
from fastprompter.core.sound_manager import (
    _DEFAULT_SOUND_MAP,
    EVENT_LABELS,
    GAIN_DB_MAX,
    GAIN_DB_MIN,
    effective_event_volume,
    get_event_gain_db,
    global_volume,
)
from fastprompter.core.translations import tr
from fastprompter.theme.themes import theme_raw_colors
from fastprompter.utils.fonts import no_aa

# PERF: every extra CELL WIDGET costs a full style+layout pass on a 58-row
# table (measured: setCellWidget dominates the build).  Auto therefore shares
# the Gain cell instead of owning a seventh column.
_COL_EVENT, _COL_ON, _COL_FILE, _COL_MODE, _COL_GAIN, _COL_PLAY = range(6)
_COL_AUTO = _COL_GAIN

#: Slider steps are whole dB: the control spans -24..+12 dB where 0 dB is
#: exactly the global volume (T-1242 spec 10-11).
_GAIN_MIN = int(GAIN_DB_MIN)
_GAIN_MAX = int(GAIN_DB_MAX)


def format_gain_db(value: float) -> str:
    """'-6 dB' / '0 dB' / '+3 dB' -- the compact numeric label."""
    rounded = round(float(value), 1)
    if abs(rounded - round(rounded)) < 0.05:
        text = f"{int(round(rounded))}"
    else:
        text = f"{rounded:.1f}"
    if rounded > 0:
        text = "+" + text
    return f"{text} dB"

class _GainSlider(QSlider):
    """A dB slider that snaps back to 0 dB (= global volume) on double-click."""

    reset_requested = pyqtSignal()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt naming)
        self.reset_requested.emit()
        event.accept()


class _LazyEventDict(dict):
    """Dictionary that triggers full row building if an unbuilt event is accessed."""

    def __init__(self, dialog, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dialog = dialog

    def __getitem__(self, key):
        if key not in self:
            self._dialog._ensure_all_events_built()
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key not in self:
            self._dialog._ensure_all_events_built()
        return super().get(key, default)


#: C3.1 -- the per-event playback override stored in sound_events[e]["mode"].
_EVENT_MODE_CHOICES = (
    ("inherit", "Inherit"),
    ("mix", "Overlay"),
    ("queue", "Stack"),
    ("replace", "Replace"),
)

# A small painted pictogram per event, so the table is scannable without
# reading every label. Drawn, not emoji: no font dependency, and it matches
# the painted-language-flags approach used elsewhere in the app.
_EVENT_GLYPHS: dict[str, str] = {
    "new": "plus", "save": "save", "silo": "swap", "project": "swap", "snippet": "doc",
    "tick": "check", "untick": "box", "delete": "cross", "clear": "cross",
    "undo": "undo", "redo": "redo", "select_all": "check_list",
    "settings": "gear", "help": "question", "hotkey": "key",
    "bold": "bold", "italic": "italic", "underline": "underline",
    "strike": "strike", "header": "header", "divider": "line",
    "snap": "corner", "find": "magnifier", "replace": "swap_r",
    "focus": "lock", "export": "export", "quit": "quit",
    "archive": "folder", "snippets_toggle": "panel", "transform": "swap_t",
    "sidebar": "panel", "lock": "lock", "copy": "copy", "paste": "paste",
    "cut": "scissors", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
    "escape": "esc", "search": "magnifier", "backup": "floppy_up",
    "restore": "restore", "reset": "reset", "timer_start": "clock",
    "profile": "user", "watcher": "eye", "type": "keyboard",
    "backspace": "key_b", "delete_forward": "key", "delete_selection": "cross",
    "click": "cursor", "hover": "cursor_hover",
    "button_click": "cursor_click", "button_release": "cursor_up",
    "chest_open": "folder_open", "chest_close": "folder", "notify": "bell",
    "error": "exclaim", "success": "check_circle", "timer": "alarm",
}

# Unknown glyph -> the bell, so a new event still gets a picture.
_GLYPH_FALLBACK = "bell"


def _luminance(color: QColor) -> float:
    """Rec.609 relative luminance, 0.0 (black) .. 1.0 (white)."""
    return (0.299 * color.red() + 0.587 * color.green()
            + 0.114 * color.blue()) / 255.0


def _contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG-style contrast ratio between two colours (>= 1.0)."""
    la = _luminance(a)
    lb = _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


_THEME_ICON_FALLBACK = QColor("#d0d0d0")


def _table_background_color(dialog: QWidget) -> QColor:
    """The ACTUAL painted background of the events table, best effort.

    Prefer the ACTIVE THEME's own background tokens; a widget QPalette is
    exactly as unreliable under QSS as palette Text was for the foreground
    (both are desynced whenever a stylesheet is active).
    """
    raw = theme_raw_colors(getattr(dialog, "main_win", None), {})
    for key in ("bg_text", "bg_main"):  # bg_text = table/editor surface
        value = raw.get(key)
        if not value:
            continue
        try:
            color = QColor(str(value))
        except (TypeError, ValueError):
            continue
        if color.isValid():
            return color
    try:
        color = dialog.table.palette().color(
            dialog.table.palette().ColorRole.Base)
        if color.isValid():
            return color
    except Exception:
        pass
    return QColor("#000000")


def _theme_icon_color(main_win, dialog: QWidget) -> QColor:
    """Icon foreground from the ACTIVE theme tokens (T-1242, spec 20/21).

    Order: theme text_main, then btn_text, then a visible neutral -- each
    accepted only if it contrasts with the table background.  Never a
    per-event rainbow: glyph shape distinguishes events, colour stays
    theme-consistent.
    """
    fallback = {"text_main": "#d4b87a", "btn_text": "#d0d0d0"}
    raw = theme_raw_colors(main_win, fallback)
    background = _table_background_color(dialog)
    for key in ("text_main", "btn_text"):
        value = raw.get(key)
        if not value:
            continue
        try:
            color = QColor(str(value))
        except (TypeError, ValueError):
            continue
        if color.isValid() and _contrast_ratio(color, background) >= 3.0:
            return color
    # All theme tokens failed the contrast guard: pick whichever neutral
    # (light or dark) actually contrasts with the background.
    neutral = QColor("#d0d0d0") if _luminance(background) < 0.5 \
        else QColor("#202020")
    if _contrast_ratio(neutral, background) >= 3.0:
        return neutral
    return _THEME_ICON_FALLBACK if _contrast_ratio(
        _THEME_ICON_FALLBACK, background) >= _contrast_ratio(
        QColor("#202020"), background) else QColor("#202020")


def _event_color(event: str, base: QColor) -> QColor:
    """The icon colour for one event.

    DELIBERATELY the theme's own colour, never a per-event hue rotation:
    a rainbow of icons inside the dark-golden app read as "the theme broke"
    (user report, v0.8.28). Distinction between events comes from the GLYPH
    SHAPE, not from colour, so the theme family is never violated."""
    return base


def _event_icon(event: str, base: QColor) -> QIcon:
    """A 20x20 painted pictogram for one sound event, tinted per event."""
    color = _event_color(event, base)
    glyph = _EVENT_GLYPHS.get(event, _GLYPH_FALLBACK)
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    pen = QPen(QColor(color), 1.4)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # helpers used by several glyphs
    def line(x1, y1, x2, y2):
        p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def arrow(x1, y1, x2, y2):
        p.drawLine(int(x1), int(y1), int(x2), int(y2))
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        for da in (2.5, -2.5):
            p.drawLine(int(x2), int(y2),
                       int(x2 - 3.5 * math.cos(ang + da)),
                       int(y2 - 3.5 * math.sin(ang + da)))

    def circle(cx, cy, r):
        p.drawEllipse(QRect(int(cx - r), int(cy - r), int(2 * r), int(2 * r)))

    if glyph == "plus":
        line(10, 4, 10, 16); line(4, 10, 16, 10)
    elif glyph == "save":
        p.drawRect(QRect(3, 3, 14, 14)); p.drawRect(QRect(6, 6, 8, 6)); line(6, 15, 14, 15)
    elif glyph == "doc":
        p.drawRect(QRect(6, 3, 8, 14)); line(8, 6, 12, 6); line(8, 9, 12, 9); line(8, 12, 11, 12)
    elif glyph == "check":
        line(3, 10, 8, 15); line(8, 15, 17, 5)
    elif glyph == "cross":
        line(5, 5, 15, 15); line(15, 5, 5, 15)
    elif glyph == "undo":
        arrow(15, 5, 7, 5); p.drawArc(QRect(4, 4, 11, 11), 60 * 16, -180 * 16)
    elif glyph == "redo":
        arrow(5, 5, 13, 5); p.drawArc(QRect(5, 4, 11, 11), 120 * 16, 180 * 16)
    elif glyph == "gear":
        circle(10, 10, 4.5); p.drawEllipse(QRect(7, 7, 6, 6))
        for a in range(0, 360, 45):
            import math
            r0, r1 = 7.5, 9.5
            p.drawLine(int(10 + r0 * math.cos(math.radians(a))),
                       int(10 + r0 * math.sin(math.radians(a))),
                       int(10 + r1 * math.cos(math.radians(a))),
                       int(10 + r1 * math.sin(math.radians(a))))
    elif glyph == "question":
        p.drawText(QRect(2, 2, 16, 16), Qt.AlignmentFlag.AlignCenter, "?")
    elif glyph == "key":
        circle(6, 10, 3.5); line(9, 10, 15, 10); line(13, 10, 13, 13); line(15, 10, 15, 13)
    elif glyph == "bold":
        p.setFont(no_aa(QFont("Verdana", 9, QFont.Weight.Bold)))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "B")
    elif glyph == "italic":
        p.setFont(no_aa(QFont("Verdana", 9, QFont.Weight.Normal)))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "I")
    elif glyph == "underline":
        p.setFont(no_aa(QFont("Verdana", 9, QFont.Weight.Normal)))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "U")
        line(4, 17, 16, 17)
    elif glyph == "strike":
        p.setFont(no_aa(QFont("Verdana", 9, QFont.Weight.Normal)))
        p.drawText(QRect(2, 1, 16, 18), Qt.AlignmentFlag.AlignCenter, "S")
        line(3, 11, 17, 11)
    elif glyph == "header":
        line(5, 4, 5, 16); line(15, 4, 15, 16); line(5, 10, 15, 10)
    elif glyph == "line":
        line(3, 10, 17, 10)
    elif glyph == "corner":
        line(3, 3, 3, 17); line(3, 17, 17, 17)
    elif glyph == "magnifier":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16)
    elif glyph == "lock":
        p.drawRect(QRect(5, 9, 10, 8)); p.drawArc(QRect(6, 4, 8, 8), 0, 180 * 16); line(9, 13, 11, 13)
    elif glyph == "export":
        arrow(10, 3, 10, 13); line(10, 3, 6, 7); line(10, 3, 14, 7); line(3, 17, 17, 17)
    elif glyph == "quit":
        arrow(10, 3, 10, 13); line(10, 3, 6, 7); line(10, 3, 14, 7); line(3, 17, 17, 17)
        line(3, 17, 17, 17)
    elif glyph == "folder":
        path = QPainterPath()
        path.moveTo(2, 8)
        path.lineTo(18, 8)
        path.lineTo(18, 17)
        path.lineTo(2, 17)
        path.closeSubpath()
        p.drawPath(path)
        line(2, 6, 8, 6)
        line(2, 6, 2, 17)
    elif glyph == "panel":
        line(3, 6, 17, 6); line(3, 11, 17, 11); line(3, 16, 17, 16)
    elif glyph == "scissors":
        line(4, 4, 16, 16); line(16, 4, 4, 16); circle(4, 4, 2.2); circle(16, 4, 2.2)
    elif glyph == "copy":
        p.drawRect(QRect(4, 6, 10, 12)); line(7, 4, 17, 4); line(17, 4, 17, 14)
    elif glyph == "paste":
        p.drawRect(QRect(4, 6, 12, 11)); p.drawRect(QRect(8, 3, 5, 4))
    elif glyph == "zoom_in":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16); line(8, 5, 8, 11); line(5, 8, 11, 8)
    elif glyph == "zoom_out":
        circle(8, 8, 4.5); line(11.5, 11.5, 16, 16); line(5, 8, 11, 8)
    elif glyph == "restore":
        circle(10, 10, 6); arrow(14, 5, 10, 5); line(10, 5, 10, 10)
    elif glyph == "reset":
        arrow(13, 13, 15, 11); p.drawArc(QRect(4, 4, 12, 12), 30 * 16, 300 * 16)
    elif glyph == "clock":
        circle(10, 10, 6.5); line(10, 6, 10, 10); line(10, 10, 14, 12)
    elif glyph == "user":
        circle(10, 6, 3); p.drawArc(QRect(4, 10, 12, 9), 0, 180 * 16)
    elif glyph == "eye":
        p.drawEllipse(QRect(2, 7, 16, 8)); circle(10, 11, 2.5)
    elif glyph == "cursor":
        p.setBrush(QColor(color))
        p.drawPolygon([QPoint(5, 3), QPoint(15, 10), QPoint(10, 11),
                       QPoint(12, 16), QPoint(8, 16), QPoint(7, 11), QPoint(5, 3)])
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif glyph == "bell":
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14); line(10, 15, 10, 17)
    elif glyph == "exclaim":
        line(10, 4, 10, 12); p.drawEllipse(QRect(8, 14, 4, 4))
    elif glyph == "alarm":
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14); line(10, 15, 10, 17)
        line(10, 6, 10, 10); line(10, 10, 13, 12)
    elif glyph == "box":
        p.drawRect(QRect(5, 5, 10, 10))
    elif glyph == "check_circle":
        circle(10, 10, 6.5); line(6.5, 10, 9, 12.5); line(9, 12.5, 14, 6.5)
    elif glyph == "check_list":
        line(3, 6, 17, 6); line(3, 11, 17, 11); line(3, 16, 17, 16)
        line(4, 5, 6, 7); line(6, 7, 11, 3)
    elif glyph == "esc":
        p.setFont(no_aa(QFont("Verdana", 6, QFont.Weight.Bold)))
        p.drawText(QRect(0, 3, 20, 14), Qt.AlignmentFlag.AlignCenter, "Esc")
    elif glyph == "floppy_up":
        p.drawRect(QRect(4, 4, 12, 12)); line(10, 6, 10, 13); line(10, 6, 7, 9); line(10, 6, 13, 9)
    elif glyph == "cursor_click":
        p.setBrush(QColor(color))
        p.drawPolygon([QPoint(4, 3), QPoint(14, 9), QPoint(9, 10),
                       QPoint(11, 15), QPoint(8, 15), QPoint(6, 10), QPoint(4, 3)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        circle(15, 4, 2.5)
    elif glyph == "cursor_up":
        p.setBrush(QColor(color))
        p.drawPolygon([QPoint(5, 4), QPoint(14, 9), QPoint(9, 10),
                       QPoint(11, 15), QPoint(8, 15), QPoint(6, 10), QPoint(5, 4)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        line(16, 3, 16, 5); line(16, 3, 14, 4); line(16, 3, 18, 4)
    elif glyph == "cursor_hover":
        p.setBrush(QColor(color))
        p.drawPolygon([QPoint(5, 4), QPoint(14, 9), QPoint(9, 10),
                       QPoint(11, 15), QPoint(8, 15), QPoint(6, 10), QPoint(5, 4)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        circle(12, 2.5, 1.6)
    elif glyph == "swap_r":
        arrow(15, 5, 7, 5); arrow(5, 15, 13, 15)
    elif glyph == "swap_t":
        arrow(13, 5, 15, 5); p.drawArc(QRect(4, 4, 12, 12), 60 * 16, 260 * 16)
    elif glyph == "key_b":
        circle(6, 10, 3.5); line(9, 10, 15, 10)
        arrow(11, 7, 8, 7)
    elif glyph == "keyboard":
        p.drawRect(QRect(2, 7, 16, 8)); line(4, 9.5, 16, 9.5)
        line(4, 12, 16, 12)
    elif glyph == "folder_open":
        p.drawLine(2, 8, 6, 4); p.drawLine(6, 4, 18, 4); p.drawLine(2, 8, 18, 8)
        line(2, 8, 2, 17); line(2, 17, 18, 17); line(18, 8, 18, 17)
    else:
        p.drawArc(QRect(4, 3, 12, 11), 0, 180 * 16); line(4, 14, 16, 14)
    p.end()
    return QIcon(pm)


class SoundSettingsDialog(QDialog):
    # Last live dialog instance, for the theme-change repaint hook in
    # theme_mixin.apply_theme. Kept as a plain reference only while the
    # dialog exists (cleared on close), never across dialog lifetimes.
    _LAST_INSTANCE = None  # type: ClassVar[Optional[SoundSettingsDialog]]

    _HUB_PAGE_ATTRS = {
        1: "presets_page",
        2: "playback_page",
        3: "voice_page",
        4: "ambience_page",
    }

    @property
    def presets_page(self):
        if getattr(self, "_presets_page_instance", None) is not None:
            return self._presets_page_instance
        return self._ensure_hub_page(1)

    @presets_page.setter
    def presets_page(self, val):
        self._presets_page_instance = val

    @property
    def playback_page(self):
        if getattr(self, "_playback_page_instance", None) is not None:
            return self._playback_page_instance
        return self._ensure_hub_page(2)

    @playback_page.setter
    def playback_page(self, val):
        self._playback_page_instance = val

    @property
    def voice_page(self):
        if getattr(self, "_voice_page_instance", None) is not None:
            return self._voice_page_instance
        return self._ensure_hub_page(3)

    @voice_page.setter
    def voice_page(self, val):
        self._voice_page_instance = val

    @property
    def ambience_page(self):
        if getattr(self, "_ambience_page_instance", None) is not None:
            return self._ambience_page_instance
        return self._ensure_hub_page(4)

    @ambience_page.setter
    def ambience_page(self, val):
        self._ambience_page_instance = val

    def _ensure_hub_page(self, index: int):
        attr = self._HUB_PAGE_ATTRS.get(index)
        if not attr:
            return None
        inst_attr = f"_{attr}_instance"
        existing = getattr(self, inst_attr, None)
        if existing is not None:
            return existing

        host = self.main_win
        page = None
        if index == 1:
            from fastprompter.ui.audio_hub_pages import PresetsPage
            page = PresetsPage(self, self.lang)
        elif index == 2:
            from fastprompter.ui.audio_hub_pages import PlaybackPage
            page = PlaybackPage(self, self.lang)
        elif index == 3:
            from fastprompter.ui.audio_hub_pages import VoicePage
            page = VoicePage(self, self.lang, getattr(host, "voice_controller", None))
        elif index == 4:
            from fastprompter.ui.audio_hub_pages import AmbiencePage
            page = AmbiencePage(self, self.lang, getattr(host, "ambience_controller", None))

        setattr(self, inst_attr, page)
        if hasattr(self, "pages") and self.pages.count() > index:
            placeholder = self.pages.widget(index)
            if placeholder is not page:
                title = self.pages.tabText(index)
                curr = self.pages.currentIndex()
                self.pages.removeTab(index)
                self.pages.insertTab(index, page, title)
                if curr == index:
                    self.pages.setCurrentIndex(index)
        return page

    def __init__(self, parent, data: dict[str, Any], sound_manager):
        super().__init__(parent)
        self.main_win = parent
        self._data = data
        self._sound_manager = sound_manager
        self._available = sound_manager.get_available_sounds()
        # PERF: every event row used to fill its OWN combo with the whole
        # library.  With ~60 events that is tens of thousands of widget items
        # and seconds of startup.  ONE shared item model is built here and
        # handed to every combo; each combo still keeps its own currentIndex.
        self._sound_model = QStandardItemModel(self)
        self._model_rows: dict[str, int] = {}
        self.lang = getattr(parent, "_current_lang", "EN")
        # Set while widgets are being filled from settings. Every handler
        # returns early on it, which is what keeps _load_settings() from
        # writing back the values it just read — and lets Reset reuse the
        # same loader instead of a second, drifting copy of it.
        self._loading = False
        self._built_events_count = 0
        self._all_events = list(EVENT_LABELS)
        self._presets_page_instance = None
        self._playback_page_instance = None
        self._voice_page_instance = None
        self._ambience_page_instance = None
        #: event -> the "show its math" block appended to the Gain tooltip
        #: after Auto Level ran (T-1242 spec 15).
        self._auto_detail: dict[str, str] = {}
        self._gains = _LazyEventDict(self)
        self._gain_labels = _LazyEventDict(self)
        self._auto_buttons = _LazyEventDict(self)
        self._combos = _LazyEventDict(self)
        self._fav_btns = _LazyEventDict(self)
        self._modes = _LazyEventDict(self)
        self._rows = _LazyEventDict(self)
        self._icon_items: dict[Any, Any] = {}
        # Register for the theme-change repaint hook; cleared on close below.
        type(self)._LAST_INSTANCE = self

        self.setWindowTitle(tr("Sound Settings", self.lang))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(720, 520)
        # Wear the app's theme. Without this the dialog is a stock-white Qt
        # window inside a dark golden app — the scrollbar and the table's
        # empty right-hand strip came out bright white.
        try:
            self.setStyleSheet(parent.styleSheet())
        except Exception:
            pass
        self._rebuild_sound_model()
        # PERF: the application installs APPLICATION-WIDE event filters (UI
        # click sound, wheel guard, scroll sound, layout shortcuts).  They
        # fire for every event of every widget, so creating ~350 cell widgets
        # ran them ~47k times.  Nothing here is a user interaction, so they
        # are suspended for the build and restored in a finally.
        self.setUpdatesEnabled(False)
        suspended = self._suspend_app_event_filters()
        try:
            self._build()
            self._load_settings()
        finally:
            self._restore_app_event_filters(suspended)
            self.setUpdatesEnabled(True)

    # ---- construction -------------------------------------------------

    _APP_FILTER_ATTRS = ("_scroll_sound_filter", "_wheel_guard",
                         "_button_sound_filter")

    def _suspend_app_event_filters(self):
        """Take the app-wide filters off while widgets are being created."""
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return []
        suspended = []
        for attr in self._APP_FILTER_ATTRS:
            handler = getattr(self.main_win, attr, None)
            if handler is None:
                continue
            try:
                app.removeEventFilter(handler)
                suspended.append(handler)
            except (RuntimeError, TypeError):
                pass
        return suspended

    def _restore_app_event_filters(self, suspended):
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        for handler in suspended:
            try:
                app.installEventFilter(handler)
            except (RuntimeError, TypeError):
                pass

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # T-1242 spec 9/35: the old copy ("Volume 0 = the global volume")
        # read as "the global volume IS zero".  Show the ACTUAL master value
        # and keep it live while the dialog is open.
        info = QLabel()
        info.setWordWrap(True)
        layout.addWidget(info)
        self._global_label = info
        self._last_master = None
        self._refresh_global_label()
        from PyQt6.QtCore import QTimer

        self._master_poll = QTimer(self)
        self._master_poll.setInterval(400)
        self._master_poll.timeout.connect(self._refresh_global_label)
        self._master_poll.start()

        # T-1238-C3: the dialog IS the Audio Hub now.  The proven event table
        # keeps its own page; the other pages are built beside it, never in a
        # second independent settings window.
        self.pages = QTabWidget()
        self._page_titles = ("Events", "Presets", "Playback", "Voice",
                             "Ambience")
        events_page = QWidget()
        layout.addWidget(self.pages, 1)

        events_layout = QVBoxLayout(events_page)
        events_layout.setContentsMargins(0, 0, 0, 0)
        events_layout.setSpacing(6)
        layout = events_layout  # the table below fills the Events page

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText(tr("Filter events…", self.lang))
        self.filter_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_box)

        # T-1242: the pictogram colour comes from the ACTIVE THEME's raw
        # tokens, never from the widget QPalette -- a QSS-heavy theme does
        # not keep QPalette.Text in sync, which left icons nearly black on
        # the dark Golden theme.  Contrast is checked against the actual
        # table background with a tiered fallback (text_main -> btn_text ->
        # visible neutral) so the icons are readable on every theme.
        icon_color = _theme_icon_color(getattr(self, "main_win", None), self)
        self._icon_color = icon_color

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            tr("Event", self.lang), tr("On", self.lang), tr("Sound", self.lang),
            tr("Mode", self.lang), tr("Gain", self.lang), "▶",
        ])
        # T-1242 (spec 19): compact 28px rows -- every control stays
        # vertically unclipped at Qt's default font metrics.  Set ONCE as the
        # default section size: a per-row setRowHeight re-runs the table's
        # geometry pass on every call.
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        # Zebra tones come from the theme's alternate-background-color
        # (themes.py), NOT from a palette tweak here — a widget palette is
        # ignored while a stylesheet is active, so the old lighter(106) hack
        # left AlternateBase at Qt's default WHITE (v0.8.29 regression:
        # "white on near-white").

        events = self._all_events
        self.table.setRowCount(len(events))
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)

        # Build initial batch of rows immediately (10 rows is enough to fill viewport)
        self._build_events_chunk(0, 10)

        self.table.setUpdatesEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_EVENT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_MODE,
                                    QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_GAIN,
                                    QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_PLAY, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.pages.addTab(events_page, tr("Events", self.lang))
        self._build_hub_pages()

        # Schedule remaining rows via singleShot timer
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._build_remaining_events)

        layout = self.layout()
        buttons = QHBoxLayout()
        stop_all = QPushButton(tr("■ STOP ALL SOUND", self.lang))
        stop_all.setToolTip(tr(
            "Silence every channel, queue, sequence and ambience layer now.\n"
            "Does not change the master mute; new sounds stay allowed.",
            self.lang))
        stop_all.clicked.connect(self._on_stop_all_sound)
        buttons.addWidget(stop_all)
        reset = QPushButton(tr("Reset to defaults", self.lang))
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        diagnostics = QPushButton(tr("Copy sound diagnostics", self.lang))
        diagnostics.clicked.connect(self._copy_sound_diagnostics)
        buttons.addWidget(diagnostics)
        auto_all = QPushButton(tr("Auto level enabled sounds", self.lang))
        auto_all.setToolTip(tr(
            "Measure every enabled sound and store matching negative gains",
            self.lang))
        auto_all.clicked.connect(self._on_auto_level_all)
        buttons.addWidget(auto_all)
        self._auto_all_button = auto_all
        # A failed preview gets a compact status line, never a modal.
        self._status_label = QLabel("")
        self._status_label.setWordWrap(False)
        buttons.addWidget(self._status_label, 1)
        buttons.addStretch()
        close = QPushButton(tr("Close", self.lang))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _build_single_row(self, row: int, event: str) -> None:
        auto_tip = tr("Measure this sound and store a matching negative gain",
                      self.lang)
        auto_text = tr("Auto", self.lang)
        play_tip = tr("Play this sound", self.lang)
        fav_tip = tr("Favorite this sound", self.lang)

        item = QTableWidgetItem(tr(EVENT_LABELS[event], self.lang))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(event)
        item.setIcon(_event_icon(event, self._icon_color))
        self.table.setItem(row, _COL_EVENT, item)
        self._icon_items[(row, _COL_EVENT)] = (event, item)

        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable)
        on.setCheckState(Qt.CheckState.Unchecked)
        on.setData(Qt.ItemDataRole.UserRole, event)
        self.table.setItem(row, _COL_ON, on)

        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(4)
        
        combo = QComboBox()
        combo.setMaxVisibleItems(20)
        self._populate_combo(combo)
        combo.currentIndexChanged.connect(
            lambda _idx, e=event, c=combo: self._set_file(e, c))
            
        fav_btn = QPushButton("☆")
        fav_btn.setCheckable(True)
        fav_btn.setFixedSize(24, 24)
        fav_btn.setToolTip(fav_tip)
        fav_btn.toggled.connect(lambda checked, c=combo: self._toggle_favorite(checked, c))
        def _update_btn(idx, c=combo, btn=fav_btn):
            is_fav = c.currentData() in self._data.get("sound_favorites", [])
            btn.blockSignals(True)
            btn.setChecked(is_fav)
            btn.setText("★" if is_fav else "☆")
            btn.blockSignals(False)
        combo.currentIndexChanged.connect(_update_btn)
        
        file_layout.addWidget(combo, 1)
        file_layout.addWidget(fav_btn, 0)
        self.table.setCellWidget(row, _COL_FILE, file_widget)
        
        self._combos[event] = combo
        self._fav_btns[event] = fav_btn

        mode = QComboBox()
        for value, text in _EVENT_MODE_CHOICES:
            mode.addItem(tr(text, self.lang), value)
        mode._en_items = [t for _v, t in _EVENT_MODE_CHOICES]
        mode.currentIndexChanged.connect(
            lambda _i, e=event, c=mode: self._set_mode(e, c))
        self.table.setCellWidget(row, _COL_MODE, mode)
        self._modes[event] = mode

        gain_cell = QWidget()
        gain_layout = QHBoxLayout(gain_cell)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.setSpacing(4)
        gain = _GainSlider(Qt.Orientation.Horizontal)
        gain.setRange(_GAIN_MIN, _GAIN_MAX)
        gain.setTickPosition(QSlider.TickPosition.TicksBelow)
        gain.setTickInterval(6)
        gain.setFixedWidth(104)
        gain.reset_requested.connect(
            lambda e=event: self._reset_gain(e))
        gain.valueChanged.connect(
            lambda v, e=event: self._set_gain(e, float(v)))
        gain_label = QLabel(format_gain_db(0.0))
        gain_label.setMinimumWidth(46)
        gain_layout.addWidget(gain)
        gain_layout.addWidget(gain_label)
        self._gains[event] = gain
        self._gain_labels[event] = gain_label

        auto = QPushButton(auto_text)
        auto.setFixedWidth(40)
        auto.setToolTip(auto_tip)
        auto.clicked.connect(lambda _c, e=event: self._auto_level(e))
        gain_layout.addWidget(auto)
        self._auto_buttons[event] = auto
        self.table.setCellWidget(row, _COL_GAIN, gain_cell)

        play = QTableWidgetItem("▶")
        play.setFlags(Qt.ItemFlag.ItemIsEnabled)
        play.setToolTip(play_tip)
        play.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, _COL_PLAY, play)

        self._rows[event] = row
        self._load_row_settings(event, row)

    def _build_events_chunk(self, start: int, count: int) -> None:
        end = min(len(self._all_events), start + count)
        was_loading = self._loading
        self._loading = True
        self.table.blockSignals(True)
        try:
            for row in range(start, end):
                self._build_single_row(row, self._all_events[row])
        finally:
            self.table.blockSignals(False)
            self._loading = was_loading
        self._built_events_count = end

    def _build_remaining_events(self) -> None:
        if self._built_events_count >= len(self._all_events):
            return
        chunk_size = 15
        self.table.setUpdatesEnabled(False)
        try:
            self._build_events_chunk(self._built_events_count, chunk_size)
        finally:
            self.table.setUpdatesEnabled(True)
        if self._built_events_count < len(self._all_events):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._build_remaining_events)

    def _ensure_all_events_built(self) -> None:
        if self._built_events_count < len(self._all_events):
            self.table.setUpdatesEnabled(False)
            try:
                self._build_events_chunk(
                    self._built_events_count,
                    len(self._all_events) - self._built_events_count)
            finally:
                self.table.setUpdatesEnabled(True)

    def _on_stop_all_sound(self) -> None:
        """T-1244 A2: the ONE canonical STOP ALL handler for the dialog.

        Delegates to SoundManager.stop_all_sound() (the same authority the
        Playback and Problip actions use); never flips master mute and
        never disables future audio.
        """
        self._sound_manager.stop_all_sound()
        controller = getattr(self.main_win, "ambience_controller", None)
        if controller is not None:
            controller.stop_runtime_only()
        self._set_status(tr("All sounds stopped", self.lang))

    def repaint_event_icons(self):
        """Re-render the painted pictograms for the ACTIVE theme (spec 21).

        Called after a theme change: the old pixmaps carry the previous
        theme's colour, so they are regenerated without rebuilding any
        other dialog state.
        """
        try:
            color = _theme_icon_color(getattr(self, "main_win", None), self)
        except Exception:
            return
        self._icon_color = color
        for (row, _column), (event, item) in getattr(self, "_icon_items",
                                                     {}).items():
            try:
                item.setIcon(_event_icon(event, color))
            except RuntimeError:
                continue  # dialog torn down mid-repaint

    def _build_hub_pages(self):
        """Presets / Playback / Voice / Ambience lazy placeholders."""
        self.pages.addTab(QWidget(), tr("Presets", self.lang))
        self.pages.addTab(QWidget(), tr("Playback", self.lang))
        self.pages.addTab(QWidget(), tr("Voice", self.lang))
        self.pages.addTab(QWidget(), tr("Ambience", self.lang))
        self.pages.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int):
        if index > 0:
            self._ensure_hub_page(index)

    # ---- cross-page refresh -------------------------------------------

    def done(self, result):  # noqa: D102 - QDialog override
        """Clear the theme-repaint hook registration before widgets die."""
        try:
            if type(self)._LAST_INSTANCE is self:
                type(self)._LAST_INSTANCE = None
        except RuntimeError:
            pass
        super().done(result)

    def reload_after_preset(self):
        """A preset was applied: re-read mappings and the global mode."""
        self._load_settings()
        page = getattr(self, "playback_page", None)
        if page is not None:
            page.reload()
        self._touch()

    def reload_sound_library(self):
        """The managed library changed: rebuild the shared picker model."""
        self._ensure_all_events_built()
        self._sound_manager.invalidate_cache()
        self._available = self._sound_manager.get_available_sounds()
        self._available += sound_library.list_managed_sounds()
        was_loading = self._loading
        self._loading = True
        try:
            selections = {event: combo.currentData()
                          for event, combo in self._combos.items()}
            self._rebuild_sound_model()
            for event, combo in self._combos.items():
                index = combo.findData(selections.get(event))
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            self._loading = was_loading
        self._load_settings()

    def events_using_ref(self, ref: str) -> list[str]:
        """Which event mappings still point at this managed-library file."""
        using = []
        for event, config in (self._data.get("sound_events") or {}).items():
            if isinstance(config, dict) and config.get("file") == ref:
                using.append(event)
        return sorted(using)

    # ---- settings <-> widgets -----------------------------------------
    def _copy_sound_diagnostics(self):
        """Everything needed to answer "I heard nothing" from one paste.

        T-1242 spec 34: the per-request entries already carry the effective
        global volume, the event gain, the effective amplitude, the source
        and rendered WAV formats and the transport's own failure reason; the
        header adds the backend and the master value they are relative to.
        No user text is included.
        """
        import json

        from PyQt6.QtWidgets import QApplication

        manager = self._sound_manager
        payload = {
            "global_volume": round(global_volume(self._data), 4),
            "backend": (manager.backend_status()
                        if hasattr(manager, "backend_status") else {}),
            "requests": manager.diagnostic_log(),
        }
        trace = getattr(manager, "transport_diagnostic_log", None)
        if callable(trace):
            payload["transport_trace"] = trace()
        QApplication.clipboard().setText(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    def _rebuild_sound_model(self):
        """Build the ONE model every file combo shares."""
        favs = set(self._data.get("sound_favorites", []))
        self._sound_model.clear()
        self._model_rows = {}
        for name in self._available:
            item = QStandardItem(f"★ {name}" if name in favs else name)
            item.setData(name, Qt.ItemDataRole.UserRole)
            self._model_rows[name] = self._sound_model.rowCount()
            self._sound_model.appendRow(item)

    def _ensure_model_entry(self, name: str, label: str | None = None) -> int:
        """Index of ``name`` in the shared model, appending it when absent.

        A mapping pointing at a file that is no longer in the library stays
        visible (marked) instead of silently showing something else.
        """
        row = self._model_rows.get(name)
        if row is not None:
            return row
        item = QStandardItem(label or name)
        item.setData(name, Qt.ItemDataRole.UserRole)
        row = self._sound_model.rowCount()
        self._model_rows[name] = row
        self._sound_model.appendRow(item)
        return row

    def _populate_combo(self, combo: QComboBox):
        # PERF: the default AdjustToContents size policy makes every combo
        # compute its sizeHint by measuring ALL 500+ library entries, and Qt
        # asks for that hint on insertion, on polish and on every relayout.
        # With ~58 combos that single default cost ~1 s of the dialog's build
        # (measured: 3.5 ms per setCellWidget here vs 0.1 ms on a bare table).
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(18)
        combo.setModel(self._sound_model)

    def _toggle_favorite(self, is_fav, combo):
        filename = combo.currentData()
        if not filename: return
        
        favs = list(self._data.get("sound_favorites", []))
        changed = False
        if is_fav and filename not in favs:
            favs.append(filename)
            changed = True
            combo.parentWidget().layout().itemAt(1).widget().setText("★")
        elif not is_fav and filename in favs:
            favs.remove(filename)
            changed = True
            combo.parentWidget().layout().itemAt(1).widget().setText("☆")
            
        if changed:
            self._data["sound_favorites"] = favs
            if hasattr(self.main_win, "state"):
                self.main_win.state.mark_dirty()
            # Update all combos with the new favorite state and sorting
            self._available = self._sound_manager.get_available_sounds()
            was_loading = self._loading
            self._loading = True
            # One model rebuild, not one per row.
            selections = {event: c.currentData()
                          for event, c in getattr(self, "_combos", {}).items()}
            self._rebuild_sound_model()
            for event, c in getattr(self, "_combos", {}).items():
                idx = c.findData(selections.get(event))
                if idx >= 0:
                    c.setCurrentIndex(idx)
            self._loading = was_loading
    def _events(self):
        events = self._data.get("sound_events")
        if not isinstance(events, dict):
            events = {}
            self._data["sound_events"] = events
        return events

    def _config(self, event):
        events = self._events()
        cfg = events.get(event)
        if not isinstance(cfg, dict):
            cfg = {}
            events[event] = cfg
        return cfg

    def _load_row_settings(self, event: str, row: int):
        cfg = self._config(event)
        item_on = self.table.item(row, _COL_ON)
        if item_on is not None:
            item_on.setCheckState(
                Qt.CheckState.Checked
                if cfg.get("enabled", "True") == "True"
                else Qt.CheckState.Unchecked)

        combo = self._combos.get(event)
        if combo is not None:
            wanted = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
            idx = combo.findData(wanted)
            if idx < 0 and wanted:
                playable = True
                try:
                    playable = self._sound_manager.ref_resolves(wanted)
                except Exception:
                    playable = False
                label = (wanted if playable
                         else f"{wanted} ({tr('missing', self.lang)})")
                idx = self._ensure_model_entry(wanted, label)
            combo.setCurrentIndex(max(0, idx))

        mode_combo = self._modes.get(event)
        if mode_combo is not None:
            wanted_mode = str(cfg.get("mode") or "inherit").lower()
            mode_index = mode_combo.findData(wanted_mode)
            mode_combo.setCurrentIndex(max(0, mode_index))

        gain_db = get_event_gain_db(event, self._data)
        slider = self._gains.get(event)
        if slider is not None:
            slider.setValue(int(round(gain_db)))
        self._refresh_gain_row(event, gain_db)

    def _load_settings(self):
        self._loading = True
        try:
            for event, row in list(self._rows.items()):
                self._load_row_settings(event, row)
        finally:
            self._loading = False

    def _touch(self):
        if hasattr(self.main_win, "mark_dirty"):
            self.main_win.mark_dirty()

    def _on_item_changed(self, item):
        """The On column is a checkable item now, not a QCheckBox widget."""
        if self._loading or item.column() != _COL_ON:
            return
        event = item.data(Qt.ItemDataRole.UserRole)
        if not event:
            return
        self._set_enabled(
            event, item.checkState() == Qt.CheckState.Checked)

    def _on_cell_clicked(self, row, column):
        if column != _COL_PLAY:
            return
        for event, mapped in self._rows.items():
            if mapped == row:
                self._preview(event)
                return

    def _set_enabled(self, event, checked):
        if self._loading:
            return
        self._config(event)["enabled"] = "True" if checked else "False"
        self._touch()

    def _set_file(self, event, combo):
        if self._loading:
            return
        name = combo.currentData()
        if not name:
            return
        self._config(event)["file"] = name
        self._touch()
        # T-1242 spec 5: warm the NEW sound so this preview (and the real
        # event) does not start on a cold, still-decoding source.
        warm = getattr(self._sound_manager, "preload_hot_set", None)
        if callable(warm):
            path = self._event_source_path(event)
            if path:
                try:
                    warm([path])
                except Exception:
                    pass
        self._preview(event)          # picking a sound plays it

    def _set_mode(self, event, combo):
        if self._loading:
            return
        self._config(event)["mode"] = str(combo.currentData() or "inherit")
        self._touch()
        # The runtime reads sound_events on every play, so the new mode is
        # live immediately; nothing here rebuilds the dialog.
        self._sound_manager.invalidate_cache()

    # -- relative gain (T-1242 spec 10-17) ---------------------------------

    def _refresh_global_label(self):
        """Show the ACTUAL master volume; re-render when the user changes it."""
        label = getattr(self, "_global_label", None)
        if label is None:
            return
        master = global_volume(self._data)
        if master == self._last_master:
            return
        self._last_master = master
        label.setText(tr("Picking a sound plays it.", self.lang) + "  "
                      + tr("Global volume: {pct}% - 0 dB = same as global",
                           self.lang).replace(
                               "{pct}", str(int(round(master * 100)))))
        for event in list(getattr(self, "_gains", {})):
            self._refresh_gain_row(event)

    def _refresh_gain_row(self, event, gain_db=None):
        """Update one row's numeric label and its truthful tooltip."""
        if gain_db is None:
            gain_db = get_event_gain_db(event, self._data)
        label = self._gain_labels.get(event)
        if label is not None:
            label.setText(format_gain_db(gain_db))
        master = global_volume(self._data)
        effective = effective_event_volume(event, self._data)
        lines = [
            tr("Global: {pct}%", self.lang).replace(
                "{pct}", str(int(round(master * 100)))),
            tr("Gain: {gain}", self.lang).replace(
                "{gain}", format_gain_db(gain_db)),
            tr("Effective amplitude: ~{pct}%", self.lang).replace(
                "{pct}", f"{effective * 100:.1f}"),
        ]
        detail = self._auto_detail.get(event)
        if detail:
            lines.append(detail)
        tooltip = "\n".join(lines)
        for widget in (self._gains.get(event), label):
            if widget is not None:
                widget.setToolTip(tooltip)

    def _set_gain(self, event, value):
        if self._loading:
            return
        gain = max(GAIN_DB_MIN, min(GAIN_DB_MAX, float(value)))
        self._config(event)["gain_db"] = f"{gain:.1f}"
        # The legacy absolute field would otherwise keep overriding the new
        # relative one both on an older build and in get_event_gain_db's
        # backward-compatible fallback.
        self._config(event)["volume"] = ""
        self._refresh_gain_row(event, gain)
        self._touch()
        self._sound_manager.invalidate_cache()

    def _reset_gain(self, event):
        """Double-click / Reset: back to 0 dB = exactly the global volume."""
        slider = self._gains.get(event)
        self._auto_detail.pop(event, None)
        if slider is None or slider.value() == 0:
            self._set_gain(event, 0.0)
        else:
            slider.setValue(0)          # valueChanged writes 0 dB

    def _event_source_path(self, event):
        """The absolute WAV this row currently points at (or '')."""
        import os as _os

        cfg = self._config(event)
        name = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
        if not name:
            return ""
        resolver = getattr(self._sound_manager, "resolve_ref_path", None)
        if callable(resolver):
            try:
                resolved = resolver(name)
                if resolved and _os.path.isfile(resolved):
                    return resolved
            except Exception:
                pass
        sounds_dir = getattr(self._sound_manager, "sounds_dir", "")
        candidate = _os.path.join(sounds_dir, name) if sounds_dir else name
        return candidate if _os.path.isfile(candidate) else ""

    def _auto_level(self, event):
        """Deterministic attenuation-only Auto Level for one event.

        It never rewrites the WAV: it stores a VISIBLE negative Gain the
        user can inspect and change.
        """
        path = self._event_source_path(event)
        payload = audio_level.analyze(path) if path else None
        if payload is None:
            self._auto_detail.pop(event, None)
            self._refresh_gain_row(event)
            self._set_status(tr("Auto unavailable for this file", self.lang))
            return None
        gain = float(payload["recommended_gain_db"])
        master = global_volume(self._data)
        self._auto_detail[event] = "\n".join([
            tr("Measured active RMS: {v} dBFS", self.lang).replace(
                "{v}", f"{payload['active_rms_dbfs']:.1f}"),
            tr("Peak: {v} dBFS", self.lang).replace(
                "{v}", f"{payload['peak_dbfs']:.1f}"),
            tr("Auto gain: {v}", self.lang).replace(
                "{v}", format_gain_db(gain)),
            tr("Global master: {pct}%", self.lang).replace(
                "{pct}", str(int(round(master * 100)))),
        ])
        slider = self._gains.get(event)
        if slider is not None:
            slider.blockSignals(True)
            slider.setValue(int(round(gain)))
            slider.blockSignals(False)
        if not self._loading:
            self._config(event)["gain_db"] = f"{gain:.1f}"
            self._config(event)["volume"] = ""
            self._touch()
            self._sound_manager.invalidate_cache()
        self._refresh_gain_row(event, gain)
        self._set_status(tr("Auto gain: {v}", self.lang).replace(
            "{v}", format_gain_db(gain)))
        return gain

    def _auto_level_all(self):
        """Auto-level every ENABLED event; returns how many rows changed."""
        self._ensure_all_events_built()
        changed = 0
        for event in list(self._rows):
            cfg = self._config(event)
            if str(cfg.get("enabled", "True")).lower() != "true":
                continue
            before = get_event_gain_db(event, self._data)
            self._auto_level(event)
            if get_event_gain_db(event, self._data) != before:
                changed += 1
        return changed

    def _on_auto_level_all(self):
        changed = self._auto_level_all()
        self._set_status(tr("Auto level: {n} changed", self.lang).replace(
            "{n}", str(changed)))

    def _set_status(self, text):
        """Compact status line -- a failed preview never needs a modal."""
        label = getattr(self, "_status_label", None)
        if label is not None:
            label.setText(text)

    def _preview(self, event):
        """Play what this row is set to, whatever the global toggles say.

        Straight through the manager's file player rather than `play(event)`:
        the preview must work while UI sounds are switched off, and it must
        not depend on the row's own enabled checkbox either.
        """
        cfg = self._config(event)
        name = cfg.get("file") or _DEFAULT_SOUND_MAP.get(event, "")
        if not name:
            return
        # T-1242 spec 17: NO special preview loudness path -- exactly the
        # global master and this row's gain, like the real event.
        level = effective_event_volume(event, self._data)
        result = self._sound_manager.play_file(name, level)
        if result is False:
            self._set_status(tr("Could not play {name}", self.lang).replace(
                "{name}", str(name)))

    def _reset(self):
        if QMessageBox.question(
                self, tr("Reset to defaults", self.lang),
                tr("Put every sound back to the shipped default?", self.lang),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._ensure_all_events_built()
        self._data["sound_events"] = {
            event: {"file": default, "enabled": "True", "volume": "",
                    "gain_db": "0.0"}
            for event, default in _DEFAULT_SOUND_MAP.items()
        }
        self._load_settings()
        self._touch()

    def _apply_filter(self, text):
        self._ensure_all_events_built()
        needle = (text or "").strip().lower()
        for event, row in self._rows.items():
            label = self.table.item(row, _COL_EVENT).text().lower()
            self.table.setRowHidden(
                row, bool(needle) and needle not in label and needle not in event)

    # ---- one canonical lifecycle (T-1242 spec A2) ----------------------

    @classmethod
    def open_canonical(cls, main_win, data, sound_manager):
        """Open THE SoundSettingsDialog: reuse, raise, or rebuild.

        The dialog is window-modal, so there can be at most one live instance;
        the class reference is refreshed on every construction and cleared in
        ``done()``.  A previous dialog that was destroyed without going
        through ``done()`` (deletion from the outside) leaves the stale
        reference behind, so the sip.isdeleted probe is the real liveness
        check.  Repeated "Open Audio Hub..." clicks therefore produce ONE
        visible canonical dialog -- never zero, never a stack of them.
        """
        from PyQt6 import sip

        live = cls._LAST_INSTANCE
        if live is not None:
            try:
                if not sip.isdeleted(live):
                    live.show()
                    live.raise_()
                    live.activateWindow()
                    return live
            except RuntimeError:
                pass
            cls._LAST_INSTANCE = None
        dialog = cls(main_win, data, sound_manager)
        dialog.show()
        return dialog
