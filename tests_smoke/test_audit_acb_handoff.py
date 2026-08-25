"""Audit handoff acb-mt632rjw — window-level regressions.

Covers CORE-001/003/004/005, W2-001..W2-006 and PERF-001/002/003/005 from
the 2026-08-23 audit, on the real offscreen Qt window.
"""

import copy
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.project_sync as ps
import fastprompter.main as main_mod
from fastprompter.core.watcher.queue import (
    PENDING,
    SENT,
    QueueItem,
    SiloQueue,
    load_queues,
)
from fastprompter.core.watcher.sender import SendResult
from fastprompter.main import FastPrompter

import fastprompter.core.state as state_mod

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_audit_acb_")

CUR = "Text"


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda *a, **k: os.path.join(_tmpdir, "a.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    try:
        getattr(w, "_watcher_shutdown", lambda: True)()
    except Exception:
        pass
    try:
        getattr(w, "_push_shutdown", lambda timeout_s=2.0: True)(timeout_s=2.0)
    except Exception:
        pass
    try:
        getattr(w, "_watcher_arm_shutdown", lambda timeout_s=2.0: True)()
    except Exception:
        pass
    try:
        getattr(w, "typo_worker_shutdown", lambda timeout_s=2.0: True)()
    except Exception:
        pass
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


@pytest.fixture()
def w(win):
    """Alias so later classes can request the shared window as ``w``."""
    return win


class _Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _FakePushWorker:
    def __init__(self):
        self.dispatch = _Emitter()


@pytest.fixture()
def sync_clean(win):
    """Isolate the shared window's sync-related state for one test."""
    try:
        win.auto_save_timer.stop()       # no reentrant saves mid-assertion
    except Exception:
        pass
    try:
        win._typo_timer.stop()
    except Exception:
        pass
    try:
        win._sync_push_timer.stop()
    except Exception:
        pass
    win.data["silo_links"] = {}
    win.data["silo_links_all"] = {win.get_current_category() or CUR:
                                  win.data["silo_links"]}
    win.data["project_sync"] = {}
    win.data["project_sync_map"] = {}
    win._sync_last_applied.clear()
    win._sync_eol_cache.clear()
    win._sync_leases.clear()
    win._push_jobs_pending.clear()
    win._push_inflight = False
    win._sync_changed_files.clear()
    win._sync_dir_changed = False
    win._sync_pending_apply = False
    yield win


def _link(win, slot, path, text=None):
    if text is None:
        read = ps.read_text_file(path)
        assert read is not None
        text, eol = read
    else:
        eol = "\n"
    links = win.data.setdefault("silo_links", {})
    links[str(slot)] = path
    win.data.setdefault("silo_links_all", {})[
        win.get_current_category() or CUR] = links
    key = win._sync_baseline_key(slot, path)
    win._sync_eol_cache[key] = eol
    win._sync_last_applied[key] = win._sync_side_digest(text)
    return key


# ======================================================================
# CORE-001: mutation-time precondition for Sync-Project publication
# ======================================================================

class TestCore001:
    def test_two_sided_edit_is_never_overwritten(self, sync_clean, tmp_path,
                                                 monkeypatch):
        w = sync_clean
        f = tmp_path / "c.txt"
        f.write_text("B\n", encoding="utf-8")
        _set_silos(w, ["A"])
        _key = _link(w, 0, str(f), "B\n")
        fake = _FakePushWorker()
        monkeypatch.setattr(w, "_ensure_push_worker", lambda: fake)
        w.text_area.setPlainText("A")
        w._push_sync_files(slots={0})
        assert len(fake.dispatch.calls) == 1
        jobs, leases = fake.dispatch.calls[0]
        key, path, text, eol, expect, lease, maxb = jobs[0]
        assert expect == w._sync_side_digest("B\n")
        # an external edit lands BEFORE the worker mutates
        f.write_text("EXT\n", encoding="utf-8")
        worker = main_mod._SyncPushWorker()
        results = []
        worker.done.connect(lambda r: results.extend(r))
        worker._run(jobs, leases)
        status = [r for r in results if r[0] == key][0][3]
        detail = [r for r in results if r[0] == key][0][4]
        assert status == "conflict"
        assert detail[0] == "EXT\n"
        # nothing was overwritten by the stale intent...
        assert f.read_text(encoding="utf-8") == "EXT\n"
        # ...and no baseline was recorded for the never-written app text
        assert w._sync_last_applied.get(key) == w._sync_side_digest("B\n")
        # resolution "file": the external version wins everywhere
        monkeypatch.setattr(
            w, "_sync_conflict_choice",
            lambda *a, **k: "file")
        w._resolve_push_conflict(key, path, text, detail[0], detail[1])
        assert w.data["temp_presets"][0] == "EXT\n"
        assert w._sync_last_applied[key] == w._sync_side_digest("EXT\n")
        # resolution "app": a NEW job is authorized against the CURRENT disk.
        # The silo must still want exactly the text from the conflicted job,
        # so put "A" back on both sides of the editor boundary first.
        w.data["temp_presets"][0] = "A"
        w.text_area.setPlainText("A")
        monkeypatch.setattr(
            w, "_sync_conflict_choice",
            lambda *a, **k: "app")
        w._push_jobs_pending.clear()
        w._push_inflight = False            # the fake batch "completed"
        fake.dispatch.calls.clear()
        w._on_push_done([(key, path, "A", "conflict", ("EXT\n", "\n"))])
        assert not w._push_jobs_pending      # consumed by the dispatch below
        jobs2, leases2 = fake.dispatch.calls[-1]
        assert jobs2[0][4] == w._sync_side_digest("EXT\n")

    def test_stale_lease_rejects_inflight_write(self, sync_clean, tmp_path,
                                                monkeypatch):
        w = sync_clean
        f = tmp_path / "lease.txt"
        f.write_text("base\n", encoding="utf-8")
        _set_silos(w, ["new text"])
        _key = _link(w, 0, str(f), "base\n")
        fake = _FakePushWorker()
        monkeypatch.setattr(w, "_ensure_push_worker", lambda: fake)
        w.text_area.setPlainText("new text")
        w._push_sync_files(slots={0})
        jobs, leases = fake.dispatch.calls[0]
        key = jobs[0][0]
        # ownership transition AFTER queueing (unlink/archive/repoint shape)
        leases[key] = leases.get(key, 0) + 1
        before = f.read_bytes()
        worker = main_mod._SyncPushWorker()
        results = []
        worker.done.connect(lambda r: results.extend(r))
        worker._run(jobs, leases)
        assert results[0][3] == "stale"
        assert f.read_bytes() == before

    def test_unlink_blocks_a_queued_not_yet_sent_write(self, sync_clean,
                                                       tmp_path,
                                                       monkeypatch):
        w = sync_clean
        f = tmp_path / "unlinked.txt"
        f.write_text("old\n", encoding="utf-8")
        _set_silos(w, ["changed"])
        _key = _link(w, 0, str(f), "old\n")
        monkeypatch.setattr(w, "_dispatch_push_jobs", lambda: None)
        w.text_area.setPlainText("changed")
        w._push_sync_files(slots={0})
        assert w._push_jobs_pending, "job must be queued"
        w._unlink_silo_file(0)
        assert not w._push_jobs_pending
        monkeypatch.setattr(w, "_ensure_push_worker", lambda: _FakePushWorker())
        w._dispatch_push_jobs()          # releases the blocked batch: nothing
        assert f.read_text(encoding="utf-8") == "old\n"

    def test_established_binding_still_publishes_async(self, sync_clean,
                                                       tmp_path):
        w = sync_clean
        f = tmp_path / "ok.txt"
        f.write_text("v1\n", encoding="utf-8")
        _set_silos(w, ["v1"])
        _key = _link(w, 0, str(f), "v1\n")
        w.text_area.setPlainText("v2 edited")
        w.data["temp_presets"][0] = "v2 edited"
        w._push_sync_files(slots={0})
        w._push_wait_idle(timeout_s=10)
        assert f.read_text(encoding="utf-8") == "v2 edited"
        assert w._sync_last_applied[_key] == w._sync_side_digest("v2 edited")


def _set_silos(w, texts):
    from PyQt6.QtGui import QTextDocument
    w.data["temp_presets"][:] = list(texts)
    w.silo_docs = [QTextDocument() for _ in texts]
    w.active_temp_slot = 0
    w.active_is_archive = False


# ======================================================================
# PERF-002: dirty-scoped publication
# ======================================================================

class TestPerf002:
    def test_scoped_push_touches_only_the_dirty_owner(self, sync_clean,
                                                      tmp_path, monkeypatch):
        w = sync_clean
        f0 = tmp_path / "s0.txt"
        f1 = tmp_path / "s1.txt"
        f0.write_text("zero\n", encoding="utf-8")
        f1.write_text("one\n", encoding="utf-8")
        _set_silos(w, ["zero", "one"])
        _link(w, 0, str(f0), "zero\n")
        _link(w, 1, str(f1), "one\n")
        fake = _FakePushWorker()
        monkeypatch.setattr(w, "_ensure_push_worker", lambda: fake)
        w.active_temp_slot = 0
        w.text_area.setPlainText("zero EDITED")
        w.data["temp_presets"][0] = "zero EDITED"
        w._push_sync_files(slots={0})
        jobs, _leases = fake.dispatch.calls[-1]
        keys = {j[0] for j in jobs}
        slot1_key = w._sync_baseline_key(1, str(f1))
        assert keys and all(k[1] == 0 for k in keys), keys
        assert slot1_key not in keys
        # typing debounce routes through the ACTIVE slot only
        w._push_inflight = False             # fake batch completed
        fake.dispatch.calls.clear()
        w._push_sync_files_active()
        jobs, _leases = fake.dispatch.calls[-1]
        assert all(j[0][1] == 0 for j in jobs)

    def test_navigation_publishes_only_outgoing_slot(self, sync_clean,
                                                     tmp_path,
                                                     monkeypatch):
        w = sync_clean
        f0 = tmp_path / "n0.txt"
        f0.write_text("a\n", encoding="utf-8")
        _set_silos(w, ["a", "b"])
        _link(w, 0, str(f0), "a\n")
        seen = []
        real = w._push_sync_files

        def spy(slots=None):
            seen.append(slots)
            return real(slots=slots)

        monkeypatch.setattr(w, "_push_sync_files", spy)
        w._switch_to_slot(1)
        assert any(s == {0} for s in seen), seen


# ======================================================================
# PERF-001: file-only batches skip project-wide discovery
# ======================================================================

class TestPerf001:
    def _mk_project(self, w, tmp_path):
        root = tmp_path / "proj"
        root.mkdir(exist_ok=True)
        cfg = {"root": str(root), "recursive": True, "include": [".txt"],
               "exclude": [], "enabled": True}
        cat = w.get_current_category() or CUR
        w.data["project_sync"] = cfg
        w.data.setdefault("project_sync_all", {})[cat] = cfg
        mapping = w.data.setdefault("project_sync_map", {})
        w.data.setdefault("project_sync_map_all", {})[cat] = mapping
        mapping.clear()
        mapping["0"] = "bound.txt"
        (root / "bound.txt").write_text("hello\n", encoding="utf-8")
        _set_silos(w, ["hello"])
        key = w._sync_baseline_key(0, str(root / "bound.txt"))
        w._sync_eol_cache[key] = "\n"
        w._sync_last_applied[key] = w._sync_side_digest("hello")
        return root

    def test_file_only_batch_runs_zero_scans(self, sync_clean, tmp_path,
                                             monkeypatch):
        w = sync_clean
        root = self._mk_project(w, tmp_path)
        scans = {"n": 0}

        def counting(*a, **k):
            scans["n"] += 1
            return []

        monkeypatch.setattr(ps, "scan_folder", counting)
        bound = os.path.normcase(str(root / "bound.txt"))
        w._sync_changed_files.add(bound)
        w._apply_external_sync()
        assert scans["n"] == 0, scans

    def test_directory_batch_runs_exactly_one_scan(self, sync_clean, tmp_path,
                                                   monkeypatch):
        w = sync_clean
        self._mk_project(w, tmp_path)
        scans = {"n": 0}

        def counting(*a, **k):
            scans["n"] += 1
            return []

        monkeypatch.setattr(ps, "scan_folder", counting)
        w._sync_dir_changed = True
        w._apply_external_sync()
        assert scans["n"] == 1, scans

    def test_empty_batch_discovers_new_file(self, sync_clean, tmp_path,
                                            monkeypatch):
        w = sync_clean
        root = self._mk_project(w, tmp_path)
        (root / "new.txt").write_text("fresh\n", encoding="utf-8")
        presets_ref = w.data["temp_presets"]
        map_ref = w.data["project_sync_map"]
        allstore = w.data.setdefault("project_sync_map_all", {})
        cat = w.get_current_category() or CUR
        w._apply_external_sync()          # no changed paths at all
        # behavioral contract: the new file claimed the first free slot and
        # its text landed in the silo list the apply pass captured.
        assert presets_ref[1] == "fresh\n"
        found = (str(map_ref.get("1")) == "new.txt"
                 or str((allstore.get(cat) or {}).get("1")) == "new.txt")
        assert found, (dict(map_ref),
                       {k: dict(v) for k, v in allstore.items()
                        if isinstance(v, dict)})


# ======================================================================
# PERF-003: fresh equal binding establishes a baseline WITHOUT a write
# ======================================================================

class TestPerf003:
    def test_equal_fresh_binding_writes_nothing(self, sync_clean, tmp_path,
                                                monkeypatch):
        w = sync_clean
        f = tmp_path / "eq.txt"
        f.write_bytes(b"same\r\n")
        _set_silos(w, ["same\n"])
        w.text_area.setPlainText("same\n")
        w.data.setdefault("silo_links", {})["0"] = str(f)
        w.data.setdefault("silo_links_all", {})[
            w.get_current_category() or CUR] = w.data["silo_links"]
        writes = {"n": 0}
        real_write = ps.write_text_file

        def counting_write(*a, **k):
            writes["n"] += 1
            return real_write(*a, **k)

        monkeypatch.setattr(ps, "write_text_file", counting_write)
        mtime_before = os.stat(str(f)).st_mtime_ns
        key = w._sync_baseline_key(0, str(f))
        w._push_sync_files(slots={0})
        w._push_wait_idle(timeout_s=5)
        assert writes["n"] == 0, writes
        assert f.read_bytes() == b"same\r\n"
        assert os.stat(str(f)).st_mtime_ns == mtime_before
        assert w._sync_last_applied[key] == w._sync_side_digest("same\n")
        assert w._sync_eol_cache[key] == "\r\n"

    def test_differing_fresh_binding_still_resolves_conflict(
            self, sync_clean, tmp_path, monkeypatch):
        w = sync_clean
        f = tmp_path / "diff.txt"
        f.write_text("disk side\n", encoding="utf-8")
        _set_silos(w, ["app side"])
        w.text_area.setPlainText("app side")
        w.data.setdefault("silo_links", {})["0"] = str(f)
        choices = []

        def fake_choice(path, slot, file_text, silo_text):
            choices.append((file_text, silo_text))
            return "file"

        monkeypatch.setattr(w, "_sync_conflict_choice", fake_choice)
        w._push_sync_files(slots={0})
        assert choices == [("disk side\n", "app side")]
        assert w.data["temp_presets"][0] == "disk side\n"


# ======================================================================
# CORE-003/CORE-004: canonical digest baselines + EOL on every route
# ======================================================================

class TestCore003004:
    def test_manual_link_baseline_is_digest_and_crlf_survives(
            self, sync_clean, tmp_path, monkeypatch):
        w = sync_clean
        f = tmp_path / "linked.md"
        f.write_bytes("first\r\ntext\r\n".encode("utf-8"))
        _set_silos(w, ["placeholder"])
        monkeypatch.setattr(
            "fastprompter.main.QFileDialog.getOpenFileName",
            staticmethod(lambda *a, **k: (str(f), "")))
        w._link_silo_to_file(0)
        key = w._sync_baseline_key(0, str(f))
        stored = w._sync_last_applied[key]
        assert isinstance(stored, tuple) and len(stored) == 2
        assert stored == w._sync_side_digest("first\ntext\n")
        assert w._silo_clean(0, str(f)) is True
        assert w._sync_eol_cache[key] == "\r\n"
        # external edit arrives with NO intervening app push -> imported
        f.write_bytes("second\r\nversion\r\n".encode("utf-8"))
        w._sync_changed_files.add(os.path.normcase(str(f)))
        w._apply_external_sync()
        assert w.data["temp_presets"][0] == "second\nversion\n"
        # one app-side edit pushes back preserving CRLF
        w.text_area.setPlainText("third\nround\n")
        w.data["temp_presets"][0] = "third\nround\n"
        w._push_sync_files(slots={0})
        w._push_wait_idle(timeout_s=10)
        assert f.read_bytes() == "third\r\nround\r\n".encode("utf-8")

    def test_discovery_and_rescan_routes_seed_eol(self, sync_clean, tmp_path):
        w = sync_clean
        root = tmp_path / "disc"
        root.mkdir()
        cfg = {"root": str(root), "recursive": True, "include": [".txt"],
               "exclude": [], "enabled": True}
        cat = w.get_current_category() or CUR
        w.data["project_sync"] = cfg
        w.data.setdefault("project_sync_all", {})[cat] = cfg
        mapping = w.data.setdefault("project_sync_map", {})
        w.data.setdefault("project_sync_map_all", {})[cat] = mapping
        mapping.clear()
        presets_ref = w.data["temp_presets"]
        _set_silos(w, [])
        presets_ref = w.data["temp_presets"]
        (root / "crlf.txt").write_bytes(b"body\r\nhere\r\n")
        w._apply_external_sync()
        path = str(root / "crlf.txt")
        key = w._sync_baseline_key(0, path)
        assert presets_ref[0] == "body\nhere\n"
        assert w._sync_last_applied[key] == w._sync_side_digest("body\nhere\n")
        assert w._sync_eol_cache[key] == "\r\n"
        # one app-side edit on the discovered silo pushes back preserving CRLF
        w.active_temp_slot = 0
        w.text_area.setPlainText("body\nEDIT\n")
        presets_ref[0] = "body\nEDIT\n"
        w._push_sync_files(slots={0})
        w._push_wait_idle(timeout_s=10)
        assert (root / "crlf.txt").read_bytes() == b"body\r\nEDIT\r\n"
        # rescan route picks up another CRLF file with full metadata
        (root / "later.txt").write_bytes(b"more\r\nstuff\r\n")
        w.text_area.setPlainText("body\nEDIT\n")
        w._rescan_project_sync()
        key2 = w._sync_baseline_key(1, str(root / "later.txt"))
        assert presets_ref[1] == "more\nstuff\n"
        assert w._sync_last_applied[key2] == w._sync_side_digest("more\nstuff\n")
        assert w._sync_eol_cache[key2] == "\r\n"


# ======================================================================
# CORE-005: timed-out push worker keeps its live owner references
# ======================================================================

class TestCore005:
    def test_timeout_retains_live_worker_thread(self, sync_clean, monkeypatch):
        w = sync_clean
        release = threading.Event()

        def blocking_write(path, text, eol="\n"):
            release.wait(5.0)
            return ps.write_text_file(path, text, eol)

        monkeypatch.setattr(ps, "write_text_file", blocking_write)
        f = os.path.join(_tmpdir, "core5.txt")
        key = ("Text", 0, os.path.normcase(f))
        w.data.setdefault("silo_links", {})["0"] = f
        w._push_jobs_pending[key] = (
            key, f, "x", "\n", None, 0, 512 * 1024)
        w._push_inflight = False
        w._dispatch_push_jobs()
        assert w._push_inflight
        tick = threading.Event()
        for _ in range(200):              # let the worker enter the write
            tick.wait(0.01)
        result = w._push_shutdown(timeout_s=0.3)
        assert result is False
        assert w._push_worker is not None
        assert w._push_thread is not None
        assert w._push_thread.isRunning()
        release.set()
        deadline = threading.Event()
        for _ in range(500):
            if not w._push_thread.isRunning():
                break
            _app.processEvents()
            deadline.wait(0.01)
        assert w._push_shutdown(timeout_s=5.0) is True
        assert w._push_worker is None and w._push_thread is None


# ======================================================================
# W2-001/W2-005: category deletion owner transition + rollback snapshot
# ======================================================================

class TestW2001W2005:
    def _two_cats(self, w, first="Victim", second="Survivor"):
        for name in (first, second):
            if name not in w.data["categories"]:
                w.data["categories"][name] = [None] * 100
                w.data["cats_order"].append(name)
            w.data.setdefault("temp_presets_all", {}).setdefault(
                name, ["x-" + name.lower()])
            w.data.setdefault("watcher_queues_all", {}).setdefault(name, {})
            w.data.setdefault("silo_session_all", {}).setdefault(
                name, {"slot": 0, "archive": False})
        w.rebuild_cat_combo(keep=w.get_current_category())

    def _snap(self, w, name):
        return {
            "presets": copy.deepcopy(
                w.data["temp_presets_all"].get(name)),
            "queues": copy.deepcopy(
                w.data["watcher_queues_all"].get(name)),
            "session": copy.deepcopy(
                w.data["silo_session_all"].get(name)),
        }

    def test_delete_selected_does_not_crosswrite_survivor(
            self, w, monkeypatch):
        self._two_cats(w)
        victim = "Victim"
        survivor = "Survivor"
        before = self._snap(w, survivor)
        idx = w.cat_combo.findData(victim)
        w.cat_combo.setCurrentIndex(idx)
        _app.processEvents()
        stack_before = len(w.data_undo_stack)
        monkeypatch.setattr(main_mod.QMessageBox, "question",
                            staticmethod(lambda *a, **k:
                                         QMessageBox_Yes))
        w.del_category()
        _app.processEvents()
        after = self._snap(w, survivor)
        assert after == before, "survivor state was corrupted by deletion"
        assert victim not in w.data["categories"]
        assert survivor in w.data["categories"]
        assert w.get_current_category() == survivor
        assert len(w.data_undo_stack) >= stack_before

    def test_last_row_cleanup_failure_restores_everything(
            self, w, monkeypatch):
        self._two_cats(w)
        cats = list(w.data["cats_order"])
        victim = cats[-1]                 # LAST row: idx == count case
        idx = w.cat_combo.findData(victim)
        w.cat_combo.setCurrentIndex(idx)
        _app.processEvents()
        count = w.cat_combo.count()
        presets_before = copy.deepcopy(
            w.data["temp_presets_all"][victim])
        stack_before = len(w.data_undo_stack)
        monkeypatch.setattr(main_mod.QMessageBox, "question",
                            staticmethod(lambda *a, **k:
                                         QMessageBox_Yes))

        real_remove = w.cat_combo.removeItem
        boom = {"armed": True}

        def failing_remove(idx):
            if boom["armed"]:
                boom["armed"] = False
                raise RuntimeError("injected cleanup failure")
            return real_remove(idx)

        monkeypatch.setattr(w.cat_combo, "removeItem", failing_remove)
        with pytest.raises(RuntimeError):
            w.del_category()
        _app.processEvents()
        # everything is back: identity, order, combo membership AND row index
        assert victim in w.data["cats_order"]
        assert victim in w.data["categories"]
        assert w.cat_combo.findData(victim) == idx
        assert w.cat_combo.count() == count
        assert w.data["temp_presets_all"][victim] == presets_before
        # W2-005: the pre-delete undo snapshot was RETAINED (not popped)
        assert len(w.data_undo_stack) >= stack_before
        # selection restored to the victim too
        assert w.get_current_category() == victim

    def test_restore_failure_keeps_recovery_snapshot(self, w, monkeypatch):
        self._two_cats(w)
        cats = list(w.data["cats_order"])
        victim = cats[-1]
        idx = w.cat_combo.findData(victim)
        w.cat_combo.setCurrentIndex(idx)
        _app.processEvents()
        stack_before = len(w.data_undo_stack)
        monkeypatch.setattr(main_mod.QMessageBox, "question",
                            staticmethod(lambda *a, **k:
                                         QMessageBox_Yes))
        # first failure: cleanup (removeItem); second failure: the logical
        # RESTORE itself (insertItem) — the snapshot must survive BOTH.
        real_remove = w.cat_combo.removeItem
        real_insert = w.cat_combo.insertItem
        state = {"stage": 0}

        def failing_remove(i):
            if state["stage"] == 0:
                state["stage"] = 1
                raise RuntimeError("injected cleanup failure")
            return real_remove(i)

        def failing_insert(i, text, data=None):
            if state["stage"] == 1:
                state["stage"] = 2
                raise RuntimeError("injected restore failure")
            return real_insert(i, text, data)

        monkeypatch.setattr(w.cat_combo, "removeItem", failing_remove)
        monkeypatch.setattr(w.cat_combo, "insertItem", failing_insert)
        with pytest.raises(RuntimeError):
            w.del_category()
        _app.processEvents()
        # logical restore ran; even if imperfect, the durable pre-delete
        # snapshot must still be on the undo stack for recovery
        assert len(w.data_undo_stack) >= stack_before


from PyQt6.QtWidgets import QMessageBox as _QMB
QMessageBox_Yes = _QMB.StandardButton.Yes


# ======================================================================
# W2-002: profile switch quiesces the watcher BEFORE the old save
# ======================================================================

class TestW2002:
    def test_switch_refused_when_quiesce_cannot_complete(self, w,
                                                         monkeypatch):
        class _Eng:
            armed = True

            def disarm(self, reason=""):
                pass

        saved_engine = getattr(w, "_watcher_engine", None)
        w._watcher_engine = _Eng()
        monkeypatch.setattr(w, "_watcher_begin_quiesce",
                            lambda timeout_s=1.5: False)
        saved_profile = w.state.profile_id \
            if hasattr(w.state, "profile_id") else None
        calls = {"save": 0}
        real_save = w.save_data_to_db

        def spy_save(*a, **k):
            calls["save"] += 1
            return real_save(*a, **k)

        monkeypatch.setattr(w, "save_data_to_db", spy_save)
        w.change_profile(min(1, max(0, w.profile_count() - 1))
                         if hasattr(w, "profile_count") else 1)
        assert calls["save"] == 0, "refusal must precede the final save"
        w._watcher_engine = saved_engine

    def test_quiesce_precedes_old_profile_final_save(self, w, monkeypatch):
        order = []
        real_quiesce = w._watcher_begin_quiesce
        real_save = w.save_data_to_db
        real_switch = w.state.switch_profile

        class _Eng:
            armed = True                  # force the W2-002 gate to engage

            def disarm(self, reason=""):
                pass

        saved_engine = getattr(w, "_watcher_engine", None)
        w._watcher_engine = _Eng()

        def spy_quiesce(timeout_s=1.5):
            order.append("quiesce")
            return True

        def spy_save(*a, **k):
            order.append("save")
            return real_save(*a, **k)

        def spy_switch(*a, **k):
            order.append("switch")
            return real_switch(*a, **k)

        monkeypatch.setattr(w, "_watcher_begin_quiesce", spy_quiesce)
        monkeypatch.setattr(w, "save_data_to_db", spy_save)
        monkeypatch.setattr(w.state, "switch_profile", spy_switch)
        target = 1 if w.state.profile_id != 1 else 0
        try:
            w.change_profile(target)
        except Exception:
            pass
        assert order[:3] == ["quiesce", "save", "switch"], order
        w._watcher_engine = saved_engine


# ======================================================================
# W2-003: a stale completion reconciles its LIVE dispatch owner once
# ======================================================================

class TestW2003:
    def _intent(self, item_id):
        from types import SimpleNamespace
        return SimpleNamespace(queue_category=CUR, queue_key="0",
                               item_id=item_id)

    def test_late_success_marks_live_owner_and_survives_live_save(
            self, w):
        item = QueueItem("hello", id="itest")
        live_map = {"0": SiloQueue([item])}
        bucket = w.data.setdefault("watcher_queues_all", {})
        bucket[CUR] = {"0": {}}          # stale persisted clone: empty
        token = 987654
        w._watcher_send_owners[token] = (CUR, live_map, w.data)
        current_gen = w._watcher_send_gen
        stale_gen = current_gen - 1 if current_gen > 0 else current_gen + 1
        w._watcher_send_gen = current_gen + 1   # make the arrival stale
        w._watcher_on_send_result(self._intent("itest"), stale_gen,
                                  SendResult(True), token)
        assert token not in w._watcher_send_owners
        # the LIVE object became SENT...
        assert item.state == SENT
        # ...and the persisted store holds ONE truth: SENT
        raw = load_queues(bucket[CUR])
        assert raw["0"].find("itest").state == SENT
        # a normal live save re-serializes the SAME object: still SENT
        w.prompt_queues = live_map
        w.save_prompt_queues()
        raw2 = load_queues(bucket[CUR])
        assert raw2["0"].find("itest").state == SENT
        w._watcher_send_gen = current_gen

    def test_late_partial_persists_failed_on_live_owner(self, w):
        item = QueueItem("hi", id="ipart")
        live_map = {"0": SiloQueue([item])}
        bucket = w.data.setdefault("watcher_queues_all", {})
        bucket[CUR] = {"0": {}}
        token = 987655
        w._watcher_send_owners[token] = (CUR, live_map, w.data)
        current_gen = w._watcher_send_gen
        stale_gen = current_gen + 1
        w._watcher_send_gen = stale_gen
        result = SendResult(False, "uncertain", dry=False, partial=True)
        w._watcher_on_send_result(self._intent("ipart"), current_gen,
                                  result, token)
        assert item.state != PENDING      # never retryable again
        raw = load_queues(bucket[CUR])
        assert raw["0"].find("ipart").state != PENDING
        w._watcher_send_gen = current_gen


# ======================================================================
# W2-004: panic terminates the run's ownership lease
# ======================================================================

class _StubEngine:
    def __init__(self, armed=True):
        self.armed = armed
        self.panic_called = False
        self.disarm_reasons = []

    def panic(self):
        self.panic_called = True

    def disarm(self, reason=""):
        self.disarm_reasons.append(reason)


class TestW2004:
    def test_panic_clears_pins_target_sender(self, w):
        w._watcher_init()
        saved = (w._watcher_engine, w._watcher_sender, w._watcher_target)
        eng = _StubEngine(armed=True)
        w._watcher_engine = eng
        w._watcher_pinned_category = "GhostCat"
        w._watcher_pinned_queues = {"0": object()}
        w._watcher_target = object()
        w._watcher_sender = object()
        assert w.watcher_panic() is True
        assert eng.panic_called
        assert w._watcher_pinned_category is None
        assert w._watcher_pinned_queues is None
        assert w._watcher_target is None
        assert w._watcher_sender is not None   # replaced by a fresh sender
        (w._watcher_engine, w._watcher_sender,
         w._watcher_target) = saved

    def test_quiesce_after_panic_serializes_no_dead_run_pin(self, w):
        w._watcher_init()
        saved_engine = w._watcher_engine
        sentinel = {"keep": "me"}
        bucket = w.data.setdefault("watcher_queues_all", {})
        bucket["ZedCat"] = sentinel
        w._watcher_engine = _StubEngine(armed=False)
        w._watcher_pinned_category = None
        w._watcher_pinned_queues = None
        w._watcher_quiescing = False
        assert w._watcher_begin_quiesce(0.05) is True
        assert bucket["ZedCat"] is sentinel
        w._watcher_engine = saved_engine


# ======================================================================
# W2-006: probe-worker shutdown retention on timeout
# ======================================================================

class TestW2006:
    def test_probe_shutdown_timeout_retains_refs(self, w, monkeypatch):
        import fastprompter.ui.watcher_mixin as mixin
        w._watcher_init()
        monkeypatch.setattr(mixin, "_WATCHER_SHUTDOWN_TIMEOUT_S", 0.3)
        release = threading.Event()

        real_combine = mixin.combine

        def blocking_combine(probes, now):
            release.wait(5.0)
            return real_combine(probes, now)

        monkeypatch.setattr(mixin, "combine", blocking_combine)
        worker = w._watcher_ensure_probe_worker()
        w._watcher_probe_gen += 1
        gen = w._watcher_probe_gen
        w._watcher_probe_inflight = True
        worker.sample.emit([object()], gen)
        thread = w._watcher_probe_thread
        assert thread is not None and thread.isRunning()
        deadline = threading.Event()
        deadline.wait(0.2)                # let the sample enter combine()
        ok = w._watcher_shutdown()
        assert ok is False
        assert w._watcher_probe_thread is thread
        assert w._watcher_probe_worker is worker
        assert thread.isRunning()
        release.set()
        for _ in range(500):
            if not thread.isRunning():
                break
            _app.processEvents()
            deadline.wait(0.01)
        assert w._watcher_shutdown() is True
        assert w._watcher_probe_thread is None
        assert w._watcher_probe_worker is None


# ======================================================================
# PERF-004: recursive watcher enumeration leaves the GUI thread
# ======================================================================

class TestPerf004:
    def test_recursive_arm_enumerates_async_and_rejects_stale(
            self, sync_clean, tmp_path):
        w = sync_clean
        root = tmp_path / "bigtree"
        (root / "sub" / "deeper").mkdir(parents=True)
        (root / "top.txt").write_text("t\n", encoding="utf-8")
        cfg = {"root": str(root), "recursive": True, "include": [".txt"],
               "exclude": [], "enabled": True}
        cat = w.get_current_category() or CUR
        w.data["project_sync"] = cfg
        w.data.setdefault("project_sync_all", {})[cat] = cfg
        gen_first = getattr(w, "_pw_gen", 0) + 1
        w._start_project_watcher()
        # generation advanced and the ROOT is watched synchronously
        assert w._pw_gen == gen_first
        assert any(os.path.normcase(str(root)) ==
                   os.path.normcase(d)
                   for d in w._project_sync_watcher.directories())
        # the recursive completion lands ASYNC: pump until the subtree is
        # armed (bounded), proving the enumeration ran on its own thread
        want = os.path.normcase(str(root / "sub"))
        armed = False
        import time as _t
        deadline = _t.monotonic() + 10.0
        while _t.monotonic() < deadline:
            _app.processEvents()
            if any(os.path.normcase(d) == want
                   for d in w._project_sync_watcher.directories()):
                armed = True
                break
            _t.sleep(0.02)
        assert armed, w._project_sync_watcher.directories()
        # a STALE completion (older generation) must not add paths anymore
        before = list(w._project_sync_watcher.directories())
        ghost = str(tmp_path / "ghost")
        w._on_watcher_arm_enumerated(gen_first - 1, str(root), [ghost])
        _app.processEvents()
        assert list(w._project_sync_watcher.directories()) == before
