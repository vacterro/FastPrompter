"""T-743 regression: toast click during modal Timers dialog.

The reported bug: Timers -> Test creates a notification toast that cannot
be clicked or dismissed.

Key findings from the regression harness:
1. Toast IS created during modal Timers dialog ✓
2. Toast mousePressEvent DOES fire ✓ (close() is called, WA_DeleteOnClose
   deletes the C++ object — RuntimeError on isHidden() proves it)
3. Toast cleanup IS correct ✓ (removed from _open list via closeEvent)

The hypothesis that modality blocks mouse input is DISPROVEN.
The actual issue may be a positioning/z-order problem where the toast
appears behind the modal dialog on certain configurations.

    uv run pytest tests_smoke/test_t743_toast_click.py -v
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import fastprompter.core.state as state_mod
import tempfile

from fastprompter.core.timers import Timer
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_t743_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"t_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    from fastprompter.ui.timer_toast import TimerToast
    for toast in list(TimerToast._open):
        try:
            toast.close()
        except Exception:
            pass
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


@pytest.fixture
def test_timer():
    import datetime
    return Timer(
        name="T-743 Probe",
        description="Regression test for toast click",
        target=datetime.datetime.now() + datetime.timedelta(seconds=60),
        sound="tick",
        volume=5,
    )


# ---------------------------------------------------------------------------
# Non-modal toast: body click and close button work
# ---------------------------------------------------------------------------


class TestToastClickNoModal:
    """Toast body click and close button dismiss when no modal dialog.

    TimerToast has WA_DeleteOnClose, so the C++ object is deleted on close.
    The fact that accessing .isHidden() after close raises RuntimeError
    ("C/C++ object deleted") is PROOF that the click -> close -> delete
    chain executed correctly.
    """

    @staticmethod
    def _is_gone(toast):
        """True if the toast was properly deleted (WA_DeleteOnClose)."""
        from PyQt6 import sip
        return sip.isdeleted(toast)

    def test_body_click_dismisses_toast(self, win, test_timer):
        from fastprompter.ui.timer_toast import TimerToast, show_toast
        from PyQt6 import sip

        toast = show_toast(win, test_timer)
        assert toast is not None, "toast must be created"
        assert toast.isVisible(), "toast must be visible"

        # Record _open before click
        in_open_before = toast in TimerToast._open

        body_center = toast.rect().center()
        QTest.mouseClick(toast, Qt.MouseButton.LeftButton, pos=body_center)
        _app.processEvents()

        assert sip.isdeleted(toast), (
            "WA_DeleteOnClose must delete toast on body click. "
            "NOT deleted = mousePressEvent did NOT fire = BUG."
        )
        assert toast not in TimerToast._open, "deleted toast must leave _open list"

    def test_close_button_dismisses_toast(self, win, test_timer):
        from fastprompter.ui.timer_toast import TimerToast, show_toast
        from PyQt6 import sip
        from PyQt6.QtWidgets import QPushButton

        toast = show_toast(win, test_timer)
        assert toast is not None

        close_btn = None
        for btn in toast.findChildren(QPushButton):
            if btn.objectName() == "CloseBtn" or btn.text() == "\u2715":
                close_btn = btn
                break

        assert close_btn is not None, "close button must exist"
        QTest.mouseClick(close_btn, Qt.MouseButton.LeftButton)
        _app.processEvents()

        assert sip.isdeleted(toast), (
            "WA_DeleteOnClose must delete toast on close-button click. "
            "NOT deleted = close button click did NOT fire = BUG."
        )
        assert toast not in TimerToast._open


# ---------------------------------------------------------------------------
# Modal dialog: toast must still receive clicks
# ---------------------------------------------------------------------------


class TestToastClickWithModal:
    """Toast must be clickable even when modal dialog is open."""

    def test_toast_appears_during_modal_timers(self, win):
        """Verify toast creation during modal Timers dialog."""
        from fastprompter.ui.timer_dialog import TimerDialog
        from fastprompter.ui.timer_toast import TimerToast

        dlg = TimerDialog(win)
        dlg.show()
        _app.processEvents()

        init_count = len(TimerToast._open)

        import fastprompter.ui.timer_dialog as td
        old_delay = td._TEST_DELAY_S
        try:
            td._TEST_DELAY_S = 0.1
            dlg.test_now()
            QTest.qWait(500)
            _app.processEvents()

            assert len(TimerToast._open) > init_count, (
                f"Toast must be created during modal. count={len(TimerToast._open)}, "
                f"activeModal={QApplication.activeModalWidget()}"
            )

            # Cleanup the test toast
            for t in TimerToast._open:
                if t not in getattr(self, "_pre_existing", []):
                    try:
                        t.close()
                    except Exception:
                        pass
        finally:
            td._TEST_DELAY_S = old_delay
            dlg.close()

    def test_toast_click_during_modal_deletes(self, win, test_timer):
        """Toast body click during active modal deletes the toast."""
        from fastprompter.ui.timer_toast import TimerToast, show_toast
        from PyQt6 import sip
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel

        modal = QDialog(win)
        modal.setModal(True)
        layout = QVBoxLayout(modal)
        layout.addWidget(QLabel("Modal"))
        modal.show()
        _app.processEvents()
        assert QApplication.activeModalWidget() is not None

        toast = show_toast(win, test_timer)
        assert toast is not None

        body_center = toast.rect().center()
        QTest.mouseClick(toast, Qt.MouseButton.LeftButton, pos=body_center)
        _app.processEvents()

        modal.close()
        assert sip.isdeleted(toast), (
            "Toast must close on body click during modal. "
            "NOT deleted = BUG: modal blocked the click event."
        )

    def test_toast_close_btn_during_modal(self, win, test_timer):
        """Close button works during active modal."""
        from fastprompter.ui.timer_toast import TimerToast, show_toast
        from PyQt6 import sip
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

        modal = QDialog(win)
        modal.setModal(True)
        layout = QVBoxLayout(modal)
        layout.addWidget(QLabel("Modal"))
        modal.show()
        _app.processEvents()

        toast = show_toast(win, test_timer)
        assert toast is not None

        close_btn = None
        for btn in toast.findChildren(QPushButton):
            if btn.objectName() == "CloseBtn" or btn.text() == "\u2715":
                close_btn = btn
                break

        assert close_btn is not None
        QTest.mouseClick(close_btn, Qt.MouseButton.LeftButton)
        _app.processEvents()

        modal.close()
        assert sip.isdeleted(toast), (
            "Toast ✕ button must work during modal."
        )


# ---------------------------------------------------------------------------
# Cleanup: no stale toasts
# ---------------------------------------------------------------------------


class TestToastCleanup:
    """Toast cleanup must leave no stale instances."""

    def test_close_removes_from_open_list(self, win, test_timer):
        from fastprompter.ui.timer_toast import TimerToast, show_toast

        toast = show_toast(win, test_timer)
        assert toast is not None
        assert toast in TimerToast._open

        if hasattr(toast, '_auto') and toast._auto is not None:
            toast._auto.stop()
        toast.close()
        _app.processEvents()

        assert toast not in TimerToast._open, "closed toast must leave _open list"

    def test_no_invisible_widget_at_toast_geometry(self, win, test_timer):
        from fastprompter.ui.timer_toast import TimerToast, show_toast

        toast = show_toast(win, test_timer)
        assert toast is not None

        center = toast.geometry().center()
        toast.close()
        _app.processEvents()

        widget_at = QApplication.widgetAt(center)
        assert not isinstance(widget_at, TimerToast), (
            f"Toast widget must not remain at its geometry after close. "
            f"widgetAt={widget_at}"
        )
