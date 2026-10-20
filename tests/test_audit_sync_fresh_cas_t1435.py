"""T-1435 (SRC-095 W2-001) — the fresh-binding GUI push path uses the SAME
compare-before-publish primitive as the worker.

Established bindings already handed their write to ``_SyncPushWorker``, which
revalidated the destination's raw disk identity before ``os.replace``. Fresh
bindings (no baseline yet) kept a hand-rolled read → re-read → write sequence:
a TOCTOU window in which an external save landing between the re-read and the
write was silently destroyed. The fix routes the fresh path through
``ps.compare_and_publish_text`` with the identity accepted at read time (or
``MISSING_ON_DISK`` when the destination was accepted as absent).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter import main as main_mod
from fastprompter.core import project_sync as ps

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("w2_001_fresh")
    original_db_path = state_mod.get_db_path
    state_mod.get_db_path = (
        lambda profile_id=1: str(tmp_path / f"w2_001_{profile_id}.db"))
    import fastprompter.utils.portable_backup as backup_mod
    original_backup = backup_mod.run_portable_backup
    backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

    from fastprompter.main import FastPrompter
    originals = {
        name: getattr(FastPrompter, name)
        for name in ("setup_single_instance_server", "register_all_hotkeys",
                     "unregister_all_hotkeys")
    }
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    for _ in range(5):
        _APP.processEvents()
    w._initializing_ui = False
    w._suspend_temp_sync = False
    # make the bound slot INACTIVE so the text always comes from the stored
    # preset, never the live editor (keeps the test deterministic).
    w.active_temp_slot = -1
    try:
        yield w
    finally:
        for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
            timer = getattr(w, name, None)
            if timer is not None:
                timer.stop()
        service = getattr(w, "limit_service", None)
        if service is not None:
            service.shutdown()
        w._in_physical_teardown = True
        push_clean = w._push_shutdown()
        if getattr(w, "state", None) is not None:
            w.state.conn = None
        w.close()
        from _qt_retire import retire
        retire(w)
        for name, value in originals.items():
            setattr(FastPrompter, name, value)
        state_mod.get_db_path = original_db_path
        backup_mod.run_portable_backup = original_backup
        assert push_clean


def _bind_fresh(win, path, silo_text):
    """Bind slot 0 to ``path`` with NO baseline (a fresh binding)."""
    win.data["silo_links"] = {"0": str(path)}
    win.data.pop("project_sync_map", None)
    win.active_temp_slot = -1
    presets = win._ensure_temp_presets()
    presets[:] = [silo_text]
    key = win._sync_baseline_key(0, str(path))
    win._sync_last_applied.pop(key, None)
    win._sync_eol_cache.pop(key, None)
    win._sync_bom_cache.pop(key, None)
    win._sync_leases.pop(key, None)
    win._sync_unsafe_bindings.discard(key)
    return presets, key


def _patch_window_write(monkeypatch, hook):
    """Inject an external writer into the compare-before-publish window."""
    real = ps.compare_and_publish_text

    def patched(path, text, expected, eol="\n", write_bom=False,
                before_publish=None):
        return real(path, text, expected, eol=eol, write_bom=write_bom,
                    before_publish=(before_publish or hook))

    monkeypatch.setattr(ps, "compare_and_publish_text", patched)


def test_w2_001_fresh_approval_publishes_when_disk_is_unchanged(win, tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"EXTERNAL\n")
    _presets, key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    win._push_sync_files(slots={0})

    assert path.read_bytes() == b"APP\n"
    assert win._sync_last_applied[key] == win._sync_side_digest("APP\n")
    assert win._sync_leases[key] == 1
    assert key not in win._sync_unsafe_bindings


def test_w2_001_fresh_external_edit_in_the_window_is_refused(
        win, tmp_path, monkeypatch):
    path = tmp_path / "f.txt"
    path.write_bytes(b"EXTERNAL\n")
    _presets, key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    _patch_window_write(monkeypatch, lambda: path.write_bytes(b"LATE\n"))
    win._push_sync_files(slots={0})

    # the late external save survives untouched; no baseline was legitimised
    assert path.read_bytes() == b"LATE\n"
    assert key not in win._sync_last_applied
    assert key in win._sync_unsafe_bindings


def test_w2_001_fresh_missing_destination_publishes_when_still_absent(
        win, tmp_path):
    path = tmp_path / "new.txt"          # absent at read
    _presets, key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    win._push_sync_files(slots={0})

    assert path.read_bytes() == b"APP\n"
    assert win._sync_last_applied[key] == win._sync_side_digest("APP\n")


def test_w2_001_fresh_missing_destination_created_in_the_window_is_refused(
        win, tmp_path, monkeypatch):
    path = tmp_path / "new.txt"          # absent at read
    _presets, key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    seen = {}

    def external_create():
        seen["created"] = True
        path.write_bytes(b"THEIRS\n")

    _patch_window_write(monkeypatch, external_create)
    win._push_sync_files(slots={0})

    assert seen.get("created") is True
    assert path.read_bytes() == b"THEIRS\n"
    assert key not in win._sync_last_applied
    assert key in win._sync_unsafe_bindings


def test_w2_001_fresh_path_passes_the_acceptance_identity(win, tmp_path,
                                                          monkeypatch):
    path = tmp_path / "f.txt"
    path.write_bytes(b"EXTERNAL\n")
    _presets, _key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    captured = {}
    real = ps.compare_and_publish_text

    def spy(p, text, expected, eol="\n", write_bom=False,
            before_publish=None):
        captured["expected"] = expected
        return real(p, text, expected, eol=eol, write_bom=write_bom,
                    before_publish=before_publish)

    monkeypatch.setattr(ps, "compare_and_publish_text", spy)
    win._push_sync_files(slots={0})

    # the identity accepted at read time, from the SAME byte read
    assert captured["expected"] == ps.raw_identity(b"EXTERNAL\n")


def test_w2_001_fresh_absent_destination_passes_missing_token(win, tmp_path,
                                                              monkeypatch):
    path = tmp_path / "absent.txt"
    _presets, _key = _bind_fresh(win, path, "APP\n")
    win._sync_conflict_choice = lambda *a, **k: "app"

    captured = {}
    real = ps.compare_and_publish_text

    def spy(p, text, expected, eol="\n", write_bom=False,
            before_publish=None):
        captured["expected"] = expected
        return real(p, text, expected, eol=eol, write_bom=write_bom,
                    before_publish=before_publish)

    monkeypatch.setattr(ps, "compare_and_publish_text", spy)
    win._push_sync_files(slots={0})

    assert captured["expected"] is ps.MISSING_ON_DISK


def test_w2_001_fresh_equal_destination_never_rewrites(win, tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"SAME\n")
    _presets, key = _bind_fresh(win, path, "SAME\n")
    called = []
    win._sync_conflict_choice = lambda *a, **k: called.append(1) or "app"
    before = path.stat().st_mtime_ns

    win._push_sync_files(slots={0})

    assert called == []                        # no conflict dialog at all
    assert path.stat().st_mtime_ns == before   # no physical rewrite
    assert win._sync_last_applied[key] == win._sync_side_digest("SAME\n")


def test_w2_001_fresh_unsafe_destination_is_never_overwritten(win, tmp_path):
    path = tmp_path / "bin.dat"
    path.write_bytes(b"\x00\x01\x02binary")
    _presets, key = _bind_fresh(win, path, "APP\n")

    win._push_sync_files(slots={0})

    assert path.read_bytes() == b"\x00\x01\x02binary"
    assert key not in win._sync_last_applied
    assert key in win._sync_unsafe_bindings


def test_w2_001_fresh_path_uses_the_conditional_primitive():
    src = inspect.getsource(main_mod.FastPrompter._push_sync_files)
    assert "compare_and_publish_text" in src
    assert "read_text_file_with_identity" in src
    # the unconditional writer and the manual re-read gate are both gone
    assert "ps.write_text_file(" not in src
    assert "_reval" not in src
