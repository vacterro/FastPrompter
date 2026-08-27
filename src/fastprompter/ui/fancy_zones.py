"""Ctrl+Q zone picker — a small map that pops up under the cursor.

Three pages, Tab switches between them and the last one is remembered:

  Quarters  the classic four-corner snap
  Columns   Left 640 / Mid 800 / Right 640, as fractions so the proportions
            hold on any panel (those pixel figures are for a 1920 screen)
  Presets   user-saved window positions (S to save, Delete to remove)

Zones are stored as FRACTIONS of the screen's available area (0..1), not
pixels, so a layout behaves the same on a 1080p laptop panel and a 4K
monitor, and automatically avoids the taskbar.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

BUILTIN_LAYOUTS: list[tuple[str, list[tuple[float, float, float, float]]]] = [
    ("Quarters", [
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ]),
    ("Columns", [
        (0.0, 0.0, 1 / 3, 1.0),
        (7 / 24, 0.0, 5 / 12, 1.0),
        (2 / 3, 0.0, 1 / 3, 1.0),
    ]),
]

_BASE_W, _BASE_H = 250, 168
_HEADER_H = 20
_PAD = 6
_MAX_PRESETS = 10


def presets_enabled(data) -> bool:
    """The Presets page is opt-in, like every other added surface here."""
    if not data:
        return False
    return str(data.get("window_presets_enabled", "True")) == "True"


def layouts_for(data=None) -> list[tuple[str, list]]:
    """Builtin pages + user presets (if any)."""
    layouts = list(BUILTIN_LAYOUTS)
    if presets_enabled(data):
        presets = _load_presets(data)
        if presets:
            layouts.append(("Presets", [_rect_of(p) for p in presets]))
    return layouts


def _rect_of(preset) -> tuple[float, float, float, float]:
    return (preset["x"], preset["y"], preset["w"], preset["h"])


def _heal_fraction(value, default=0.0):
    """A window-rectangle coordinate as a FRACTION of the available screen.

    Must be finite and within [0, 1]; width/height also take a positive floor
    so a zero/negative/NaN/Inf value (a corrupt preset, a window spanning
    every monitor, or legacy junk) can never be applied as a real geometry that
    places the window off-screen or collapses it to nothing (T-1025).
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(0.0, min(1.0, f))


def _heal_size_fraction(value):
    """A width/height fraction: finite, in (0, 1], with a small positive floor
    so the window never collapses to zero size."""
    f = _heal_fraction(value, default=0.1)
    return f if f > 0.02 else 0.1


# UI state a preset can carry beyond its rectangle. None means "the preset
# does not say", which is what every preset saved before this existed holds —
# and it must leave the current window alone rather than force a default.
# Booleans toggle; the valued keys (theme/font/scale/toolbar) are applied
# only when present.
_BOOL_STATE_KEYS = ("zen", "zen_solo", "sidebar")
_STR_STATE_KEYS = ("theme", "font_size", "ui_scale", "toolbar_position")
_UI_STATE_KEYS = _BOOL_STATE_KEYS + _STR_STATE_KEYS


def _ui_state_of(item):
    """The tri-state UI flags of a stored preset: True / False / None for the
    booleans, the raw string / None for the valued keys.

    Booleans are HEALED, not coerced: a persisted string "False" must stay
    False, never become True via ``bool("False")``. Only a genuine True, or an
    explicit "true"/"yes" string, is True. A missing key stays None ("the
    preset does not say").
    """
    out = {}
    if isinstance(item, dict):
        for key in _BOOL_STATE_KEYS:
            val = item.get(key)
            if val is None:
                out[key] = None
            elif isinstance(val, bool):
                out[key] = val
            elif isinstance(val, str):
                out[key] = val.strip().lower() in ("true", "1", "yes")
            else:
                out[key] = bool(val)
        for key in _STR_STATE_KEYS:
            val = item.get(key)
            out[key] = None if val is None else str(val)
    else:
        for key in _UI_STATE_KEYS:
            out[key] = None
    return out


def _captures_ui_state(data) -> bool:
    """The geometry-only toggle: False means a saved preset carries nothing
    but its rectangle (plus the window state), so applying it cannot touch
    any app state."""
    if not data:
        return True
    return str(data.get("window_presets_capture_state", "True")) == "True"


def _current_ui_state(main_win) -> dict:
    """Snapshot the LIVE app state a preset should carry. Empty dict when the
    geometry-only toggle is off — then a preset must change nothing but the
    window's box."""
    if not _captures_ui_state(getattr(main_win, "data", None)):
        return {}
    data = getattr(main_win, "data", None) or {}
    return {
        "zen": bool(getattr(main_win, "focus_mode", False)),
        "zen_solo": bool(getattr(main_win, "zen_solo", False)),
        "sidebar": bool(getattr(main_win, "sidebar_visible", True)),
        "theme": str(data.get("theme", "Default")),
        "font_size": str(data.get("font_size", "11")),
        "ui_scale": str(data.get("ui_scale", "0.5")),
        "toolbar_position": str(data.get("toolbar_position", "top")),
    }


def _load_presets(data):
    """Normalise to dicts: {name, x, y, w, h, state, zen, sidebar}.

    Accepts the original bare [x, y, w, h] shape too — the first build wrote
    that, and a saved preset must not vanish because the format grew.
    """
    if not data:
        return []
    raw = data.get("window_presets", [])
    if not isinstance(raw, list):
        return []
    out = []
    for i, item in enumerate(raw):
        try:
            if isinstance(item, dict):
                x = _heal_fraction(item["x"])
                y = _heal_fraction(item["y"])
                w = _heal_size_fraction(item["w"])
                h = _heal_size_fraction(item["h"])
                p = {
                    "name": str(item.get("name") or f"Preset {i + 1}"),
                    "x": x, "y": y, "w": w, "h": h,
                    "state": "maximized"
                    if item.get("state") == "maximized" else "normal",
                    **_ui_state_of(item),
                }
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                x = _heal_fraction(item[0])
                y = _heal_fraction(item[1])
                w = _heal_size_fraction(item[2])
                h = _heal_size_fraction(item[3])
                p = {"name": f"Preset {i + 1}", "x": x, "y": y,
                     "w": w, "h": h, "state": "normal", **_ui_state_of(None)}
            else:
                continue
        except (TypeError, ValueError, KeyError):
            continue
        # a non-finite or collapsed geometry cannot be applied safely; drop the
        # whole preset rather than let it place the window off-screen
        if not (math.isfinite(p["x"]) and math.isfinite(p["y"])
                and p["w"] > 0 and p["h"] > 0):
            continue
        out.append(p)
    return out


def _save_presets(data, presets):
    """Accepts dicts or the legacy bare [x, y, w, h] — symmetric with
    _load_presets, which has always taken both. Without this, a caller still
    handing over the old shape raised TypeError on save."""
    out = []
    for i, p in enumerate(presets):
        if isinstance(p, dict):
            entry = {
                "name": str(p.get("name") or f"Preset {i + 1}"),
                "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
                "state": p.get("state", "normal"),
            }
            # Written only when the preset actually knows: an absent key is
            # "leave the window as it is", and writing False for it would
            # silently turn every old preset into "open with zen off".
            for key, val in _ui_state_of(p).items():
                if val is not None:
                    entry[key] = val
            out.append(entry)
        elif isinstance(p, (list, tuple)) and len(p) >= 4:
            x, y, w, h = p[:4]
            out.append({"name": f"Preset {i + 1}", "x": x, "y": y,
                        "w": w, "h": h, "state": "normal"})
    data["window_presets"] = out


def apply_ui_state(main_win, preset) -> None:
    """Put the window into the zen/sidebar state a preset recorded.

    Toggles rather than sets, because that is the only API the window has —
    and each is compared against the CURRENT state first, so applying a
    preset twice is not the same as pressing Ctrl+D twice. A key the preset
    does not carry is left alone: presets saved before this existed must not
    start forcing the chrome back on.

    Zen goes first: it collapses the sidebar itself, so the sidebar flag has
    to be applied after it, or leaving zen would immediately undo it.
    """
    if main_win is None or not isinstance(preset, dict):
        return
    state = _ui_state_of(preset)

    want_zen = state["zen"]
    if want_zen is not None and bool(getattr(main_win, "focus_mode", False)) != want_zen:
        toggle = getattr(main_win, "toggle_focus_mode", None)
        if callable(toggle):
            toggle()

    # The zen SOLO sub-state is a second stage of the same mode: record it
    # too, so "I was in zen solo" comes back as zen solo, not plain zen.
    want_solo = state["zen_solo"]
    if want_solo is not None and bool(getattr(main_win, "focus_mode", False)):
        is_solo = bool(getattr(main_win, "zen_solo", False))
        if want_solo and not is_solo:
            enter = getattr(main_win, "_enter_zen_solo", None)
            if callable(enter):
                enter()
        elif not want_solo and is_solo:
            leave = getattr(main_win, "exit_zen_solo", None)
            if callable(leave):
                leave()

    want_sidebar = state["sidebar"]
    # In zen there is deliberately no sidebar; honouring the flag there would
    # put one back on screen inside the mode that exists to remove it.
    if (want_sidebar is not None
            and not bool(getattr(main_win, "focus_mode", False))):
        if bool(getattr(main_win, "sidebar_visible", True)) != want_sidebar:
            toggle = getattr(main_win, "toggle_sidebar_visibility", None)
            if callable(toggle):
                toggle()

    # The valued keys apply only when the preset actually carries them — a
    # preset saved before these existed must not force any of them.
    want_theme = state["theme"]
    if want_theme:
        change = getattr(main_win, "change_theme", None)
        if callable(change):
            change(want_theme)

    want_font = state["font_size"]
    if want_font:
        try:
            size = int(float(want_font))
        except (TypeError, ValueError):
            size = None
        if size is not None:
            change = getattr(main_win, "change_font_size", None)
            if callable(change):
                change(size)

    want_scale = state["ui_scale"]
    if want_scale:
        try:
            scale = float(want_scale)
        except (TypeError, ValueError):
            scale = None
        if scale is not None:
            setter = getattr(main_win, "_set_unified_scale", None)
            if callable(setter):
                setter(scale)

    want_toolbar = state["toolbar_position"]
    if want_toolbar in ("top", "bottom"):
        apply = getattr(main_win, "apply_toolbar_position", None)
        if callable(apply):
            apply(bottom=(want_toolbar == "bottom"))


class FancyZoneOverlay(QWidget):
    """Compact zone picker, drawn as a map of the screen."""

    def __init__(self, main_win=None):
        super().__init__()
        self.main_win = main_win
        self._zones: list[QRect] = []
        self._cells: list[QRect] = []
        self._layouts: list[tuple[str, list]] = list(BUILTIN_LAYOUTS)
        self._layout_idx = 0
        self._hot = -1
        self._avail = QRect()
        self._focus_locked = False

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def _accent(self) -> QColor:
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache and cache.get("raw_colors"):
                return QColor(cache["raw_colors"].get("accent", "#6aa9ff"))
        except Exception:
            pass
        return QColor("#6aa9ff")

    def _colors(self):
        raw = {}
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache:
                raw = cache.get("raw_colors") or {}
        except Exception:
            raw = {}
        return (QColor(raw.get("bg_main", "#1b1b1b")),
                QColor(raw.get("text_main", "#c0c0c0")),
                self._accent())

    def _rebuild_zones(self):
        a = self._avail
        self._zones = [
            QRect(a.x() + round(fx * a.width()),
                  a.y() + round(fy * a.height()),
                  max(1, round(fw * a.width())),
                  max(1, round(fh * a.height())))
            for fx, fy, fw, fh in self._layouts[self._layout_idx][1]
        ]

        box = QRect(_PAD, _HEADER_H, self.width() - 2 * _PAD,
                    self.height() - _HEADER_H - _PAD)
        if a.isValid() and a.height():
            ratio = a.width() / a.height()
            w = min(box.width(), int(box.height() * ratio))
            h = min(box.height(), int(w / ratio) if ratio else box.height())
            box = QRect(box.x() + (box.width() - w) // 2,
                        box.y() + (box.height() - h) // 2, w, h)
        self._map = box
        self._cells = [
            QRect(box.x() + round(fx * box.width()),
                  box.y() + round(fy * box.height()),
                  max(2, round(fw * box.width())),
                  max(2, round(fh * box.height())))
            for fx, fy, fw, fh in self._layouts[self._layout_idx][1]
        ]

    def _prepare(self, main_win):
        """Load the pages and the screen the picker would act on.

        Split out of open_for so fast mode can place a window without ever
        building or showing the picker.
        """
        self.main_win = main_win
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return None

        data = getattr(main_win, "data", {}) or {}
        self._layouts = layouts_for(data)
        saved = data.get("fancyzones_layout", "")
        self._layout_idx = next(
            (i for i, (name, _) in enumerate(self._layouts) if name == saved), 0)
        self._avail = screen.availableGeometry()
        return screen

    def apply_fast(self, main_win, step: int = 1) -> bool:
        """Fast mode: no picker, just move to the next zone of the saved page.

        The picker is the right surface when you are choosing; when you
        already know the two or three spots you work in, it is a modal step
        between you and the window move. This advances a remembered index
        through the current page's zones and applies it directly.
        """
        if self._prepare(main_win) is None or not self._layouts:
            return False
        zones = self._layouts[self._layout_idx][1]
        if not zones:
            return False
        data = getattr(main_win, "data", {}) or {}
        try:
            idx = int(data.get("fancyzones_fast_idx", -1))
        except (TypeError, ValueError):
            idx = -1
        idx = (idx + step) % len(zones)
        data["fancyzones_fast_idx"] = str(idx)
        self._rebuild_zones()
        return self.apply_zone(idx)

    def open_for(self, main_win):
        screen = self._prepare(main_win)
        if screen is None:
            return False
        data = getattr(main_win, "data", {}) or {}

        try:
            scale = float(data.get("ui_scale", "0.5"))
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(0.75, min(2.0, scale))
        w, h = int(_BASE_W * scale), int(_BASE_H * scale)

        pos = QCursor.pos()
        sg = screen.geometry()
        x = min(max(sg.left(), pos.x() - w // 2), sg.right() - w + 1)
        y = min(max(sg.top(), pos.y() - h // 2), sg.bottom() - h + 1)
        self.setGeometry(QRect(x, y, w, h))

        self._rebuild_zones()
        self._hot = -1
        self._lock_focus(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()
        return True

    def _lock_focus(self, on):
        mw = self.main_win
        if mw is None:
            return
        if on and not self._focus_locked:
            if hasattr(mw, "_increment_focus_lock"):
                mw._increment_focus_lock()
                self._focus_locked = True
        elif not on and self._focus_locked:
            self._focus_locked = False
            if hasattr(mw, "_decrement_focus_lock"):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(300, mw._decrement_focus_lock)

    def closeEvent(self, event):
        self._lock_focus(False)
        super().closeEvent(event)

    def _zone_at(self, pos) -> int:
        for i, cell in enumerate(self._cells):
            if cell.contains(pos):
                return i
        return -1

    def apply_zone(self, idx: int) -> bool:
        if not (0 <= idx < len(self._zones)) or self.main_win is None:
            return False
        z = self._zones[idx]
        mw = self.main_win

        if getattr(mw, "is_locked", False):
            self.close()
            return False

        try:
            mw.data["fancyzones_layout"] = self._layouts[self._layout_idx][0]
            if hasattr(mw, "mark_dirty"):
                mw.mark_dirty()
        except Exception:
            # T-1080: a dropped layout persist must not vanish silently — the
            # user's chosen fancy-zones layout would not survive restart with
            # no log and no feedback. Log it; geometry apply below still runs.
            from fastprompter.core.logging import logger
            logger.debug("fancy-zones layout persist failed", exc_info=True)

        if mw.isMinimized():
            mw.showNormal()

        # A preset can carry a STATE. Maximized has to be applied as a state,
        # not as a rectangle — setGeometry on a maximized window is ignored,
        # and a "maximized" preset restored as a mere rect is not maximized.
        if self._is_presets_page():
            presets = _load_presets(getattr(mw, "data", None))
            if 0 <= idx < len(presets) and presets[idx].get("state") == "maximized":
                mw.showMaximized()
                apply_ui_state(mw, presets[idx])
                self.close()
                if not mw.isVisible():
                    mw.show()
                mw.raise_()
                mw.activateWindow()
                return True
            if 0 <= idx < len(presets):
                apply_ui_state(mw, presets[idx])
            if mw.isMaximized():
                mw.showNormal()      # leave maximized before placing a rect

        w = max(z.width(), mw.minimumWidth())
        h = max(z.height(), mw.minimumHeight())
        a = self._avail
        x = min(z.x(), a.right() - w + 1) if a.isValid() else z.x()
        y = min(z.y(), a.bottom() - h + 1) if a.isValid() else z.y()
        if a.isValid():
            x, y = max(a.left(), x), max(a.top(), y)

        mw.setGeometry(QRect(x, y, w, h))
        self.close()
        if not mw.isVisible():
            mw.show()
        mw.raise_()
        mw.activateWindow()
        return True

    def cycle_layout(self, step: int = 1):
        if not self._layouts:
            return
        self._layout_idx = (self._layout_idx + step) % len(self._layouts)
        self._rebuild_zones()
        self._hot = -1
        self.update()

    def _is_presets_page(self):
        return (0 <= self._layout_idx < len(self._layouts)
                and self._layouts[self._layout_idx][0] == "Presets")

    def _save_current_as_preset(self):
        mw = self.main_win
        if mw is None:
            return
        a = self._avail
        if not a.isValid() or a.width() <= 0 or a.height() <= 0:
            return
        data = getattr(mw, "data", None)
        if data is None:
            return
        g = mw.geometry()
        # Fractions must stay finite and within [0, 1] (a window larger than the
        # available area, or an odd screen config, must not store NaN/Inf or an
        # out-of-range value that later places the window off-screen).
        fx = _heal_fraction((g.x() - a.x()) / a.width())
        fy = _heal_fraction((g.y() - a.y()) / a.height())
        fw = _heal_size_fraction((g.width() / a.width()))
        fh = _heal_size_fraction((g.height() / a.height()))
        presets = _load_presets(data)
        if len(presets) >= _MAX_PRESETS:
            return
        presets.append({
            "name": f"Preset {len(presets) + 1}",
            "x": fx, "y": fy, "w": fw, "h": fh,
            # the window STATE, not just its box: a maximized window has a
            # normal-geometry rect that says nothing about being maximized
            "state": "maximized" if mw.isMaximized() else "normal",
            # …and the APP state, the half a rectangle cannot hold: theme,
            # font, scale, toolbar position, zen (incl. its solo stage) and
            # the sidebar. The geometry-only toggle makes this {} so a preset
            # changes nothing but the window's box.
            **_current_ui_state(mw),
        })
        _save_presets(data, presets)
        if hasattr(mw, "mark_dirty"):
            mw.mark_dirty()
        self._layouts = layouts_for(data)
        self._layout_idx = next(
            (i for i, (n, _) in enumerate(self._layouts) if n == "Presets"),
            self._layout_idx)
        self._rebuild_zones()
        self._hot = -1
        self.update()

    def _delete_preset(self, idx):
        mw = self.main_win
        if mw is None:
            return
        data = getattr(mw, "data", None)
        if data is None:
            return
        presets = _load_presets(data)
        if not (0 <= idx < len(presets)):
            return
        presets.pop(idx)
        _save_presets(data, presets)
        if hasattr(mw, "mark_dirty"):
            mw.mark_dirty()
        self._layouts = layouts_for(data)
        if not presets:
            self._layout_idx = 0
        else:
            self._layout_idx = next(
                (i for i, (n, _) in enumerate(self._layouts) if n == "Presets"),
                0)
        self._rebuild_zones()
        self._hot = -1
        self.update()

    # ---- input --------------------------------------------------------
    def mouseMoveEvent(self, event):
        hot = self._zone_at(event.pos())
        if hot != self._hot:
            self._hot = hot
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._zone_at(event.pos())
            if idx >= 0:
                self.apply_zone(idx)
                return
        self.close()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
            return
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.apply_zone(key - Qt.Key.Key_1)
            return
        if key == Qt.Key.Key_0:
            self.apply_zone(9)
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.cycle_layout(1)
            return
        if key in (Qt.Key.Key_Backtab, Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.cycle_layout(-1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_zone(self._hot if self._hot >= 0 else 0)
            return
        if key == Qt.Key.Key_S:
            self._save_current_as_preset()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._is_presets_page() and self._hot >= 0:
                self._delete_preset(self._hot)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.close()

    # ---- paint --------------------------------------------------------
    def paintEvent(self, _event):
        if not self._cells:
            return
        bg, text, accent = self._colors()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            p.fillRect(self.rect(), bg)
            p.setPen(QPen(accent, 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF()))
            font.setBold(True)
            p.setFont(font)
            p.setPen(text)
            name = self._layouts[self._layout_idx][0]
            p.drawText(QRect(_PAD, 2, self.width() - 2 * _PAD, _HEADER_H - 2),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       name)
            hint = "S=save  Del=remove" if self._is_presets_page() else "Tab"
            p.drawText(QRect(_PAD, 2, self.width() - 2 * _PAD, _HEADER_H - 2),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       hint)

            names = []
            if self._is_presets_page():
                names = [p["name"] for p in
                         _load_presets(getattr(self.main_win, "data", None))]

            fill = QColor(accent)
            fill.setAlpha(40)
            hot_fill = QColor(accent)
            hot_fill.setAlpha(120)

            for i, cell in enumerate(self._cells):
                inner = cell.adjusted(1, 1, -1, -1)
                p.fillRect(inner, hot_fill if i == self._hot else fill)
                p.setPen(QPen(accent, 2 if i == self._hot else 1))
                p.drawRect(inner)

                p.setPen(text if i != self._hot else accent.lighter(150))
                label = str(i + 1) if i < 9 else "0"
                if names:
                    label = f"{label}  {names[i]}" if i < len(names) else label
                p.drawText(QRectF(inner), Qt.AlignmentFlag.AlignCenter, label)
        finally:
            p.end()
