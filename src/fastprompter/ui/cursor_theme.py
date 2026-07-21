"""Carry a cursor set inside the program.

The point is that the program keeps its OWN copy. Reading the live registry
scheme would just mirror whatever Windows is already drawing, so the toggle
would do nothing visible and there would be nothing to offer the "set it in
the system" button. Instead the current scheme is COPIED into the app's data
folder once, and from then on the program uses its own files no matter what
the system scheme becomes later.

Qt reads `.cur` natively. Animated `.ani` files it cannot read at all, so
those roles keep their stock shape in-app rather than silently vanishing -
but the files are still copied, because installing the set back into Windows
needs them.
"""

from __future__ import annotations

import json
import os
import shutil
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


# Windows stores a saved scheme as one comma-separated string in this exact
# role order. There is no key naming them, so the order IS the schema.
_SCHEME_ORDER = (
    "Arrow", "Help", "AppStarting", "Wait", "Crosshair", "IBeam", "NWPen",
    "No", "SizeNS", "SizeWE", "SizeNWSE", "SizeNESW", "SizeAll", "UpArrow",
    "Hand", "Pin", "Person",
)


def read_named_schemes():
    """{scheme name: {role: path}} for every scheme saved on this machine.

    The applied scheme is only half the story: switching Windows back to the
    default empties every value under Control Panel\\Cursors while the user's
    own scheme stays listed here, files and all. Reading only the applied one
    meant "copy my set" found nothing the moment the user was on stock
    cursors - which is exactly when they would want to grab their set.
    """
    if sys.platform != "win32":
        return {}
    try:
        import winreg
    except ImportError:
        return {}

    schemes = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\Cursors\Schemes") as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if not name or not isinstance(value, str):
                    continue
                roles = {}
                for role, item in zip(_SCHEME_ORDER, value.split(",")):
                    item = item.strip()
                    if not item:
                        continue
                    full = os.path.expandvars(item)
                    if os.path.isfile(full):
                        roles[role] = full
                if roles:
                    schemes[name] = roles
    except OSError:
        logger.debug("saved cursor schemes unreadable", exc_info=True)
    return schemes


def best_available_scheme():
    """The set to copy: the applied one, else the user's own saved one.

    Returns (name, {role: path}). Prefers whatever Windows is actually
    using; when that is the bare default it falls back to a saved scheme,
    newest-looking custom one first, so there is still something to take.
    """
    name, paths = read_scheme()
    if paths:
        return name or "applied", paths

    saved = read_named_schemes()
    if not saved:
        return "", {}
    for candidate in ("___CURRENT___", "__CURRENT__", "CURRENT"):
        if candidate in saved:
            return candidate, saved[candidate]
    # no obvious "mine": take the richest set rather than guessing by name
    pick = max(saved.items(), key=lambda kv: len(kv[1]))
    return pick[0], pick[1]


def bundle_dir():
    """Where the program keeps its own copy of the set."""
    from fastprompter.utils.paths import get_data_dir
    return os.path.join(get_data_dir(), "cursors")


def _manifest_path():
    return os.path.join(bundle_dir(), "scheme.json")


def load_bundle():
    """(name, {role: path}) of the copy the program owns, or ("", {})."""
    manifest = _manifest_path()
    if not os.path.isfile(manifest):
        return "", {}
    try:
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        logger.debug("cursor bundle manifest unreadable", exc_info=True)
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    folder = bundle_dir()
    paths = {}
    for role, filename in (data.get("files") or {}).items():
        full = os.path.join(folder, str(filename))
        if os.path.isfile(full):
            paths[role] = full
    return str(data.get("name") or ""), paths


def capture_current_scheme():
    """Copy the live Windows scheme into the program. Returns (name, paths).

    Copied rather than referenced so the set keeps working after Windows is
    switched to something else - which is the whole reason this exists.
    """
    name, source = best_available_scheme()
    if not source:
        return "", {}
    folder = bundle_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        logger.exception("could not create the cursor folder")
        return "", {}

    files, paths = {}, {}
    for role, src in source.items():
        target_name = f"{role}{os.path.splitext(src)[1].lower()}"
        target = os.path.join(folder, target_name)
        try:
            shutil.copyfile(src, target)
        except OSError:
            logger.debug("could not copy %s", src, exc_info=True)
            continue
        files[role] = target_name
        paths[role] = target

    if not files:
        return "", {}
    try:
        with open(_manifest_path(), "w", encoding="utf-8") as fh:
            json.dump({"name": name, "files": files}, fh, indent=1)
    except OSError:
        logger.exception("could not write the cursor manifest")
    return name, paths


def clear_bundle():
    """Forget the copy, so the program falls back to stock shapes."""
    folder = bundle_dir()
    if not os.path.isdir(folder):
        return False
    try:
        shutil.rmtree(folder)
        return True
    except OSError:
        logger.exception("could not remove the cursor folder")
        return False


def build_cursor_map(paths=None):
    """{Qt.CursorShape: QCursor} for every role Qt can actually load.

    Roles whose file is animated (or otherwise unreadable) are left out, so
    the caller falls back to the stock shape instead of showing nothing.
    """
    if paths is None:
        _name, paths = load_bundle()
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


def install_to_system(paths=None):
    """Point Windows at the set the program is carrying.

    Only ever called from an explicit button press. It writes the same
    registry values Windows itself uses and then asks the system to reload
    them, so nothing is left needing a logout.
    """
    if paths is None:
        _name, paths = load_bundle()
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
