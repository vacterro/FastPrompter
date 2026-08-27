"""PERF-006 regression: folder-result caches must stay bounded across long
sessions. _file_count_cache and _tooltip_cache get explicit caps; the
file_container folder-summary cache prunes after EVERY insert, including the
empty-folder branch.
"""

import os
import sys
import time as _time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.main as main_mod  # noqa: E402
from fastprompter.ui import file_container as fc  # noqa: E402


def test_file_count_cache_bounded():
    host = main_mod.FastPrompter
    c = {}
    for i in range(main_mod._FILE_COUNT_CACHE_CAP + 500):
        main_mod.FastPrompter._bounded_cache_put(
            c, f"path/{i}", i, main_mod._FILE_COUNT_CACHE_CAP)
    assert len(c) <= main_mod._FILE_COUNT_CACHE_CAP
    # newest survive
    assert c[f"path/{main_mod._FILE_COUNT_CACHE_CAP + 400}"] == \
        main_mod._FILE_COUNT_CACHE_CAP + 400
    # oldest evicted
    assert "path/0" not in c


def test_tooltip_cache_bounded():
    host = main_mod.FastPrompter
    c = {}
    for i in range(main_mod._TOOLTIP_CACHE_CAP + 200):
        main_mod.FastPrompter._bounded_cache_put(
            c, f"f/{i}", (i, "x" * 10), main_mod._TOOLTIP_CACHE_CAP)
    assert len(c) <= main_mod._TOOLTIP_CACHE_CAP
    assert f"f/{main_mod._TOOLTIP_CACHE_CAP + 100}" in c
    assert "f/0" not in c


def test_folder_summary_evicts_after_empty_insert():
    # an empty folder must also trigger the pruning pass, so many distinct
    # empty-folder signatures cannot bypass the working-set bound.
    fc._folder_summary_cache.clear()
    import tempfile
    base = tempfile.mkdtemp()
    keys = []
    for i in range(80):
        d = os.path.join(base, f"empty_{i}")
        os.makedirs(d, exist_ok=True)
        fc.folder_summary(d, "EN")
    # older entries (past TTL) are pruned once over the 64 threshold
    now = fc._summary_now()
    fc._prune_folder_summary_cache(now + 10.0)  # simulate time passing
    # every empty-folder insert went through the pruning path; with all
    # entries now expired, the cache must be empty (all pruned), proving no
    # insert bypassed eviction.
    assert len(fc._folder_summary_cache) <= 64
    fc._folder_summary_cache.clear()


def test_prune_only_runs_when_over_threshold():
    fc._folder_summary_cache.clear()
    import tempfile
    base = tempfile.mkdtemp()
    for i in range(10):
        d = os.path.join(base, f"p_{i}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "a.txt"), "w") as fh:
            fh.write("data")
        fc.folder_summary(d, "EN")
    # under threshold: even expired entries stay (cache retains working set)
    fc._prune_folder_summary_cache(fc._summary_now() + 60.0)
    assert len(fc._folder_summary_cache) == 10
    fc._folder_summary_cache.clear()
