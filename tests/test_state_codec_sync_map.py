"""CORE-002 (audit acb-mt632rjw): persisted Sync-Project mapping state is
quarantined at decode time and can never resolve outside the sync root.

The codec treats ``project_sync_map(_all)`` values as untrusted input:
absolute, drive-qualified, backslash or traversal paths are dropped instead
of being normalized into a usable outside write target. Runtime resolution
(``resolve_relative_path``) re-validates containment against the LIVE root,
including symlink/reparse escapes. Explicit per-silo links stay untouched —
those are intentionally user-selected external absolute paths.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import project_sync as ps
from fastprompter.core.state import _decode_structured_setting, _is_safe_sync_rel


def _decode_map_all(raw):
    return _decode_structured_setting(
        "project_sync_map_all", raw, dict, {}, legacy_ast=False)


class TestCodecQuarantine:
    def test_traversal_entry_is_dropped(self):
        out = _decode_map_all('{"Text": {"0": "../outside.txt", "1": "ok.txt"}}')
        assert out == {"Text": {"1": "ok.txt"}}

    def test_absolute_and_drive_entries_are_dropped(self):
        out = _decode_map_all(
            '{"Text": {"0": "/etc/passwd", "1": "C:/evil.txt", "2": "keep.md"}}')
        assert out == {"Text": {"2": "keep.md"}}

    def test_backslash_and_dot_segments_are_dropped(self):
        out = _decode_map_all(
            '{"Text": {"0": "a\\\\b.txt", "1": "./x.txt", "2": "a/../b.txt"}}')
        assert out == {"Text": {}}

    def test_non_string_values_are_dropped(self):
        out = _decode_map_all('{"Text": {"0": 42, "1": null, "2": "fine.txt"}}')
        assert out == {"Text": {"2": "fine.txt"}}

    def test_wrong_typed_category_member_is_dropped(self):
        out = _decode_map_all('{"Text": ["not", "a", "dict"], "Other": {}}')
        assert out == {"Other": {}}

    def test_safe_relative_paths_survive_nested(self):
        out = _decode_map_all(
            '{"Text": {"3": "docs/nested/file.md"}, '
            '"Code": {"0": "deep/dir/a.py"}}')
        assert out == {
            "Text": {"3": "docs/nested/file.md"},
            "Code": {"0": "deep/dir/a.py"},
        }


class TestSafeRelPredicate:
    def test_predicate_matches_policy(self):
        assert _is_safe_sync_rel("a.txt")
        assert _is_safe_sync_rel("d/s/f.md")
        assert not _is_safe_sync_rel("../x")
        assert not _is_safe_sync_rel("C:/x")
        assert not _is_safe_sync_rel("/x")
        assert not _is_safe_sync_rel("a\\b")
        assert not _is_safe_sync_rel("")
        assert not _is_safe_sync_rel(None)
        assert not _is_safe_sync_rel("a//b")
        assert not _is_safe_sync_rel("./a")


class TestRuntimeContainment:
    def test_resolve_rejects_escape_forms(self, tmp_path):
        root = str(tmp_path)
        for bad in ("../out.txt", "a/../../out.txt", "/abs.txt",
                    "C:/abs.txt"):
            assert ps.resolve_relative_path(root, bad) is None
        # backslashes are intentionally normalized to slashes at resolution
        # time (Windows user input); the CODEC is stricter and quarantines
        # stored backslash paths outright.
        got = ps.resolve_relative_path(root, "a\\b.txt")
        if got is not None:
            assert os.path.commonpath(
                [os.path.realpath(root), os.path.realpath(got)]) \
                == os.path.realpath(root)

    def test_resolve_keeps_ordinary_nested_path(self, tmp_path):
        root = tmp_path
        (root / "sub").mkdir()
        target = root / "sub" / "f.txt"
        target.write_text("hi", encoding="utf-8")
        got = ps.resolve_relative_path(str(root), "sub/f.txt")
        assert got is not None
        assert os.path.samefile(got, str(target))

    def test_symlink_escape_is_rejected(self, tmp_path):
        from tests._helpers import junction_ok
        if not junction_ok():
            import pytest
            pytest.skip("symlinks unavailable")
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        link = root / "jump"
        try:
            os.symlink(str(outside), str(link))
        except OSError:
            import pytest
            pytest.skip("symlink creation denied")
        assert ps.resolve_relative_path(str(root), "jump/x.txt") is None

    def test_explicit_silo_links_are_not_root_confined(self):
        # per-silo links are user-chosen ABSOLUTE external files by design;
        # nothing in the sync-root policy may reject them. Links live in the
        # per-category store and bind to the flat alias untouched.
        from fastprompter.core.state import bind_active_category
        data = {"silo_links_all": {"Text": {"0": "D:/notes/external.md"}}}
        bind_active_category(data, "Text")
        assert data["silo_links"]["0"] == "D:/notes/external.md"
        assert data["silo_links_all"]["Text"]["0"] == "D:/notes/external.md"
