"""Regression tests for the canonical File Container path-safety helpers.

Proves the containment invariants for validate_component / safe_join /
is_within on Windows path semantics: drive-qualified and absolute names must
never discard the container root, ``..`` must never escape, and reserved
Windows names must never be written.
"""

import os

import pytest

from fastprompter.utils.path_safety import (
    is_within,
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
