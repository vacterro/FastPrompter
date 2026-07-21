"""Use the user's own Windows cursor set inside the program.

Windows applies a cursor scheme system-wide, but a Qt app asks for stock
*shapes* and gets whatever the platform draws for them - which on some
setups is not the scheme the user actually installed. This reads the
scheme straight out of the registry and hands back real QCursors.

Qt reads `.cur` natively. Animated `.ani` files it cannot read at all, so
those roles (the busy/working cursors) keep their stock shape rather than
silently vanishing.
"""

from __future__ import annotations

import os
import struct
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QPixmap

from fastprompter.core.logging import logger

DEVIANTART_URL = (
    "https://www.deviantart.com/potatoddas/art/"
    "Simple-Perfect-Cursors-946177131"
)

# Registry role -> the Qt shape it stands in for. Roles Qt has no shape for
# (Pin, Person, NWPen) are read but simply never asked for.
_ROLE_TO_SHAPE = {
    "Arrow": Qt.CursorShape.ArrowCursor,
    "IBeam": Qt.CursorShape.IBeamCursor,
    "Hand": Qt.CursorShape.PointingHandCursor,
    "Crosshair": Qt.CursorShape.CrossCursor,
    "Help": Qt.CursorShape.WhatsThisCursor,
    "No": Qt.CursorShape.ForbiddenCursor,
    "SizeAll": Qt.CursorShape.SizeAllCursor,
    "SizeNS": Qt.CursorShape.SizeVerCursor,
    "SizeWE": Qt.CursorShape.SizeHorCursor,
    "SizeNESW": Qt.CursorShape.SizeBDiagCursor,
    "SizeNWSE": Qt.CursorShape.SizeFDiagCursor,
    "UpArrow": Qt.CursorShape.UpArrowCursor,
    "Wait": Qt.CursorShape.WaitCursor,
    "AppStarting": Qt.CursorShape.BusyCursor,
}


def _cur_hotspot(path):
    """Hot spot from a .cur header, or None.

    A .cur is an ICO whose per-image `planes`/`bitcount` fields are reused
    to carry the hot spot. Without reading it every cursor would click from
    its top-left corner, which is wrong for everything but the arrow.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(6)
            if len(head) < 6:
                return None
            reserved, kind, count = struct.unpack("<HHH", head)
            if reserved != 0 or kind != 2 or count < 1:
                return None      # kind 2 is a cursor; 1 would be an icon
            entry = fh.read(16)
            if len(entry) < 16:
                return None
            x, y = struct.unpack("<HH", entry[4:8])
            return int(x), int(y)
    except OSError:
        logger.debug("could not read hot spot from %s", path, exc_info=True)
        return None


def read_scheme():
    """(scheme name, {role: file path}) from the current user's settings."""
    if sys.platform != "win32":
        return "", {}
    try:
        import winreg
    except ImportError:
        return "", {}

    paths = {}
    name = ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\Cursors") as key:
            try:
                name = str(winreg.QueryValueEx(key, "")[0] or "")
            except OSError:
                name = ""
            index = 0
            while True:
                try:
                    role, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if not role or not isinstance(value, str) or not value:
                    continue
                full = os.path.expandvars(value)
                if os.path.isfile(full):
                    paths[role] = full
    except OSError:
        logger.debug("cursor scheme unreadable", exc_info=True)
    return name, paths


def build_cursor_map(paths=None):
    """{Qt.CursorShape: QCursor} for every role Qt can actually load.

    Roles whose file is animated (or otherwise unreadable) are left out, so
    the caller falls back to the stock shape instead of showing nothing.
    """
    if paths is None:
        _name, paths = read_scheme()
    cursors = {}
    for role, shape in _ROLE_TO_SHAPE.items():
        path = paths.get(role)
        if not path:
            continue
        pixmap = QPixmap(path)
        if pixmap.isNull():
            continue            # .ani and friends - keep the stock shape
        spot = _cur_hotspot(path)
        if spot is None:
            cursors[shape] = QCursor(pixmap)
        else:
            x, y = spot
            x = min(max(0, x), max(0, pixmap.width() - 1))
            y = min(max(0, y), max(0, pixmap.height() - 1))
            cursors[shape] = QCursor(pixmap, x, y)
    return cursors


def install_to_system(paths):
    """Make this set the live Windows cursor scheme.

    Only ever called from an explicit button press. It writes the same
    registry values Windows itself uses and then asks the system to reload
    them, so nothing is left needing a logout.
    """
    if sys.platform != "win32" or not paths:
        return False
    try:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors",
                            0, winreg.KEY_SET_VALUE) as key:
            for role, path in paths.items():
                winreg.SetValueEx(key, role, 0, winreg.REG_SZ, path)
        # SPI_SETCURSORS = 0x0057: re-read the scheme now
        ctypes.windll.user32.SystemParametersInfoW(0x0057, 0, None, 3)
        return True
    except Exception:
        logger.exception("could not install the cursor scheme")
        return False
