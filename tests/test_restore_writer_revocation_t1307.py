"""W2-001 (audit/12, SRC-041 R004): restore establishes a MONOTONIC
external-writer boundary.

Two writer families used to cross the restore boundary:

* the one-way mirror: ``_sync_mechanical_write`` re-registered an already
  issued snapshot, so a revoked pre-restore snapshot repopulated its own
  destination ownership with the OLD sequence and published stale RAM;
* the Sync-Project push: ``_suppress`` was set OUTSIDE the physical mutation
  gate, so a worker already inside its critical section could pass the check
  and still write.

These regressions are deterministic: thread pauses are explicit events, and
every physical write is counted. They prove the epoch/barrier behaviour, not
timing luck.
"""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import fastprompter.main as main_mod
from fastprompter.core import project_sync as ps
from fastprompter.utils import path_safety
from fastprompter.utils.path_safety import capture_resolved_root

_APP = QApplication.instance() or QApplication([])


def _issue(snapshot):
    return main_mod._sync_register_snapshot(snapshot)


def _snapshot(tmp_path, dest, text):
    return {
        "files": {dest: text},
        "root": str(tmp_path),
        "root_identity": capture_resolved_root(str(tmp_path)),
        "_write_seq": None,
    }


def _key(dest):
    return os.path.normcase(os.path.abspath(dest))


# ----------------------------------------------------------------- one-way
class TestOneWayMirrorEpoch:
    def test_executed_after_revoke_writes_nothing_and_never_re_registers(
            self, tmp_path):
        dest = str(tmp_path / "mirror" / "silo.md")
        snap = _issue(_snapshot(tmp_path, dest, "STALE"))

        main_mod._sync_revoke_all()

        written, errors = main_mod._sync_mechanical_write(snap)
        assert written == []
        assert not os.path.exists(dest)
        assert _key(dest) not in main_mod._SYNC_LATEST_REQUESTED

        # Re-issuing the old snapshot must NOT give it ownership back.
        main_mod._sync_register_snapshot(snap)
        assert _key(dest) not in main_mod._SYNC_LATEST_REQUESTED
        written, _ = main_mod._sync_mechanical_write(snap)
        assert written == []
        assert not os.path.exists(dest)

    def test_paused_before_final_replace_is_refused_after_revoke(
            self, tmp_path, monkeypatch):
        dest = str(tmp_path / "mirror" / "silo.md")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write("DISK")

        snap = _issue(_snapshot(tmp_path, dest, "STALE"))
        entered = threading.Event()
        release = threading.Event()
        real_unique = path_safety.unique_temp_path

        def paused_unique(target, tag="fp"):
            entered.set()
            assert release.wait(5.0)
            return real_unique(target, tag)

        monkeypatch.setattr(path_safety, "unique_temp_path", paused_unique)
        result = {}

        def run():
            result["written"], result["errors"] = \
                main_mod._sync_mechanical_write(snap)

        worker = threading.Thread(target=run)
        worker.start()
        assert entered.wait(5.0)

        # Revoke while the writer is paused after its pre-check; the pause is
        # BEFORE the final in-lock replace section, so nothing may publish.
        main_mod._sync_revoke_all()
        release.set()
        worker.join(5.0)

        assert result["written"] == []
        with open(dest, encoding="utf-8") as fh:
            assert fh.read() == "DISK"
        leftovers = [n for n in os.listdir(os.path.dirname(dest))
                     if n.startswith("silo.md.")]
        assert leftovers == [], "the owned temp must be removed"

    def test_repeated_revoke_is_monotonic_and_idempotent(self, tmp_path):
        dest = str(tmp_path / "mirror" / "silo.md")
        old = _issue(_snapshot(tmp_path, dest, "OLD"))
        main_mod._sync_revoke_all()
        epoch_after_first = main_mod._SYNC_EPOCH
        main_mod._sync_revoke_all()
        assert main_mod._SYNC_EPOCH == epoch_after_first + 1

        # A snapshot issued AFTER the revocation is current and publishes.
        fresh = _issue(_snapshot(tmp_path, dest, "FRESH"))
        written, errors = main_mod._sync_mechanical_write(fresh)
        assert written == [dest]
        assert not errors

        # The old one still cannot, and revoking again changes nothing for it.
        main_mod._sync_revoke_all()
        written, _ = main_mod._sync_mechanical_write(old)
        assert written == []

    def test_restore_barrier_waits_for_in_flight_replace(self, tmp_path,
                                                         monkeypatch):
        """A writer already inside the final replace section FINISHES before
        the barrier returns (it held the lock first); nothing after it may."""
        dest = str(tmp_path / "mirror" / "silo.md")
        snap = _issue(_snapshot(tmp_path, dest, "PRE-RESTORE"))
        entered = threading.Event()
        release = threading.Event()
        real_replace = os.replace

        def slow_replace(src, dst):
            entered.set()
            assert release.wait(5.0)
            return real_replace(src, dst)

        monkeypatch.setattr(main_mod.os, "replace", slow_replace)
        result = {}

        def run():
            result["written"], _ = main_mod._sync_mechanical_write(snap)

        writer = threading.Thread(target=run)
        writer.start()
        assert entered.wait(5.0)

        barrier_done = threading.Event()

        def barrier():
            main_mod._sync_revoke_all()
            barrier_done.set()

        barrier_thread = threading.Thread(target=barrier)
        barrier_thread.start()
        # The barrier must be blocked behind the in-flight replace section.
        assert not barrier_done.wait(0.2)

        release.set()
        writer.join(5.0)
        barrier_thread.join(5.0)

        assert result["written"] == [dest]
        assert barrier_done.is_set()
        # And the revoked snapshot may not publish again afterwards.
        assert main_mod._sync_mechanical_write(snap)[0] == []


# ------------------------------------------------------------- Sync-Project
def _job(key, path, text, lease, expect, had_bom=False):
    return (key, path, text, "\n", expect, lease, 10_000_000, had_bom)


def _worker_with_recorder():
    worker = main_mod._SyncPushWorker()
    results = []
    # Direct connection: the test calls ``_run`` from plain threads with no Qt
    # event loop, and the recorder must fire synchronously with the emit.
    worker.done.connect(results.append, Qt.ConnectionType.DirectConnection)
    return worker, results


def _fake_owner(worker, leases, gate, pending=None):
    import types
    owner = types.SimpleNamespace(
        _push_worker=worker,
        _sync_leases=leases,
        _sync_commit_gate=gate,
        _push_jobs_pending=dict(pending or {}),
    )
    owner._establish_sync_writer_barrier = lambda: (
        main_mod.FastPrompter._establish_sync_writer_barrier(owner))
    owner._resume_sync_push_after_restore_refusal = lambda: (
        main_mod.FastPrompter
        ._resume_sync_push_after_restore_refusal(owner))
    return owner


class TestSyncPushBarrier:
    def test_job_paused_before_gate_is_stale_after_barrier(
            self, tmp_path, monkeypatch):
        path = str(tmp_path / "linked.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("OLD")
        old_digest = main_mod.FastPrompter._sync_side_digest("OLD")

        worker, results = _worker_with_recorder()
        leases = {"K": 0}
        gate = threading.Lock()
        owner = _fake_owner(worker, leases, gate)
        job = _job("K", path, "NEW", leases["K"], old_digest)

        entered = threading.Event()
        release = threading.Event()
        real_read = ps.read_text_file

        def paused_read(p, max_bytes):
            entered.set()
            assert release.wait(5.0)
            return real_read(p, max_bytes)

        monkeypatch.setattr(ps, "read_text_file", paused_read)
        writes = []
        real_write = ps.write_text_file
        monkeypatch.setattr(
            ps, "write_text_file",
            lambda *a, **k: (writes.append(a[0]), real_write(*a, **k))[1])

        thread = threading.Thread(target=worker._run,
                                  args=([job], leases, gate))
        thread.start()
        assert entered.wait(5.0)

        # The barrier runs while the worker is paused BEFORE its gate.
        owner._establish_sync_writer_barrier()
        assert worker._suppress is True

        release.set()
        thread.join(5.0)

        assert results and results[-1][0][3] == "stale"
        assert writes == []
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "OLD"

    def test_worker_inside_gate_finishes_then_future_publication_revoked(
            self, tmp_path, monkeypatch):
        path = str(tmp_path / "linked.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("OLD")
        old_digest = main_mod.FastPrompter._sync_side_digest("OLD")

        worker, results = _worker_with_recorder()
        leases = {"K": 0}
        gate = threading.Lock()
        owner = _fake_owner(worker, leases, gate)
        job = _job("K", path, "NEW", leases["K"], old_digest)

        entered = threading.Event()
        release = threading.Event()
        real_write = ps.write_text_file
        writes = []

        def paused_write(*a, **k):
            writes.append(a[0])
            entered.set()
            assert release.wait(5.0)
            return real_write(*a, **k)

        monkeypatch.setattr(ps, "write_text_file", paused_write)

        thread = threading.Thread(target=worker._run,
                                  args=([job], leases, gate))
        thread.start()
        assert entered.wait(5.0)

        barrier_done = threading.Event()

        def barrier():
            owner._establish_sync_writer_barrier()
            barrier_done.set()

        barrier_thread = threading.Thread(target=barrier)
        barrier_thread.start()
        # The barrier waits for the writer inside the physical section.
        assert not barrier_done.wait(0.2)

        release.set()
        thread.join(5.0)
        barrier_thread.join(5.0)

        assert barrier_done.is_set()
        assert writes == [path]
        assert results and results[-1][0][3] == "ok"

        # A second pre-restore job with the OLD lease is now stale: no write.
        before = list(writes)
        worker._run([job], leases, gate)
        assert results[-1][0][3] == "stale"
        assert writes == before

    def test_missing_target_recreation_branch_is_revoked(
            self, tmp_path, monkeypatch):
        path = str(tmp_path / "linked.txt")  # does NOT exist
        worker, results = _worker_with_recorder()
        leases = {"K": 0}
        gate = threading.Lock()
        owner = _fake_owner(worker, leases, gate)
        job = _job("K", path, "TEXT", leases["K"], None)

        owner._establish_sync_writer_barrier()
        worker._run([job], leases, gate)
        assert results[-1][0][3] == "stale"
        assert not os.path.exists(path)

        # Refused restore: reopen the live runtime, but the OLD job stays
        # revoked; only a FRESH capture (new lease) may publish.
        owner._resume_sync_push_after_restore_refusal()
        assert worker._suppress is False
        worker._run([job], leases, gate)
        assert results[-1][0][3] == "stale"
        assert not os.path.exists(path)

        fresh = _job("K", path, "TEXT", leases["K"], None)
        worker._run([fresh], leases, gate)
        assert results[-1][0][3] == "ok"
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "TEXT"

    def test_existing_target_replacement_branch_is_revoked(
            self, tmp_path, monkeypatch):
        path = str(tmp_path / "linked.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("OLD")
        old_digest = main_mod.FastPrompter._sync_side_digest("OLD")
        worker, results = _worker_with_recorder()
        leases = {"K": 0}
        gate = threading.Lock()
        owner = _fake_owner(worker, leases, gate)
        job = _job("K", path, "NEW", leases["K"], old_digest)

        owner._establish_sync_writer_barrier()
        worker._run([job], leases, gate)
        assert results[-1][0][3] == "stale"
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "OLD"

        owner._resume_sync_push_after_restore_refusal()
        fresh = _job("K", path, "NEW", leases["K"], old_digest)
        worker._run([fresh], leases, gate)
        assert results[-1][0][3] == "ok"
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "NEW"

    def test_barrier_drops_pending_jobs_and_bumps_every_lease(
            self, tmp_path):
        path = str(tmp_path / "linked.txt")
        worker, _results = _worker_with_recorder()
        leases = {"A": 3, "B": 7}
        gate = threading.Lock()
        job = _job("A", path, "TEXT", 3, None)
        owner = _fake_owner(worker, leases, gate, pending={"A": job})
        lease_before = dict(leases)

        owner._establish_sync_writer_barrier()

        assert owner._push_jobs_pending == {}
        assert leases == {k: v + 1 for k, v in lease_before.items()}
        assert worker._suppress is True
