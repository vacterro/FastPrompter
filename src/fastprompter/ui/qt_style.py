"""Deterministic cross-Windows control rendering (T-1461).

Measured defect, on a real Windows desktop: Qt resolves the native
``windowsvista`` style, which paints its own sub-controls and IGNORES the
theme stylesheet for them. A themed dark dialog therefore carried a white
radio indicator and a ~1000px near-white block inside every silo table.
The offscreen test platform resolves to ``fusion`` already, which is why the
whole defect was invisible to the headless suite.

Fix: pin ``Fusion`` before the ``QApplication`` exists, so the stylesheet is
the single source of truth for every control surface on every Windows
build. Both calls below are read once, at construction, and ignored
afterwards -- they MUST stay above ``QApplication(sys.argv)``.
"""

from __future__ import annotations

#: The style every Windows build must resolve to, whatever the OS default.
DETERMINISTIC_STYLE = "Fusion"


def configure_deterministic_style() -> str:
    """Pin the Qt style and DPI rounding policy. Call BEFORE QApplication.

    Returns the style name that was requested. Never raises: a style that
    cannot be applied must not stop the app from starting.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication, QStyleFactory

    # Qt6 removed AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps (they are
    # always on now); the rounding policy is the supported replacement and
    # must also be set before the application object exists.
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    if QStyleFactory.create(DETERMINISTIC_STYLE) is None:
        return ""
    QApplication.setStyle(DETERMINISTIC_STYLE)
    return DETERMINISTIC_STYLE
