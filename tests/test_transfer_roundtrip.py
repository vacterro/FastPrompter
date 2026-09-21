"""T-1217: real SQLite close/reopen transfer round-trips (isolated DB only).

Every test here uses an isolated tmp_path database and a PRIVATE tmp files
root. The repository data/ tree is never touched; the state module is
redirected BEFORE the first construction (T-1222 isolation lesson).

STAGE B/B28: the text-only transfer relies on the NORMAL dirty/save
lifecycle (no forced durable commit). These tests prove that a transfer
followed by an ordinary save survives a full close/reopen of a brand-new
window from the same SQLite DB.
"""
import hashlib
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import fastprompter.core.state as state_mod
from fastprompter.core.usage_limits.service import UsageLimitService

_tmpdir_holder = {}


def _patch_state(tmp_path):
    state_mod.get_db_path = lambda profile_id=1: str(
        tmp_path / f"t1217_{profile_id}.db")
    state_mod.run_portable_backup = lambda *a, **k: None


def _patch_window_class():
    from fastprompter.main import FastPrompter
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None


@pytest.fixture
def rw(monkeypatch, tmp_path):
    """A real FastPrompter window on an ISOLATED tmp SQLite profile."""
    from fastprompter.main import FastPrompter
    _patch_state(tmp_path)
    _patch_window_class()
    monkeypatch.setattr(UsageLimitService, "schedule_auto",
                        lambda *a, **kw: None)
    w = FastPrompter()
    w._initializing_ui = False
    _tmpdir_holder["tmp"] = tmp_path
    yield w
    _shutdown(w)


def _shutdown(w):
    try:
        from PyQt6 import sip
        if sip.isdeleted(w):
            return
    except Exception:
        pass
    if hasattr(w, "limit_service") and w.limit_service is not None:
        try:
            w.limit_service.shutdown()
        except Exception:
            pass
    try:
        w._wait_for_undo_saves()
    except Exception:
        pass
    from PyQt6.QtCore import QTimer
    for timer in w.findChildren(QTimer):
        timer.stop()
    w._logical_finalized = True
    w.tray_icon.hide()
    w.close()
    # T-1286: receiver-scoped retirement (canonical _qt_retire). The previous
    # bare deleteLater() left the window pending until a later test pumped an
    # event loop; the accumulated backlog stalled tests/test_timer_fire.py.
    from _qt_retire import retire
    retire(w)


def _open_again(tmp_path):
    """A BRAND NEW window reading the SAME SQLite DB (no in-memory carry)."""
    from fastprompter.main import FastPrompter
    _patch_state(tmp_path)
    _patch_window_class()
    w = FastPrompter()
    w._initializing_ui = False
    return w


def _add_destination(win, name="PROJB"):
    if name not in win.data["categories"]:
        win.data["categories"][name] = [None] * 100
        win.data.setdefault("cats_order", []).append(name)
        win.data.setdefault("temp_presets_all", {})[name] = [""] * 10


def _read_cat(win, cat):
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, cat)
    win.silo_last_edited = win.data.setdefault(
        "silo_last_edited_all", {}).setdefault(cat, {})
    return win.data["temp_presets"]


def _seed_identity(win, tmp_path, src, with_folder=True):
    """Distinct sentinels for every transferable identity field."""
    win.data["silo_colors_all"][src] = {"0": "#778899"}
    win.data["silo_type_all"][src] = {"0": "kanban"}
    win.data["silo_project_paths_all"][src] = {"0": "ROUNDTRIP-PATH"}
    win.data["silo_links_all"][src] = {"0": "ROUNDTRIP-LINK.txt"}
    win.data["silo_last_edited_all"][src] = {0: 321}
    win.data["silo_view_state_all"][src] = {"s0": {"cursor": 12}}
    win.data["silo_ticked_all"][src] = [0]
    win.data["silo_selected_all"][src] = [0]
    win.data["silo_gaps_all"][src] = [0]
    win.data["silo_gap_names_all"][src] = {"0": "ROUNDTRIP-GAP"}
    digest = None
    if with_folder:
        root = str(tmp_path / "files")
        win.data["silo_folders_all"][src] = {"0": "assets"}
        folder = (tmp_path / "files" / win._category_files_dir(src) / "assets")
        folder.mkdir(parents=True)
        payload = b"ROUNDTRIP-BYTES-\xe4\xbd\xa0\xe5\xa5\xbd"
        (folder / "keep.txt").write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        return root, digest
    return None, None


def test_real_db_close_reopen_transfer_roundtrip(rw, tmp_path):
    """B15: transfer (text-only, NORMAL save path), close, reopen the SAME
    SQLite DB in a brand-new window: destination owns everything, source
    owns nothing, and the source's structural extent survives (T-1222)."""
    win = rw
    src = win.get_current_category()
    _add_destination(win)
    dst = "PROJB"
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, src)
    win.data["temp_presets"][0] = ""
    win.data.setdefault("silo_last_edited_all", {}).setdefault(src, {})
    win.silo_last_edited = win.data["silo_last_edited_all"][src]
    win.text_area.setPlainText("ROUNDTRIP-LIVE-TEXT")
    win._cache_timer.stop()
    _seed_identity(win, tmp_path, src, with_folder=False)
    assert win.transfer_silo_to_project(0, dst) is True
    # B28: the text-only transfer relies on the normal save lifecycle --
    # a plain close-time save must be enough (no durable= force here).
    assert win.save_data_to_db() is True
    _shutdown(win)

    win2 = _open_again(tmp_path)
    try:
        ds = _read_cat(win2, dst).index("ROUNDTRIP-LIVE-TEXT")
        assert ds >= 0
        assert win2.data["silo_colors"].get(str(ds)) == "#778899"
        assert win2.data["silo_types"].get(str(ds)) == "kanban"
        assert win2.data["silo_project_paths"].get(str(ds)) == "ROUNDTRIP-PATH"
        assert win2.data["silo_links"].get(str(ds)) == "ROUNDTRIP-LINK.txt"
        assert win2.silo_last_edited.get(ds) == 321
        assert win2.data["silo_view_state_all"][dst].get(f"s{ds}") == {"cursor": 12}
        assert ds in win2.data["silo_ticked"]
        assert ds in win2.data["silo_selected"]
        assert win2.data["silo_gaps"] == [ds]
        assert win2.data["silo_gap_names"].get(str(ds)) == "ROUNDTRIP-GAP"
        # the moved text exists exactly once in the destination space
        assert _read_cat(win2, dst).count("ROUNDTRIP-LIVE-TEXT") == 1

        # source project no longer owns the transferred identity
        src_presets = _read_cat(win2, src)
        assert src_presets[0] == ""
        assert win2.data["silo_colors"].get("0") is None
        assert win2.data["silo_types"].get("0") is None
        assert win2.data["silo_project_paths"].get("0") is None
        assert win2.data["silo_links"].get("0") is None
        assert 0 not in win2.silo_last_edited
        assert win2.data["silo_view_state_all"][src].get("s0") != {"cursor": 12}
        assert 0 not in win2.data["silo_ticked"]
        assert 0 not in win2.data["silo_selected"]
        assert not win2.data["silo_gaps"]
        assert win2.data["silo_gap_names"].get("0") is None
        # T-1222: empty source silo existence itself is persisted state --
        # the extent must still cover the source slot
        assert len(src_presets) >= 10
        assert src_presets.count("") >= 1
    finally:
        _shutdown(win2)


def test_real_db_folder_roundtrip_follows_the_bytes(rw, tmp_path, monkeypatch):
    """B16: physical folder + mapping + byte identity survive close/reopen."""
    win = rw
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path / "files"))
    src = win.get_current_category()
    _add_destination(win)
    dst = "PROJB"
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, src)
    win.data["temp_presets"][0] = ""
    root, digest = _seed_identity(win, tmp_path, src, with_folder=True)
    win.text_area.setPlainText("FOLDER-LIVE-TEXT")
    win._cache_timer.stop()
    assert win.transfer_silo_to_project(0, dst) is True
    assert win.save_data_to_db() is True
    _shutdown(win)

    win2 = _open_again(tmp_path)
    try:
        win2._files_root = lambda: str(tmp_path / "files")
        presets = _read_cat(win2, dst)
        ds = presets.index("FOLDER-LIVE-TEXT")
        mapped = win2.data["silo_folders"].get(str(ds))
        assert mapped, "destination must own a folder mapping after reopen"
        located = (tmp_path / "files" / win2._category_files_dir(dst) / mapped)
        assert located.is_dir(), f"mapping must point at the physical folder: {mapped}"
        payload = (located / "keep.txt").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest
        # the source mapping is gone and the old location is empty
        _read_cat(win2, src)
        assert win2.data["silo_folders"].get("0") is None
        old = (tmp_path / "files" / win2._category_files_dir(src) / "assets")
        assert not old.exists()
    finally:
        _shutdown(win2)


def test_real_db_destination_name_collision_is_persistent(
        rw, tmp_path, monkeypatch):
    """B17: a physical 'assets' dir already at the destination must never be
    touched: the incoming folder is renamed deterministically, the mapping
    stores THAT name, and a reopen keeps the renamed mapping."""
    win = rw
    monkeypatch.setattr(win, "_files_root", lambda: str(tmp_path / "files"))
    src = win.get_current_category()
    _add_destination(win)
    dst = "PROJB"
    from fastprompter.core.state import bind_active_category
    bind_active_category(win.data, src)
    win.data["temp_presets"][0] = ""
    root, _ = _seed_identity(win, tmp_path, src, with_folder=True)
    # the destination already owns a DIFFERENT folder named 'assets'
    stranger = (tmp_path / "files" / win._category_files_dir(dst) / "assets")
    stranger.mkdir(parents=True)
    (stranger / "stranger.txt").write_text("STRANGER-BYTES")
    win.text_area.setPlainText("COLLISION-LIVE-TEXT")
    win._cache_timer.stop()
    assert win.transfer_silo_to_project(0, dst) is True
    assert win.save_data_to_db() is True
    _shutdown(win)

    win2 = _open_again(tmp_path)
    try:
        win2._files_root = lambda: str(tmp_path / "files")
        presets = _read_cat(win2, dst)
        ds = presets.index("COLLISION-LIVE-TEXT")
        mapped = win2.data["silo_folders"].get(str(ds))
        assert mapped and mapped != "assets", (
            f"incoming folder must get a non-colliding name, got {mapped!r}")
        incoming = (tmp_path / "files" / win2._category_files_dir(dst) / mapped)
        assert (incoming / "keep.txt").read_bytes().startswith(b"ROUNDTRIP-BYTES")
        # the stranger folder is untouched and separate
        assert (stranger / "stranger.txt").read_text() == "STRANGER-BYTES"
        assert (stranger / "keep.txt").exists() is False
    finally:
        _shutdown(win2)
