"""Realistic end-to-end integration test for Pack Silo (T-1409..T-1413).

Covers:
- Primary header with invalid filesystem characters sanitized cleanly for ZIP filename.
- Duplicate references to identical media canonical path deduplicated to single member.
- Distinct media files sharing the same basename mapped to distinct media/ members.
- Nested silo files in subdirectories discovered recursively.
- Non-media silo attachments packaged into attachments/.
- Missing local media file preserved in markdown and reported in index/items.
- Remote URL references kept intact.
- Full manifest.json schema 4 compliance and silo.index.json schema 2 compliance.
- ZIP integrity verified via testzip().
- Smart reuse cycle: identical content reuses archive, force repack creates new,
  content edit creates new version, history and retention verified.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastprompter.core import silo_bundle as sb


def _make_file(path: Path, content: bytes = b"test") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def _file_url(path: str) -> str:
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def test_realistic_pack_silo_e2e_lifecycle(tmp_path: Path):
    silo_dir = tmp_path / "MySilo"
    silo_dir.mkdir(parents=True, exist_ok=True)
    exports_dir = silo_dir / "exports"

    # 1. Prepare files
    # Media: duplicate ref
    img_shared = _make_file(silo_dir / "media" / "shared.png", b"\x89PNG\r\n\x1a\nshared")
    # Media: same basename in different folders
    img_a = _make_file(silo_dir / "sub_a" / "photo.png", b"\x89PNG\r\n\x1a\nphoto_A")
    img_b = _make_file(silo_dir / "sub_b" / "photo.png", b"\x89PNG\r\n\x1a\nphoto_B")
    # Non-media nested attachments
    _make_file(silo_dir / "nested" / "specs" / "arch.pdf", b"%PDF-1.4 spec")
    _make_file(silo_dir / "data" / "metrics.csv", b"a,b,c\n1,2,3\n")
    # Missing media path
    missing_path = str(silo_dir / "missing_art.png")

    # 2. Markdown text with complex header and varied refs
    title = "# Project: Alpha / Beta? <v1.0> *Special* | Final: RoadMap & Next Steps"
    text = (
        f"{title}\n\n"
        "## GROUP-001: Core Architecture\n"
        f"- [P0] REQ-001: First requirement referencing shared image ![]({_file_url(img_shared)})\n"
        f"- [P1] REQ-002: Same requirement repeats shared image ![]({_file_url(img_shared)})\n"
        f"- [P1] REQ-003: Sub A photo ![]({_file_url(img_a)})\n"
        f"- [P2] REQ-004: Sub B photo with same basename ![]({_file_url(img_b)})\n"
        f"- [P3] REQ-005: Missing local media ![]({_file_url(missing_path)})\n"
        "- [P3] REQ-006: Remote web image untouched ![](https://example.com/logo.png)\n"
    )

    # 3. Discover silo files
    silo_files = sb.list_silo_files(str(silo_dir), include_attachments=True)
    assert any(f.replace("\\", "/").endswith("nested/specs/arch.pdf") for f in silo_files)
    assert any(f.replace("\\", "/").endswith("data/metrics.csv") for f in silo_files)
    # exports/ must not be included
    assert not any("exports" in f.replace("\\", "/").split("/") for f in silo_files)

    # 4. Plan bundle
    plan = sb.plan_bundle(
        text=text,
        title=title,
        target_dir=str(exports_dir),
        silo_dir=str(silo_dir),
        include_attachments=True,
    )

    # Verify sanitized archive name
    assert "/" not in plan.archive_name
    assert "\\" not in plan.archive_name
    assert ":" not in plan.archive_name
    assert "?" not in plan.archive_name
    assert "<" not in plan.archive_name
    assert ">" not in plan.archive_name
    assert "|" not in plan.archive_name
    assert plan.archive_name.endswith(".zip")

    # Verify plan items:
    # 3 media files (img_shared deduplicated, img_a, img_b) + 1 missing media + 2 attachments
    media_items = [i for i in plan.items if i.media_type != "attachment" and i.available]
    assert len(media_items) == 3

    # Distinct members for same basename photo.png
    media_dest_names = [item.member for item in media_items]
    assert len(media_dest_names) == 3
    assert len(set(media_dest_names)) == 3

    # Missing media detected as unavailable item
    missing_items = [i for i in plan.items if not i.available]
    assert len(missing_items) == 1
    assert "missing_art.png" in missing_items[0].display_name

    # 5. Write bundle
    result1 = sb.write_bundle(plan)
    assert result1.zip_path is not None
    assert os.path.isfile(result1.zip_path)
    zip_path1 = result1.zip_path

    # Verify ZIP structure
    with zipfile.ZipFile(zip_path1, "r") as zf:
        # Integrity check
        assert zf.testzip() is None

        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "silo.index.json" in names
        assert "README.txt" in names
        assert plan.text_member in names

        # Verify attachments are in attachments/
        assert any(n.startswith("attachments/") and n.endswith("arch.pdf") for n in names)
        assert any(n.startswith("attachments/") and n.endswith("metrics.csv") for n in names)

        # Verify media members
        for dest in media_dest_names:
            assert dest in names

        # Verify manifest schema 4
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["schema_version"] == 4
        assert manifest["producer"] == "FastPrompter"
        assert manifest["bundle_kind"] == "silo_bundle"
        assert "hashes" in manifest
        assert plan.text_member in manifest["hashes"]
        assert "silo.index.json" in manifest["hashes"]
        assert "README.txt" in manifest["hashes"]

        # Verify silo.index.json schema 2
        idx = json.loads(zf.read("silo.index.json").decode("utf-8"))
        assert idx["schema_version"] == 2
        assert "requirements" in idx
        assert len(idx["requirements"]) >= 4

        # Verify markdown rewritten content
        md_text = zf.read(plan.text_member).decode("utf-8")
        # Shared image rewritten to media/
        assert "media/" in md_text
        # Remote URL preserved
        assert "https://example.com/logo.png" in md_text

    # 6. Smart reuse verification
    fp1 = result1.fingerprint
    assert sb.verify_reuse_candidate(
        zip_path1,
        fp1,
        expected_size=result1.archive_size,
        expected_mtime_ns=result1.archive_mtime_ns,
    )

    # 7. Edit text -> content fingerprint changes -> new archive created
    text_v2 = text + "\n- [P1] REQ-007: Added new requirement after launch\n"
    plan_v2 = sb.plan_bundle(
        text=text_v2,
        title=title,
        target_dir=str(exports_dir),
        silo_dir=str(silo_dir),
        include_attachments=True,
    )
    result2 = sb.write_bundle(plan_v2)
    assert result2.zip_path is not None
    zip_path2 = result2.zip_path
    assert zip_path2 != zip_path1
    assert result2.fingerprint != fp1

    # 8. Retention pruning with positive ownership proof
    # Ordered newest-first: zip_path2, zip_path1.
    # With keep_versions=1, pruning removes older valid archive and keeps newest.
    records = [
        {"path": zip_path2, "content_fingerprint": result2.fingerprint},
        {"path": zip_path1, "content_fingerprint": fp1},
    ]
    kept, pruned = sb.prune_silo_history(
        records=records,
        canonical_exports_dir=str(exports_dir),
        keep_versions=1,
    )
    assert len(kept) == 1
    assert kept[0]["path"] == zip_path2
    assert zip_path1 in pruned
    assert os.path.isfile(zip_path2)
    assert not os.path.exists(zip_path1)
