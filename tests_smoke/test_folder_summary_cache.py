"""Regression (P2-24): the File Container tooltip summary is cached.

The header tooltip used to re-walk the folder tree on the GUI thread on
every refresh, so a silo folder with subfolders on an HDD/NAS froze the
window on each switch. The summary is now cached per (folder, direct-listing
signature, lang): an unchanged folder is never re-walked, a direct change
invalidates immediately, and the short TTL bounds staleness for nested
changes. The live count badge (_silo_file_count) never caches.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _seed(d):
    os.makedirs(os.path.join(d, "sub"), exist_ok=True)
    with open(os.path.join(d, "a.txt"), "w", encoding="utf-8") as f:
        f.write("x" * 100)
    with open(os.path.join(d, "sub", "b.bin"), "w", encoding="utf-8") as f:
        f.write("y" * 200)


class TestFolderSummaryCache:
    def test_unchanged_folder_is_never_re_walked(self, tmp_path, monkeypatch):
        import fastprompter.ui.file_container as fc

        d = str(tmp_path / "silo")
        _seed(d)
        fc._folder_summary_cache.clear()
        real_walk = os.walk
        calls = []

        def counting_walk(path, *a, **k):
            calls.append(path)
            return real_walk(path, *a, **k)

        monkeypatch.setattr(fc.os, "walk", counting_walk)
        first = fc.folder_summary(d)
        assert calls, "the first call must walk the tree"
        calls.clear()
        second = fc.folder_summary(d)
        assert second == first
        assert calls == [], "an unchanged folder must NOT be re-walked"
        fc._folder_summary_cache.clear()

    def test_direct_change_invalidates_immediately(self, tmp_path, monkeypatch):
        import fastprompter.ui.file_container as fc

        d = str(tmp_path / "silo2")
        _seed(d)
        fc._folder_summary_cache.clear()
        real_walk = os.walk
        calls = []
        monkeypatch.setattr(
            fc.os, "walk",
            lambda p, *a, **k: (calls.append(p) or real_walk(p, *a, **k)))
        fc.folder_summary(d)
        calls.clear()
        with open(os.path.join(d, "c.txt"), "w", encoding="utf-8") as f:
            f.write("z")
        fc.folder_summary(d)
        assert calls, "a direct change must recompute"
        fc._folder_summary_cache.clear()

    def test_ttl_bounds_staleness_for_nested_changes(self, tmp_path, monkeypatch):
        import fastprompter.ui.file_container as fc

        d = str(tmp_path / "silo3")
        _seed(d)
        fc._folder_summary_cache.clear()
        clock = [1000.0]
        monkeypatch.setattr(fc, "_summary_now", lambda: clock[0])
        real_walk = os.walk
        calls = []
        monkeypatch.setattr(
            fc.os, "walk",
            lambda p, *a, **k: (calls.append(p) or real_walk(p, *a, **k)))
        fc.folder_summary(d)
        calls.clear()
        # unchanged listing inside the TTL: served from cache, no re-walk
        fc.folder_summary(d)
        assert calls == [], "inside the TTL nothing is re-walked"
        # after the TTL the summary is allowed to recompute
        clock[0] += fc._SUMMARY_TTL + 0.01
        fc.folder_summary(d)
        assert calls, "an expired TTL allows recomputation"
        fc._folder_summary_cache.clear()
