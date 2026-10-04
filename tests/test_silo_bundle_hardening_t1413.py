"""T-1413 — Silo bundle truth, portability and ownership hardening.

Initial RED regression suite covering:
A. Media target with spaces and parentheses
B. Late source disappearance before/during write_bundle
C. Nested silo media discovery
D. Retention safety: foreign ZIP at stale history path must not be deleted
E. Tampered reuse candidate of identical size rejected
F. Leading primary title + divider does not manufacture empty group
G. Tilde fences (~~~) do not create requirement structure
H. Conservative free-text paragraphs split on blank lines
"""

from __future__ import annotations

import json
import os
import zipfile

from fastprompter.core import silo_bundle as sb
from fastprompter.core import silo_index as si


def _png(dirpath, name="a.png", data=b"\x89PNG\r\n\x1a\npayload"):
    path = os.path.join(str(dirpath), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _file_url(path: str) -> str:
    # URL encoded file path
    from urllib.parse import quote
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def _read_bundle(zip_path: str):
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        index_data = None
        if "silo.index.json" in zf.namelist():
            index_data = json.loads(zf.read("silo.index.json").decode("utf-8"))
        readme = None
        if "README.txt" in zf.namelist():
            readme = zf.read("README.txt").decode("utf-8")
        members = set(zf.namelist())
    return manifest, index_data, readme, members


# --- A. Media target with spaces and parentheses -----------------------

def test_a_media_target_with_spaces_and_parentheses(tmp_path):
    shot = _png(tmp_path, "shot one (final).png")
    text = f"• Test requirement\n  ![]({_file_url(shot)})\n"
    plan = sb.plan_bundle(
        text=text,
        title="Target Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    expected_member = "media/001_shot one (final).png"
    assert expected_member in members

    # Requirement must own the media member
    req = index_data["requirements"][0]
    assert req["media"] == [expected_member], f"Expected media to be linked, got: {req['media']}"
    assert expected_member not in index_data["unscoped_media"]

    # Manifest reverse mapping must link back
    item = next(i for i in manifest["items"] if i["member"] == expected_member)
    assert req["id"] in item["linked_requirements"]


# --- B. Late source disappearance ---------------------------------------

def test_b_late_source_disappearance_yields_partial_bundle(tmp_path):
    img_a = _png(tmp_path, "a.png")
    img_b = _png(tmp_path, "b.png")
    text = f"• Keep A\n  ![]({_file_url(img_a)})\n• Lose B\n  ![]({_file_url(img_b)})\n"
    plan = sb.plan_bundle(
        text=text,
        title="Late Vanish Test",
        target_dir=str(tmp_path / "exports"),
    )

    # Vanish image B after planning but before writing
    os.remove(img_b)

    result = sb.write_bundle(plan)
    # Must NOT abort publication with an unhandled exception or index validation failure
    assert result.zip_path is not None, f"Expected partial bundle publication, got error: {result.error}"
    assert len(result.items) == 1
    assert len(result.missing) == 1

    manifest, index_data, readme, members = _read_bundle(result.zip_path)
    assert "media/001_a.png" in members
    assert "media/002_b.png" not in members

    # Requirement for B must record missing_media, not media
    req_b = index_data["requirements"][1]
    assert req_b["media"] == []
    assert "media/002_b.png" in req_b.get("missing_media", [])

    # Manifest status must be truthful
    b_item = next(i for i in manifest["items"] if i["member"] == "media/002_b.png")
    assert b_item["status"] == "missing"
    assert manifest["missing"] == 1
    assert manifest["included"] == 1


# --- C. Nested silo media discovery -------------------------------------

def test_c_nested_silo_media_discovery(tmp_path):
    silo_dir = tmp_path / "silo"
    silo_dir.mkdir()
    _png(silo_dir, "top.png")
    _png(silo_dir / "screens", "nested.png")
    _png(silo_dir / "screens" / "sub", "deep.png")

    files = sb.list_silo_files(str(silo_dir))
    names = [os.path.basename(f) for f in files]
    assert "top.png" in names
    assert "nested.png" in names, "nested file in screens/ was omitted"
    assert "deep.png" in names, "deep nested file was omitted"


# --- D. Retention safety: foreign ZIP must not be deleted ---------------

def test_d_foreign_zip_at_stale_history_path_survives(tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    foreign_zip = str(exports_dir / "custom_bundle_20261001_000000.zip")

    # Create a non-FastPrompter ZIP (e.g. user archive without FastPrompter manifest)
    with zipfile.ZipFile(foreign_zip, "w") as zf:
        zf.writestr("user_notes.txt", "Important user files, not a FastPrompter bundle")

    history_records = [
        {
            "path": str(exports_dir / "newest.zip"),
            "content_fingerprint": "fp_newest",
        },
        {
            "path": foreign_zip,
            "content_fingerprint": "fp_old",
        },
    ]

    kept, pruned = sb.prune_silo_history(
        records=history_records,
        canonical_exports_dir=str(exports_dir),
        keep_versions=1,
    )

    # The foreign zip MUST NOT be deleted from disk
    assert os.path.isfile(foreign_zip), "Retention deleted an unowned / foreign ZIP!"
    assert foreign_zip not in pruned


# --- E. Tampered reuse candidate rejected -------------------------------

def test_e_same_size_tampered_reuse_candidate_rejected(tmp_path):
    shot = _png(tmp_path, "shot.png", b"original_payload_12345")
    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_file_url(shot)})\n",
        title="Tamper Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    original_zip = result.zip_path
    original_size = os.path.getsize(original_zip)
    original_fp = result.fingerprint

    # Tamper with the zip: change bytes inside media member while keeping length identical
    tampered_zip = str(tmp_path / "exports" / "tampered.zip")
    with zipfile.ZipFile(original_zip, "r") as src, zipfile.ZipFile(tampered_zip, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("media/"):
                data = b"tampered_payload_12345"  # same byte length
            dst.writestr(item, data)

    # Candidate should fail verification because member hash does not match manifest
    assert not sb.verify_reuse_candidate(tampered_zip, original_fp, expected_size=original_size)


# --- F. Primary title + divider does not manufacture empty group --------

def test_f_primary_title_and_divider_creates_no_empty_group():
    md = (
        "# FastPrompter: (Evening 03 Oct - 17:39)\n"
        "---\n"
        "• Requirement A\n"
        "• Requirement B\n"
    )
    idx = si.build_silo_index(md, source_member="test.md")
    # Must only produce groups that own requirements
    assert len(idx.groups) == 1
    assert idx.groups[0]["id"] == "GROUP-001"
    for r in idx.requirements:
        assert r.group_id == "GROUP-001"


# --- G. Tilde fences (~~~) do not create requirement structure ----------

def test_g_tilde_fences_do_not_create_structure():
    md = (
        "• Requirement 1\n"
        "~~~\n"
        "- not a bullet inside code\n"
        "---\n"
        "• fake bullet inside code\n"
        "~~~\n"
        "• Requirement 2\n"
    )
    idx = si.build_silo_index(md, source_member="test.md")
    assert len(idx.requirements) == 2
    assert idx.requirements[0]["id"] == "REQ-001"
    assert idx.requirements[1]["id"] == "REQ-002"


# --- H. Conservative free-text paragraphs split on blank lines ----------

def test_h_conservative_free_text_paragraphs_split():
    md = (
        "First cohesive paragraph describing user need A.\n"
        "\n"
        "Second cohesive paragraph describing user need B.\n"
        "\n"
        "Third cohesive paragraph describing user need C.\n"
    )
    idx = si.build_silo_index(md, source_member="test.md")
    assert len(idx.requirements) == 3
    assert "user need A" in idx.requirements[0].text
    assert "user need B" in idx.requirements[1].text
    assert "user need C" in idx.requirements[2].text


# --- Section 34. Portable Markdown Regression Matrix -------------------

def test_section_34_portable_markdown_target_matrix(tmp_path):
    target_names = [
        "simple.png",
        "my screenshot.png",
        "shot (final).png",
        "100% ready.png",
        "hash#name.png",
        "Japanese 画像.png",
        "emoji 🧪.png",
    ]
    lines = ["# Target Matrix Test"]
    for name in target_names:
        p = _png(tmp_path, name)
        lines.append(f"• Requirement for {name}\n  ![]({_file_url(p)})\n")
    # Also add a second reference to the first image
    first_p = os.path.join(str(tmp_path), target_names[0])
    lines.append(f"• Duplicate reference\n  ![]({_file_url(first_p)})\n")

    text = "\n".join(lines)
    plan = sb.plan_bundle(
        text=text,
        title="Matrix Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    # Every target name must roundtrip and be linked to its requirement
    reqs = index_data["requirements"]
    for idx, name in enumerate(target_names):
        req = reqs[idx]
        assert len(req["media"]) == 1
        m_name = req["media"][0]
        assert name in m_name
        assert m_name in members
        assert m_name not in index_data["unscoped_media"]
        # Reverse mapping check
        m_item = next(i for i in manifest["items"] if i["member"] == m_name)
        assert req["id"] in m_item["linked_requirements"]

    # Duplicate ref requirement owns the member too
    dup_req = reqs[-1]
    assert dup_req["media"] == [reqs[0]["media"][0]]


# --- Section 35. Partial Publication Regression Matrix -----------------

def test_section_35_partial_publication_three_images(tmp_path):
    img_a = _png(tmp_path, "img_a.png")
    img_b = _png(tmp_path, "img_b.png")
    img_c = _png(tmp_path, "img_c.png")
    text = (
        f"• Req A\n  ![]({_file_url(img_a)})\n"
        f"• Req B\n  ![]({_file_url(img_b)})\n"
        f"• Req C\n  ![]({_file_url(img_c)})\n"
    )
    plan = sb.plan_bundle(
        text=text,
        title="Three Images Test",
        target_dir=str(tmp_path / "exports"),
    )

    # Image B vanishes right before write_bundle
    os.remove(img_b)

    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    assert len(result.items) == 2
    assert len(result.missing) == 1

    manifest, index_data, readme, members = _read_bundle(result.zip_path)
    assert "media/001_img_a.png" in members
    assert "media/002_img_b.png" not in members
    assert "media/003_img_c.png" in members
    assert manifest["included"] == 2
    assert manifest["missing"] == 1

    req_b = index_data["requirements"][1]
    assert req_b["media"] == []
    assert req_b.get("missing_media") == ["media/002_img_b.png"]
    # No leaked absolute paths in text
    assert str(tmp_path) not in req_b["text"]


# --- Section 36. Retention Ownership Regression Matrix -----------------

def test_section_36_retention_ownership_matrix(tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    # 1. Valid owned schema-4 bundle
    owned_zip = str(exports_dir / "owned_bundle.zip")
    with zipfile.ZipFile(owned_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "producer": "FastPrompter",
            "bundle_kind": "silo_bundle",
            "schema_version": 4,
            "content_fingerprint": "fp_owned",
        }))

    # 2. Valid owned bundle with mismatched fingerprint
    mismatched_zip = str(exports_dir / "mismatched_bundle.zip")
    with zipfile.ZipFile(mismatched_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "producer": "FastPrompter",
            "bundle_kind": "silo_bundle",
            "schema_version": 4,
            "content_fingerprint": "fp_actual",
        }))

    # 3. ZIP without manifest.json
    no_manifest_zip = str(exports_dir / "no_manifest.zip")
    with zipfile.ZipFile(no_manifest_zip, "w") as zf:
        zf.writestr("some_file.txt", "data")

    # 4. ZIP with random manifest.json (no producer, no bundle_kind)
    random_manifest_zip = str(exports_dir / "random_manifest.zip")
    with zipfile.ZipFile(random_manifest_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "OtherApp", "schema_version": 99}))

    # 5. ZIP with producer != FastPrompter
    wrong_producer_zip = str(exports_dir / "wrong_producer.zip")
    with zipfile.ZipFile(wrong_producer_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "producer": "NotFastPrompter",
            "bundle_kind": "silo_bundle",
            "schema_version": 4,
            "content_fingerprint": "fp_wrong_prod",
        }))

    # 6. ZIP with bundle_kind != silo_bundle
    wrong_kind_zip = str(exports_dir / "wrong_kind.zip")
    with zipfile.ZipFile(wrong_kind_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "producer": "FastPrompter",
            "bundle_kind": "other_bundle",
            "schema_version": 4,
            "content_fingerprint": "fp_wrong_kind",
        }))

    # 7. Corrupt ZIP
    corrupt_zip = str(exports_dir / "corrupt.zip")
    with open(corrupt_zip, "wb") as f:
        f.write(b"not a valid zip file header")

    # 8. Missing file
    missing_zip = str(exports_dir / "missing_on_disk.zip")

    # Build history records where all files exceed retention limit (keep_versions = 0)
    records = [
        {"path": owned_zip, "content_fingerprint": "fp_owned"},
        {"path": mismatched_zip, "content_fingerprint": "fp_recorded"},
        {"path": no_manifest_zip, "content_fingerprint": "fp_x"},
        {"path": random_manifest_zip, "content_fingerprint": "fp_y"},
        {"path": wrong_producer_zip, "content_fingerprint": "fp_wrong_prod"},
        {"path": wrong_kind_zip, "content_fingerprint": "fp_wrong_kind"},
        {"path": corrupt_zip, "content_fingerprint": "fp_corrupt"},
        {"path": missing_zip, "content_fingerprint": "fp_missing"},
    ]

    kept, pruned = sb.prune_silo_history(
        records=records,
        canonical_exports_dir=str(exports_dir),
        keep_versions=0,  # Prune all excess
    )

    # ONLY owned_zip may be pruned and deleted from disk!
    assert not os.path.exists(owned_zip), "Valid owned bundle was not pruned"
    assert owned_zip in pruned

    # ALL other files MUST survive!
    assert os.path.exists(mismatched_zip)
    assert os.path.exists(no_manifest_zip)
    assert os.path.exists(random_manifest_zip)
    assert os.path.exists(wrong_producer_zip)
    assert os.path.exists(wrong_kind_zip)
    assert os.path.exists(corrupt_zip)


# --- Section 37. Smart Reuse Regression Matrix -------------------------

def test_section_37_smart_reuse_matrix(tmp_path):
    shot = _png(tmp_path, "screen.png")
    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_file_url(shot)})\n",
        title="Reuse Matrix Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    zip_path = result.zip_path
    fp = result.fingerprint
    size = result.archive_size
    mtime_ns = result.archive_mtime_ns

    # 1. Unchanged current archive: fast reuse
    assert sb.verify_reuse_candidate(zip_path, fp, expected_size=size, expected_mtime_ns=mtime_ns)

    # 2. Archive mtime changed (or unverified mtime): deep integrity verify succeeds
    assert sb.verify_reuse_candidate(zip_path, fp, expected_size=size, expected_mtime_ns=mtime_ns + 999999)

    # 3. Archive media tampered (same size): deep verify fails
    tampered_zip = str(tmp_path / "exports" / "tampered_media.zip")
    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(tampered_zip, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("media/"):
                data = b"x" * len(data)  # replace payload with same length
            dst.writestr(item, data)
    assert not sb.verify_reuse_candidate(tampered_zip, fp, expected_size=size)

    # 4. Manifest tampered (wrong fingerprint): reject reuse
    tampered_man_zip = str(tmp_path / "exports" / "tampered_manifest.zip")
    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(tampered_man_zip, "w") as dst:
        for item in src.infolist():
            if item.filename == "manifest.json":
                m_data = json.loads(src.read(item.filename).decode("utf-8"))
                m_data["content_fingerprint"] = "tampered_fp"
                dst.writestr(item, json.dumps(m_data))
            else:
                dst.writestr(item, src.read(item.filename))
    assert not sb.verify_reuse_candidate(tampered_man_zip, fp)

    # 5. Old schema-3 bundle: rejected for schema-4 smart reuse
    schema3_zip = str(tmp_path / "exports" / "schema3.zip")
    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(schema3_zip, "w") as dst:
        for item in src.infolist():
            if item.filename == "manifest.json":
                m_data = json.loads(src.read(item.filename).decode("utf-8"))
                m_data["schema_version"] = 3
                dst.writestr(item, json.dumps(m_data))
            else:
                dst.writestr(item, src.read(item.filename))
    assert not sb.verify_reuse_candidate(schema3_zip, fp)
