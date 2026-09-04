"""Tests for FastPrompter startup and lazy UI optimizations.

Verifies:
- Lazy Settings UI (Priority 1)
- Lazy Kanban & Table Views (Priority 2)
- Archive Button Pool (Priority 3)
- Silo Button Pool (Priority 4)
- Lazy Number Tabs (Priority 5)
- Startup timings telemetry (10 points)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_startup_")


@pytest.fixture(scope="module")
def clean_window():
    for widget in list(QApplication.allWidgets()):
        try:
            widget.deleteLater()
        except Exception:
            pass
    _app.processEvents()

    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"lazy_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    FastPrompter._init_limit_service = lambda self: None

    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()

    yield w

    # Clean teardown
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.date_timer.stop()
    w._cache_timer.stop()
    if hasattr(w, "limit_service") and w.limit_service is not None:
        try:
            w.limit_service.shutdown()
        except Exception:
            pass
    if getattr(w, "state", None) is not None:
        w.state.conn = None
    w.conn = None
    w.close()
    w.deleteLater()
    _app.processEvents()


def test_startup_timings_coverage(clean_window):
    """Assert all required startup timing points are recorded."""
    w = clean_window
    expected_keys = [
        "1_FastPrompterState_load",
        "2_pre_init_migrations",
        "3_init_ui_total",
        "4_header_settings",
        "5_sidebar",
        "6_editor_highlighter_construction",
        "7_kanban_table_construction",
        "8_apply_theme",
    ]
    for k in expected_keys:
        assert k in w._startup_timings, f"Missing timing key: {k}"
        assert w._startup_timings[k] >= 0.0, f"Timing {k} must be non-negative"


def test_lazy_settings_lifecycle(clean_window):
    """Assert settings widgets are not materialized until mini_settings revealed."""
    w = clean_window
    assert getattr(w, "_settings_built", False) is False
    assert getattr(w, "cb_top", None) is None
    assert getattr(w, "cb_lock_window", None) is None
    assert getattr(w, "cb_focus", None) is None

    # Reveal settings
    w.mini_settings_frame.setVisible(True)
    _app.processEvents()

    assert w._settings_built is True
    assert getattr(w, "cb_top", None) is not None
    assert getattr(w, "cb_lock_window", None) is not None
    assert getattr(w, "cb_focus", None) is not None

    # Idempotent: opening again does not rebuild or change references
    cb_top_ref = w.cb_top
    w._ensure_settings_built()
    assert w.cb_top is cb_top_ref


def test_lazy_kanban_and_table_widgets(clean_window):
    """Assert Kanban and Table widgets are None at startup and build on demand."""
    w = clean_window
    assert w.kanban_widget is None
    assert w.table_widget is None

    # Demand Kanban
    kb = w._get_or_create_kanban_widget()
    assert kb is not None
    assert w.kanban_widget is kb
    assert w._get_or_create_kanban_widget() is kb

    # Demand Table
    tb = w._get_or_create_table_widget()
    assert tb is not None
    assert w.table_widget is tb
    assert w._get_or_create_table_widget() is tb


def test_archive_button_pool(clean_window):
    """Assert archive buttons start bounded and grow on demand."""
    w = clean_window
    assert len(w.archive_buttons) == 0

    w._ensure_archive_buttons(15)
    assert len(w.archive_buttons) >= 15

    w._ensure_archive_buttons(5)
    assert len(w.archive_buttons) >= 15


def test_silo_button_pool(clean_window):
    """Assert silo buttons start bounded (< 50) and grow up to 50 on demand."""
    w = clean_window
    assert len(w.silo_buttons) < 50
    assert len(w.silo_buttons) >= 10

    w._ensure_silo_buttons(30)
    assert len(w.silo_buttons) >= 30

    w._ensure_silo_buttons(100)
    assert len(w.silo_buttons) <= 50


def test_lazy_number_tabs(clean_window):
    """Assert numbox tabs are not rebuilt when disabled at startup."""
    w = clean_window
    if w.data.get("numbox_tabs", "False") != "True":
        assert not hasattr(w, "cat_numbox") or w.cat_numbox is None or w._cat_numbox_dirty

    w._toggle_numbox_mode(True)
    _app.processEvents()
    assert hasattr(w, "cat_numbox")
    assert w.cat_numbox is not None
    assert w.cat_numbox.isVisible()
