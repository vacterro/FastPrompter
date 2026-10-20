"""T-1432 (SRC-093) — CORE-005 / CORE-006 regression suite.

CORE-005: Fast Pack Selection must make the SAME admission decision as full
silo packing. Selected text belonging to a document that is not the active
silo's owner document must be refused BEFORE any side effect (no target
directory, no ZIP, no history, no coverage, no clipboard), and a valid binding
must still pack normally.

CORE-006: the plan carries no ``content_fingerprint`` until it is written, so
smart reuse compared candidates against a missing key and was dead for every
valid bundle. Production preflight must derive the SAME logical fingerprint
``write_bundle`` will publish, making reuse reachable and an unchanged second
selection reuse the SAME ZIP without allocating a ``_2``.
"""

from __future__ import annotations

import inspect
import os
import zipfile
from unittest.mock import MagicMock

from _bundle_op_wait import pump_until_idle

from fastprompter.core import silo_bundle as sb
from fastprompter.main import FastPrompter


def _png(dirpath, name="shot.png", data=b"\x89PNG\r\n\x1a\npayload"):
    path = os.path.join(str(dirpath), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


# --- CORE-006: production preflight == eventual write fingerprint ----------

def test_core006_preflight_fingerprint_equals_written_fingerprint(tmp_path):
    silo_dir = str(tmp_path / "silo")
    os.makedirs(silo_dir, exist_ok=True)
    shot = _png(silo_dir, "shot.png")
    selected_text = f"• Fix the copy icon\n  ![]({shot})\n"

    plan = sb.plan_selection_bundle(
        selected_text=selected_text,
        title="Silo Title",
        target_dir=str(tmp_path / "silo" / "exports" / "fast"),
        silo_dir=silo_dir,
        category="Cat1",
        app_version="0.8.71",
        line_start=1,
        line_end=2,
    )

    # The defect's evidence: the plan has no fingerprint to compare against.
    assert plan.manifest.get("content_fingerprint") in (None, "")

    preflight_fp, _cache = sb.preflight_content_fingerprint(plan)
    assert preflight_fp

    result = sb.write_bundle(plan)
    assert not result.error, result.error
    assert result.fingerprint == preflight_fp


# --- CORE-005: refusal happens before any side effect ----------------------

class _SelHarness:
    """A bare host carrying the shipped Fast Pack Selection entry point.

    Grafts the real admission helper (``_active_silo_bundle_context``) and the
    real ``fast_pack_selection`` so the production control flow is what runs.
    History is in-memory and re-feeds the next call, so smart reuse is
    exercised end to end.
    """

    def __init__(self, silo_dir, doc_text, sel=(2, 13), bound=True,
                 category="TestCat"):
        cursor = MagicMock()
        cursor.hasSelection.return_value = True
        cursor.selectionStart.return_value = sel[0]
        cursor.selectionEnd.return_value = sel[1]
        editor = MagicMock()
        editor.textCursor.return_value = cursor
        editor.toPlainText.return_value = doc_text

        self.text_area = editor
        self.text_edit = editor
        self.active_temp_slot = 0
        self.active_is_archive = False
        self.editing_snippet = False
        self.silo_dir = str(silo_dir)
        self.category = category
        self.VERSION = "0.8.71"
        self._current_lang = "EN"
        self._last_bundle_path = None
        self._bound = bound
        self.refusals = []
        self.records = []
        self.coverage_events = []
        self.clipboard_paths = []
        self.toasts = []

    # --- admission inputs ---
    def _silo_document_bound(self, slot, is_arch):
        return bool(self._bound)

    def _silo_folder_dir(self, slot, is_arch):
        return self.silo_dir

    def _active_silo_id(self):
        return "silo_test_1"

    def get_current_category(self):
        return self.category

    # --- selection / title ---
    def _editor_text_snapshot(self):
        return self.text_area.toPlainText()

    def silo_queue_label(self, slot):
        return f"Silo {slot}"

    # --- reporting / side-effect sinks ---
    def _show_in_app_toast(self, *a, **k):
        self.toasts.append((a, k))

    def _silo_bundle_report_unavailable(self, reason=None):
        self.refusals.append(reason)

    def _reveal_path(self, path):
        pass

    def _record_bundle_coverage(self, **kwargs):
        self.coverage_events.append(kwargs)

    # --- history (in-memory, real shape) ---
    def _silo_bundle_history(self, silo_id, clean_missing=True):
        return {"records": list(self.records), "source_cache": {}}

    def _silo_bundle_history_candidates(self, silo_id, target_dir):
        return list(self.records)

    def _silo_bundle_record_success(self, silo_id, zip_path, display_title,
                                    fingerprint, target_dir, options_sig,
                                    archive_size, archive_mtime_ns,
                                    signatures=None, silo_dir=None,
                                    keep_versions=5,
                                    bundle_kind="silo_bundle"):
        st = os.stat(zip_path)
        self.records.insert(0, {
            "path": zip_path,
            "content_fingerprint": fingerprint,
            "bundle_kind": bundle_kind,
            "target_dir": target_dir,
            "archive_size": st.st_size,
            "archive_mtime_ns": getattr(st, "st_mtime_ns",
                                        int(st.st_mtime * 1e9)),
        })

    def _silo_bundle_apply_retention(self, *a, **k):
        pass


_SelHarness._active_silo_bundle_context = FastPrompter._active_silo_bundle_context
_SelHarness.fast_pack_selection = FastPrompter.fast_pack_selection
# PERF-001: Fast Pack dispatches through the shared bundle worker and completes
# through the shared completion half, so the harness carries both.
_SelHarness._silo_bundle_dispatch = FastPrompter._silo_bundle_dispatch
_SelHarness._bundle_on_finished = FastPrompter._bundle_on_finished
_SelHarness._fast_pack_complete = FastPrompter._fast_pack_complete
_SelHarness._silo_bundle_candidates_for_target = (
    FastPrompter._silo_bundle_candidates_for_target)
_SelHarness._silo_bundle_title = staticmethod(
    FastPrompter.__dict__["_silo_bundle_title"].__func__)
_SelHarness.active_silo_title = FastPrompter.active_silo_title


def _patch_clipboard(monkeypatch, harness):
    from fastprompter.ui import image_viewer

    def _copy(paths):
        harness.clipboard_paths.extend(list(paths))
        return True

    monkeypatch.setattr(image_viewer, "copy_files_to_clipboard", _copy)


def test_core005_mismatched_owner_refuses_before_any_side_effect(
        tmp_path, monkeypatch):
    harness = _SelHarness(tmp_path / "silo", "• Hello World item", bound=False)
    os.makedirs(harness.silo_dir, exist_ok=True)
    _patch_clipboard(monkeypatch, harness)

    result = harness.fast_pack_selection()

    assert result is None
    assert harness.refusals == ["INVALID_DOCUMENT_BINDING"]
    # zero side effects
    assert not os.path.isdir(os.path.join(harness.silo_dir, "exports"))
    assert harness.records == []
    assert harness.coverage_events == []
    assert harness.clipboard_paths == []
    assert harness._last_bundle_path is None


def test_core005_valid_binding_still_packs(qapp, tmp_path, monkeypatch):
    harness = _SelHarness(tmp_path / "silo", "• Hello World item", bound=True)
    os.makedirs(harness.silo_dir, exist_ok=True)
    _patch_clipboard(monkeypatch, harness)

    # PERF-001: the entry point dispatches and returns the operation; the
    # archive is published by the owned worker and reported on completion.
    op = harness.fast_pack_selection()
    assert op is not None
    assert pump_until_idle(harness)

    result = harness._last_bundle_path
    assert result is not None
    assert result.endswith(".zip") and os.path.isfile(result)
    assert harness.refusals == []
    assert harness.clipboard_paths == [result]
    assert len(harness.records) == 1


def test_core005_selection_read_from_the_validated_editor_only():
    src = inspect.getsource(FastPrompter.fast_pack_selection)
    # no fallback that could rebind to a different widget after validation
    assert 'getattr(self, "text_edit"' not in src
    # identity is validated before a byte of selection is read
    assert src.index("_active_silo_bundle_context()") < src.index("editor.textCursor()")


# --- CORE-006: smart reuse through the production path ---------------------

def test_core006_unchanged_selection_reuses_same_zip(qapp, tmp_path, monkeypatch):
    harness = _SelHarness(tmp_path / "silo", "• Hello World item")
    os.makedirs(harness.silo_dir, exist_ok=True)
    _patch_clipboard(monkeypatch, harness)

    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    first = harness._last_bundle_path
    assert first and os.path.isfile(first)
    fast_dir = os.path.join(harness.silo_dir, "exports", "fast")
    assert sorted(os.listdir(fast_dir)) == [os.path.basename(first)]

    # identical selection, unchanged content -> the SAME archive, no _2
    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    second = harness._last_bundle_path
    assert second == first
    assert sorted(os.listdir(fast_dir)) == [os.path.basename(first)]
    assert harness.clipboard_paths == [first, first]
    assert len(harness.records) == 1


def test_core006_changed_selection_creates_a_fresh_archive(qapp, tmp_path, monkeypatch):
    harness = _SelHarness(tmp_path / "silo", "• Hello World item")
    os.makedirs(harness.silo_dir, exist_ok=True)
    _patch_clipboard(monkeypatch, harness)

    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    first = harness._last_bundle_path
    assert first and os.path.isfile(first)

    harness.text_area.toPlainText.return_value = "• A different problem entirely"
    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    third = harness._last_bundle_path

    assert third and third != first
    fast_dir = os.path.join(harness.silo_dir, "exports", "fast")
    assert len(os.listdir(fast_dir)) == 2
    assert len(harness.records) == 2


def test_core006_tampered_candidate_is_rejected_and_republished(
        qapp, tmp_path, monkeypatch):
    harness = _SelHarness(tmp_path / "silo", "• Hello World item")
    os.makedirs(harness.silo_dir, exist_ok=True)
    _patch_clipboard(monkeypatch, harness)

    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    first = harness._last_bundle_path
    assert first and os.path.isfile(first)

    # tamper: the recorded size no longer matches the file on disk
    harness.records[0]["archive_size"] = os.stat(first).st_size + 1

    harness.fast_pack_selection()
    assert pump_until_idle(harness)
    second = harness._last_bundle_path

    # reuse was refused, so a fresh (never-clobbering) archive was published
    assert second and second != first and os.path.isfile(second)
    assert len(harness.records) == 2
    with zipfile.ZipFile(second, "r") as zf:
        assert "manifest.json" in zf.namelist()
