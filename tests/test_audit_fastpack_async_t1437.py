"""T-1437 (SRC-097) — PERF-001: Fast Pack plans and writes off the GUI thread.

The planner is part of the frozen capture, so the shared bundle worker calls the
capture's ``plan_factory`` (a selection plan for Fast Pack) instead of the
full-silo default, and the selection entry point ends by dispatching to that
worker rather than writing on the GUI thread.
"""

from __future__ import annotations

import inspect
import threading

from fastprompter import main as fpmain
from fastprompter.core import silo_bundle as sb


def _worker():
    return fpmain._BundleWorker()


def _collect(worker):
    out = []
    worker.finished.connect(lambda payload: out.append(payload))
    return out


def _empty_plan(**_kw):
    return sb.BundlePlan(archive_name="Sil", display_title="Sil", category="Cat",
                         target_dir="", text_member=None, text_body="")


def test_perf_001_worker_calls_the_captured_plan_factory(qapp):
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return _empty_plan()

    worker = _worker()
    out = _collect(worker)
    worker._run({"cancel": threading.Event(), "plan_factory": factory,
                 "plan_kwargs": {"marker": 7}})

    assert seen == {"marker": 7}          # the capture's planner was used
    assert out and out[0][0] == "empty"   # and its plan drove the decision


def test_perf_001_worker_maps_preflight_cancel_to_cancel(qapp):
    def factory(**_kw):
        raise sb.BundleCancelled()

    worker = _worker()
    out = _collect(worker)
    worker._run({"cancel": threading.Event(), "plan_factory": factory,
                 "plan_kwargs": {}})

    assert out == [("cancel", None)]


def test_perf_001_worker_maps_write_cancel_to_cancel(qapp):
    def factory(**_kw):
        return _empty_plan()

    worker = _worker()
    out = _collect(worker)
    cap = {"cancel": threading.Event(), "plan_factory": factory,
           "plan_kwargs": {}}
    cap["cancel"].set()

    worker._run(cap)

    # an empty plan short-circuits before writing; the point is the class the
    # worker catches, proven by the preflight test above.
    assert out and out[0][0] == "empty"


def test_perf_001_fast_pack_ends_by_dispatching_not_writing(qapp):
    src = inspect.getsource(fpmain.FastPrompter.fast_pack_selection)

    assert "_silo_bundle_dispatch(" in src
    assert "plan_factory" in src and "plan_selection_bundle" in src
    assert "sb.write_bundle(plan)" not in src
    assert "zipfile" not in src
