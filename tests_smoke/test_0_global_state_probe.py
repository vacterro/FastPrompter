"""TEMPORARY diagnostic (T-1300 triage): global QApplication state at the
tests/ -> tests_smoke/ boundary after the residue purge."""

from __future__ import annotations


def test_probe_global_state():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        print("PROBE no-app")
        return
    f = app.font()
    print(f"PROBE font={f.family()!r} pt={f.pointSize()} px={f.pixelSize()} "
          f"widgets={len(app.allWidgets())} "
          f"quitOnLast={app.quitOnLastWindowClosed()} "
          f"style={app.style().objectName()!r}")
    qss = app.styleSheet()
    print(f"PROBE qss_len={len(qss)} qss_head={qss[:60]!r}")

    import sys

    import PyQt6.QtWidgets as real_widgets

    import fastprompter.main as main_mod
    import fastprompter.ui.editor as editor_mod

    print("PROBE sysmod-real", sys.modules.get("PyQt6.QtWidgets") is real_widgets)
    print("PROBE main-QApplication-real",
          main_mod.QApplication is real_widgets.QApplication)
    print("PROBE editor-QApplication-real",
          getattr(editor_mod, "QApplication", real_widgets.QApplication)
          is real_widgets.QApplication)
    print("PROBE main-module", main_mod.__file__)
