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
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_sync_async_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"a_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
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
