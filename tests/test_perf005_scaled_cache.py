"""PERF-005 regression: scaled-WAV temp cache must stay within its
byte/file/memory budget; startup pruning removes leftovers; grace window
protects in-flight playback.
"""

import os
import time as _time
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.core.sound_manager as sm_mod

from fastprompter.core.sound_manager import (
    _bounded_cache_insert,
    _prune_scaled_cache_dir,
    _scaled_cache_dir,
    _SCALED_MEM_CACHE_CAP,
    _SCALED_CACHE_GRACE_SECONDS,
)


def test_bounded_cache_stays_below_cap():
    c = {}
    for i in range(_SCALED_MEM_CACHE_CAP + 100):
        _bounded_cache_insert(c, (f"p{i}", i), (True, f"/tmp/s{i}.wav"))
        # must still be bounded at every step
        assert len(c) <= _SCALED_MEM_CACHE_CAP + 1, f"overflow at {i}"
    assert len(c) <= _SCALED_MEM_CACHE_CAP + 1
    # newest entries survive
    keys = {k for k in c}
    for i in range(_SCALED_MEM_CACHE_CAP - 20, _SCALED_MEM_CACHE_CAP + 100):
        assert (f"p{i}", i) in keys, f"recent key p{i} evicted"


def test_bounded_cache_keeps_recent():
    c = {}
    for i in range(100):
        _bounded_cache_insert(c, (f"k{i}", i), (True, f"/s{i}.wav"))
    assert len(c) == 100
    assert (f"k0", 0) in c
    # insert many more
    for i in range(100, _SCALED_MEM_CACHE_CAP + 50):
        _bounded_cache_insert(c, (f"k{i}", i), (True, f"/s{i}.wav"))
    # oldest keys evicted, newest survive
    assert (f"k{_SCALED_MEM_CACHE_CAP - 1}", _SCALED_MEM_CACHE_CAP - 1) in c
    # but first few may have been evicted
    evicted = sum(1 for i in range(10) if (f"k{i}", i) not in c)
    assert evicted > 0, "oldest entries should be evicted under pressure"


def test_prune_removes_oldest_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sm_mod, "_scaled_cache_dir", lambda: str(tmp_path))
    old_file = tmp_path / "old_v50.wav"
    old_file.write_bytes(b"x" * 200_000)
    _touch(old_file, _time.time() - _SCALED_CACHE_GRACE_SECONDS - 60)
    new_file = tmp_path / "new_v75.wav"
    new_file.write_bytes(b"y" * 50_000)
    # new file is younger than grace window
    _touch(new_file, _time.time() - 5)
    total = old_file.stat().st_size + new_file.stat().st_size
    monkeypatch.setattr(sm_mod, "_SCALED_CACHE_MAX_BYTES", total - 100_000)
    _prune_scaled_cache_dir()
    assert not old_file.exists(), "old file beyond grace should be pruned"
    assert new_file.exists(), "young file within grace must survive"


def test_prune_protects_just_written_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sm_mod, "_scaled_cache_dir", lambda: str(tmp_path))
    for i in range(5):
        p = tmp_path / f"old_stale_v{i}.wav"
        p.write_bytes(b"z" * 300_000)
        _touch(p, _time.time() - _SCALED_CACHE_GRACE_SECONDS - 120)
    protect = str(tmp_path / "just_written_v50.wav")
    with open(protect, "wb") as fh:
        fh.write(b"a" * 50_000)
    monkeypatch.setattr(sm_mod, "_SCALED_CACHE_MAX_BYTES", 60_000)
    _prune_scaled_cache_dir(protect=protect)
    assert os.path.exists(protect), "protected file must survive pruning"


def _touch(path, ts):
    os.utime(str(path), (ts, ts))