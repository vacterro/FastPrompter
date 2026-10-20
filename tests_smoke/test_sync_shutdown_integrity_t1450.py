"""T-1450: Sync-Project push shutdown integrity + CORE-005 publication barrier.

Defect classes eliminated:
* FALSE_CLEAN_SHUTDOWN — `_push_shutdown` reported True whenever the worker
  thread was absent/stopped, BEFORE any pending/in-flight logical work was
  validated (main.py early-return branch).
* UNPROVABLE_TEST_BARRIER — the old CORE-005 test patched
  `ps.write_text_file`, which is not on the worker's publication path
  (`_SyncPushWorker._run` publishes via `ps.compare_and_publish_text`).

Wave-1 red controls (B/C/D) fail against the unmodified baseline; E/F/G are
green controls proving already-correct paths stay correct. Every case emits a
JSON state line (run pytest with `-s`) so the before/after matrix is
machine-comparable.
"""

import inspect
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.project_sync as ps
from fastprompter import main as main_mod

_app = QApplication.instance() or QApplication([])

CUR = "Text"
# One bounded wall-clock budget for every blocking barrier in this module.
BARRIER_S = 10.0


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


@pytest.fixture()
def sync_win(win):
    """Isolate the shared window's Sync-Project push state for one test."""
    for attr in ("auto_save_timer", "_typo_timer", "_sync_push_timer"):
        timer = getattr(win, attr, None)
        try:
            timer.stop()
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
    win._restore_stale_memory = False
    # A previous test must never leak a live push thread into this one.
    if win._push_thread is not None:
        try:
            win._push_shutdown(timeout_s=5.0)
        except Exception:
            pass
        if win._push_thread is not None and win._push_thread.isRunning():
            win._push_thread.quit()
            win._push_thread.wait(2000)
    yield win


def _state(w, path):
    """Machine-comparable shutdown-state snapshot for one case."""
    thread = w._push_thread
    return {
        "pending": len(w._push_jobs_pending),
        "inflight": bool(w._push_inflight),
        "worker": w._push_worker is not None,
        "thread_running": bool(thread is not None and thread.isRunning()),
        "dest_exists": os.path.exists(path),
        "dest_text": (open(path, encoding="utf-8").read()
                      if os.path.exists(path) else None),
    }


def _emit(case, res, before, after):
    print("T1450-STATE " + json.dumps(
        {"case": case, "shutdown_return": res, "before": before,
         "after": after}, sort_keys=True))


def _enqueue(w, path, text):
    """Queue one real 8-field job for ``path`` and return its key."""
    cat = w.get_current_category() or CUR
    key = (cat, 0, os.path.normcase(path))
    expect = None
    if os.path.exists(path):
        cur = ps.read_text_file_with_identity(path, 512 * 1024)
        if cur is not None:
            expect = w._sync_side_digest(cur[0])
    w.data["silo_links"]["0"] = path
    w._push_jobs_pending[key] = (
        key, path, text, "\n", expect, 0, 512 * 1024, False)
    return key


class _BlockPublish:
    """Deterministic barrier on the REAL publication primitive.

    Wraps the original ``ps.compare_and_publish_text`` (captured BEFORE the
    patch, so the wrapper can never recurse): the worker thread sets
    ``entered`` when it reaches the actual publication call and blocks until
    ``release`` — or the bounded BARRIER_S deadline — is reached.
    """

    def __init__(self, monkeypatch):
        self.entered = threading.Event()
        self.release = threading.Event()
        self._orig = ps.compare_and_publish_text

        def _blocking(*args, **kwargs):
            self.entered.set()
            self.release.wait(BARRIER_S)
            return self._orig(*args, **kwargs)

        monkeypatch.setattr(ps, "compare_and_publish_text", _blocking)

    def wait_entered(self):
        assert self.entered.wait(BARRIER_S), \
            "worker never entered compare_and_publish_text"

    def unblock(self):
        self.release.set()


def _force_idle(w, timeout_s=5.0):
    """Teardown guard: release is caller-set; pump then retire if possible."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if not w._push_inflight and not w._push_jobs_pending:
            break
        time.sleep(0.01)
    if w._push_thread is not None and w._push_thread.isRunning():
        try:
            w._push_shutdown(timeout_s=timeout_s)
        except Exception:
            pass
    if w._push_thread is not None and w._push_thread.isRunning():
        w._push_thread.quit()
        w._push_thread.wait(2000)


# ======================================================================
# Case A — old CORE-005 interception mismatch, positively demonstrated
# ======================================================================

class TestCaseAInterception:
    def test_write_text_file_is_not_on_the_publication_path(
            self, sync_win, tmp_path, monkeypatch):
        """The old test patched ``ps.write_text_file``; the worker publishes
        through ``ps.compare_and_publish_text``. Prove the dead interception:
        the worker never calls the unconditional writer itself, so an
        interception placed there never sees a worker publication — the
        destination is physically written through the conditional gate
        regardless, and that gate still runs when patched."""
        w = sync_win
        f = str(tmp_path / "case_a.txt")
        calls = {"compare_and_publish": 0}
        real_cap = ps.compare_and_publish_text

        def counting_cap(*a, **k):
            calls["compare_and_publish"] += 1
            return real_cap(*a, **k)

        monkeypatch.setattr(ps, "compare_and_publish_text", counting_cap)
        _enqueue(w, f, "case-a")
        w._dispatch_push_jobs()
        assert w._push_wait_idle(timeout_s=BARRIER_S) is True
        _emit("A-interception", None, {"dest": None},
              {"calls": dict(calls),
               "dest_text": open(f, encoding="utf-8").read()})
        # ps.write_text_file is only the atomic replace step INSIDE the
        # conditional gate; the worker itself never calls it, which is what
        # made the old write_text_file-level interception blind.
        worker_src = inspect.getsource(main_mod._SyncPushWorker._run)
        assert "ps.write_text_file(" not in worker_src
        assert "compare_and_publish_text" in worker_src
        assert calls["compare_and_publish"] >= 1, \
            "no publication happened at all"
        assert open(f, encoding="utf-8").read() == "case-a"


# ======================================================================
# Case B — pending queue, NO worker thread (red on baseline)
# ======================================================================

class TestCaseBPendingNoWorker:
    def test_pending_without_worker_never_reports_clean(
            self, sync_win, tmp_path):
        w = sync_win
        f = str(tmp_path / "case_b.txt")
        _enqueue(w, f, "case-b-newest")
        before = _state(w, f)
        res = w._push_shutdown(timeout_s=BARRIER_S)
        after = _state(w, f)
        _emit("B-pending-no-worker", res, before, after)
        if res is True:
            # Clean report requires the authorized job to be PHYSICALLY done.
            assert after["pending"] == 0
            assert after["dest_exists"] and after["dest_text"] == "case-b-newest"
        else:
            # Refusal must preserve every pending job, never drop state.
            assert before["pending"] == after["pending"] == 1
            assert not after["dest_exists"]
        assert w._push_inflight is False


# ======================================================================
# Case C — pending queue, thread already STOPPED (red on baseline)
# ======================================================================

class TestCaseCStoppedThreadPending:
    def test_stopped_thread_with_pending_recovers_or_refuses(
            self, sync_win, tmp_path):
        w = sync_win
        f = str(tmp_path / "case_c.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("old")
        w._ensure_push_worker()
        w._push_thread.quit()
        assert w._push_thread.wait(5000)
        assert not w._push_thread.isRunning()
        _enqueue(w, f, "case-c-newest")
        before = _state(w, f)
        res = w._push_shutdown(timeout_s=BARRIER_S)
        after = _state(w, f)
        _emit("C-stopped-thread-pending", res, before, after)
        if res is True:
            assert after["pending"] == 0
            assert after["dest_text"] == "case-c-newest"
            assert w._push_thread is None and w._push_worker is None
        else:
            assert before["pending"] == after["pending"] == 1
            assert after["dest_text"] == "old"


# ======================================================================
# Case D — unresolved in-flight flag, thread STOPPED (red on baseline)
# ======================================================================

class TestCaseDInflightStoppedThread:
    def test_inflight_with_stopped_thread_never_claims_clean(
            self, sync_win, tmp_path):
        w = sync_win
        f = str(tmp_path / "case_d.txt")
        w._ensure_push_worker()
        w._push_thread.quit()
        assert w._push_thread.wait(5000)
        assert not w._push_thread.isRunning()
        # Simulate a batch whose physical work may or may not have finished:
        # the GUI completion callback never arrived and the thread is gone.
        w._push_inflight = True
        before = _state(w, f)
        res = w._push_shutdown(timeout_s=3.0)
        after = _state(w, f)
        _emit("D-inflight-stopped-thread", res, before, after)
        assert res is False, \
            "stopped thread was accepted as proof of logical completion"
        # Ownership retained — never dropped while state is unresolved.
        assert w._push_worker is not None


# ======================================================================
# Case E — genuinely blocked publication on a RUNNING thread
# ======================================================================

class TestCaseEBlockedPublication:
    def test_blocked_publication_existing_destination(
            self, sync_win, tmp_path, monkeypatch):
        w = sync_win
        f = str(tmp_path / "case_e.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("old")
        blk = _BlockPublish(monkeypatch)
        try:
            _enqueue(w, f, "case-e-newest")
            w._dispatch_push_jobs()
            blk.wait_entered()
            before = _state(w, f)
            res = w._push_shutdown(timeout_s=0.3)
            after = _state(w, f)
            _emit("E-blocked-running", res, before, after)
            assert res is False
            assert w._push_worker is not None and w._push_thread is not None
            assert w._push_thread.isRunning()
            assert after["dest_text"] == "old"
        finally:
            blk.unblock()
        assert w._push_wait_idle(timeout_s=BARRIER_S) is True
        assert open(f, encoding="utf-8").read() == "case-e-newest"
        assert w._push_shutdown(timeout_s=BARRIER_S) is True
        assert w._push_worker is None and w._push_thread is None

    def test_blocked_publication_refuses_external_modification(
            self, sync_win, tmp_path, monkeypatch):
        """An external save that lands while publication is blocked must
        defeat the compare-before-publish gate; shutdown still drains clean
        and the external content survives."""
        w = sync_win
        f = str(tmp_path / "case_e3.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("old")
        monkeypatch.setattr(w, "_sync_conflict_choice", lambda *a, **k: "file")
        w.active_temp_slot = -1      # conflict resolves from presets, not GUI
        presets = w.data.setdefault("temp_presets_all", {}).setdefault(
            w.get_current_category() or CUR, [None] * 100)
        presets[0] = "case-e3-app"    # silo still wants exactly the sent text
        blk = _BlockPublish(monkeypatch)
        try:
            _enqueue(w, f, "case-e3-app")
            w._dispatch_push_jobs()
            blk.wait_entered()
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("external")
            blk.unblock()
            res = w._push_shutdown(timeout_s=BARRIER_S)
            final = open(f, encoding="utf-8").read()
            _emit("E3-external-modification", res, None,
                  {"dest_text": final, "presets0": presets[0]})
            assert res is True
            assert final == "external", "external edit was clobbered"
            assert presets[0] == "external"
        finally:
            blk.unblock()
        _force_idle(w)

    def test_blocked_publication_missing_destination(
            self, sync_win, tmp_path, monkeypatch):
        w = sync_win
        f = str(tmp_path / "case_e2.txt")
        blk = _BlockPublish(monkeypatch)
        try:
            _enqueue(w, f, "case-e2-newest")
            w._dispatch_push_jobs()
            blk.wait_entered()
            res = w._push_shutdown(timeout_s=0.3)
            _emit("E2-blocked-missing-dest", res, None,
                  {"dest_exists": os.path.exists(f)})
            assert res is False
            assert not os.path.exists(f)
            assert w._push_thread is not None and w._push_thread.isRunning()
        finally:
            blk.unblock()
        assert w._push_wait_idle(timeout_s=BARRIER_S) is True
        assert open(f, encoding="utf-8").read() == "case-e2-newest"
        assert w._push_shutdown(timeout_s=BARRIER_S) is True


# ======================================================================
# Case F — publication finished, GUI completion not yet processed
# ======================================================================

class TestCaseFUnprocessedCompletion:
    def test_queued_completion_still_proves_clean(
            self, sync_win, tmp_path, monkeypatch):
        w = sync_win
        f = str(tmp_path / "case_f.txt")
        blk = _BlockPublish(monkeypatch)
        try:
            _enqueue(w, f, "case-f-newest")
            w._dispatch_push_jobs()
            blk.wait_entered()
            blk.unblock()           # physical write completes on the worker
            # Deliberately NO processEvents: done stays queued on the GUI.
            time.sleep(0.2)
            before = _state(w, f)
            res = w._push_shutdown(timeout_s=BARRIER_S)
            after = _state(w, f)
            _emit("F-unprocessed-completion", res, before, after)
            assert res is True
            assert after["dest_text"] == "case-f-newest"
            assert after["pending"] == 0 and after["inflight"] is False
        finally:
            blk.unblock()
        assert w._push_worker is None and w._push_thread is None


# ======================================================================
# Case G — newest pending write follows an earlier in-flight write
# ======================================================================

class TestCaseGCoalescedNewestWins:
    def test_newest_snapshot_survives_shutdown(self, sync_win, tmp_path,
                                               monkeypatch):
        """Newest write queued behind an in-flight write of the same binding.

        The second snapshot is an authorized app-side edit, so the
        worker's two-sided-edit guard routes it through the operator
        choice; "app" is the authorized overwriting decision and must land
        the NEWEST text before shutdown may report clean."""
        w = sync_win
        f = str(tmp_path / "case_g.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("old")
        monkeypatch.setattr(w, "_sync_conflict_choice",
                            lambda *a, **k: "app")
        w.active_temp_slot = -1      # conflict resolves from presets, not GUI
        _spy = {"resolve": [], "done": []}
        _orig_resolve = w._resolve_push_conflict

        def _spy_resolve(key, path, text, dtxt, deol, dbom=False):
            _spy["resolve"].append((text, dtxt))
            return _orig_resolve(key, path, text, dtxt, deol, dbom)

        monkeypatch.setattr(w, "_resolve_push_conflict", _spy_resolve)
        _orig_done = w._on_push_done

        def _spy_done(results):
            _spy["done"].append([(r[0], r[2], r[3]) for r in results])
            return _orig_done(results)

        monkeypatch.setattr(w, "_on_push_done", _spy_done)
        blk = _BlockPublish(monkeypatch)
        try:
            _enqueue(w, f, "case-g-old")
            presets = w.data.setdefault("temp_presets_all", {}).setdefault(
                w.get_current_category() or CUR, [None] * 100)
            presets[0] = "case-g-newest"
            w._dispatch_push_jobs()
            blk.wait_entered()
            # Newer authorized snapshot arrives while batch 1 is in flight.
            _enqueue(w, f, "case-g-newest")
            blk.unblock()
            res = w._push_shutdown(timeout_s=BARRIER_S)
            final = open(f, encoding="utf-8").read()
            _emit("G-coalesced-newest", res, None,
                  {"dest_text": final, "spy": _spy})
            assert res is True
            assert final == "case-g-newest"
        finally:
            blk.unblock()
        _force_idle(w)

    def test_pending_coalescing_keeps_only_newest(self, sync_win, tmp_path):
        w = sync_win
        f = str(tmp_path / "case_g2.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("old")
        key = _enqueue(w, f, "case-g2-intermediate")
        _enqueue(w, f, "case-g2-newest")     # same key: supersedes pending
        assert len(w._push_jobs_pending) == 1
        assert w._push_jobs_pending[key][2] == "case-g2-newest"
        res = w._push_shutdown(timeout_s=BARRIER_S)
        final = open(f, encoding="utf-8").read()
        _emit("G2-pending-coalescing", res, None, {"dest_text": final})
        assert res is True
        assert final == "case-g2-newest"


# ======================================================================
# Restore-revocation suppression + repeated start/shutdown cycles
# ======================================================================

class TestCaseRestoreAndCycles:
    def test_restore_revocation_never_publishes_pending(
            self, sync_win, tmp_path, monkeypatch):
        w = sync_win
        f = str(tmp_path / "case_r.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("pre-restore")
        _enqueue(w, f, "stale-pre-restore-text")
        w._restore_stale_memory = True
        before = _state(w, f)
        res = w._push_shutdown(timeout_s=BARRIER_S)
        after = _state(w, f)
        _emit("R-restore-revocation", res, before, after)
        assert res is True
        assert after["dest_text"] == "pre-restore"
        assert after["pending"] == 0

    def test_repeated_start_shutdown_cycles_clean(self, sync_win, tmp_path):
        w = sync_win
        for i in range(5):
            f = str(tmp_path / f"cycle_{i}.txt")
            _enqueue(w, f, f"cycle-{i}")
            assert w._push_shutdown(timeout_s=BARRIER_S) is True
            assert open(f, encoding="utf-8").read() == f"cycle-{i}"
            assert w._push_worker is None and w._push_thread is None
        _emit("CYCLES-5", True, None, {"cycles": 5})
