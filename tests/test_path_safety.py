"""Regression tests for the canonical File Container path-safety helpers.

Proves the containment invariants for validate_component / safe_join /
is_within on Windows path semantics: drive-qualified and absolute names must
never discard the container root, ``..`` must never escape, and reserved
Windows names must never be written.
"""

import os

import pytest

from fastprompter.utils.path_safety import (
    alloc_fs_names,
    capture_resolved_root,
    fs_component,
    is_within,
    is_within_captured_root,
    is_within_resolved,
    safe_join,
    validate_component,
)


@pytest.mark.parametrize("name,expected", [
    ("note.txt", "note.txt"),
    ("просто заметка.txt", "просто заметка.txt"),
    ("my notes.txt", "my notes.txt"),
    ("dash-name", "dash-name"),
    ("a_b", "a_b"),
    ("..evil", "..evil"),        # a dot-run inside a plain name is legal
    ("a..b", "a..b"),
    ("clip 2026-01-01", "clip 2026-01-01"),
])
def test_valid_names_pass_unchanged(name, expected):
    clean, reason = validate_component(name)
    assert clean == expected, reason


def test_trailing_dots_and_spaces_are_normalized():
    assert validate_component("foo .") == ("foo", "")
    assert validate_component("foo.") == ("foo", "")
    assert validate_component(".") == (None, "the name is only dots or spaces")
    assert validate_component("...") == (None, "the name is only dots or spaces")
    assert validate_component("   ") == (None, "the name is empty")


@pytest.mark.parametrize("name", [
    "",
    ".",
    "..",
    "../x",
    "..\\x",
    "..\\..\\x",
    "a/..\\b",
    "a/b",
    "a\\b",
    "foo:bar",
    "C:\\evil.txt",
    "c:/evil.txt",
    "\\evil",
    "/evil",
    "\\\\server\\share\\evil",
    "\\\\?\\C:\\evil",
    "CON",
    "con",
    "CON.txt",
    "NUL",
    "prn",
    "aux.bin",
    "COM1",
    "com9",
    "LPT3",
    "lpt8.txt",
    "name\0x",
    "a\tb",
])
def test_unsafe_names_are_rejected(name):
    clean, reason = validate_component(name)
    assert clean is None, f"{name!r} should be rejected, got {clean!r}: {reason}"


def test_drive_qualified_never_discards_root(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    joined, reason = safe_join(root, "C:\\evil.txt")
    assert joined is None, f"drive-qualified must not discard root, got {joined!r}"
    assert reason


def test_safe_join_containment(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    joined, reason = safe_join(root, "note.txt")
    assert joined == os.path.join(root, "note.txt")
    assert reason == ""


def test_safe_join_cannot_escape_via_traversal(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    outside = str(tmp_path / "outside")
    os.makedirs(outside)
    for name in ("..", "../x", "..\\x", "..\\..\\x"):
        joined, reason = safe_join(root, name)
        assert joined is None, f"{name!r} escaped: {joined!r}"
        assert reason


def test_is_within_uses_canonical_paths(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    outside = str(tmp_path / "root_evil")
    os.makedirs(outside)
    # root_evil is a sibling, not inside root — a string-prefix check would
    # wrongly accept it.
    assert is_within(root, os.path.join(root, "child")) is True
    assert is_within(root, root) is True
    assert is_within(root, outside) is False
    assert is_within(root, os.path.join(root, "..", "root", "child")) is True
    assert is_within(root, os.path.join(root, "..", "outside")) is False


def test_case_insensitive_drive_letter(tmp_path):
    root = str(tmp_path / "ROOT")
    os.makedirs(root)
    # normcase() on Windows lowercases; a candidate written with a different
    # case must still be reported inside.
    assert is_within(root, os.path.join(root, "Child")) is True


def test_nested_traversal_in_component(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    joined, reason = safe_join(root, "a\\..\\..\\x")
    assert joined is None
    assert reason


def test_no_file_is_written_outside_root(tmp_path):
    root = str(tmp_path / "root")
    outside = str(tmp_path / "outside")
    os.makedirs(root)
    os.makedirs(outside)
    for name in ("..\\..\\evil.txt", "C:\\evil.txt", "..", "CON.txt"):
        joined, reason = safe_join(root, name)
        assert joined is None, (name, joined)
    assert os.listdir(outside) == []


def test_empty_captured_root_identity_fails_closed(tmp_path):
    root = str(tmp_path / "root")
    os.makedirs(root)
    assert is_within_captured_root(root, "", os.path.join(root, "file.txt")) is False


# ---------------------------------------------------------------------------
# Filesystem-name codec: fs_component / alloc_fs_names (Phase-1 second pass).
# ---------------------------------------------------------------------------


class TestFsComponent:
    """Display name -> safe single filesystem component, preserving Unicode."""

    @pytest.mark.parametrize("name", [
        "normal", "with spaces", "Проект", "Ülesanne", "日本語",
        "emoji 🎯 ok", "dots.in.middle",
    ])
    def test_valid_names_are_preserved_verbatim(self, name):
        comp, needed = fs_component(name)
        assert needed is False
        assert comp == name

    @pytest.mark.parametrize("name", [
        "..", "../x", "..\\x", "C:\\evil", "c:/evil", "\\abs", "/abs",
        "\\\\server\\share", "A:B", "A?B", "CON", "nul", "name\x00ctrl",
        "a/b",
    ])
    def test_hostile_names_are_encoded_not_aliased(self, name):
        comp, needed = fs_component(name)
        assert needed is True
        assert validate_component(comp)[0] == comp, comp
        # the digest makes the encoding injective in practice
        comp2, _ = fs_component(name)
        assert comp2 == comp                     # deterministic
        other, _ = fs_component("some other name")
        assert comp != other

    def test_trailing_dot_space_is_normalized_not_aliased(self):
        # validate_component already strips trailing dots/spaces, so the
        # codec keeps the normalized plain name and stays contained
        comp, needed = fs_component("trailing. ")
        assert needed is False
        assert comp == "trailing"
        assert validate_component(comp)[0] == comp

    def test_distinct_logical_names_never_collapse(self):
        a, _ = fs_component("..")
        b, _ = fs_component("...")               # both sanitize to nothing
        assert a != b
        c, _ = fs_component("a:b")
        d, _ = fs_component("a?b")
        assert c != d
        e, _ = fs_component("CON")
        f, _ = fs_component("con")
        assert e != f

    def test_readable_prefix_is_kept(self):
        comp, _ = fs_component("..\\..\\project alpha")
        assert comp.startswith(".._.._project alpha_")

    def test_long_names_stay_distinct(self):
        long_a = "A" * 200 + " one"
        long_b = "A" * 200 + " two"
        a, _ = fs_component(long_a)
        b, _ = fs_component(long_b)
        assert a != b


class TestAllocFsNames:
    def test_case_only_names_are_disambiguated(self):
        out = alloc_fs_names(["Project", "project"])
        assert len(set(os.path.normcase(v) for v in out.values())) == 2
        assert out["Project"] == "Project"
        assert out["project"] != "project"      # hashed, never overwrites

    def test_deterministic_for_the_same_set(self):
        names = ["Code", "Text", "A:B", "..", "日本語", "project", "Project"]
        out1 = alloc_fs_names(names)
        out2 = alloc_fs_names(names)
        assert out1 == out2

    def test_distinct_names_never_share_a_component(self):
        names = ["a:b", "a?b", "a<b", "a>b", "CON", "con", "..", "...",
                 "project", "Project", "Проект", "ПРОЕКТ",
                 "x" * 200 + "1", "x" * 200 + "2"]
        out = alloc_fs_names(names)
        comps = [os.path.normcase(v) for v in out.values()]
        assert len(comps) == len(set(comps)), "silent collision in allocator"
        assert len(out) == len(names)

    def test_components_are_safe_and_contained(self, tmp_path):
        root = str(tmp_path / "syncroot")
        os.makedirs(root)
        names = ["..", "../outside", "..\\outside", "C:\\evil", "CON",
                 "A:B", "trailing. ", "normal"]
        out = alloc_fs_names(names)
        for comp in out.values():
            assert validate_component(comp)[0] == comp
            assert is_within(root, os.path.join(root, comp))
        # and no component escapes to the parent
        parent = str(tmp_path)
        before = sorted(os.listdir(parent))
        for comp in out.values():
            os.makedirs(os.path.join(root, comp), exist_ok=True)
        assert sorted(os.listdir(parent)) == before


def _junction_ok():
    """Can we create a directory junction/symlink on this machine?"""
    import tempfile
    try:
        base = tempfile.mkdtemp()
        target = tempfile.mkdtemp()
        link = os.path.join(base, "j")
        os.symlink(target, link, target_is_directory=True)
        os.rmdir(link)
        os.rmdir(base)
        os.rmdir(target)
        return True
    except (OSError, NotImplementedError):
        return False


_JUNCTION_OK = _junction_ok()


@pytest.mark.skipif(not _JUNCTION_OK, reason="cannot create junctions/symlinks")
class TestReparseContainment:
    """Phase-6: lexical containment must not report a junction that resolves
    outside the root as 'inside'."""

    def test_junction_escape_is_rejected(self, tmp_path):
        root = str(tmp_path / "root")
        os.makedirs(root)
        outside = str(tmp_path / "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(root, "jump"),
                   target_is_directory=True)
        cand = os.path.join(root, "jump", "file.md")
        assert is_within(root, cand) is True         # lexical: yes
        assert is_within_resolved(root, cand) is False  # real: escaped

    def test_ordinary_nested_directory_passes(self, tmp_path):
        root = str(tmp_path / "root")
        sub = os.path.join(root, "a", "b")
        os.makedirs(sub)
        assert is_within_resolved(root, os.path.join(sub, "file.md"))

    def test_junction_inside_root_passes(self, tmp_path):
        root = str(tmp_path / "root")
        real = os.path.join(root, "real")
        os.makedirs(real)
        os.symlink(real, os.path.join(root, "alias"),
                   target_is_directory=True)
        assert is_within_resolved(root, os.path.join(root, "alias", "file.md"))

    def test_root_chosen_through_an_alias(self, tmp_path):
        real = os.path.join(str(tmp_path), "real")
        os.makedirs(real)
        alias = os.path.join(str(tmp_path), "alias_root")
        os.symlink(real, alias, target_is_directory=True)
        assert is_within_resolved(alias, os.path.join(alias, "file.md"))

    def test_replacing_root_itself_invalidates_captured_identity(self, tmp_path):
        root = str(tmp_path / "root")
        outside = str(tmp_path / "outside")
        os.makedirs(root)
        os.makedirs(outside)
        identity = capture_resolved_root(root)
        os.rmdir(root)
        os.symlink(outside, root, target_is_directory=True)

        candidate = os.path.join(root, "escaped.txt")
        assert is_within_resolved(root, candidate) is True
        assert is_within_captured_root(root, identity, candidate) is False
