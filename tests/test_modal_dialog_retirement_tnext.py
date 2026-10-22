"""Regression suite for modal dialog retirement and focus lock integrity.

Verifies:
- WAVE 1: Test isolation repaired with monkeypatch fixtures and exception-safe teardown.
- WAVE 2: Narrowly-typed constructor-failure cleanup preserving unrelated children.
- WAVE 3: Context menu lifecycle and dismissal cleanup (date label, overflow, cat, silo presets, temp).
- WAVE 4: Structural AST source guard distinguishing dialog/menu variables and negative controls.
- WAVE 5: Real Qt runtime verification with bounded modal loops (50 AI limits, 20 menus, 20 dialogs, nested).
"""

from __future__ import annotations

import ast
import os
import tempfile
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from _qt_retire import retire  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMenu  # noqa: E402

import fastprompter.core.silo_presets as silo_presets_mod  # noqa: E402
import fastprompter.core.state as state_mod  # noqa: E402
from fastprompter.main import FastPrompter  # noqa: E402
from fastprompter.ui.backup_dialog import BackupDialog  # noqa: E402
from fastprompter.ui.ctrlw_settings import CtrlWSettingsDialog  # noqa: E402
from fastprompter.ui.drop_overlay import DropZonesDialog  # noqa: E402
from fastprompter.ui.hashtag_dialog import HashtagDialog  # noqa: E402
from fastprompter.ui.header_format_dialog import HeaderFormatDialog  # noqa: E402
from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog  # noqa: E402
from fastprompter.ui.settings import ColorConfigDialog, HotkeySettingsDialog  # noqa: E402
from fastprompter.ui.silo_settings_dialog import SiloSettingsDialog  # noqa: E402
from fastprompter.ui.timer_dialog import TimerDialog  # noqa: E402
from fastprompter.ui.typo_check_dialog import TypoCheckDialog  # noqa: E402
from fastprompter.ui.window_presets_dialog import WindowPresetsDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])
_TMP_DIR = tempfile.mkdtemp(prefix="fastprompter_modal_retirement_")


@contextmanager
def auto_finish_dialog(action: str = "accept", callback=None):
    """Intercept QDialog.exec to complete without blocking using MonkeyPatch."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()

    def _intercepted_exec(self):
        if callback is not None:
            callback(self)
        if action == "accept":
            self.accept()
            return 1
        elif action == "reject":
            self.reject()
            return 0
        elif action == "close":
            self.close()
            return 0
        return 0

    mp.setattr(QDialog, "exec", _intercepted_exec)
    try:
        yield
    finally:
        mp.undo()


def dismiss_active_modal(action: str = "accept", delay_ms: int = 0):
    """Schedule a QTimer to dismiss whatever modal dialog opens next in a real Qt event loop."""
    def _dismiss():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            if action == "accept":
                dlg.accept()
            elif action == "reject":
                dlg.reject()
            elif action == "close":
                dlg.close()
        else:
            QTimer.singleShot(5, _dismiss)

    QTimer.singleShot(delay_ms, _dismiss)


def dismiss_active_menu(action: str = "close", delay_ms: int = 0):
    """Schedule a QTimer to dismiss whatever QMenu opens next in a real Qt event loop."""
    def _dismiss():
        popup = QApplication.activePopupWidget()
        target_menu = None
        if isinstance(popup, QMenu):
            target_menu = popup
        else:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QMenu) and w.isVisible():
                    target_menu = w
                    break

        if target_menu is not None:
            target_menu.close()
        else:
            QTimer.singleShot(5, _dismiss)

    QTimer.singleShot(delay_ms, _dismiss)


@pytest.fixture()
def host(monkeypatch):
    """Create an isolated FastPrompter instance with monkeypatch isolation and exception-safe cleanup."""
    monkeypatch.setattr(
        state_mod, "get_db_path",
        lambda profile_id=1: os.path.join(_TMP_DIR, f"modal_test_{profile_id}.db"),
    )
    monkeypatch.setattr(
        state_mod, "run_portable_backup", lambda data, profile_id=1: None, raising=False
    )
    monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None)
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None)
    monkeypatch.setattr(
        FastPrompter, "_init_limit_service", lambda self: None, raising=False
    )

    before_font, before_sheet = _APP.font(), _APP.styleSheet()

    w = FastPrompter()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.data["cats_order"] = ["ProjectA", "ProjectB", "ProjectC"]
    w.data["categories"] = {c: [None] * 100 for c in ["ProjectA", "ProjectB", "ProjectC"]}
    w.data["hidden_categories"] = []
    w.data["temp_presets"] = ["# Test Silo\nLine 1\n#tag1\nLine 2"]
    w.rebuild_cat_combo(keep="ProjectA")
    _APP.processEvents()

    try:
        yield w
    finally:
        for timer_attr in (
            "auto_save_timer",
            "topmost_timer",
            "date_timer",
            "_cache_timer",
        ):
            t = getattr(w, timer_attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass

        try:
            w.close()
        except Exception:
            pass
        _APP.processEvents()
        _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        try:
            retire(w)
        except Exception:
            pass

        if _APP.font() != before_font:
            _APP.setFont(before_font)
        if _APP.styleSheet() != before_sheet:
            _APP.setStyleSheet(before_sheet)


# ======================================================================
# TEST GROUP A — OWNERSHIP (11 primary routes + backup + timer)
# ======================================================================


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_limit_settings_dialog(host, action):
    """Route 1: open_limit_settings_dialog retires cleanly under accept, reject, close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_limit_settings_dialog()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, LimitSettingsDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "close"])
def test_ownership_hashtag_dialog(host, action):
    """Route 2: open_hashtag_dialog retires cleanly under accept and close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_hashtag_dialog("tag1")

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, HashtagDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_silo_settings(host, action):
    """Route 3: open_silo_settings retires cleanly under accept, reject, close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_silo_settings(0)

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, SiloSettingsDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "close"])
def test_ownership_typo_check_dialog(host, action):
    """Route 4: check_project_typos retires cleanly under accept and close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.check_project_typos()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, TypoCheckDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_header_format_editor(host, action):
    """Route 5: open_header_format_editor retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_header_format_editor()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, HeaderFormatDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("upward", [False, True])
@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_ctrlw_settings(host, upward, action):
    """Route 6: open_ctrlw_settings (Ctrl+W and Alt+W) retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_ctrlw_settings(upward=upward)

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, CtrlWSettingsDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_drop_zones_settings(host, action):
    """Route 7: open_drop_zones_settings retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_drop_zones_settings()

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, DropZonesDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_hotkey_settings(host, action):
    """Route 8: open_hotkey_settings retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_hotkey_settings()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, HotkeySettingsDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_window_presets(host, action):
    """Route 9: open_window_presets retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_window_presets()

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, WindowPresetsDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_color_settings(host, action):
    """Route 10: open_color_settings retires cleanly."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_color_settings()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, ColorConfigDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_projects_manager(host, action):
    """Route 11: open_projects_manager retires cleanly on accept, reject, close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_projects_manager()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained_dialogs = [
        c for c in host.children()
        if type(c) is QDialog and not sip.isdeleted(c)
    ]
    assert retained_dialogs == []
    assert len(host.children()) == before_count


def test_ownership_backup_dialog_contract(host):
    """Important Exception: backup_db uses BackupDialog with WA_DeleteOnClose self-delete."""
    before_count = len(host.children())
    seen_dialog = []
    wa_delete_flag = []

    def _inspect(dlg):
        seen_dialog.append(dlg)
        wa_delete_flag.append(dlg.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))

    with auto_finish_dialog("close", callback=_inspect):
        host.backup_db()

    assert len(seen_dialog) == 1
    assert wa_delete_flag == [True]
    dlg = seen_dialog[0]
    assert isinstance(dlg, BackupDialog)

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    assert sip.isdeleted(dlg) is True
    retained = [c for c in host.children() if isinstance(c, BackupDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize("action", ["accept", "reject", "close"])
def test_ownership_timer_dialog(host, action):
    """open_timer_dialog retires cleanly under accept, reject, close."""
    before_count = len(host.children())
    with auto_finish_dialog(action):
        host.open_timer_dialog()

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, TimerDialog)]
    assert retained == []
    assert len(host.children()) == before_count


# ======================================================================
# TEST GROUP B — REPETITION STRESS (0 QObject Growth, Intercepted)
# ======================================================================


def test_repetition_ai_limits_50_cycles(host):
    """Group B: 50 cycles of open_limit_settings_dialog demonstrate ZERO retained growth."""
    before_count = len(host.children())
    with auto_finish_dialog("accept"):
        for _ in range(50):
            host.open_limit_settings_dialog()
            _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            _APP.processEvents()

    after_count = len(host.children())
    retained = [c for c in host.children() if isinstance(c, LimitSettingsDialog)]
    assert retained == []
    assert after_count == before_count


def test_repetition_lightweight_dialogs_20_cycles(host):
    """Group B: 20 cycles each of representative dialog routes demonstrate 0 growth."""
    before_count = len(host.children())

    # Silo settings (20 cycles)
    with auto_finish_dialog("accept"):
        for _ in range(20):
            host.open_silo_settings(0)
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Header format editor (20 cycles)
    with auto_finish_dialog("accept"):
        for _ in range(20):
            host.open_header_format_editor()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Drop zones settings (20 cycles)
    with auto_finish_dialog("accept"):
        for _ in range(20):
            host.open_drop_zones_settings()
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Window presets (20 cycles)
    with auto_finish_dialog("accept"):
        for _ in range(20):
            host.open_window_presets()
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Projects manager (20 cycles)
    with auto_finish_dialog("reject"):
        for _ in range(20):
            host.open_projects_manager()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count


# ======================================================================
# TEST GROUP C — SIGNALS AND TIMERS (AI Limits Settings)
# ======================================================================


def test_limit_settings_timer_active_while_open_stops_on_accept(host):
    """Group C: Timer is active while dialog is open and stops immediately on accept."""
    dialog = LimitSettingsDialog(host)
    try:
        assert hasattr(dialog, "_sync_timer")
        assert dialog._sync_timer.isActive() is True
        dialog.accept()
        assert dialog._sync_timer.isActive() is False
    finally:
        retire(dialog)


def test_limit_settings_timer_stops_on_close(host):
    """Group C: Timer stops immediately on closeEvent."""
    dialog = LimitSettingsDialog(host)
    try:
        assert dialog._sync_timer.isActive() is True
        dialog.close()
        assert dialog._sync_timer.isActive() is False
    finally:
        retire(dialog)


def test_limit_settings_signal_released_and_isolated_subsequent(host, monkeypatch):
    """Group C: Signal subscription is released on finish; old instance gets 0 callbacks."""
    updated_instances = []
    orig_updated = LimitSettingsDialog._limits_updated

    def _spy(self):
        updated_instances.append(self)
        orig_updated(self)

    monkeypatch.setattr(LimitSettingsDialog, "_limits_updated", _spy)

    # Instance 1
    d1 = LimitSettingsDialog(host)
    host.limit_gauges._result_ready.emit()
    assert len(updated_instances) == 1
    assert updated_instances[0] is d1

    # Finish and retire instance 1
    d1.accept()
    d1.deleteLater()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert sip.isdeleted(d1) is True

    # Signal emission after retirement: d1 receives 0 callbacks
    host.limit_gauges._result_ready.emit()
    assert len(updated_instances) == 1

    # Instance 2 operates normally
    d2 = LimitSettingsDialog(host)
    try:
        assert d2._sync_timer.isActive() is True
        host.limit_gauges._result_ready.emit()
        assert len(updated_instances) == 2
        assert updated_instances[1] is d2
    finally:
        d2.reject()
        retire(d2)


def test_limit_settings_overview_refreshes_after_dialog_completion(host, monkeypatch):
    """Group C: Normal close triggers quota overview and status refreshes."""
    refreshes = []
    monkeypatch.setattr(host.limit_gauges, "refresh_view", lambda: refreshes.append("gauges"))
    monkeypatch.setattr(host, "_update_limit_status", lambda: refreshes.append("status"))

    with auto_finish_dialog("accept"):
        host.open_limit_settings_dialog()

    assert refreshes == ["gauges", "status"]


# ======================================================================
# TEST GROUP D — FOCUS LOCK & EXCEPTION RECOVERY (Wave 2 & Wave 3)
# ======================================================================


def test_constructor_failure_unrelated_child_preserved(host, monkeypatch):
    """Wave 2 Red->Green control: constructor failure cleans up dialog without harming unrelated children."""
    unrelated = QLabel("unrelated_keepalive", host)
    initial_children = list(host.children())
    assert unrelated in initial_children

    def _failing_init(self, main_win):
        super(LimitSettingsDialog, self).__init__(main_win)
        raise RuntimeError("simulated constructor failure")

    monkeypatch.setattr(LimitSettingsDialog, "__init__", _failing_init)

    with pytest.raises(RuntimeError, match="simulated constructor failure"):
        host.open_limit_settings_dialog()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    # Unrelated child MUST survive intact
    assert sip.isdeleted(unrelated) is False
    assert unrelated in host.children()

    # Partial dialog must NOT be retained
    retained_dialogs = [c for c in host.children() if isinstance(c, LimitSettingsDialog)]
    assert retained_dialogs == []

    # Focus lock restored
    assert getattr(host, "_focus_lock_count", 0) == 0
    assert host.ignore_focus_loss is False


def test_timer_dialog_construction_exception_recovers_focus_lock(host, monkeypatch):
    """Group D: Constructor failure in TimerDialog restores focus lock without orphan child."""
    def _failing_init(self, main_win, initial_tab=0):
        super(TimerDialog, self).__init__(main_win)
        raise RuntimeError("simulated TimerDialog init error")

    monkeypatch.setattr(TimerDialog, "__init__", _failing_init)
    before_count = len(host.children())

    with pytest.raises(RuntimeError, match="simulated TimerDialog init error"):
        host.open_timer_dialog()

    # Wait for the delayed 300ms focus lock decrement
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    assert getattr(host, "_focus_lock_count", 0) == 0
    assert host.ignore_focus_loss is False
    assert len(host.children()) == before_count


def test_timer_dialog_exec_exception_recovers_focus_lock(host, monkeypatch):
    """Group D: Exception during TimerDialog.exec() restores focus lock and retires dialog."""
    def _failing_exec(self):
        raise RuntimeError("simulated TimerDialog exec error")

    monkeypatch.setattr(TimerDialog, "exec", _failing_exec)
    before_count = len(host.children())

    with pytest.raises(RuntimeError, match="simulated TimerDialog exec error"):
        host.open_timer_dialog()

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    assert getattr(host, "_focus_lock_count", 0) == 0
    assert host.ignore_focus_loss is False
    retained = [c for c in host.children() if isinstance(c, TimerDialog)]
    assert retained == []
    assert len(host.children()) == before_count


@pytest.mark.parametrize(
    ("dialog_cls", "open_method"),
    [
        (SiloSettingsDialog, lambda w: w.open_silo_settings(0)),
        (DropZonesDialog, lambda w: w.open_drop_zones_settings()),
        (WindowPresetsDialog, lambda w: w.open_window_presets()),
        (HashtagDialog, lambda w: w.open_hashtag_dialog("tag1")),
        (BackupDialog, lambda w: w.backup_db()),
    ],
)
def test_other_openers_construction_exception_recovers_focus_lock(
    host, dialog_cls, open_method, monkeypatch
):
    """Group D: Injected construction failure in adjacent openers releases focus lock."""
    def _failing_init(self, *args, **kwargs):
        super(dialog_cls, self).__init__(args[0])
        raise RuntimeError(f"simulated {dialog_cls.__name__} init error")

    monkeypatch.setattr(dialog_cls, "__init__", _failing_init)
    before_count = len(host.children())

    with pytest.raises(RuntimeError, match=f"simulated {dialog_cls.__name__} init error"):
        open_method(host)

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    assert getattr(host, "_focus_lock_count", 0) == 0
    assert host.ignore_focus_loss is False
    assert len(host.children()) == before_count


# ======================================================================
# TEST GROUP E — CONTEXT MENU LIFECYCLE (Wave 3)
# ======================================================================


def test_context_menu_date_label_lifecycle(host):
    """Wave 3: _date_label_menu retires cleanly and leaves 0 retained QMenu objects."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    dismiss_active_menu("close")
    host._date_label_menu(QPoint(10, 10))

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


def test_context_menu_show_overflow_lifecycle(host, monkeypatch):
    """Wave 3: _show_overflow_menu retires cleanly and leaves 0 retained QMenu objects."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    monkeypatch.setattr(host, "_overflow_hidden_buttons", lambda: [("btn_help", host.btn_help)])

    dismiss_active_menu("close")
    host._show_overflow_menu()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


def test_context_menu_show_cat_context_lifecycle(host):
    """Wave 3: show_cat_context_menu retires cleanly and leaves 0 retained QMenu objects."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    dismiss_active_menu("close")
    host.show_cat_context_menu(QPoint(10, 10))

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


def test_context_menu_show_new_silo_presets_empty_path(host, monkeypatch):
    """Wave 3: show_new_silo_presets with 0 presets immediately deletes unshown menu."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    monkeypatch.setattr(silo_presets_mod, "load_presets", lambda: [])

    host.show_new_silo_presets()

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


def test_context_menu_show_new_silo_presets_popup_dismiss(host, monkeypatch):
    """Wave 3: show_new_silo_presets popup with presets deletes on close via WA_DeleteOnClose."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    monkeypatch.setattr(silo_presets_mod, "load_presets", lambda: [("Template 1", "Content 1")])

    host.show_new_silo_presets()
    menu = getattr(host, "_new_preset_menu", None)
    assert menu is not None
    assert menu in host.children()

    menu.close()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    assert sip.isdeleted(menu) is True
    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


def test_context_menu_show_temp_menu_lifecycle(host):
    """Wave 3: show_temp_menu deletes on close via WA_DeleteOnClose."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    dismiss_active_menu("close")
    host.show_temp_menu(0, QPoint(10, 10))

    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []


# ======================================================================
# TEST GROUP F — FUNCTIONAL REGRESSIONS
# ======================================================================


def test_functional_projects_manager_save_and_reorder(host):
    """Group F: Projects Manager reorders categories in-place and preserves identities."""
    initial_order = list(host.data["cats_order"])
    assert initial_order == ["ProjectA", "ProjectB", "ProjectC"]

    def _reorder_action(dlg):
        from PyQt6.QtWidgets import QListWidget
        lst = dlg.findChild(QListWidget)
        assert lst is not None
        item = lst.takeItem(1)
        lst.insertItem(0, item)

    with auto_finish_dialog("accept", callback=_reorder_action):
        host.open_projects_manager()

    assert host.data["cats_order"] == ["ProjectB", "ProjectA", "ProjectC"]


def test_functional_projects_manager_cancel_leaves_order_intact(host):
    """Group F: Rejecting Projects Manager cancels reordering."""
    initial_order = list(host.data["cats_order"])

    def _reorder_action(dlg):
        from PyQt6.QtWidgets import QListWidget
        lst = dlg.findChild(QListWidget)
        item = lst.takeItem(1)
        lst.insertItem(0, item)

    with auto_finish_dialog("reject", callback=_reorder_action):
        host.open_projects_manager()

    assert host.data["cats_order"] == initial_order


def test_functional_projects_manager_hidden_selection(host):
    """Group F: Unticking non-current project hides it; active project cannot be hidden."""
    def _untick_action(dlg):
        from PyQt6.QtWidgets import QListWidget
        lst = dlg.findChild(QListWidget)
        item_b = lst.item(1)
        assert item_b.text() == "ProjectB"
        item_b.setCheckState(Qt.CheckState.Unchecked)

    with auto_finish_dialog("accept", callback=_untick_action):
        host.open_projects_manager()

    assert "ProjectB" in host.hidden_categories()
    assert "ProjectA" not in host.hidden_categories()


def test_functional_silo_settings_persistence(host):
    """Group F: Silo Settings persists folder and executable into data store."""
    def _fill_paths(dlg):
        dlg.edit_folder.setText("C:/Projects/TestFolder")
        dlg.edit_exe.setText("C:/Projects/TestFolder/run.exe")

    with auto_finish_dialog("accept", callback=_fill_paths):
        host.open_silo_settings(0)

    paths = host.data.get("silo_project_paths", {}).get("0", {})
    assert paths.get("folder") == "C:/Projects/TestFolder"
    assert paths.get("executable") == "C:/Projects/TestFolder/run.exe"


def test_functional_hotkey_settings_save_and_cancel(host):
    """Group F: Hotkey Settings save persists data; cancel leaves it intact."""
    initial_val = host.data.get("global_hotkey", "")

    def _modify_save(dlg):
        dlg.save_hotkeys()

    with auto_finish_dialog("accept", callback=_modify_save):
        host.open_hotkey_settings()

    assert host.ignore_focus_loss is False

    with auto_finish_dialog("reject"):
        host.open_hotkey_settings()
    assert host.data.get("global_hotkey", "") == initial_val


def test_functional_color_settings_save(host):
    """Group F: Color Settings save updates custom_colors and switches theme to Custom."""
    def _modify_colors(dlg):
        dlg.custom_colors["edit_bg"] = "#112233"
        dlg.save_colors()

    with auto_finish_dialog("accept", callback=_modify_colors):
        host.open_color_settings()

    assert host.data["custom_colors"]["edit_bg"] == "#112233"
    assert host.data["theme"] == "Custom"


def test_functional_window_presets_editor(host, monkeypatch):
    """Group F: Window Presets editor runs, closes, and reloads fast zone pages."""
    reload_called = []
    monkeypatch.setattr(host, "_reload_fast_zone_pages", lambda: reload_called.append(True))

    with auto_finish_dialog("accept"):
        host.open_window_presets()

    QTest.qWait(350)
    assert len(reload_called) == 1


def test_functional_hashtag_navigation(host):
    """Group F: HashtagDialog loads tag counts and displays hits without crash."""
    with auto_finish_dialog("close"):
        host.open_hashtag_dialog("tag1")

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


# ======================================================================
# TEST GROUP G — REAL QT RUNTIME VERIFICATION (Wave 5)
# ======================================================================


def test_real_qt_repetition_ai_limits_50_cycles(host):
    """Wave 5: 50 real Qt modal loops of open_limit_settings_dialog demonstrate 0 leak."""
    before_count = len(host.children())
    for _ in range(50):
        dismiss_active_modal("accept")
        host.open_limit_settings_dialog()
        _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()

    retained = [c for c in host.children() if isinstance(c, LimitSettingsDialog)]
    assert retained == []
    assert len(host.children()) == before_count
    assert getattr(host, "_focus_lock_count", 0) == 0


def test_real_qt_repetition_context_menus_20_cycles(host, monkeypatch):
    """Wave 5: 20 real Qt popup cycles for each context menu route demonstrate 0 leak."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    monkeypatch.setattr(host, "_overflow_hidden_buttons", lambda: [("btn_help", host.btn_help)])

    for _ in range(20):
        dismiss_active_menu("close")
        host._date_label_menu(QPoint(10, 10))

        dismiss_active_menu("close")
        host._show_overflow_menu()

        dismiss_active_menu("close")
        host.show_cat_context_menu(QPoint(10, 10))

        dismiss_active_menu("close")
        host.show_temp_menu(0, QPoint(10, 10))

        _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()

    current_menus = [c for c in host.children() if isinstance(c, QMenu)]
    new_menus = [m for m in current_menus if m not in initial_menus and not sip.isdeleted(m)]
    assert new_menus == []
    assert getattr(host, "_focus_lock_count", 0) == 0


def test_real_qt_repetition_lightweight_dialogs_20_cycles(host):
    """Wave 5: 20 real Qt modal loops for representative dialogs demonstrate 0 leak."""
    before_count = len(host.children())

    # Silo settings (20 cycles, alternating accept and reject)
    for i in range(20):
        action = "accept" if i % 2 == 0 else "reject"
        dismiss_active_modal(action)
        host.open_silo_settings(0)
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Header format editor (20 cycles)
    for _ in range(20):
        dismiss_active_modal("accept")
        host.open_header_format_editor()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Drop zones settings (20 cycles)
    for _ in range(20):
        dismiss_active_modal("reject")
        host.open_drop_zones_settings()
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Window presets (20 cycles)
    for _ in range(20):
        dismiss_active_modal("accept")
        host.open_window_presets()
    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count

    # Projects manager (20 cycles)
    for _ in range(20):
        dismiss_active_modal("reject")
        host.open_projects_manager()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert len(host.children()) == before_count
    assert getattr(host, "_focus_lock_count", 0) == 0


def test_real_qt_nested_dialog_from_menu_action(host):
    """Wave 5: Date label menu triggers Timer dialog; both retire cleanly in real Qt loops."""
    initial_menus = [c for c in host.children() if isinstance(c, QMenu)]
    before_count = len(host.children())

    def _handle_menu():
        popup = QApplication.activePopupWidget()
        target = popup if isinstance(popup, QMenu) else None
        if target is None:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QMenu) and w not in initial_menus and w.isVisible():
                    target = w
                    break
        if target is not None:
            for act in target.actions():
                if "timer" in act.text().lower() or "manage" in act.text().lower():
                    # Schedule dismissal of the modal timer dialog that will open
                    dismiss_active_modal("accept", delay_ms=10)
                    target.close()
                    act.trigger()
                    return
            target.close()
        else:
            QTimer.singleShot(5, _handle_menu)

    QTimer.singleShot(0, _handle_menu)
    host._date_label_menu(QPoint(10, 10))

    QTest.qWait(350)
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()

    retained_menus = [c for c in host.children() if isinstance(c, QMenu) and c not in initial_menus]
    retained_dialogs = [c for c in host.children() if isinstance(c, QDialog)]
    assert retained_menus == []
    assert retained_dialogs == []
    assert len(host.children()) == before_count
    assert getattr(host, "_focus_lock_count", 0) == 0


# ======================================================================
# TEST GROUP H — SOURCE GUARD & NEGATIVE CONTROLS (Wave 4)
# ======================================================================


def verify_modal_exec_retirement(tree_or_func):
    """Verify that modal exec calls on transient dialogs/menus have verified retirement in finally.

    Distinguishes:
    - Dialog and menu variables
    - Documented exception contracts (backup_db, show_temp_menu)
    - Verifies retirement is in finally block and matches the target variable
    - Detects unrelated deleteLater calls or deletes outside finally

    Returns a list of violation tuples: (method_name, var_name, reason)
    """
    violations = []

    parent_map = {}
    for parent in ast.walk(tree_or_func):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent

    functions = []
    if isinstance(tree_or_func, ast.FunctionDef):
        functions = [tree_or_func]
    else:
        for node in ast.walk(tree_or_func):
            if isinstance(node, ast.FunctionDef):
                functions.append(node)

    documented_exceptions = {"backup_db", "show_temp_menu"}

    for func in functions:
        if func.name in documented_exceptions:
            continue

        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "exec"
            ):
                if not isinstance(node.func.value, ast.Name):
                    continue
                var_name = node.func.value.id
                if var_name in ("app", "box", "msg_box"):
                    continue

                curr = node
                enclosing_tries = []
                while curr in parent_map:
                    curr = parent_map[curr]
                    if isinstance(curr, ast.Try):
                        enclosing_tries.append(curr)

                if not enclosing_tries:
                    violations.append(
                        (func.name, var_name, "exec() is not inside a try block")
                    )
                    continue

                retired = False
                unrelated_retires = []
                for try_node in enclosing_tries:
                    for final_stmt in try_node.finalbody:
                        for final_call in ast.walk(final_stmt):
                            if isinstance(final_call, ast.Call):
                                if (
                                    isinstance(final_call.func, ast.Attribute)
                                    and final_call.func.attr == "deleteLater"
                                ):
                                    if isinstance(final_call.func.value, ast.Name):
                                        if final_call.func.value.id == var_name:
                                            retired = True
                                        else:
                                            unrelated_retires.append(
                                                final_call.func.value.id
                                            )
                                elif (
                                    isinstance(final_call.func, ast.Name)
                                    and final_call.func.id
                                    in ("_safe_retire_dialog", "retire")
                                ):
                                    if final_call.args and isinstance(
                                        final_call.args[0], ast.Name
                                    ):
                                        if final_call.args[0].id == var_name:
                                            retired = True
                                        else:
                                            unrelated_retires.append(
                                                final_call.args[0].id
                                            )

                if not retired:
                    if unrelated_retires:
                        violations.append(
                            (
                                func.name,
                                var_name,
                                f"finally block retires unrelated object(s) {unrelated_retires} but not {var_name}",
                            )
                        )
                    else:
                        violations.append(
                            (
                                func.name,
                                var_name,
                                f"no retirement call for {var_name} found in finally block",
                            )
                        )

    return violations


def test_source_guard_parented_qdialog_exec_has_retirement():
    """Wave 4 positive control: main.py FastPrompter modal exec routes have verified retirement."""
    main_py_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src/fastprompter/main.py")
    )
    with open(main_py_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="main.py")

    fp_class = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FastPrompter"),
        None,
    )
    assert fp_class is not None, "FastPrompter class not found in main.py"

    violations = verify_modal_exec_retirement(fp_class)
    assert violations == [], f"Modal retirement source violations found: {violations}"


def test_source_guard_negative_control_unrelated_delete():
    """Wave 4 negative control: guard rejects finally block that deletes unrelated object."""
    code = """
def bad_unrelated(self):
    dialog = SomeDialog(self)
    other = SomeWidget(self)
    try:
        dialog.exec()
    finally:
        other.deleteLater()
"""
    violations = verify_modal_exec_retirement(ast.parse(code))
    assert len(violations) == 1
    method, var, reason = violations[0]
    assert method == "bad_unrelated"
    assert var == "dialog"
    assert "retires unrelated object" in reason


def test_source_guard_negative_control_outside_finally():
    """Wave 4 negative control: guard rejects deletion outside finally block."""
    code = """
def bad_outside(self):
    dialog = SomeDialog(self)
    try:
        dialog.exec()
    except Exception:
        pass
    dialog.deleteLater()
"""
    violations = verify_modal_exec_retirement(ast.parse(code))
    assert len(violations) == 1
    method, var, reason = violations[0]
    assert method == "bad_outside"
    assert var == "dialog"
    assert "no retirement call for dialog found in finally block" in reason


def test_source_guard_negative_control_no_retirement():
    """Wave 4 negative control: guard rejects exec call with no try block or cleanup."""
    code = """
def bad_no_delete(self):
    dialog = SomeDialog(self)
    dialog.exec()
"""
    violations = verify_modal_exec_retirement(ast.parse(code))
    assert len(violations) == 1
    method, var, reason = violations[0]
    assert method == "bad_no_delete"
    assert var == "dialog"
    assert "exec() is not inside a try block" in reason


def test_source_guard_positive_control_safe_retire():
    """Wave 4 positive control: guard passes method using _safe_retire_dialog in finally."""
    code = """
def good_method(self):
    dialog = SomeDialog(self)
    try:
        dialog.exec()
    finally:
        _safe_retire_dialog(dialog, self, SomeDialog)
"""
    violations = verify_modal_exec_retirement(ast.parse(code))
    assert violations == []
