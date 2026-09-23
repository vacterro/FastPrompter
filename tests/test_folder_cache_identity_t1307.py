"""PERF-003 (audit/12, SRC-041 R009): File Container cache identity is
fixed-size.

The old ``_dir_size``/``folder_summary`` keys embedded ``tuple(sorted(all
direct names))``, so even a valid hit re-listed and sorted the whole directory,
and the caches retained full filename inventories as keys (measured: 100,000
names -> ~6 MiB per key). One logical entry per canonical directory identity
with a fixed-size generation signal now serves both concerns.
"""

import os
import sys

import pytest

from fastprompter.ui import file_container as fc


@pytest.fixture(autouse=True)
def _clean_caches():
    fc._dir_size_cache.clear()
    fc._folder_summary_cache.clear()
    yield
    fc._dir_size_cache.clear()
    fc._folder_summary_cache.clear()


class TestWarmHitIsFixedCost:
    def test_warm_hit_never_enumerates_or_retains_names(
            self, tmp_path, monkeypatch):
        folder = tmp_path / "huge"
        folder.mkdir()
        calls = {"listdir": 0}
        real_listdir = os.listdir

        def counting_listdir(path):
            calls["listdir"] += 1
            if str(path) == str(folder):
                return [f"file_{i}.txt" for i in range(100_000)]
            return real_listdir(path)

        monkeypatch.setattr(fc.os, "listdir", counting_listdir)
        monkeypatch.setattr(fc.os.path, "isdir",
                            lambda p: False)
        monkeypatch.setattr(fc.os.path, "getsize", lambda p: 1)

        first = fc.folder_summary(str(folder), "EN")
        assert calls["listdir"] == 1
        assert "100000 item(s)" in first

        second = fc.folder_summary(str(folder), "EN")
        assert second == first
        assert calls["listdir"] == 1, \
            "a warm hit must not enumerate the directory to rebuild the key"

        # Retained identity is O(1) w.r.t. entry count: one entry per
        # canonical directory, and its key/value do not scale with names.
        assert len(fc._folder_summary_cache) == 1
        key, value = next(iter(fc._folder_summary_cache.items()))
        retained = sys.getsizeof(key) + sys.getsizeof(value)
        assert retained < 4096

    def test_retained_cache_memory_does_not_grow_with_name_count(
            self, tmp_path, monkeypatch):
        small = tmp_path / "small"
        large = tmp_path / "large"
        small.mkdir()
        large.mkdir()
        real_listdir = os.listdir

        def listing(path):
            if str(path) == str(small):
                return [f"f{i}.txt" for i in range(100)]
            if str(path) == str(large):
                return [f"f{i}.txt" for i in range(100_000)]
            return real_listdir(path)

        monkeypatch.setattr(fc.os, "listdir", listing)
        monkeypatch.setattr(fc.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(fc.os.path, "getsize", lambda p: 1)

        fc.folder_summary(str(small), "EN")
        fc.folder_summary(str(large), "EN")

        def retained_for(folder):
            canon = os.path.normcase(os.path.abspath(str(folder)))
            total = 0
            for key, value in fc._folder_summary_cache.items():
                if key[0] == canon:
                    total += sys.getsizeof(key) + sys.getsizeof(value)
            return total

        delta = retained_for(large) - retained_for(small)
        assert delta < 4096, \
            "a 1000x larger directory must not retain 1000x more cache bytes"

    def test_generation_change_replaces_the_same_path_entry(
            self, tmp_path, monkeypatch):
        folder = tmp_path / "gen"
        folder.mkdir()
        generation = {"value": 1}
        monkeypatch.setattr(fc, "_dir_generation",
                            lambda p: generation["value"])
        monkeypatch.setattr(fc.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(fc.os.path, "getsize", lambda p: 1)
        real_listdir = os.listdir
        names = {"list": ["a.txt"]}
        monkeypatch.setattr(fc.os, "listdir",
                            lambda p: list(names["list"])
                            if str(p) == str(folder)
                            else real_listdir(p))

        assert "1 item(s)" in fc.folder_summary(str(folder), "EN")

        names["list"] = ["a.txt", "b.txt"]
        generation["value"] = 2
        assert "2 item(s)" in fc.folder_summary(str(folder), "EN")
        # Old historical signatures must NOT linger as extra keys.
        assert len(fc._folder_summary_cache) == 1

    def test_entry_caps_still_hold(self, tmp_path, monkeypatch):
        real_listdir = os.listdir
        monkeypatch.setattr(fc.os, "listdir",
                            lambda p: ["x.txt"]
                            if str(p).startswith(str(tmp_path))
                            else real_listdir(p))
        monkeypatch.setattr(fc.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(fc.os.path, "getsize", lambda p: 1)

        for i in range(80):
            d = tmp_path / f"cap_{i}"
            d.mkdir()
            fc.folder_summary(str(d), "EN")
        fc._prune_folder_summary_cache(fc._summary_now() + 10.0)
        assert len(fc._folder_summary_cache) <= 64

    def test_dir_size_cache_cap_still_holds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fc.os, "walk", lambda *a, **k: iter(()))
        for i in range(300):
            d = tmp_path / f"sz_{i}"
            d.mkdir()
            assert fc._dir_size(str(d)) == 0
        assert len(fc._dir_size_cache) <= 256


class TestApplicationMutationInvalidates:
    def test_publish_new_file_invalidates_the_directory(self, tmp_path):
        folder = tmp_path / "container"
        folder.mkdir()
        with open(folder / "seed.txt", "w", encoding="utf-8") as fh:
            fh.write("seed")
        fc.folder_summary(str(folder), "EN")
        fc._dir_size(str(folder))
        canon = os.path.normcase(os.path.abspath(str(folder)))
        assert any(k[0] == canon for k in fc._folder_summary_cache)
        assert canon in fc._dir_size_cache

        tmp = folder / "new.fptmp-abc"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("new")
        fc._publish_new_file(str(tmp), str(folder / "new.txt"))

        assert canon not in fc._dir_size_cache
        assert not any(k[0] == canon for k in fc._folder_summary_cache)

    def test_dir_size_cache_is_path_keyed_and_warm(self, tmp_path,
                                                   monkeypatch):
        folder = tmp_path / "sub"
        folder.mkdir()
        with open(folder / "a.bin", "wb") as fh:
            fh.write(b"12345")
        walks = {"n": 0}
        real_walk = os.walk

        def counting_walk(path, *a, **k):
            walks["n"] += 1
            return real_walk(path, *a, **k)

        monkeypatch.setattr(fc.os, "walk", counting_walk)
        assert fc._dir_size(str(folder)) == 5
        assert walks["n"] == 1
        assert fc._dir_size(str(folder)) == 5
        assert walks["n"] == 1, "a warm hit must not re-walk the subtree"
        assert len(fc._dir_size_cache) == 1

    def test_cancellation_and_traversal_cap_are_preserved(self, tmp_path):
        folder = tmp_path / "big"
        folder.mkdir()
        for i in range(10):
            with open(folder / f"f{i}.txt", "w", encoding="utf-8") as fh:
                fh.write("x")

        assert fc._dir_size(str(folder), _cap=4, cancel_check=None) == 4
        # cancellation is read per walk, not part of the cache identity: a
        # cancelled read must be uncached so it is re-walked next time.
        fc._dir_size_cache.clear()
        assert fc._dir_size(str(folder), _cap=2000,
                            cancel_check=lambda: True) == 0
