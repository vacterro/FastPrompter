"""T-817 guardrails: undo save must use at most ONE physical writer and
coalesce dispatches into the newest pending snapshot per path.

The old code spawned a fresh ``fastprompter-undo-write`` daemon thread per
dispatch; when json/disk work outran the 1 s debounce the threads piled up
unbounded, each holding its own snapshot, all serialized on one lock.

These tests drive the real FastPrompter methods on a Qt-free stub window
(no QApplication, no QTimer) so the writer machinery itself — the thing the
ticket is about — is exercised headlessly.
"""

import json
import os
import threading
import time

import pytest


def _make():
    from types import SimpleNamespace

    from fastprompter.main import FastPrompter

    s = SimpleNamespace()
    s._undo_timer = None
    s._undo_pending_jobs = {}
    s._undo_save_failed = False
    s._undo_save_backlog = {}
    s._undo_save_cv = threading.Condition()
    s._undo_save_writer = None
    s._undo_save_quit = False
    s._undo_save_threads = set()
    s._undo_save_jobs = {}
    # The namespace is not a FastPrompter instance, so the methods it must
    # call through `self` are bound onto the stub explicitly.
    for _m in ("_dispatch_undo_save", "_undo_writer_loop", "_write_undo_file",
               "_wait_for_undo_saves"):
        setattr(s, _m, getattr(FastPrompter, _m).__get__(s))
    return s, FastPrompter


def _dispatch(s, F, path, tag):
    s._undo_pending_jobs[path] = {"undo": [{"tag": tag}], "redo": []}
    F._dispatch_undo_save(s)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _wait_dump_count(calls, want, timeout=5.0):
    deadline = time.monotonic() + timeout
    while calls["n"] < want and time.monotonic() < deadline:
        time.sleep(0.005)
    assert calls["n"] >= want, f"dump called {calls['n']} times, wanted {want}"


def test_100_dispatches_one_writer_one_coalesced_snapshot(
        tmp_path, monkeypatch):
    calls = {"n": 0}
    release = threading.Event()
    real_dump = json.dump

    def gated_dump(obj, f, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            release.wait(10)
        return real_dump(obj, f, **kw)

    monkeypatch.setattr(json, "dump", gated_dump)
    s, F = _make()
    path = os.path.join(str(tmp_path), "p1_undo.json")

    for i in range(100):
        _dispatch(s, F, path, i)

    # Writer 1 is stuck inside the first dump: exactly one physical writer,
    # and the 100 pending snapshots coalesced into the single newest one.
    _wait_dump_count(calls, 1)
    assert len(s._undo_save_threads) == 1, "more than one physical writer"
    assert s._undo_save_backlog == {path: {"undo": [{"tag": 99}], "redo": []}}, \
        "backlog must hold only the newest pending snapshot"

    release.set()
    assert F._wait_for_undo_saves(s) is True
    assert _read_json(path) == {"undo": [{"tag": 99}], "redo": []}
    assert s._undo_save_threads == set()


def test_two_profile_paths_both_persist_newest(tmp_path, monkeypatch):
    calls = {"n": 0}
    release = threading.Event()
    real_dump = json.dump

    def gated_dump(obj, f, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            release.wait(10)
        return real_dump(obj, f, **kw)

    monkeypatch.setattr(json, "dump", gated_dump)
    s, F = _make()
    pa = os.path.join(str(tmp_path), "a_undo.json")
    pb = os.path.join(str(tmp_path), "b_undo.json")

    for i in range(30):
        _dispatch(s, F, pa, ("a", i))
        _dispatch(s, F, pb, ("b", i))

    _wait_dump_count(calls, 1)
    assert len(s._undo_save_threads) == 1
    assert set(s._undo_save_backlog) == {pa, pb}, \
        "one coalesced newest snapshot per profile path"

    release.set()
    assert F._wait_for_undo_saves(s) is True
    assert _read_json(pa) == {"undo": [{"tag": ["a", 29]}], "redo": []}
    assert _read_json(pb) == {"undo": [{"tag": ["b", 29]}], "redo": []}


def test_earlier_failed_write_still_fails_the_drain(tmp_path, monkeypatch):
    calls = {"n": 0}
    release = threading.Event()
    real_dump = json.dump

    def gated_dump(obj, f, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            release.wait(10)
        return real_dump(obj, f, **kw)

    monkeypatch.setattr(json, "dump", gated_dump)
    s, F = _make()
    pa = os.path.join(str(tmp_path), "a_undo.json")
    pb = os.path.join(str(tmp_path), "b_undo.json")

    real_replace = os.replace

    def failing_replace(src, dst):
        if dst == pa:
            raise OSError("disk full for A")
        return real_replace(src, dst)

    monkeypatch.setattr("fastprompter.main.os.replace", failing_replace)

    _dispatch(s, F, pa, ("a", 7))
    _dispatch(s, F, pb, ("b", 9))
    _wait_dump_count(calls, 1)

    release.set()
    assert F._wait_for_undo_saves(s) is False, \
        "the failed A write must make the drain report failure"
    assert _read_json(pb) == {"undo": [{"tag": ["b", 9]}], "redo": []}, \
        "the healthy path must still persist its newest state"
    assert not os.path.exists(pa), "failed path must not be published"
    leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert not leftovers, f"orphan temp left behind: {leftovers}"


def test_writer_reused_across_batches_without_thread_pileup(
        tmp_path, monkeypatch):
    """A live writer must absorb later dispatches, not spawn a second one."""
    calls = {"n": 0}
    release = threading.Event()
    real_dump = json.dump

    def gated_dump(obj, f, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            release.wait(10)
        return real_dump(obj, f, **kw)

    monkeypatch.setattr(json, "dump", gated_dump)
    s, F = _make()
    path = os.path.join(str(tmp_path), "u_undo.json")

    _dispatch(s, F, path, 1)
    _wait_dump_count(calls, 1)
    for i in range(2, 50):
        _dispatch(s, F, path, i)
    assert len(s._undo_save_threads) == 1, "dispatch spawned a second writer"

    release.set()
    assert F._wait_for_undo_saves(s) is True
    assert _read_json(path) == {"undo": [{"tag": 49}], "redo": []}


def test_drain_without_pending_is_clean(tmp_path):
    s, F = _make()
    assert F._wait_for_undo_saves(s) is True
    assert s._undo_save_threads == set()