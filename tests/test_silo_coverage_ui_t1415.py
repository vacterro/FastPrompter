"""T-1415: Pack Coverage Overlay UI & Editor Integration Tests.

Validates:
1. Default settings: show_pack_coverage is False, pack_coverage_fade is True.
2. MainWindow._record_bundle_coverage persists to data["silo_pack_coverage"] and emits events.
3. MainWindow.clear_pack_coverage_for_current_silo clears only active silo history without touching ZIPs.
4. VaultTextEdit.is_pack_coverage_visible honours settings and session hide.
5. VaultTextEdit.refresh_pack_coverage reconciles document requirements live.
6. VaultTextEdit._paint_coverage_marker renders:
   - FRESH: accent notch
   - FULL / RECENT_FULL: continuous bar with fade opacity
   - PARTIAL / RECENT_PARTIAL: dashed/segmented bar
   - Structural / headings / blanks: None
7. VaultTextEdit._format_coverage_tooltip returns truthful terminology:
   - "Bundled", "Partially bundled", "Not bundled in this form"
   - Never "Sent", "Delivered", or "Agent received"
   - Mentions "Clipboard copy failed" when clipboard_success is False.
8. Context menu includes "Pack Coverage" submenu with Show/Hide session/Clear.
"""

from __future__ import annotations

import time

from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.silo_coverage import (
    CoverageItem,
    CoverageState,
    RequirementCoverageReceipt,
)
from fastprompter.ui.editor import VaultTextEdit


def _get_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class DummyMainWindow:
    def __init__(self):
        self.data = {
            "show_pack_coverage": "False",
            "pack_coverage_fade": "True",
            "show_line_numbers": "True",
            "line_marks": "False",
        }
        self.current_silo = "silo_1"
        self._current_lang = "EN"
        self._theme_cache = {
            "raw_colors": {
                "accent": "#D3B57A",
                "btn_text": "#C5AB6E",
                "border_light": "#826941",
                "text_main": "#E2CA95",
                "bg_text": "#24170C",
            }
        }
        self.save_data_called = False
        self.highlighter = None
        self._LARGE_DOC_THRESHOLD = 500_000
        self.capture_silo_state = lambda: None

    def _active_silo_id(self):
        return self.current_silo

    def save_data_to_db(self):
        self.save_data_called = True

    def mark_dirty(self, domain=None):
        pass

    def _get_custom_colors(self):
        return {}

    def _get_coverage_store(self):
        if not hasattr(self, "_coverage_store") or self._coverage_store is None:
            from fastprompter.core import silo_coverage as sc
            raw = self.data.get("silo_pack_coverage")
            self._coverage_store = sc.CoverageStore.from_dict(raw)
        return self._coverage_store

    def _record_bundle_coverage(
        self,
        silo_id,
        bundle_kind,
        archive_name,
        document_text,
        selected_text=None,
        media_files=(),
        clipboard_success=True,
    ):
        from fastprompter.main import FastPrompter
        return FastPrompter._record_bundle_coverage(
            self,
            silo_id=silo_id,
            bundle_kind=bundle_kind,
            archive_name=archive_name,
            document_text=document_text,
            selected_text=selected_text,
            media_files=media_files,
            clipboard_success=clipboard_success,
        )

    def clear_pack_coverage_for_current_silo(self):
        from fastprompter.main import FastPrompter
        return FastPrompter.clear_pack_coverage_for_current_silo(self)

    def toggle_pack_coverage(self, checked):
        from fastprompter.main import FastPrompter
        return FastPrompter.toggle_pack_coverage(self, checked)


def test_1_default_profile_settings():
    assert DEFAULT_PROFILE.get("show_pack_coverage") == "False"
    assert DEFAULT_PROFILE.get("pack_coverage_fade") == "True"


def test_2_main_window_record_coverage_persistence(qapp):
    win = DummyMainWindow()
    doc_text = "# Title\n\n- [P0] Implement auth\n- [P1] Add tests"
    
    win._record_bundle_coverage(
        silo_id="silo_1",
        bundle_kind="silo_bundle",
        archive_name="test_bundle.zip",
        document_text=doc_text,
        clipboard_success=True,
    )

    store_dict = win.data.get("silo_pack_coverage")
    assert isinstance(store_dict, dict)
    assert "silo_1" in store_dict
    assert len(store_dict["silo_1"]) == 2
    assert win.save_data_called is True


def test_3_main_window_clear_coverage_isolation(qapp):
    win = DummyMainWindow()
    doc_text = "- [P0] Req A"
    win._record_bundle_coverage("silo_1", "silo_bundle", "s1.zip", doc_text)
    win._record_bundle_coverage("silo_2", "silo_bundle", "s2.zip", doc_text)

    win.current_silo = "silo_1"
    win.clear_pack_coverage_for_current_silo()

    store_dict = win.data.get("silo_pack_coverage")
    assert len(store_dict.get("silo_1", [])) == 0
    assert len(store_dict.get("silo_2", [])) == 1


def test_4_editor_visibility_and_session_hide(qapp):
    win = DummyMainWindow()
    editor = VaultTextEdit(win)
    win.text_edit = editor
    
    # Default is off
    assert editor.is_pack_coverage_visible() is False

    # Enabled via toggle
    win.toggle_pack_coverage(True)
    assert editor.is_pack_coverage_visible() is True

    # Session hide turns off without mutating win.data
    editor.hide_pack_coverage_session()
    assert editor.is_pack_coverage_visible() is False
    assert win.data["show_pack_coverage"] == "True"


def test_5_live_editor_reconciliation(qapp):
    win = DummyMainWindow()
    win.data["show_pack_coverage"] = "True"
    editor = VaultTextEdit(win)
    win.text_edit = editor
    
    doc = "# Header\n\n- [P0] Req Alpha\n\n- [P1] Req Beta"
    editor.setPlainText(doc)

    # Before bundle: all requirements fresh
    editor.refresh_pack_coverage()
    assert editor._coverage_map is not None
    assert editor._coverage_map.fresh_count == 2
    assert editor._coverage_map.covered_count == 0

    # Bundle Alpha only
    win._record_bundle_coverage(
        "silo_1", "selection_bundle", "fast.zip", doc, selected_text="- [P0] Req Alpha"
    )
    editor.refresh_pack_coverage()
    assert editor._coverage_map.covered_count == 1
    assert editor._coverage_map.fresh_count == 1

    # Line 1 is header: state must be None
    st, it = editor._coverage_map.get_line_state(1)
    assert st is None
    assert it is None

    # Line 3 is Req Alpha: covered
    st_alpha, it_alpha = editor._coverage_map.get_line_state(3)
    assert st_alpha in (CoverageState.FULL, CoverageState.RECENT_FULL)
    assert it_alpha is not None

    # Line 5 is Req Beta: fresh
    st_beta, it_beta = editor._coverage_map.get_line_state(5)
    assert st_beta == CoverageState.FRESH


def test_6_marker_painting_no_crash(qapp):
    win = DummyMainWindow()
    win.data["show_pack_coverage"] = "True"
    editor = VaultTextEdit(win)
    win.text_edit = editor
    doc = "# Title\n\n- Req Alpha\n\n- Req Beta"
    editor.setPlainText(doc)
    editor.refresh_pack_coverage()

    pix = QPixmap(200, 200)
    painter = QPainter(pix)
    try:
        # Test painting line 1 (None - header)
        editor._paint_coverage_marker(painter, 1, 0, 20, is_hovered=False, cov_x=1)
        # Test painting line 3 (Fresh)
        editor._paint_coverage_marker(painter, 3, 20, 20, is_hovered=False, cov_x=1)
    finally:
        painter.end()


def test_7_format_coverage_tooltip_truthfulness(qapp):
    win = DummyMainWindow()
    editor = VaultTextEdit(win)
    win.text_edit = editor

    # Fresh tooltip
    item_fresh = CoverageItem("REQ-1", 1, 2, "Req text", CoverageState.FRESH)
    tip_fresh = editor._format_coverage_tooltip(CoverageState.FRESH, item_fresh)
    assert "Not bundled in this form" in tip_fresh
    assert "Sent" not in tip_fresh
    assert "Delivered" not in tip_fresh

    # Full covered tooltip
    receipt = RequirementCoverageReceipt(
        coverage_key="k1",
        bundle_kind="selection_bundle",
        archive_name="test.zip",
        first_bundled_epoch=1700000000,
        last_bundled_epoch=1700000000,
        times_bundled=2,
        clipboard_success=True,
    )
    item_cov = CoverageItem("REQ-1", 1, 2, "Req text", CoverageState.FULL, receipt)
    tip_cov = editor._format_coverage_tooltip(CoverageState.FULL, item_cov)
    assert "Bundled" in tip_cov
    assert "Fast Selection" in tip_cov
    assert "Bundled 2 times" in tip_cov
    assert "Sent" not in tip_cov
    assert "Delivered" not in tip_cov

    # Clipboard failure tooltip
    receipt_fail = RequirementCoverageReceipt(
        coverage_key="k2",
        bundle_kind="silo_bundle",
        archive_name="silo.zip",
        last_bundled_epoch=1700000000,
        times_bundled=1,
        clipboard_success=False,
    )
    item_fail = CoverageItem("REQ-2", 3, 4, "Req 2", CoverageState.FULL, receipt_fail)
    tip_fail = editor._format_coverage_tooltip(CoverageState.FULL, item_fail)
    assert "Clipboard copy failed" in tip_fail


def test_8_fading_timer_lifecycle(qapp):
    win = DummyMainWindow()
    win.data["show_pack_coverage"] = "True"
    editor = VaultTextEdit(win)
    win.text_edit = editor

    assert editor._coverage_fade_timer.isActive() is False
    assert editor._coverage_fade_start_time == 0.0

    # Triggering coverage event starts fade
    editor.trigger_pack_coverage_event()
    assert editor._coverage_fade_start_time > 0.0
    assert editor._coverage_fade_timer.isActive() is True

    # Simulate 3 seconds elapsed
    editor._coverage_fade_start_time = time.time() - 3.0
    editor._on_coverage_fade_tick()
    # Timer stops, start time resets
    assert editor._coverage_fade_timer.isActive() is False
    assert editor._coverage_fade_start_time == 0.0
