"""Phase-8 (second pass): async/coalesced Sync-to-Disk worker.

Proves:
* the capture call never blocks on a busy/slow worker
* coalescing keeps the NEWEST snapshot; intermediate ones are dropped
* a stale generation can never publish wrong cache state
* a sync-root change cannot redirect an old queued job
* writes land in the captured root, contained and atomic
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from _helpers import junction_ok
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_sync_async_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"a_{profile_id}.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


class _Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _FakeWorker:
    def __init__(self):
        self.dispatch = _Emitter()


@pytest.fixture()
def fake_worker(win, monkeypatch):
    fw = _FakeWorker()
    monkeypatch.setattr(win, "_sync_ensure_worker", lambda: fw)
    return fw


def _setup(win, tmp_path, root=None):
    root = root or str(tmp_path / "root")
    win._sync_init()
    try:
        win._sync_timer.stop()
    except Exception:
        pass
    win._sync_pending = None
    win._sync_busy = False
    win._sync_shutting_down = False
    win.data["sync_path"] = root
    win.data["sync_mode"] = "Silo"
    win.data["active_temp_slot"] = 0
    win.data["temp_presets"][0] = "# t\nv1"
    win._sync_written = {}
    return root


class TestCaptureNeverBlocks:
    def test_busy_worker_does_not_block_the_capture_call(self, win, tmp_path):
        _setup(win, tmp_path)
        win._sync_init()
        win._sync_busy = True          # simulate a slow worker in flight
        t0 = time.monotonic()
        win.sync_to_disk(force=True)   # must return immediately, only queue
        assert time.monotonic() - t0 < 1.0
        assert win._sync_pending is not None
        win._sync_pending = None
        win._sync_busy = False


class TestCoalescing:
    def test_newest_snapshot_wins_and_stale_done_is_dropped(self, win, tmp_path, fake_worker):
        _setup(win, tmp_path)
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()              # snap1 in flight (gen 1)
        assert len(fake_worker.dispatch.calls) == 1
        snap1, gen1 = fake_worker.dispatch.calls[0]

        win.data["temp_presets"][0] = "# t\nv2"   # newer content while busy
        win.sync_to_disk(force=True)              # -> pending = snap2 (gen 2)
        assert win._sync_pending is not None

        # snap1 completes, but its generation is stale
        win._sync_on_done(gen1, snap1, list(snap1["files"]), [])
        assert gen1 != win._sync_gen
        assert win._sync_written == {}, "a stale result must not touch the cache"

        # the newest pending snapshot is dispatched next
        win._sync_dispatch_pending()
        assert len(fake_worker.dispatch.calls) == 2
        snap2, gen2 = fake_worker.dispatch.calls[1]
        assert gen2 == win._sync_gen
        assert list(snap2["files"].values()) == ["# t\nv2"]

        win._sync_on_done(gen2, snap2, list(snap2["files"]), [])
        assert any(v == "# t\nv2" for v in win._sync_written.values())
        win._sync_pending = None
        win._sync_busy = False

    def test_done_after_disarm_is_dropped(self, win, tmp_path, fake_worker):
        _setup(win, tmp_path)
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        snap1, gen1 = fake_worker.dispatch.calls[0]
        win._sync_gen += 1                        # a newer run superseded it
        win._sync_on_done(gen1, snap1, list(snap1["files"]), [])
        assert win._sync_written == {}

    def test_stale_completion_still_drains_newest_pending(self, win, tmp_path, fake_worker):
        """Phase-1 regression: a stale completion must NOT strand the newest
        pending snapshot. gen1 is stale by the time it completes; gen2 was
        captured while busy and must be dispatched BY THE STALE COMPLETION
        itself, not by an external nudge."""
        _setup(win, tmp_path)
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()              # gen1 enters the worker
        snap1, gen1 = fake_worker.dispatch.calls[0]
        assert win._sync_busy is True

        win.data["temp_presets"][0] = "# t\nv2"   # newer content while busy
        win.sync_to_disk(force=True)              # gen2 becomes pending
        assert win._sync_pending is not None
        assert gen1 != win._sync_gen

        # gen1 completes STALE
        win._sync_on_done(gen1, snap1, list(snap1["files"]), [])

        # THE CONTRACT: the stale completion still drains the newest pending
        assert len(fake_worker.dispatch.calls) == 2, \
            "a stale completion must dispatch the newest pending snapshot"
        snap2, gen2 = fake_worker.dispatch.calls[1]
        assert gen2 == win._sync_gen
        assert win._sync_pending is None
        assert win._sync_busy is True             # gen2 is now in flight
        assert list(snap2["files"].values()) == ["# t\nv2"]
        assert win._sync_written == {}, "the stale gen1 result touched no cache"

        win._sync_on_done(gen2, snap2, list(snap2["files"]), [])
        assert any(v == "# t\nv2" for v in win._sync_written.values())
        assert win._sync_pending is None
        assert win._sync_busy is False


class TestRootIsolation:
    def test_old_job_keeps_its_captured_root(self, win, tmp_path, fake_worker):
        root_a = _setup(win, tmp_path, str(tmp_path / "rootA"))
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        snap_a, gen_a = fake_worker.dispatch.calls[0]
        assert snap_a["root"] == root_a
        # snap_a's files point into root_a, never anywhere else
        for dest in snap_a["files"]:
            assert os.path.normcase(dest).startswith(os.path.normcase(root_a))

        root_b = str(tmp_path / "rootB")
        win.data["sync_path"] = root_b
        win.sync_to_disk(force=True)              # root changed while busy
        assert win._sync_pending is not None

        # snap_a completes but its generation is stale (root B superseded it)
        win._sync_on_done(gen_a, snap_a, list(snap_a["files"]), [])
        assert gen_a != win._sync_gen
        assert win._sync_written == {}, "a stale job must not update the cache"

        # the pending root-B snapshot is dispatched next and targets root_b
        win._sync_dispatch_pending()
        assert len(fake_worker.dispatch.calls) == 2
        snap_b, gen_b = fake_worker.dispatch.calls[1]
        assert snap_b["root"] == root_b
        assert gen_b == win._sync_gen
        for dest in snap_b["files"]:
            assert os.path.normcase(dest).startswith(os.path.normcase(root_b))
        win._sync_pending = None
        win._sync_busy = False

    def test_real_worker_completion_returns_to_gui_thread(self, win, tmp_path, monkeypatch):
        from fastprompter import main as m

        _setup(win, tmp_path)
        worker_threads = []
        completion_threads = []
        real_write = m._sync_mechanical_write
        real_done = win._sync_on_done

        def record_write(snapshot, lock_timeout_s=None):
            worker_threads.append(QThread.currentThread())
            return real_write(snapshot, lock_timeout_s)

        def record_done(*args):
            completion_threads.append(QThread.currentThread())
            return real_done(*args)

        monkeypatch.setattr(m, "_sync_mechanical_write", record_write)
        monkeypatch.setattr(win, "_sync_on_done", record_done)
        win._sync_done_worker = None
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            _app.processEvents()
            if not win._sync_busy:
                break
            time.sleep(0.01)

        assert worker_threads == [m._SYNC_SHARED_THREAD]
        assert completion_threads == [_app.thread()]

    def test_real_worker_writes_each_root(self, win, tmp_path):
        import time as _t
        root_a = _setup(win, tmp_path, str(tmp_path / "rootA"))
        win.sync_to_disk(force=True)
        deadline = _t.monotonic() + 5
        while _t.monotonic() < deadline:
            _app.processEvents()
            if win._sync_written:
                break
            _t.sleep(0.01)
        assert list(os.walk(root_a))[0][2] or any(
            f.endswith(".md") for _, _, fs in os.walk(root_a) for f in fs)

        root_b = str(tmp_path / "rootB")
        win.data["sync_path"] = root_b
        win._sync_written = {}
        win.sync_to_disk(force=True)
        deadline = _t.monotonic() + 5
        while _t.monotonic() < deadline:
            _app.processEvents()
            if win._sync_written:
                break
            _t.sleep(0.01)
        files_b = [f for _, _, fs in os.walk(root_b) for f in fs]
        assert any(f.endswith(".md") for f in files_b)
        # no temp leftovers anywhere
        for r in (root_a, root_b):
            assert not any(f.endswith(".tmp") for _, _, fs in os.walk(r) for f in fs)
        win.data["sync_path"] = ""
        win.data["sync_mode"] = "Off"


class TestShutdownFlush:
    """Phase-2: a normal shutdown must flush the final mirror, not discard it."""

    def _mirror_text(self, root):
        texts = []
        for base, _d, files in os.walk(root):
            for f in files:
                if f.endswith(".md"):
                    texts.append(open(os.path.join(base, f), encoding="utf-8").read())
        return "\n".join(texts)

    def test_edit_then_immediate_shutdown_flushes_mirror(self, win, tmp_path):
        """Test A: edit -> quit immediately (before the debounce fires) ->
        the final mirror still contains the edit."""
        root = _setup(win, tmp_path)
        win.text_area.setPlainText("# t\nfinal edit")   # the editor is the save source
        win.data["temp_presets"][0] = "# t\nfinal edit"  # belt-and-braces: the capture
        win.save_data_to_db(force=True)          # queues sync on the debounce
        assert win.data["temp_presets"][0] == "# t\nfinal edit", (
            f"capture source wiped before shutdown: {win.data['temp_presets'][:3]!r}"
        )
        win._sync_shutdown(timeout_s=10)         # immediate close
        if "# t\nfinal edit" not in self._mirror_text(root):
            _diag = ("sync_path=%r sync_mode=%r slot=%r presets=%r "
                     "busy=%r pending=%r gen=%r shutting=%r")
            raise AssertionError(
                _diag % (win.data.get("sync_path"), win.data.get("sync_mode"),
                         win.active_temp_slot, win.data.get("temp_presets"),
                         getattr(win, "_sync_busy", None),
                         getattr(win, "_sync_pending", None),
                         getattr(win, "_sync_gen", None),
                         getattr(win, "_sync_shutting_down", None)))
        assert "# t\nfinal edit" in self._mirror_text(root)

    def test_shutdown_with_pending_flushes_newest(self, win, tmp_path):
        """Test B: newer content queued behind an older job -> shutdown
        coalesces and flushes the NEWEST content."""
        root = _setup(win, tmp_path)
        win.data["temp_presets"][0] = "# t\nnewest"
        win.sync_to_disk(force=True)             # pending on the debounce
        win._sync_shutdown(timeout_s=5)
        assert "# t\nnewest" in self._mirror_text(root)

    def test_shutdown_with_no_pending_returns_cleanly(self, win, tmp_path):
        """Test C: nothing to mirror -> shutdown returns quickly and cleanly."""
        _setup(win, tmp_path)
        win.data["sync_path"] = ""
        win.data["sync_mode"] = "Off"
        t0 = time.monotonic()
        win._sync_shutdown(timeout_s=0.5)
        assert time.monotonic() - t0 <= 6.0
        assert win._sync_pending is None and win._sync_busy is False

    def test_shutdown_timeout_is_bounded(self, win, tmp_path, fake_worker):
        """Test E: a busy/hung worker must not block shutdown past the bound."""
        _setup(win, tmp_path)
        win.data["temp_presets"][0] = "# t\nstuck"
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()             # 'in flight' (fake never completes)
        assert win._sync_busy is True
        t0 = time.monotonic()
        win._sync_shutdown(timeout_s=0.2)
        assert time.monotonic() - t0 <= 6.0       # bounded, not a hang
        assert win._sync_pending is None
        assert win._sync_busy is True, "timeout must not falsify physical idleness"
        # the real worker thread is still usable for the next test
        win._sync_inflight_gen = 0
        win._sync_shutting_down = False

    def test_global_shutdown_is_bounded_and_explicit(self, win):
        """Test F: the process-wide worker has an explicit bounded shutdown.

        The shutdown hook must stop the shared QThread (no longer running),
        and a later dispatch must recreate a fresh worker. Teardown safety is
        pinned by the sync-teardown suite; this is the in-process contract."""
        from fastprompter import main as m

        _setup(win, None, root=_tmp_path_for(win))
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        assert m._SYNC_SHARED_THREAD is not None
        t0 = time.monotonic()
        m.sync_shutdown_global()
        assert time.monotonic() - t0 <= 6.0
        assert m._SYNC_SHARED_THREAD is None, \
            "the globals are nulled so a fresh worker can spawn"
        # the retired wrapper keeps the stopped thread alive for teardown
        assert m._RETIRED_WORKERS, "the shutdown must retire the worker"
        _, retired_thread = m._RETIRED_WORKERS[-1]
        assert retired_thread.isRunning() is False, \
            "the shutdown hook must stop the shared QThread"

        # the window still believes a job was in flight; clear it so a fresh
        # dispatch can spawn the recreated worker
        win._sync_pending = None
        win._sync_busy = False
        win._sync_written = {}
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _app.processEvents()
            if win._sync_written:
                break
            time.sleep(0.01)
        assert win._sync_written
        win._sync_pending = None
        win._sync_busy = False


def _tmp_path_for(win):
    import tempfile
    return tempfile.mkdtemp(prefix="fastprompter_gshutdown_")


class TestWorkerReuseAfterShutdown:
    def test_worker_recovers_after_shutdown(self, win, tmp_path):
        """After a shutdown flush, a new sync on a new window state works."""
        _setup(win, tmp_path)
        win._sync_shutdown(timeout_s=0.5)        # retire this window's activity
        win._sync_shutting_down = False
        win._sync_written = {}
        win.data["temp_presets"][0] = "# t\nreborn"
        win.sync_to_disk(force=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _app.processEvents()
            if win._sync_written:
                break
            time.sleep(0.01)
        assert any(v == "# t\nreborn" for v in win._sync_written.values())


@pytest.mark.skipif(not junction_ok(), reason="cannot create junctions/symlinks")
class TestWorkerReparseContainment:
    """Phase-6: the sync worker revalidates every destination against the
    captured root at MUTATION time — a junction swapped in after capture must
    not redirect the write outside the root."""

    def test_junction_swapped_after_capture_is_rejected(self):
        from fastprompter.main import _SyncWorker
        from fastprompter.utils.path_safety import capture_resolved_root

        results = []
        worker = _SyncWorker()
        worker.done.connect(
            lambda gen, snap, written, errors: results.append((written, errors)))

        root = tempfile.mkdtemp()
        outside = tempfile.mkdtemp()
        cat = os.path.join(root, "cat")             # not a dir yet
        dest = os.path.join(cat, "01_t.md")         # capture-time lexical dest

        # the junction appears AFTER the snapshot was conceptually captured
        os.symlink(outside, cat, target_is_directory=True)

        worker._run({"root": root, "root_identity": capture_resolved_root(root),
                     "files": {dest: "# t\nbody"}}, 1)

        assert results, "the worker must report the outcome"
        written, errors = results[0]
        assert written == []
        assert errors and "captured root" in errors[0][1]
        assert not os.path.exists(os.path.join(outside, "01_t.md")), \
            "the write must not land outside the root"
        assert not os.path.exists(dest)

    def test_ordinary_nested_destination_writes(self):
        from fastprompter.main import _SyncWorker
        from fastprompter.utils.path_safety import capture_resolved_root

        results = []
        worker = _SyncWorker()
        worker.done.connect(
            lambda gen, snap, written, errors: results.append((written, errors)))

        root = tempfile.mkdtemp()
        dest = os.path.join(root, "cat", "01_t.md")
        worker._run({"root": root, "root_identity": capture_resolved_root(root),
                     "files": {dest: "# t\nbody"}}, 1)

        written, errors = results[0]
        assert errors == []
        assert dest in written
        assert open(dest, encoding="utf-8").read() == "# t\nbody"
        import shutil as _sh
        _sh.rmtree(root)


class TestProfileLifecycle:
    """Phase-10: a profile switch retires the old profile's in-flight sync;
    its stale result cannot update the new profile's cache or generation."""

    def test_profile_switch_makes_old_generation_stale(self, win, tmp_path, fake_worker):
        root = _setup(win, tmp_path)
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        snap_a, gen_a = fake_worker.dispatch.calls[0]
        assert win._sync_busy is True

        win._sync_on_profile_change()       # profile A -> B while A in flight
        assert gen_a != win._sync_gen
        assert win._sync_pending is None

        win._sync_on_done(gen_a, snap_a, list(snap_a["files"]), [])
        assert win._sync_written == {}, "A's stale result must not touch the cache"
        assert win._sync_pending is None
        assert win._sync_busy is False

        # B's first mirror is NOT skipped by A's cache (it was cleared)
        win.sync_to_disk(force=True)
        win._sync_dispatch_pending()
        snap_b, gen_b = fake_worker.dispatch.calls[-1]
        assert gen_b == win._sync_gen
        assert snap_b["root"] == root
        win._sync_on_done(gen_b, snap_b, list(snap_b["files"]), [])
        assert any(v == "# t\nv1" for v in win._sync_written.values())
        win._sync_pending = None
        win._sync_busy = False
