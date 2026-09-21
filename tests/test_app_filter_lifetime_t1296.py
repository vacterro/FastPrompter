"""T-1296: app-level event filters die with the window that installed them.

The contamination this pins (found via an ordered-prefix bisect):
``tests/test_clipboard_interop_t1269.py`` builds a real FastPrompter and
retires it; its four QApplication event filters survived on the application,
holding the window's SoundManager wrapper. Every later dialog Show then
raised ``RuntimeError: wrapped C/C++ object of type SoundManager has been
deleted`` inside ``AppearanceShowFilter``, and under pytest's log capture the
retained ``exc_info`` frames (whose locals include the shown widget) leaked
every later shown dialog -- ``test_timer_dialog_wave``'s hundred-open residue
assertion found all 100 alive and ``test_timer_fire``'s 50 ms job starved,
reproducibly, only under ordered-suite history.

The repair is ownership: the filters are parented to the window, so window
destruction (production shutdown or ``_qt_retire.retire``) destroys them and
Qt removes them from every event-filter chain by itself. No global drain, no
swallowed errors: with the owner dead there IS no stale authority left to
raise.
"""

from __future__ import annotations

import gc
import os
import sys
import weakref

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture()
def live_window(tmp_path, monkeypatch):
    """One real FastPrompter, alive; the test retires it when needed."""
    import fastprompter.core.state as state_mod
    import fastprompter.utils.portable_backup as backup_mod

    monkeypatch.setattr(
        state_mod, "get_db_path",
        lambda profile_id=1: str(tmp_path / f"t1296_{profile_id}.db"))
    monkeypatch.setattr(
        backup_mod, "run_portable_backup",
        lambda data, profile_id=1, **_kw: None)

    from fastprompter.main import FastPrompter

    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    try:
        app = QApplication.instance() or QApplication([])
        w = FastPrompter()
        for _ in range(5):
            app.processEvents()
        yield w
        from _qt_retire import retire

        if not sip.isdeleted(w):
            w.close()
            retire(w)
        app.processEvents()
    finally:
        for name, value in originals.items():
            setattr(FastPrompter, name, value)


_FILTERS = ("_scroll_sound_filter", "_wheel_guard",
            "_button_sound_filter", "_appearance_sound_filter")


class TestFilterLifetimeOwnership:
    def test_filters_are_children_of_the_window(self, live_window):
        children = {id(child) for child in live_window.children()}
        for name in _FILTERS:
            flt = getattr(live_window, name, None)
            assert flt is not None, name
            assert id(flt) in children, (
                f"{name} must be owned by the window it serves")

    def test_window_destruction_destroys_every_filter(self, live_window):
        from _qt_retire import retire

        app = QApplication.instance()
        live_window.close()
        retire(live_window)
        app.processEvents()
        for name in _FILTERS:
            flt = getattr(live_window, name, None)
            assert flt is not None, name
            assert sip.isdeleted(flt), (
                f"{name} survived its window; a stale app-level filter "
                "keeps consulting a dead SoundManager on every later event")

    def test_no_stale_authority_leaks_later_dialogs(self, tmp_path,
                                                    monkeypatch):
        """End to end: after a window is retired, a fresh TimerDialog shown
        in the same QApplication must be fully collected afterwards."""
        import fastprompter.core.state as state_mod
        import fastprompter.utils.portable_backup as backup_mod

        monkeypatch.setattr(
            state_mod, "get_db_path",
            lambda profile_id=1: str(tmp_path / f"t1296b_{profile_id}.db"))
        monkeypatch.setattr(
            backup_mod, "run_portable_backup",
            lambda data, profile_id=1, **_kw: None)

        from fastprompter.main import FastPrompter

        originals = {
            name: getattr(FastPrompter, name)
            for name in ("setup_single_instance_server", "register_all_hotkeys",
                         "unregister_all_hotkeys")
        }
        FastPrompter.setup_single_instance_server = lambda self: None
        FastPrompter.register_all_hotkeys = lambda self: None
        FastPrompter.unregister_all_hotkeys = lambda self: None
        try:
            app = QApplication.instance() or QApplication([])
            w = FastPrompter()
            for _ in range(5):
                app.processEvents()
            w.close()
            from _qt_retire import retire

            retire(w)
            app.processEvents()

            sys.path.insert(0, os.path.dirname(__file__))
            import test_timer_dialog_wave as tw

            refs = []
            for _ in range(10):
                d = tw._dlg()
                d.show()
                app.processEvents()
                d.close()
                d.deleteLater()
                refs.append(weakref.ref(d))
                app.processEvents()
            del d
            app.processEvents()
            gc.collect()
            alive = [r for r in refs if r() is not None]
            assert alive == [], (
                f"{len(alive)} dialogs leaked through stale app-level "
                "filter authority after the owning window was destroyed")
        finally:
            for name, value in originals.items():
                setattr(FastPrompter, name, value)
