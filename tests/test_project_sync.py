"""Sync-Project core: include/exclude matching, scanning, EOL handling,
safe read/write, slot allocation."""

import os

from fastprompter.core import project_sync as ps

# ------------------------------------------------------- include / exclude


def test_include_extension_list_parsing():
    assert ps.parse_ext_list(".txt .md, py") == [".txt", ".md", ".py"]
    assert ps.parse_ext_list("") == []
    assert ps.parse_ext_list("TXT") == [".txt"]


def test_exclude_matches_path_components():
    assert ps.match_exclude("node_modules/x/y.py", ["node_modules"])
    assert ps.match_exclude("a/b/.git/config", [".git"])
    assert not ps.match_exclude("mynode_modules/x.py", ["node_modules"])


def test_exclude_wildcards_match_basenames():
    assert ps.match_exclude("src/app.min.js", ["*.min.js"])
    assert ps.match_exclude("app.min.js", ["*.min.js"])
    assert not ps.match_exclude("src/app.js", ["*.min.js"])


def test_is_text_file():
    assert ps.is_text_file("readme.md")
    assert ps.is_text_file("src/main.py")
    assert not ps.is_text_file("image.png")
    assert not ps.is_text_file("src/main.py", exclude=["src"])
    assert not ps.is_text_file("notes.txt", include=[".md"])
    assert ps.is_text_file("notes.txt", include=[".txt", ".md"])


def test_resolve_relative_path_rejects_escape_and_accepts_nested(tmp_path):
    root = str(tmp_path)
    assert ps.resolve_relative_path(root, "src/main.py") == os.path.realpath(
        str(tmp_path / "src" / "main.py"))
    assert ps.resolve_relative_path(root, "../outside.txt") is None
    assert ps.resolve_relative_path(root, "/outside.txt") is None


def test_resolve_relative_path_preserves_whitespace_filenames(tmp_path):
    # CORE-006: leading/trailing whitespace is a legal filename character and
    # must NOT be stripped. " lead.txt" and "lead.txt" are distinct entries.
    root = str(tmp_path)
    (tmp_path / "lead.txt").write_text("plain", encoding="utf-8")
    (tmp_path / " lead.txt").write_text("spaced", encoding="utf-8")
    plain = ps.resolve_relative_path(root, "lead.txt")
    spaced = ps.resolve_relative_path(root, " lead.txt")
    assert plain is not None and spaced is not None
    assert plain != spaced
    assert os.path.basename(plain) == "lead.txt"
    assert os.path.basename(spaced) == " lead.txt"
    # Each resolves to its own file and writes affect only that file.
    assert os.path.samefile(plain, str(tmp_path / "lead.txt"))
    assert os.path.samefile(spaced, str(tmp_path / " lead.txt"))


def test_resolve_relative_path_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        return  # symlinks may be disabled on the test host
    assert ps.resolve_relative_path(str(root), "linked/file.txt") is None


# -------------------------------------------------------------- scanning


def test_scan_folder_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\x00")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("c", encoding="utf-8")
    (sub / "d.log").write_text("d", encoding="utf-8")
    files = ps.scan_folder(str(tmp_path))
    assert files == ["a.txt", "b.md", "sub/c.py", "sub/d.log"]


def test_scan_folder_excludes_directories(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    junk = tmp_path / "node_modules"
    junk.mkdir()
    (junk / "b.txt").write_text("b", encoding="utf-8")
    files = ps.scan_folder(str(tmp_path))
    assert files == ["a.txt"]


def test_scan_folder_flat_mode(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b", encoding="utf-8")
    files = ps.scan_folder(str(tmp_path), recursive=False)
    assert files == ["a.txt"]


def test_scan_folder_skips_huge_files(tmp_path):
    (tmp_path / "a.txt").write_text("x" * 1000, encoding="utf-8")
    files = ps.scan_folder(str(tmp_path), max_bytes=100)
    assert files == []


# ------------------------------------------------------------- read / write


def test_read_text_file_normalises_eol(tmp_path):
    p = tmp_path / "crlf.txt"
    p.write_bytes(b"one\r\ntwo\r\nthree\n")
    text, eol, had_bom = ps.read_text_file(str(p))
    assert text == "one\ntwo\nthree\n"
    assert eol == "\r\n"
    assert had_bom is False


def test_read_text_file_removes_utf8_bom(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfhello\n")
    text, eol, had_bom = ps.read_text_file(str(p))
    assert (text, eol, had_bom) == ("hello\n", "\n", True)


def test_read_text_file_binary_and_huge_are_skipped(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\x00\x01\x02")
    assert ps.read_text_file(str(p)) is None
    big = tmp_path / "big.txt"
    big.write_text("x" * 2000, encoding="utf-8")
    assert ps.read_text_file(str(big), max_bytes=100) is None


def test_read_text_file_non_utf8_fails_closed_and_preserves_bytes(tmp_path):
    """W2-002: a cp1251 file is not silently lossy-decoded into U+FFFD and
    later rewritten as UTF-8. It must be skipped, leaving the bytes intact."""
    p = tmp_path / "legacy.txt"
    original = "Привет\r\nмир\r\n".encode("cp1251")
    p.write_bytes(original)
    assert ps.read_text_file(str(p)) is None
    assert p.read_bytes() == original, "source bytes must stay untouched"


def test_write_text_file_applies_eol_and_roundtrips(tmp_path):
    p = tmp_path / "out.txt"
    written = ps.write_text_file(str(p), "one\ntwo\n", eol="\r\n")
    assert written == "one\r\ntwo\r\n"
    assert p.read_bytes() == b"one\r\ntwo\r\n"
    text, eol, had_bom = ps.read_text_file(str(p))
    assert (text, eol, had_bom) == ("one\ntwo\n", "\r\n", False)


def test_write_text_file_preserves_utf8_bom(tmp_path):
    """CORE-007: a FastPrompter edit must not silently drop a UTF-8 BOM."""
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfalpha\r\n")
    text, eol, had_bom = ps.read_text_file(str(p))
    assert (had_bom, eol) == (True, "\r\n")
    # App-side edit appended, written back with the original BOM + CRLF.
    written = ps.write_text_file(str(p), text + "beta\n", eol=eol,
                                 write_bom=had_bom)
    assert written == "alpha\r\nbeta\r\n"
    assert p.read_bytes() == b"\xef\xbb\xbfalpha\r\nbeta\r\n"


def test_write_text_file_adds_no_bom_by_default(tmp_path):
    p = tmp_path / "plain.txt"
    ps.write_text_file(str(p), "hi\n", write_bom=True)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    ps.write_text_file(str(p), "hi\n", write_bom=False)
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_text_file_leaves_no_temp_file(tmp_path):
    p = tmp_path / "out.txt"
    ps.write_text_file(str(p), "hello\n")
    assert not os.path.exists(str(p) + ".fp-sync-tmp")


def test_write_text_file_fails_cleanly_on_bad_dir(tmp_path):
    missing = tmp_path / "nope" / "out.txt"
    assert ps.write_text_file(str(missing), "hello\n") is None


def test_detect_eol_majority():
    assert ps.detect_eol("a\r\nb\r\nc\n") == "\r\n"
    assert ps.detect_eol("a\nb\nc\r\n") == "\n"


# ------------------------------------------------------------- slot mapping


def test_free_slots_starts_at_end_and_honours_cap():
    mapping = {"0": "a.md", "1": "b.md"}
    assert ps.free_slots(mapping, 2, 3) == [2, 3, 4]
    full = {str(i): f"{i}.md" for i in range(100)}
    assert ps.free_slots(full, 100, 5) == []


def test_free_slots_skips_claimed_gaps():
    mapping = {"0": "a.md", "2": "c.md"}
    # slot 1 is claimed, so appending starts at 3
    assert ps.free_slots(mapping, 3, 2) == [3, 4]
