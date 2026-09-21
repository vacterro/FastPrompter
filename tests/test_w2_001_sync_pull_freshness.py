"""W2-001: the asynchronous Sync-Project reader must not commit a stale
observation across the time-of-check/time-of-use boundary.

Every test is a real two-phase race:

    phase 1  ``_collect_sync_pull`` observes the filesystem (worker side);
    phase 2  the filesystem moves on;
    commit   the EXACT live ``_apply_external_sync_collected`` runs.

Required behaviour: a transient delete/recreate may never detach a stable
silo binding, stale text may never be applied or bound, a superseded
discovery may never allocate a slot, rejected observations are requeued
through the existing debounce (bounded, coalesced), and genuine absence
still detaches (W2-003 preserved).
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


class _FakeTimer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1

    def stop(self):
        pass


class _Fake:
    """Minimal host for the real commit function.

    ``_apply_external_change`` is stubbed (its own baseline/conflict logic is
    covered elsewhere) so these tests isolate the freshness boundary. The
    requeue path is the REAL implementation.
    """

    def __init__(self, root):
        self.root = str(root)
        self.data = {"temp_presets": ["", "", "", ""]}
        self.active_temp_slot = -1
        self.editing_snippet = None
        self._invalidated = []
        self._sync_eol_cache = {}
        self._sync_bom_cache = {}
        self._sync_last_applied = {}
        self._dirty = 0
        self._refreshes = 0
        self._sync_changed_files = set()
        self._sync_dir_changed = False
        self._sync_pending_apply = False
        self._sync_shutting_down = False
        self._sync_apply_timer = _FakeTimer()

    # --- helpers the real commit code calls ------------------------------
    def _ensure_temp_presets(self):
        return self.data.setdefault("temp_presets", [])

    def _sync_invalidate_binding(self, idx, path):
        self._invalidated.append((idx, path))

    def _sync_baseline_key(self, slot, path):
        return f"{slot}:{path}"

    def _sync_side_digest(self, text):
        return text

    def _apply_external_change(self, slot, path, text, eol, presets, active,
                               editing_snippet, applied):
        applied[slot] = text

    def mark_dirty(self):
        self._dirty += 1

    def refresh_temp_presets(self):
        self._refreshes += 1

    def _requeue_stale_sync(self, paths, dir_level=False):
        import fastprompter.main as main_mod
        return main_mod.FastPrompter._requeue_stale_sync(
            self, paths, dir_level=dir_level)


def _commit(fake, request, result):
    import fastprompter.main as main_mod
    return main_mod.FastPrompter._apply_external_sync_collected(
        fake, request, result)


def _collect(request):
    import fastprompter.main as main_mod
    return main_mod._collect_sync_pull(request)


def _request(root, mapping=None, changed=(), dir_changed=True, links=()):
    return {
        "gen": 1,
        "profile_id": None,
        "category": "",
        "root": str(root),
        "mapping": tuple((mapping or {}).items()),
        "links": tuple(links),
        "changed": {os.path.normcase(p) for p in changed},
        "dir_changed": dir_changed,
        "include": [".txt"],
        "exclude": [],
        "recursive": True,
        "max_bytes": 1 << 20,
    }


def _rewrite(path, text, bump_ns):
    """Rewrite ``path`` and force a distinct mtime_ns.

    Same-size rewrites are the hard case: the identity must change even when
    the byte count does not.
    """
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.utime(path, ns=(bump_ns, bump_ns))


RECREATED = "FILE RECREATED AFTER THE WORKER SAW IT MISSING"


def test_mapped_missing_reappeared_keeps_binding(tmp_path):
    """Mapped file absent at worker-read time, recreated before commit."""
    fake = _Fake(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("ORIGINAL", encoding="utf-8")
    fake.data["project_sync_map"] = {"0": "a.txt"}

    os.remove(path)                       # phase 1: worker observes absence
    request = _request(tmp_path, {"0": "a.txt"},
                       changed=[str(path)], dir_changed=False)
    result = _collect(request)
    assert [row[3] for row in result["mapped"]] == ["missing"]

    path.write_text(RECREATED, encoding="utf-8")   # phase 2: it is back

    _commit(fake, request, result)

    # The stable binding survives and nothing was detached.
    assert fake.data["project_sync_map"] == {"0": "a.txt"}
    assert fake._invalidated == []
    # The current generation is re-read asynchronously instead.
    assert os.path.normcase(str(path)) in fake._sync_changed_files
    assert fake._sync_apply_timer.starts == 1


def test_mapped_missing_reappeared_then_true_absence_detaches(tmp_path):
    """W2-003 preserved: confirmed current absence still detaches."""
    fake = _Fake(tmp_path)
    fake.data["project_sync_map"] = {"0": "gone.txt"}
    request = _request(tmp_path, {"0": "gone.txt"},
                       changed=[str(tmp_path / "gone.txt")], dir_changed=False)
    result = _collect(request)
    assert [row[3] for row in result["mapped"]] == ["missing"]

    _commit(fake, request, result)

    assert fake.data["project_sync_map"] == {}
    assert fake._invalidated == [(0, str(tmp_path / "gone.txt"))]
    assert fake._sync_apply_timer.starts == 0


def test_mapped_read_stale_generation_is_never_applied(tmp_path):
    """Worker read generation A; disk holds B at commit. A must not apply."""
    fake = _Fake(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("AAAA", encoding="utf-8")
    fake.data["project_sync_map"] = {"0": "a.txt"}
    request = _request(tmp_path, {"0": "a.txt"},
                       changed=[str(path)], dir_changed=False)

    result = _collect(request)
    assert result["mapped"][0][4][0] == "AAAA"

    _rewrite(path, "BBBBBBBB", 4_000_000_000)   # phase 2: newer generation

    _commit(fake, request, result)

    assert fake.data["temp_presets"][0] == ""    # stale text not applied
    assert fake.data["project_sync_map"] == {"0": "a.txt"}
    assert os.path.normcase(str(path)) in fake._sync_changed_files
    assert fake._sync_apply_timer.starts == 1

    # The requeued pull converges on the current generation.
    fake._sync_changed_files.clear()
    fake._sync_pending_apply = False
    fresh = _collect(_request(tmp_path, {"0": "a.txt"},
                              changed=[str(path)], dir_changed=False))
    _commit(fake, fresh, fresh)
    assert fake.data["temp_presets"][0] == "BBBBBBBB"


def test_mapped_read_unchanged_generation_applies(tmp_path):
    """Over-rejection guard: a current observation still applies normally."""
    fake = _Fake(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("HELLO", encoding="utf-8")
    fake.data["project_sync_map"] = {"0": "a.txt"}
    request = _request(tmp_path, {"0": "a.txt"},
                       changed=[str(path)], dir_changed=False)

    _commit(fake, request, _collect(request))

    assert fake.data["temp_presets"][0] == "HELLO"
    assert fake._sync_apply_timer.starts == 0


def test_new_discovery_stale_content_never_bound(tmp_path):
    """Discovered file replaced before commit must not claim a slot."""
    fake = _Fake(tmp_path)
    path = tmp_path / "new.txt"
    path.write_text("OLD_SNAPSHOT", encoding="utf-8")

    request = _request(tmp_path, {}, changed=[], dir_changed=True)
    result = _collect(request)
    assert [row[0] for row in result["new"]] == ["new.txt"]
    assert result["new"][0][2][0] == "OLD_SNAPSHOT"

    _rewrite(path, "NEW_DISK", 5_000_000_000)   # phase 2: replaced

    _commit(fake, request, result)

    assert fake.data.get("project_sync_map", {}) == {}
    assert fake.data["temp_presets"] == ["", "", "", ""]  # no slot claimed
    assert fake._sync_dir_changed is True        # discovery requeued
    assert fake._sync_apply_timer.starts == 1


def test_new_discovery_deleted_before_commit_never_bound(tmp_path):
    """Discovered file deleted before commit must not claim a slot."""
    fake = _Fake(tmp_path)
    path = tmp_path / "new.txt"
    path.write_text("OLD_SNAPSHOT", encoding="utf-8")

    request = _request(tmp_path, {}, changed=[], dir_changed=True)
    result = _collect(request)
    assert [row[0] for row in result["new"]] == ["new.txt"]

    os.remove(path)                             # phase 2: gone

    _commit(fake, request, result)

    assert fake.data.get("project_sync_map", {}) == {}
    assert fake.data["temp_presets"] == ["", "", "", ""]  # no slot claimed
    assert fake._sync_dir_changed is True


def test_link_read_stale_generation_is_never_applied(tmp_path):
    """Per-silo links obey the same generation rule as mapped files."""
    fake = _Fake(tmp_path)
    path = tmp_path / "link.txt"
    path.write_text("LINK_A", encoding="utf-8")
    fake.data["silo_links"] = {"0": str(path)}

    request = _request(tmp_path, {}, changed=[str(path)], dir_changed=False,
                       links=[("0", str(path))])
    result = _collect(request)
    assert result["links"][0][2] == "read"
    assert result["links"][0][3][0] == "LINK_A"

    _rewrite(path, "LINK_B", 6_000_000_000)     # phase 2: replaced

    _commit(fake, request, result)

    assert fake.data["temp_presets"][0] == ""
    assert os.path.normcase(str(path)) in fake._sync_changed_files
    assert fake._sync_apply_timer.starts == 1


def test_repeated_stale_completions_are_idempotent_and_coalesced(tmp_path):
    """The same stale completion applied twice must not duplicate work."""
    fake = _Fake(tmp_path)
    path = tmp_path / "new.txt"
    path.write_text("OLD_SNAPSHOT", encoding="utf-8")
    request = _request(tmp_path, {}, changed=[], dir_changed=True)
    stale = _collect(request)
    _rewrite(path, "NEW_DISK", 7_000_000_000)

    _commit(fake, request, stale)
    first_requeue = fake._sync_apply_timer.starts
    _commit(fake, request, stale)               # duplicate completion

    assert fake.data.get("project_sync_map", {}) == {}
    assert fake.data["temp_presets"] == ["", "", "", ""]  # no duplication
    # The second stale completion coalesces into the already-queued pull.
    assert first_requeue == 1
    assert fake._sync_apply_timer.starts == 1
    # No watcher redispatch storm: one bounded path per rejected row.
    assert len(fake._sync_changed_files) <= 1


def test_requeue_is_suppressed_during_shutdown(tmp_path):
    """Teardown must not start new async work."""
    fake = _Fake(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("AAAA", encoding="utf-8")
    fake.data["project_sync_map"] = {"0": "a.txt"}
    request = _request(tmp_path, {"0": "a.txt"},
                       changed=[str(path)], dir_changed=False)
    result = _collect(request)
    _rewrite(path, "BBBBBBBB", 8_000_000_000)

    fake._sync_shutting_down = True
    _commit(fake, request, result)

    assert fake.data["temp_presets"][0] == ""
    assert fake._sync_apply_timer.starts == 0
