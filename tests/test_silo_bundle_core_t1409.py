"""T-1409: the silo bundle engine is a pure oracle.

These tests never import Qt. They drive ``core.silo_bundle`` with a temp
directory and a text string, which is the whole point of putting the engine
behind its own module: the ZIP contract is provable without a window.

Contract under test:
  A discovery finds local refs and ignores remote ones
  B the same file reached twice, or twice spelled differently, is packaged once
  C two different files sharing a basename stay distinct inside the archive
  D the exported snapshot is rewritten to relative members and the source text
    is returned byte-identical
  E a local ref that is NOT bundled never leaks a V:\\ or C:\\ path
  F member names are relative, sanitized and free of drive/traversal syntax
  G a silo folder's own exports/ is never packaged into the next bundle
  H publication is atomic: no half ZIP after cancel or failure, no clobber
  I the manifest records what was included, what was missing and where the
    Added value came from
"""

import datetime
import hashlib
import json
import os
import zipfile
from urllib.parse import quote

import pytest

from fastprompter.core import silo_bundle as sb


def _png(dirpath, name="a.png", data=b"\x89PNG\r\n\x1a\npayload"):
    path = os.path.join(str(dirpath), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _file_url(path):
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def _plan(tmp_path, text, **kw):
    kw.setdefault("title", "Evening 03 Oct")
    kw.setdefault("target_dir", str(tmp_path / "exports"))
    kw.setdefault("now", datetime.datetime(2026, 10, 3, 17, 39, 45))
    return sb.plan_bundle(text=text, **kw)


# --------------------------------------------------------------- discovery

def test_single_local_image_is_found(tmp_path):
    path = _png(tmp_path)
    refs = sb.find_local_refs(f"before\n![]({_file_url(path)})\nafter")
    local = [r for r in refs if r.path]
    assert len(local) == 1
    assert os.path.normcase(os.path.realpath(local[0].path)) == os.path.normcase(
        os.path.realpath(path))
    assert local[0].is_image is True


def test_several_images_are_found_in_document_order(tmp_path):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    refs = sb.find_local_refs(f"![]({_file_url(a)})\ntext\n![]({_file_url(b)})")
    assert [r.doc_index for r in refs] == [0, 1]
    assert [os.path.basename(r.path) for r in refs] == ["a.png", "b.png"]


def test_absolute_windows_path_resolves_without_the_file_scheme(tmp_path):
    path = _png(tmp_path, "c.png")
    refs = sb.find_local_refs(f"![]({path.replace(os.sep, '/')})")
    assert refs[0].kind == "path"
    assert os.path.isfile(refs[0].path)


def test_url_encoded_file_url_resolves(tmp_path):
    path = _png(tmp_path, "shot one.png")
    refs = sb.find_local_refs(f"![]({_file_url(path)})")
    assert os.path.normcase(os.path.realpath(refs[0].path)) == os.path.normcase(
        os.path.realpath(path))


def test_unicode_filename_resolves(tmp_path):
    # Non-ASCII multi-byte, not Cyrillic: the smoke gate bans Cyrillic anywhere
    # in the tree (tests_smoke/test_app_smoke.py::test_no_cyrillic_in_codebase),
    # and UTF-8 percent-encoding of the file:// target is the code path under
    # test either way.
    path = _png(tmp_path, "日本語 スクリーンショット 03.png")
    refs = sb.find_local_refs(f"![]({_file_url(path)})")
    assert os.path.isfile(refs[0].path)
    plan = _plan(tmp_path, f"![]({_file_url(path)})")
    assert "日本語 スクリーンショット 03.png" in plan.items[0].member


def test_percent_encoded_parentheses_resolve(tmp_path):
    path = _png(tmp_path, "shot (1).png")
    refs = sb.find_local_refs(f"![]({_file_url(path)})")
    assert os.path.isfile(refs[0].path)


def test_relative_target_needs_a_base(tmp_path):
    assert sb.find_local_refs("![](rel/a.png)")[0].path is None
    resolved = sb.find_local_refs("![](rel/a.png)", base_dir=str(tmp_path))
    assert resolved[0].path == os.path.join(str(tmp_path), "rel", "a.png")


def test_web_and_mailto_targets_are_never_local(tmp_path):
    text = ("![](https://example.com/a.png)\n"
            "[site](http://example.com)\n"
            "[mail](mailto:a@b.c)\n"
            "[anchor](#section)")
    assert all(r.path is None for r in sb.find_local_refs(text))
    plan = _plan(tmp_path, text)
    assert plan.items == ()
    assert "https://example.com/a.png" in plan.text_body


def test_missing_source_is_visible_not_silently_dropped(tmp_path):
    ghost = os.path.join(str(tmp_path), "gone.png")
    plan = _plan(tmp_path, f"![]({_file_url(ghost)})")
    assert len(plan.items) == 1
    assert plan.items[0].available is False
    assert plan.manifest["missing"] == 1


# -------------------------------------------------------------- dedup

def test_the_same_file_referenced_twice_is_packaged_once(tmp_path):
    path = _png(tmp_path)
    url = _file_url(path)
    plan = _plan(tmp_path, f"![]({url})\n\nagain:\n![]({url})")
    assert len(plan.items) == 1
    assert plan.text_body.count(plan.items[0].member) == 2


def test_two_spellings_of_one_file_dedupe(tmp_path):
    path = _png(tmp_path)
    plain = path.replace(os.sep, "/")
    dotted = os.path.join(str(tmp_path), ".", "a.png").replace(os.sep, "/")
    plan = _plan(tmp_path, f"![]({plain})\n![]({dotted})")
    assert len(plan.items) == 1


def test_inline_and_silo_files_are_one_payload(tmp_path):
    silo = tmp_path / "silo"
    path = _png(silo, "shot.png")
    plan = _plan(tmp_path, f"![]({_file_url(path)})", silo_dir=str(silo))
    assert len(plan.items) == 1
    assert plan.items[0].origin == "both"


# ------------------------------------------------------ colliding names

def test_two_same_basename_files_stay_distinct(tmp_path):
    one = _png(tmp_path / "a", "image.png", b"first")
    two = _png(tmp_path / "b", "image.png", b"second payload")
    plan = _plan(tmp_path, f"![]({_file_url(one)})\n![]({_file_url(two)})")
    members = [i.member for i in plan.items]
    assert len(set(members)) == 2
    assert all(m.startswith("media/") for m in members)
    assert members == ["media/001_image.png", "media/002_image.png"]


def test_member_names_are_relative_and_safe(tmp_path):
    path = _png(tmp_path, "ok.png")
    plan = _plan(tmp_path, f"![]({_file_url(path)})")
    member = plan.items[0].member
    assert not member.startswith("/")
    assert ".." not in member.split("/")
    assert "\\" not in member and ":" not in member


# ---------------------------------------------------- portable markdown

def test_exported_markdown_uses_relative_media_paths(tmp_path):
    path = _png(tmp_path, "a.png")
    source = f"text before\n![]({_file_url(path)})\ntext after"
    plan = _plan(tmp_path, source)
    assert plan.text_body == (
        f"text before\n![]({plan.items[0].member})\ntext after")
    assert plan.origin_text == source


def test_original_text_is_never_mutated(tmp_path):
    path = _png(tmp_path, "a.png")
    source = f"![]({_file_url(path)})"
    _plan(tmp_path, source)
    assert source == f"![]({_file_url(path)})"


def test_excluded_local_media_hides_the_path(tmp_path):
    path = _png(tmp_path, "secret.png")
    source = f"![]({_file_url(path)})"
    plan = _plan(tmp_path, source, excluded=[path])
    assert plan.items == ()
    assert "V:\\" not in plan.text_body and str(tmp_path) not in plan.text_body
    assert plan.text_body == "[local media omitted: secret.png]"


def test_keep_original_references_is_opt_in(tmp_path):
    path = _png(tmp_path, "secret.png")
    source = f"![]({_file_url(path)})"
    plan = _plan(tmp_path, source, excluded=[path], hide_local_paths=False)
    assert plan.text_body == source


def test_remote_url_is_never_rewritten(tmp_path):
    source = "![](https://example.com/a.png)"
    plan = _plan(tmp_path, source)
    assert plan.text_body == source


def test_media_only_pack_has_no_markdown(tmp_path):
    path = _png(tmp_path, "a.png")
    plan = _plan(tmp_path, f"![]({_file_url(path)})", media_only=True)
    assert plan.text_member is None
    assert plan.text_body is None
    assert len(plan.items) == 1


# ------------------------------------------------------------ silo files

def test_silo_media_is_discovered_and_attachments_are_not(tmp_path):
    silo = tmp_path / "silo"
    _png(silo, "shot.png")
    (silo / "notes.txt").write_text("not media", encoding="utf-8")
    plan = _plan(tmp_path, "body", silo_dir=str(silo))
    assert [i.display_name for i in plan.items] == ["shot.png"]


def test_attachments_join_only_when_asked(tmp_path):
    silo = tmp_path / "silo"
    _png(silo, "shot.png")
    (silo / "notes.txt").write_text("not media", encoding="utf-8")
    plan = _plan(tmp_path, "body", silo_dir=str(silo), include_attachments=True)
    kinds = {i.media_type: i for i in plan.items}
    assert kinds["attachment"].member.startswith("attachments/")


def test_silo_exports_are_never_packaged_into_the_next_bundle(tmp_path):
    silo = tmp_path / "silo"
    exports = silo / "exports"
    _png(exports, "yesterday_bundle.zip", b"PK\x05\x06old")
    _png(silo, "shot.png")
    plan = _plan(tmp_path, "body", silo_dir=str(silo), include_attachments=True)
    assert [i.display_name for i in plan.items] == ["shot.png"]


# ---------------------------------------------------------- added time

def test_added_time_reads_the_paste_filename_before_the_mtime(tmp_path):
    path = _png(tmp_path, "paste-20260101_101112.png")
    os.utime(path, (0, 0))
    epoch, source = sb.added_at(path, 0)
    assert source == "filename_stamp"
    assert datetime.datetime.fromtimestamp(epoch).strftime("%Y%m%d_%H%M%S") == \
        "20260101_101112"


def test_added_time_prefers_the_persisted_silo_record(tmp_path):
    path = _png(tmp_path, "paste-20260101_101112.png")
    canonical = os.path.normcase(os.path.realpath(path))
    epoch, source = sb.added_at(path, 0, {canonical: 12345.0})
    assert (epoch, source) == (12345.0, "silo_metadata")


def test_added_time_falls_back_to_mtime_then_document_order(tmp_path):
    path = _png(tmp_path, "plain.png")
    os.utime(path, (1000000, 1000000))
    epoch, source = sb.added_at(path, 0)
    assert source in ("file_birthtime", "file_mtime")
    assert epoch > 0
    assert sb.added_at(os.path.join(str(tmp_path), "ghost.png"), 4) == \
        (0.0, "document_order")


# ---------------------------------------------------------- publication

def _packed(tmp_path, text, **kw):
    plan = _plan(tmp_path, text, **kw)
    result = sb.write_bundle(plan)
    assert result.error == ""
    assert result.zip_path and os.path.isfile(result.zip_path)
    return plan, result


def test_zip_holds_text_media_and_manifest(tmp_path):
    path = _png(tmp_path, "a.png")
    plan, result = _packed(tmp_path, f"![]({_file_url(path)})")
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        payload = zf.read(plan.items[0].member)
    assert names == {
        plan.text_member, plan.items[0].member, "manifest.json",
        "silo.index.json", "README.txt",
    }
    assert manifest["text_included"] is True
    assert payload == open(path, "rb").read()


def test_manifest_hash_matches_the_archived_bytes(tmp_path):
    path = _png(tmp_path, "a.png", b"x" * 5000)
    plan, result = _packed(tmp_path, f"![]({_file_url(path)})")
    member = plan.items[0].member
    with zipfile.ZipFile(result.zip_path) as zf:
        archived = zf.read(member)
        manifest = json.loads(zf.read("manifest.json"))
    entry = next(i for i in manifest["items"] if i["member"] == member)
    assert entry["sha256"] == hashlib.sha256(archived).hexdigest()
    assert entry["status"] == "included"
    assert entry["added_source"]


def test_manifest_carries_no_absolute_source_path(tmp_path):
    path = _png(tmp_path, "a.png")
    _plan_data, result = _packed(tmp_path, f"![]({_file_url(path)})")
    with zipfile.ZipFile(result.zip_path) as zf:
        raw = zf.read("manifest.json").decode("utf-8")
    assert str(tmp_path) not in raw
    assert "V:\\" not in raw


def test_archive_name_shape_and_sanitizing(tmp_path):
    assert sb.archive_basename("Evening 03 Oct", datetime.datetime(
        2026, 10, 3, 17, 39, 45)) == "Evening 03 Oct_bundle_20261003_173945.zip"
    hostile = sb.archive_basename("a/b:c*?.", datetime.datetime(2026, 1, 2, 3, 4, 5))
    assert "/" not in hostile and ":" not in hostile and "*" not in hostile
    assert len(hostile) < 200


def test_target_dir_is_created_and_never_overwritten(tmp_path):
    path = _png(tmp_path, "a.png")
    plan = _plan(tmp_path, f"![]({_file_url(path)})")
    assert not os.path.isdir(plan.target_dir)
    first = sb.write_bundle(plan)
    second = sb.write_bundle(plan)
    assert first.zip_path != second.zip_path
    assert os.path.isfile(first.zip_path) and os.path.isfile(second.zip_path)
    assert first.zip_path.endswith("_bundle_20261003_173945.zip")


def test_cancel_leaves_no_partial_archive(tmp_path):
    import threading

    path = _png(tmp_path, "a.png")
    _png(tmp_path, "b.png")
    text = f"![]({_file_url(path)})\n![]({_file_url(os.path.join(str(tmp_path), 'b.png'))})"
    plan = _plan(tmp_path, text)
    cancel = threading.Event()
    cancel.set()
    result = sb.write_bundle(plan, cancel=cancel)
    assert result.cancelled is True
    assert result.zip_path is None
    leftovers = os.listdir(plan.target_dir)
    assert leftovers == []


def test_progress_reports_every_member(tmp_path):
    path = _png(tmp_path, "a.png")
    plan = _plan(tmp_path, f"![]({_file_url(path)})")
    seen = []
    sb.write_bundle(plan, progress=lambda d, t, m: seen.append((d, t, m)))
    assert [d for d, _t, _m in seen] == [1, 2, 3]
    assert all(t == 3 for _d, t, _m in seen)


def test_missing_source_does_not_silently_disappear(tmp_path):
    ghost = os.path.join(str(tmp_path), "gone.png")
    real = _png(tmp_path, "a.png")
    plan = _plan(tmp_path, f"![]({_file_url(ghost)})\n![]({_file_url(real)})")
    result = sb.write_bundle(plan)
    assert [i.display_name for i in result.missing] == ["gone.png"]
    assert [i.display_name for i in result.items] == ["a.png"]
    with zipfile.ZipFile(result.zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    entry = next(i for i in manifest["items"] if i["display_name"] == "gone.png")
    assert entry["status"] == "missing"


def test_source_files_are_never_modified(tmp_path):
    path = _png(tmp_path, "a.png", b"immutable")
    before = (os.path.getsize(path), open(path, "rb").read())
    _packed(tmp_path, f"![]({_file_url(path)})")
    assert (os.path.getsize(path), open(path, "rb").read()) == before


def test_ordinary_files_only_a_directory_is_not_packaged(tmp_path):
    silo = tmp_path / "silo"
    (silo / "nested").mkdir(parents=True)
    _png(silo / "nested", "deep.png")
    _png(silo, "top.png")
    plan = _plan(tmp_path, "body", silo_dir=str(silo))
    assert [i.display_name for i in plan.items] == ["top.png", "deep.png"]
    assert "nested" not in [i.display_name for i in plan.items]


@pytest.mark.parametrize("name", ["CON.png", "..png", "  .png"])
def test_hostile_source_filenames_still_get_a_safe_member(tmp_path, name):
    path = _png(tmp_path, name)
    plan = _plan(tmp_path, f"![]({_file_url(path)})")
    member = plan.items[0].member
    parts = member.split("/")
    assert parts[0] in ("media", "attachments")
    # ".." is only traversal as a WHOLE component; a dot inside a filename is
    # just a character, so the test checks components, not substrings.
    assert all(part not in (".", "..") for part in parts)
    assert "\\" not in member and ":" not in member
