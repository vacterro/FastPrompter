"""T-1300 smoke-harness lifetime sentinel (T-1264 reproducer anchor).

Runs LAST in tests_smoke collection order. It constructs a real FastPrompter
through the SAME module-scoped fixture contract every other smoke module uses,
drives the apply_theme / QApplication.setStyleSheet path, pumps the event loop,
and lets the fixture retire itself through its own test lifecycle.

This module is also the sentinel for the native-crash reproducer: with a
contaminated prefix of smoke modules, construction here dies with a native
abnormal exit (0xC0000409 / 0xC0000005) instead of a normal pytest exit.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_sentinel_constructs_and_applies_theme(win):
    win.show()
    _app.processEvents()
    win.apply_theme()
    _app.processEvents()
    assert win.isEnabled()
