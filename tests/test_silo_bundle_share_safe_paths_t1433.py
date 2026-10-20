"""Share-safe bundle privacy — one control per path class (T-1433 privacy).

A generated share bundle is handed to other people, so it may never disclose an
absolute local filesystem path through generated metadata. The redaction ran as
one token across every path class; this module pins that each class has its own
control AND its own negative control, because a control that eats ordinary
prose destroys the content it was meant to protect.

Classes (each a positive control and a negative control):

    1. Windows drive path      C:\\Users\\Bob\\My Documents\\secret file.txt
    2. UNC path                \\\\server\\share\\Private Folder\\a b.txt
    3. POSIX absolute path     /home/bob/private/secret.txt
    4. file:// URL              file:///home/bob/private/secret%20file.txt
    5. spaces + Unicode         C:\\Users\\Bob\\Na\u00efve caf\u00e9\\\u043f\u043b\u0430\u0442\u0430.txt
    6. a path embedded in otherwise harmless prose, after a remote URL and
       inside a Markdown target

Never redacted (negative controls):

    * http:// / https:// targets
    * ordinary prose that merely contains a slash (``Version 3/4``)
    * "C:" with no path after it
    * POSIX-shaped but non-workstation text (``/api/v1/endpoint``)

Final rule from the module: over-redacting a path is the safe side, so the
assertions above check that NOTHING local survives, and the negative controls
check that nothing legible is destroyed either.
"""

import json
import os
import zipfile
from urllib.parse import quote

import pytest

from fastprompter.core import silo_bundle as sb

BS = chr(92)
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png(dirpath, name="a.png"):
    path = os.path.join(str(dirpath), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(PNG_BYTES)
    return path


def _file_url(path):
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def _pack(tmp_path, text, **kw):
    kw.setdefault("title", "Evening 03 Oct")
    kw.setdefault("target_dir", str(tmp_path / "exports"))
    plan = sb.plan_bundle(text=text, **kw)
    return plan, sb.write_bundle(plan)


def _read_member(zip_path, member):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member).decode("utf-8")


# ---------------------------------------------------------------------------
# One control per class of local workstation path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", ["A", "B", "C", "D", "E", "F"])
def test_every_path_class_is_redacted(cls):
    """Every class of local path is redacted, whatever else the text holds."""
    if cls == "A":  # Windows drive path, with spaces
        text = f"notes C:{BS}Users{BS}Bob{BS}My Documents{BS}secret file.txt end"
    elif cls == "B":  # UNC path, with spaces
        text = f"notes {BS}{BS}server{BS}share{BS}Private Folder{BS}a b.txt end"
    elif cls == "C":  # POSIX absolute path
        text = "notes /home/bob/private/secret.txt end"
    elif cls == "D":  # file:// URL, percent-encoded space
        text = "notes file:///home/bob/private/secret%20file.txt end"
    elif cls == "E":  # spaces + non-ASCII (folders and file name)
        text = "unicode C:" + BS + "Users" + BS + "Bob" + BS + "Na\u00efve caf\u00e9" \
            + BS + "\u043f\u043b\u0430\u0442\u0430.txt end"
    else:  # a path embedded in harmless prose, behind a remote URL
        text = ("see https://example.com/a/b.png then C:" + BS + "Users"
                + BS + "Bob" + BS + "a.txt then more prose")

    out, count = sb.sanitize_residual_local_paths(text)
    assert count >= 1
    assert "[local path omitted" in out
    # The redacted token keeps NO leading structure behind it: either the whole
    # absolute path or the bare filename is all that may remain.
    for residue in (
        f"C:{BS}Users{BS}Bob",
        f"{BS}{BS}server{BS}share",
        "/home/bob/private",
        "file:///home",
    ):
        assert residue not in out
    # Ordinary prose around the redaction survives verbatim.
    assert out.startswith(("notes ", "unicode ", "see "))


def test_markdown_targets_of_every_local_class_are_redacted():
    """A link/image target is atomic, so it is redacted as one span."""
    posix = "see [doc](/home/bob/x.txt) and ![i](</home/bob/my pic.png>) here"
    win = f"see [doc](C:{BS}Users{BS}Bob{BS}x.txt) here"
    url = "see [doc](file:///V:/tools/app.exe) here"
    for text in (posix, win, url):
        out, count = sb.sanitize_residual_local_paths(text)
        assert count >= 1, text
        assert "[local path omitted" in out, text
        for residue in ("/home/bob", f"C:{BS}Users{BS}Bob", "file:///"):
            assert residue not in out, text


def test_a_path_after_a_remote_url_is_still_redacted():
    """The walk must not stop at a remote URL and leave everything after it."""
    text = ("logo https://example.com/logo.png and path C:" + BS + "Users"
            + BS + "Bob" + BS + "a.txt at the end")
    out, count = sb.sanitize_residual_local_paths(text)
    assert count == 1
    assert "https://example.com/logo.png" in out     # remote URL untouched
    assert f"C:{BS}Users{BS}Bob" not in out           # the path after it is not


# ---------------------------------------------------------------------------
# Negative controls: ordinary user content must survive.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "https://example.com/a/b.png stays",
    "http://example.com/x stays",
    "Version 3/4 done",
    "notes C: drive only, no path",
    "notes /api/v1/endpoint stays",
    "notes ./relative/path/file.txt stays",
    "notes ../parent/file.txt stays",
    "notes media/001_shot.png stays",
    "# Heading with a slash: and/or, neither",
])
def test_ordinary_content_is_preserved(text):
    out, count = sb.sanitize_residual_local_paths(text)
    assert count == 0, text
    assert out == text, text


def test_redaction_preserves_the_words_around_the_path():
    """The prose after a redacted path is not glued to the omission marker."""
    text = f"move C:{BS}Users{BS}Bob{BS}a.txt please and keep this sentence"
    out, count = sb.sanitize_residual_local_paths(text)
    assert count == 1
    assert out == "move [local path omitted: a.txt] please and keep this sentence"


def test_trailing_punctuation_after_a_path_is_preserved():
    text = f"see C:{BS}Users{BS}Bob{BS}a.txt, then continue"
    out, count = sb.sanitize_residual_local_paths(text)
    assert count == 1
    assert out == "see [local path omitted: a.txt], then continue"


# ---------------------------------------------------------------------------
# End-to-end: the privacy boundary holds on the published surfaces.
# ---------------------------------------------------------------------------


def test_published_surfaces_carry_no_local_path(tmp_path):
    """A hostile title and a hostile document name no absolute path."""
    shot = _png(tmp_path, "shot.png")
    hostile_title = f"Notes from {tmp_path}"
    hostile_doc = (
        f"# {hostile_title}\n\n"
        f"![]({_file_url(shot)})\n\n"
        f"{BS*2}server{BS}share{BS}x.txt\n"
        "/home/bob/private.txt\n"
    )
    _plan, result = _pack(tmp_path, hostile_doc, title=hostile_title)

    surfaces = {
        "manifest.json": _read_member(result.zip_path, "manifest.json"),
        "README.txt": _read_member(result.zip_path, "README.txt"),
        "silo.index.json": _read_member(result.zip_path, "silo.index.json"),
    }
    doc_member = json.loads(surfaces["manifest.json"]).get("canonical_source")
    if doc_member:
        surfaces[doc_member] = _read_member(result.zip_path, doc_member)

    for name, surface in surfaces.items():
        assert str(tmp_path) not in surface, name
        assert f"{BS}{BS}server{BS}share" not in surface, name
        assert "/home/bob" not in surface, name
        assert "file:///" not in surface, name

    # ... while the artifact identity is stated on the readable surface.
    assert f"Artifact ID: {result.artifact_id}" in surfaces["README.txt"]
    manifest = json.loads(surfaces["manifest.json"])
    assert manifest["artifact_identity"]["id"] == result.artifact_id
    assert manifest["artifact_identity"]["content_fingerprint"] == manifest["content_fingerprint"]
