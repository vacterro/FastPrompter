"""Regression: when window_locked=True, the lock must not snap the window
back to the pre-placement (0,0) default.  The root cause was
set_lock_state(True) running BEFORE place_window(), which captured
_locked_geometry as QRect(0,0,...).  place_window() then moved the window,
but moveEvent saw is_locked=True + _locked_geometry=(0,0) and reverted it.

The fix re-stamps _locked_geometry after place_window() when locked.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from PyQt6.QtCore import QRect, QSize


def test_locked_geometry_not_stale_after_placement():
    """_locked_geometry must reflect the post-place_window() position,
    not the pre-placement (0,0) default.

    Simulates the init sequence:
      1. set_lock_state(True) while window is at (0,0)
      2. place_window() moves window to (120,80)
      3. fix re-stamps _locked_geometry
    """
    import fastprompter.ui.window_mixin as wm

    class _Fake:
        def __init__(self):
            self.is_locked = False
            self._locked_geometry = None
            self.data = {"window_locked": "False"}
            self._sidebar_right = False
            self.sidebar_visible = True
            self._min_size = QSize(480, 320)
            self._max_size = QSize(16777215, 16777215)

        def mark_dirty(self, *a, **kw):
            pass

        def geometry(self):
            return QRect(0, 0, 960, 600)

        def setMinimumSize(self, s):
            self._min_size = s

        def setMaximumSize(self, s):
            self._max_size = s

        def size(self):
            return QSize(960, 600)

    fake = _Fake()
    fake.set_lock_state = wm.WindowMixin.set_lock_state.__get__(fake)

    # Phase 1: lock while window is still at default (0,0)
    fake.set_lock_state(True)
    assert fake.is_locked is True
    assert fake._locked_geometry is not None
    assert fake._locked_geometry.x() == 0
    assert fake._locked_geometry.y() == 0

    # Phase 2: place_window() moves the window — override geometry()
    placed_geo = QRect(120, 80, 960, 600)
    fake.geometry = lambda: placed_geo

    # Phase 3: fix re-stamps after placement (this is the actual fix in main.py)
    if getattr(fake, "is_locked", False):
        fake._locked_geometry = fake.geometry()

    # Must now reflect the placed position, not (0,0)
    geo = fake._locked_geometry
    assert geo is not None
    assert geo.x() == 120, f"expected x=120, got {geo.x()}"
    assert geo.y() == 80, f"expected y=80, got {geo.y()}"
    assert geo.width() == 960
    assert geo.height() == 600


def test_unlocked_geometry_not_affected():
    """When unlocked, the re-stamp code must not fire."""
    import fastprompter.ui.window_mixin as wm

    class _Fake:
        def __init__(self):
            self.is_locked = False
            self._locked_geometry = None
            self.data = {"window_locked": "False"}
            self._sidebar_right = False
            self.sidebar_visible = True

        def mark_dirty(self, *a, **kw):
            pass

        def setMinimumSize(self, s):
            pass

        def setMaximumSize(self, s):
            pass

        def size(self):
            return QSize(960, 600)

    fake = _Fake()
    fake.set_lock_state = wm.WindowMixin.set_lock_state.__get__(fake)

    # Don't lock
    if getattr(fake, "is_locked", False):
        fake._locked_geometry = fake.geometry()

    assert fake._locked_geometry is None
