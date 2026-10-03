"""T-1250: editor snapshot failure-sentinel integrity.

`_editor_text_snapshot()` returns None when the editor/document cannot
currently be read. None means SNAPSHOT UNAVAILABLE -- never "the user
authored an empty document". Every mutating consumer must fail closed on
None while a legitimate "" snapshot still persists normally.

The static guard at the bottom of this file bans the collapsing pattern
``_editor_text_snapshot() or ""`` anywhere in production code.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastprompter.main import FastPrompter

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "fastprompter"


def _window(**over):
    """Minimal MainWindow shell bound to the real methods under test."""
    w = SimpleNamespace(
        data={
            "temp_presets": ["KEEP-ME"],
            "archive_temp_presets": ["KEEP-ME"],
            "categories": {},
            "last_text": "KEEP-ME",
            "last_tab_idx": 0,
            "last_geometry": "",
            "font_size": 11,
            "preview_mode": "None",
            "paste_mode": "Plain",
            "tray_visible": "True",
            "close_on_focus_loss": "True",
            "ctrl_c_closes": "True",
        },
        active_temp_slot=0,
        active_is_archive=False,
        editing_snippet=None,
        silo_last_edited={},
        _visible_silos=10,
        _last_cached_text="KEEP-ME",
        _log_snapshot_unavailable=MagicMock(),
        mark_dirty=MagicMock(),
        _remember_active_document_text=MagicMock(),
        _update_active_silo_ui=MagicMock(),
        # T-1408: the flush calls this after moving silo_last_edited. Covered
        # for real in tests/test_header_follow_edit_t1408.py; here it only has
        # to exist, because this double is standing in for the whole window.
        refresh_header_stamp=MagicMock(),
        _active_doc=MagicMock(return_value=MagicMock()),
        _document_owner_matches=MagicMock(return_value=True),
        _refuse_unowned_flush=MagicMock(),
        get_current_category=MagicMock(return_value="Code"),
        capture_silo_state=MagicMock(),
        capture_silo_session=MagicMock(),
        play_click_sound=MagicMock(),
        _cache_timer=SimpleNamespace(stop=MagicMock()),
        _begin_batch_update=MagicMock(),
        _end_batch_update=MagicMock(),
        cancel_editing=MagicMock(),
        refresh_temp_presets=MagicMock(),
        refresh_archive_panel=MagicMock(),
        text_area=SimpleNamespace(
            setFocus=MagicMock(),
            ensureCursorVisible=MagicMock(),
            blockSignals=MagicMock(),
            toPlainText=MagicMock(return_value="LIVE"),
        ),
        _queue_silo_text_history=MagicMock(),
        _flush_live_editor=MagicMock(),
        _sync_silo_folder=MagicMock(),
        _files_root=MagicMock(return_value=""),
        _mirror_settings_dirty=MagicMock(return_value=False),
        _editor_text_snapshot=MagicMock(return_value=None),
    )
    for key, value in over.items():
        setattr(w, key, value)
    return w


# ---------------------------------------------------------------------------
# A. CACHE — FAILURE
# ---------------------------------------------------------------------------

def test_a_cache_failure_never_erases_stored_text():
    w = _window()
    FastPrompter.cache_current_text(w)
    assert w.data["temp_presets"][0] == "KEEP-ME"
    # a failed observation must never become the authoritative cached edit
    assert w._last_cached_text is None
    w.mark_dirty.assert_not_called()
    assert w.silo_last_edited == {}
    w._update_active_silo_ui.assert_not_called()


def test_a2_cache_failure_refuses_snippet_store_too():
    w = _window(editing_snippet=("Code", 0))
    w.data["categories"]["Code"] = [{"text": "KEEP-ME"}]
    FastPrompter.cache_current_text(w)
    assert w.data["categories"]["Code"][0]["text"] == "KEEP-ME"
    w.mark_dirty.assert_not_called()


def test_a3_cache_failure_diagnostic_names_operation_and_slot():
    w = _window(active_temp_slot=3, active_is_archive=True)
    FastPrompter.cache_current_text(w)
    w._log_snapshot_unavailable.assert_called_once_with(
        "cache_current_text", True)


# ---------------------------------------------------------------------------
# B. CACHE — LEGITIMATE EMPTY
# ---------------------------------------------------------------------------

def test_b_cache_legitimate_empty_still_persists():
    w = _window(_editor_text_snapshot=MagicMock(return_value=""))
    doc = MagicMock()
    w._active_doc = MagicMock(return_value=doc)
    FastPrompter.cache_current_text(w)
    assert w.data["temp_presets"][0] == ""
    assert w._last_cached_text == ""
    w.mark_dirty.assert_called_once_with("temp")
    assert 0 in w.silo_last_edited
    w._update_active_silo_ui.assert_called_once_with(raw="")


# ---------------------------------------------------------------------------
# C/D. SYNC — BINDING SKIPPED ON FAILURE
# ---------------------------------------------------------------------------

def _sync_window(tmp_path, snapshot_value, baseline):
    link = tmp_path / "linked_silo.txt"
    link.write_text("KEEP-ME", encoding="utf-8")
    w = _window(
        _sync_last_applied={},
        _push_jobs_pending={},
        _push_inflight=True,          # short-circuit the worker dispatch
        _ensure_temp_presets=MagicMock(return_value=["KEEP-ME"]),
        _link_file_for_slot=MagicMock(return_value=str(link)),
        _sync_file_for_slot=MagicMock(return_value=None),
        _sync_max_bytes=MagicMock(return_value=1_000_000),
        _sync_baseline_key=MagicMock(return_value="k0"),
        _sync_baseline_value=MagicMock(return_value=baseline),
        _sync_eol_cache={},
        _sync_bom_cache={},
        _sync_lease=MagicMock(return_value=0),
        _sync_conflict_choice=MagicMock(),
        _sync_flag_unsafe_binding=MagicMock(),
        _dispatch_push_jobs=MagicMock(),
        _sync_side_digest=FastPrompter._sync_side_digest,
        _editor_text_snapshot=MagicMock(return_value=snapshot_value),
    )
    return w, link


def test_c_sync_established_binding_failure_skips_round(tmp_path):
    w, link = _sync_window(tmp_path, None, "previously-written-digest")
    before = link.read_bytes()
    FastPrompter._push_sync_files(w)
    # no pending push job, no baseline mutation, physical file untouched
    assert w._push_jobs_pending == {}
    assert w._sync_last_applied == {}
    assert link.read_bytes() == before
    w._sync_conflict_choice.assert_not_called()


def test_d_sync_fresh_binding_failure_no_conflict_no_empty(tmp_path):
    w, link = _sync_window(tmp_path, None, None)
    before = link.read_bytes()
    FastPrompter._push_sync_files(w)
    assert w._push_jobs_pending == {}
    assert w._sync_last_applied == {}
    assert link.read_bytes() == before
    # a failed read must not open the fresh-binding conflict workflow with
    # synthetic "" as the app side
    w._sync_conflict_choice.assert_not_called()
    w._sync_flag_unsafe_binding.assert_not_called()


def test_m_sync_legitimate_empty_still_enqueues_write(tmp_path):
    w, link = _sync_window(tmp_path, "", "previously-written-digest")
    FastPrompter._push_sync_files(w)
    assert "k0" in w._push_jobs_pending
    job = w._push_jobs_pending["k0"]
    assert job[2] == ""                    # the genuine empty text
    assert job[4] == "previously-written-digest"  # expected disk digest
    assert link.read_bytes() == b"KEEP-ME"  # nothing written this round


# ---------------------------------------------------------------------------
# E/F/G. COMMIT
# ---------------------------------------------------------------------------

def test_e_commit_snapshot_failure_direct_fallback_success(qapp):
    from PyQt6.QtWidgets import QTextEdit

    w = _window(_editor_text_snapshot=MagicMock(return_value=None))
    ta = QTextEdit()
    ta.setPlainText("old")
    ta.toPlainText = MagicMock(return_value="LIVE")
    w.text_area = ta
    FastPrompter.commit_current_text(w)
    w._flush_live_editor.assert_called_once_with("LIVE")


def test_f_commit_both_reads_fail_refuses():
    w = _window(_editor_text_snapshot=MagicMock(return_value=None))
    w.text_area.toPlainText = MagicMock(
        side_effect=RuntimeError("wrapped C/C++ object deleted"))
    FastPrompter.commit_current_text(w)
    w._flush_live_editor.assert_not_called()
    w._log_snapshot_unavailable.assert_called_once()


def test_g_commit_valid_empty_commits():
    w = _window(_editor_text_snapshot=MagicMock(return_value=""))
    FastPrompter.commit_current_text(w)
    w._flush_live_editor.assert_called_once_with("")


def test_g2_commit_snapshot_success_skips_fallback():
    w = _window(_editor_text_snapshot=MagicMock(return_value="hello"))
    FastPrompter.commit_current_text(w)
    w.text_area.toPlainText.assert_not_called()
    w._flush_live_editor.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# H/I. NAVIGATION — FAILURE ABORTS THE OWNERSHIP TRANSITION
# ---------------------------------------------------------------------------

def test_h_normal_navigation_failure_aborts():
    w = _window(_editor_text_snapshot=MagicMock(return_value=None))
    FastPrompter._switch_to_slot(w, 1)
    assert w.active_temp_slot == 0
    assert w.active_is_archive is False
    assert w.data["temp_presets"][0] == "KEEP-ME"
    # abort happens BEFORE any transition side effect
    w.capture_silo_state.assert_not_called()
    w.play_click_sound.assert_not_called()
    w._sync_silo_folder.assert_not_called()
    w._log_snapshot_unavailable.assert_called_once()


def test_i_archive_navigation_failure_aborts():
    w = _window(_editor_text_snapshot=MagicMock(return_value=None),
                active_is_archive=True)
    FastPrompter._switch_to_slot(w, 1, is_archive=True)
    assert w.active_temp_slot == 0
    assert w.active_is_archive is True
    assert w.data["archive_temp_presets"][0] == "KEEP-ME"
    w.capture_silo_state.assert_not_called()
    w.play_click_sound.assert_not_called()
    w._sync_silo_folder.assert_not_called()
    w._log_snapshot_unavailable.assert_called_once()


def test_h2_valid_snapshot_still_publishes_outgoing_text():
    # positive control for the guard: a readable document still flushes.
    w = _window(_editor_text_snapshot=MagicMock(return_value="CHANGED"))
    w._cache_timer = SimpleNamespace(stop=MagicMock())
    FastPrompter._switch_to_slot(w, 0)     # same slot: flush + early return
    assert w.data["temp_presets"][0] == "CHANGED"
    w._sync_silo_folder.assert_called_once_with("Code", "KEEP-ME", "CHANGED")
    assert 0 in w.silo_last_edited
    w.mark_dirty.assert_called_once_with("temp")


def test_h3_normal_legitimate_empty_still_publishes():
    # "" from a readable document is real user content, not a failure.
    w = _window(_editor_text_snapshot=MagicMock(return_value=""))
    FastPrompter._switch_to_slot(w, 0)     # same slot: flush + early return
    assert w.data["temp_presets"][0] == ""
    w._sync_silo_folder.assert_called_once_with("Code", "KEEP-ME", "")
    w.mark_dirty.assert_called_once_with("temp")


def test_h4_archive_whitespace_outgoing_keeps_preexisting_skip():
    # pre-existing archive contract (unchanged by T-1250): a whitespace-only
    # outgoing archive read does not flush, and the stored text survives.
    w = _window(_editor_text_snapshot=MagicMock(return_value="  "),
                active_is_archive=True)
    FastPrompter._switch_to_slot(w, 0, is_archive=True)
    assert w.data["archive_temp_presets"][0] == "KEEP-ME"
    w._sync_silo_folder.assert_not_called()


# ---------------------------------------------------------------------------
# J/K. REAL SNAPSHOT FAILURE PATHS (exception + deleted widget)
# ---------------------------------------------------------------------------

def test_j_document_exception_becomes_none_and_fails_closed(qapp):
    from PyQt6.QtWidgets import QTextEdit

    class _BoomDocEdit(QTextEdit):
        def document(self):
            raise RuntimeError("wrapped C/C++ object of type "
                               "QTextDocument has been deleted")

    w = _window()
    ta = _BoomDocEdit()
    ta.setPlainText("LIVE")
    w.text_area = ta
    # bind the REAL snapshot over the fake shell
    w._editor_text_snapshot = lambda: FastPrompter._editor_text_snapshot(w)
    # the REAL snapshot converts the exception into None...
    assert FastPrompter._editor_text_snapshot(w) is None
    # ...and the mutating consumers fail closed on it
    FastPrompter.cache_current_text(w)
    assert w.data["temp_presets"][0] == "KEEP-ME"
    assert w._last_cached_text is None


def test_k_deleted_text_area_reads_as_unavailable_not_empty(qapp):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QTextEdit

    w = _window()
    ta = QTextEdit()
    ta.setPlainText("LIVE")
    w.text_area = ta
    w._editor_text_snapshot = lambda: FastPrompter._editor_text_snapshot(w)
    assert FastPrompter._editor_text_snapshot(w) == "LIVE"
    sip.delete(ta)
    assert FastPrompter._editor_text_snapshot(w) is None
    FastPrompter.cache_current_text(w)
    assert w.data["temp_presets"][0] == "KEEP-ME"
    w.mark_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# SCOPE 6 — save_data_to_db (authoritative persistence caller)
# ---------------------------------------------------------------------------

def _state():
    return SimpleNamespace(
        save_data_to_db=MagicMock(return_value=True),
        last_save_had_temp_text=False,
    )


def test_save_failure_refuses_live_flush_and_view_capture():
    w = _window(state=_state(),
                _editor_text_snapshot=MagicMock(return_value=None))
    assert FastPrompter.save_data_to_db(w) is True
    # the stored silo text is NOT overwritten from an unreadable editor
    w._flush_live_editor.assert_not_called()
    w.capture_silo_state.assert_not_called()
    # the persistence metadata still carries the last real observation
    assert w.state.save_data_to_db.call_args.args[0] == "KEEP-ME"
    assert w._last_cached_text is None


def test_m_save_legitimate_empty_persists():
    w = _window(state=_state(),
                _editor_text_snapshot=MagicMock(return_value=""))
    assert FastPrompter.save_data_to_db(w) is True
    w._flush_live_editor.assert_called_once_with("")
    assert w.state.save_data_to_db.call_args.args[0] == ""
    w.capture_silo_state.assert_called_once()


# ---------------------------------------------------------------------------
# L. STATIC GUARD — no mutating production path may collapse the sentinel
# ---------------------------------------------------------------------------

def _sentinel_collapse_sites(tree):
    """Yield line numbers for every `_editor_text_snapshot()` call used as
    a truthiness operand of an `or` chain — the `or ""` collapse."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        for operand in node.values[:-1]:   # the final operand cannot collapse
            for sub in ast.walk(operand):
                is_call = isinstance(sub, ast.Call)
                if not is_call:
                    continue
                if (isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "_editor_text_snapshot"):
                    yield sub.lineno
                elif (isinstance(sub.func, ast.Name)
                        and sub.func.id == "_editor_text_snapshot"):
                    yield sub.lineno


def test_l_no_production_sentinel_collapse():
    offenders = []
    py_files = sorted(SRC_ROOT.rglob("*.py"))
    assert py_files, "production tree not found"
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line in _sentinel_collapse_sites(tree):
            offenders.append(f"{path}:{line}")
    assert not offenders, (
        "T-1250 regression: _editor_text_snapshot() collapsed by `or` in:\n"
        + "\n".join(offenders))


# ---------------------------------------------------------------------------
# BOUNDED DIAGNOSTIC
# ---------------------------------------------------------------------------

def test_refusal_diagnostic_is_throttled(monkeypatch):
    w = _window()
    calls = []
    import fastprompter.core.logging as logging_mod
    monkeypatch.setattr(logging_mod, "logger",
                        SimpleNamespace(warning=lambda *a, **k: calls.append(a)))
    FastPrompter._snapshot_refusal_last_log = 0.0
    try:
        FastPrompter._log_snapshot_unavailable(w, "cache_current_text", False)
        FastPrompter._log_snapshot_unavailable(w, "cache_current_text", False)
        assert len(calls) == 1                  # one line per minute at most
        assert "cache_current_text" in calls[0]
        assert "refused" in calls[0][0]
    finally:
        FastPrompter._snapshot_refusal_last_log = 0.0


def test_refusal_diagnostic_never_logs_contents():
    import inspect
    source = inspect.getsource(FastPrompter._log_snapshot_unavailable)
    # guard against someone "helpfully" adding the document text to the log
    assert "current_text" not in source
    assert "toPlainText" not in source
