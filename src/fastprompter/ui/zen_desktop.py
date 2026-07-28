"""Stage-2 Zen: minimise everything on the desktop except FastPrompter.

Deliberately conservative. This reaches outside the app and touches the
user's other windows, so the rule everywhere below is: if anything is
uncertain, do less. Only plainly visible, non-minimised, titled top-level
windows of OTHER processes are touched, and every handle that IS touched is
remembered so the third Ctrl+D (or simply clicking away) can put it back.

Windows only — on any other platform both calls are no-ops and Zen keeps
working exactly as it did before.
"""

from __future__ import annotations

import sys

from fastprompter.core.logging import logger

_IS_WINDOWS = sys.platform == "win32"

SW_MINIMIZE = 6
SW_RESTORE = 9
GW_OWNER = 4
# a window with either of these is furniture (tool palettes, tray hosts),
# not something the user thinks of as an open window
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20


def _user32():
    if not _IS_WINDOWS:
        return None
    # An offscreen Qt session has no desktop to sweep, but ctypes would
    # happily minimise the REAL windows of whoever is running the suite.
    # Found the hard way: a fuzz test that toggles Zen swept the developer's
    # desktop mid-run.
    import os
    if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        return None
    import ctypes
    return ctypes.windll.user32


def minimise_others(own_hwnds):
    """Minimise every other visible top-level window. Returns the handles.

    `own_hwnds` are this app's own windows, which are never touched.
    """
    u = _user32()
    if u is None:
        return []
    import ctypes
    from ctypes import wintypes

    own = {int(h) for h in own_hwnds if h}
    touched = []

    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _visit(hwnd, _lparam):
        try:
            h = int(hwnd)
            if h in own:
                return True
            if not u.IsWindowVisible(h) or u.IsIconic(h):
                return True
            if u.GetWindow(h, GW_OWNER):
                return True          # owned popup: its owner is the window
            ex = u.GetWindowLongW(h, GWL_EXSTYLE)
            if ex & WS_EX_TOOLWINDOW:
                return True
            if u.GetWindowTextLengthW(h) <= 0:
                return True          # untitled: shell furniture, not a window
            u.ShowWindow(h, SW_MINIMIZE)
            touched.append(h)
        except Exception:
            logger.debug("zen: skipped a window", exc_info=True)
        return True

    try:
        u.EnumWindows(CB(_visit), 0)
    except Exception:
        logger.exception("zen: EnumWindows failed")
    return touched


def restore(hwnds):
    """Put back exactly what minimise_others() took down."""
    u = _user32()
    if u is None or not hwnds:
        return
    # reverse order so the window that was on top ends up on top again
    for h in reversed(list(hwnds)):
        try:
            if u.IsWindow(h) and u.IsIconic(h):
                u.ShowWindow(h, SW_RESTORE)
        except Exception:
            logger.debug("zen: could not restore a window", exc_info=True)
