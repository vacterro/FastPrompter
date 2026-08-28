"""W2-003 (acb-mtbqjyvd): rescan must not unlink existing Sync-Project
bindings when the file is only temporarily unsyncable (over-limit, non-text,
transient read failure) — only genuine physical deletion removes the mapping.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


class _Fake:
    def __init__(self):
        self.data = {}
        self._invalidated = []
        self._eol_cache = {}
        self._bom_cache = {}
        self._last_applied = {}

    def _sync_config(self):
        return True

    def _sync_root(self):
        return str(self.root)

    def _sync_include(self):
        return [".txt"]

    def _sync_exclude(self):
        return []

    def _sync_recursive(self):
        return True

    def _sync_max_bytes(self):
        return 10  # tiny: makes files over-limit easily

    def _sync_invalidate_binding(self, key, path):
        self._invalidated.append((key, path))

    def _sync_baseline_key(self, slot, path):
        return f"{slot}:{path}"

    def _sync_side_digest(self, text):
        return text

    def _ensure_temp_presets(self):
        return self.data.setdefault("temp_presets", [])

    def _start_project_watcher(self):
        pass

    def _update_project_tooltip(self):
        pass

    def mark_dirty(self):
        pass

    def refresh_temp_presets(self):
        pass


def _fake_app():
    import fastprompter.main as main_mod
    main_mod.FastPrompter._rescan_project_sync.__get__(object)  # noqa
    f = _Fake()
    return f


def test_rescan_keeps_binding_when_file_over_limit(tmp_path, monkeypatch):
    import fastprompter.main as main_mod
    f = _Fake()
    f.root = tmp_path
    (tmp_path / "a.txt").write_text("12345678901")  # 11 bytes > max 10
    f.data["project_sync_map"] = {"0": "a.txt"}
    main_mod.FastPrompter._rescan_project_sync(f)
    # mapping retained (file exists, just over-limit)
    assert f.data["project_sync_map"] == {"0": "a.txt"}
    assert f._invalidated == []


def test_rescan_drops_binding_when_file_deleted(tmp_path, monkeypatch):
    import fastprompter.main as main_mod
    f = _Fake()
    f.root = tmp_path
    f.data["project_sync_map"] = {"0": "gone.txt"}
    main_mod.FastPrompter._rescan_project_sync(f)
    assert f.data["project_sync_map"] == {}
    assert f._invalidated == [(0, str(tmp_path / "gone.txt"))]


def test_rescan_keeps_binding_when_binary(tmp_path, monkeypatch):
    import fastprompter.main as main_mod
    f = _Fake()
    f.root = tmp_path
    with open(tmp_path / "b.txt", "wb") as fh:
        fh.write(b"\x00\x01\x02binary")
    f.data["project_sync_map"] = {"0": "b.txt"}
    main_mod.FastPrompter._rescan_project_sync(f)
    assert f.data["project_sync_map"] == {"0": "b.txt"}
    assert f._invalidated == []
