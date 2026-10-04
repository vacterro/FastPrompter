"""T-1412 — Structured AI-ingestion upgrade for SILO bundles.

Validates the machine-readable requirement index (silo.index.json),
manifest schema 3 extensions, reverse media mappings, dimensions metadata,
atomic validation, and smart-reuse migration.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile

from PyQt6.QtWidgets import QApplication
from test_silo_bundle_clipboard_t1409 import (  # noqa: F401
    _body,
    _clipboard_urls,
    _members,
    _png,
    _run,
    _url,
    _Win,
)
from test_silo_bundle_clipboard_t1409 import win as _win_fixture

from fastprompter.core import silo_bundle as sb

win = _win_fixture


def _zips(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".zip")
    )


def _exports(w) -> str:
    return os.path.join(w.silo_dir, "exports")


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


# ======================================================================
# A: Bullet parsing
# ======================================================================

def test_a_bullet_variety_parsing(tmp_path):
    md = (
        "• First unicode bullet\n"
        "⁃ Second hyphen bullet\n"
        "‣ Third triangle bullet\n"
        "- Fourth dash bullet\n"
        "* Fifth star bullet\n"
        "+ Sixth plus bullet\n"
        "1. Seventh numbered bullet\n"
        "2) Eighth paren bullet\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Bullet Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    assert "silo.index.json" in members
    assert "README.txt" in members
    assert index_data["schema_version"] in (1, 2)
    assert len(index_data["requirements"]) == 8

    reqs = index_data["requirements"]
    assert reqs[0]["id"] == "REQ-001"
    assert reqs[0]["source_order"] == 1
    assert "First unicode bullet" in reqs[0]["text"]
    assert reqs[6]["id"] == "REQ-007"
    assert reqs[7]["id"] == "REQ-008"
    assert manifest["requirement_count"] == 8


# ======================================================================
# B: Separators and Groups
# ======================================================================

def test_b_separators_and_group_labels(tmp_path):
    md = (
        "# Core Features\n"
        "• Requirement 1\n"
        "• Requirement 2\n"
        "---\n"
        "# Secondary Features\n"
        "• Requirement 3\n"
        "* * *\n"
        "• Requirement 4\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Group Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    groups = index_data["groups"]
    assert len(groups) == 3
    assert groups[0]["id"] == "GROUP-001"
    assert groups[0]["source_label"] == "Core Features"
    assert groups[1]["id"] == "GROUP-002"
    assert groups[1]["source_label"] == "Secondary Features"
    assert groups[2]["id"] == "GROUP-003"

    reqs = index_data["requirements"]
    assert len(reqs) == 4
    assert reqs[0]["group_id"] == "GROUP-001"
    assert reqs[1]["group_id"] == "GROUP-001"
    assert reqs[2]["group_id"] == "GROUP-002"
    assert reqs[3]["group_id"] == "GROUP-003"

    assert manifest["group_count"] == 3


# ======================================================================
# C: Continuation lines and child bullets
# ======================================================================

def test_c_continuation_lines_and_child_bullets(tmp_path):
    md = (
        "• Parent requirement\n"
        "  Continuation line 1\n"
        "  - Sub bullet A\n"
        "  - Sub bullet B\n"
        "  Continuation line 2\n"
        "• Next requirement\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Continuation Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert len(reqs) == 2
    parent = reqs[0]
    assert parent["id"] == "REQ-001"
    assert "Continuation line 1" in parent["text"]
    assert "- Sub bullet A" in parent["text"]
    assert "- Sub bullet B" in parent["text"]
    assert "Continuation line 2" in parent["text"]
    assert parent["line_start"] == 1
    assert parent["line_end"] == 5

    next_req = reqs[1]
    assert next_req["id"] == "REQ-002"
    assert next_req["line_start"] == 6
    assert next_req["line_end"] == 6


# ======================================================================
# D: Conservative free-text fallback
# ======================================================================

def test_d_conservative_free_text_fallback(tmp_path):
    md = (
        "# Overview\n"
        "This is an unbulleted specification paragraph.\n"
        "It describes the system architecture in free-form prose.\n"
        "---\n"
        "Second cohesive block across the thematic break.\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Prose Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert len(reqs) == 2
    assert "architecture in free-form prose" in reqs[0]["text"]
    assert reqs[0]["group_id"] == "GROUP-001"
    assert "Second cohesive block" in reqs[1]["text"]
    assert reqs[1]["group_id"] == "GROUP-002"


# ======================================================================
# E: Code fence isolation
# ======================================================================

def test_e_code_fences_do_not_split_requirements(tmp_path):
    md = (
        "• Implement parser with sample:\n"
        "  ```python\n"
        "  --- # this separator inside code must not split\n"
        "  • fake bullet inside code\n"
        "  ```\n"
        "• Following requirement\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Fence Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert len(reqs) == 2
    assert "fake bullet inside code" in reqs[0]["text"]
    assert reqs[0]["id"] == "REQ-001"
    assert reqs[1]["id"] == "REQ-002"
    assert len(index_data["groups"]) == 1


# ======================================================================
# F: Media association (forward and reverse mapping)
# ======================================================================

def test_f_forward_and_reverse_media_mapping(tmp_path):
    shot1 = _png(tmp_path, "shot1.png")
    shot2 = _png(tmp_path, "shot2.png")
    md = (
        f"• Requirement A\n  ![]({_url(shot1)})\n"
        f"• Requirement B\n  ![]({_url(shot2)})\n"
        f"• Requirement C reuses shot1\n  ![]({_url(shot1)})\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Media Mapping",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert len(reqs) == 3
    # Forward mapping
    assert reqs[0]["media"] == ["media/001_shot1.png"]
    assert reqs[1]["media"] == ["media/002_shot2.png"]
    assert reqs[2]["media"] == ["media/001_shot1.png"]

    # Reverse manifest mapping
    items_map = {item["member"]: item for item in manifest["items"]}
    assert items_map["media/001_shot1.png"]["linked_requirements"] == [
        "REQ-001",
        "REQ-003",
    ]
    assert items_map["media/002_shot2.png"]["linked_requirements"] == ["REQ-002"]

    assert manifest["scoped_media_count"] == 2
    assert manifest["unscoped_media_count"] == 0


# ======================================================================
# G: Silo Files unscoped media
# ======================================================================

def test_g_silo_files_unscoped_media(tmp_path):
    silo_dir = tmp_path / "silo"
    silo_dir.mkdir()
    shot1 = _png(silo_dir, "inline.png")
    _png(silo_dir, "unreferenced.png")
    with open(silo_dir / "notes.txt", "w") as f:
        f.write("Attachment file")

    md = f"• Only refers to inline\n  ![]({_url(shot1)})\n"
    plan = sb.plan_bundle(
        text=md,
        title="Unscoped Test",
        silo_dir=str(silo_dir),
        target_dir=str(tmp_path / "exports"),
        include_silo_media=True,
        include_attachments=True,
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    # unreferenced.png is unscoped media
    assert "media/002_unreferenced.png" in index_data["unscoped_media"]
    assert manifest["unscoped_media_count"] == 1
    assert manifest["scoped_media_count"] == 1

    items_map = {item["member"]: item for item in manifest["items"]}
    assert items_map["media/002_unreferenced.png"]["linked_requirements"] == []
    assert items_map["media/001_inline.png"]["linked_requirements"] == ["REQ-001"]


# ======================================================================
# H: Missing media recording
# ======================================================================

def test_h_missing_media_recorded_truthfully(tmp_path):
    ghost = os.path.join(str(tmp_path), "vanished.png")
    real = _png(tmp_path, "real.png")
    md = (
        f"• First requirement with real\n  ![]({_url(real)})\n"
        f"• Second requirement with missing\n  ![]({_url(ghost)})\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Missing Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert len(reqs) == 2
    assert reqs[0]["media"] == ["media/001_real.png"]
    assert "missing_media" not in reqs[0]

    assert reqs[1]["media"] == []
    assert reqs[1]["missing_media"] == ["media/002_vanished.png"]

    items_map = {item["member"]: item for item in manifest["items"]}
    assert items_map["media/002_vanished.png"]["status"] == "missing"
    assert items_map["media/002_vanished.png"]["linked_requirements"] == ["REQ-002"]


# ======================================================================
# I: Explicit priority markers
# ======================================================================

def test_i_explicit_priority_markers(tmp_path):
    md = (
        "• P0 Critical crash on boot\n"
        "• P1: Heavy memory leak\n"
        "• [P2] Dark mode contrast\n"
        "• **P3** Minor alignment\n"
        "• No priority specified\n"
        "• Text mentioning Port 8080 or page 2\n"
    )
    plan = sb.plan_bundle(
        text=md,
        title="Priority Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    reqs = index_data["requirements"]
    assert reqs[0]["priority"] == "P0"
    assert reqs[1]["priority"] == "P1"
    assert reqs[2]["priority"] == "P2"
    assert reqs[3]["priority"] == "P3"
    assert "priority" not in reqs[4]
    assert "priority" not in reqs[5]


# ======================================================================
# J: Privacy / no absolute local path leakage
# ======================================================================

def test_j_privacy_boundary_no_local_path_leakage(tmp_path):
    img = _png(tmp_path, "local_screenshot.png")
    raw_text = (
        f"# Silo with paths\n\n"
        f"• Task referencing ![]({_url(img)}) on disk\n"
        f"• Also unbundled local file [omitted](file:///C:/Secret/Doc.pdf)\n"
    )
    plan = sb.plan_bundle(
        text=raw_text,
        title="Privacy Test",
        target_dir=str(tmp_path / "exports"),
        hide_local_paths=True,
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None

    with zipfile.ZipFile(result.zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith((".json", ".txt", ".md")):
                content = zf.read(name).decode("utf-8")
                assert str(tmp_path) not in content
                assert "file:///" not in content
                assert "C:\\" not in content
                assert "V:\\" not in content


# ======================================================================
# K: Image dimensions metadata
# ======================================================================

def test_k_image_dimensions_metadata(tmp_path):
    shot = _png(tmp_path, "shot.png")
    canonical = sb._canonical(shot)
    dimensions = {canonical: {"width": 1920, "height": 1080}}

    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_url(shot)})\n",
        title="Dim Test",
        target_dir=str(tmp_path / "exports"),
        dimensions=dimensions,
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    item = manifest["items"][0]
    assert item["width"] == 1920
    assert item["height"] == 1080


def test_k_image_dimensions_fallback_when_absent(tmp_path):
    shot = _png(tmp_path, "shot.png")
    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_url(shot)})\n",
        title="No Dim Test",
        target_dir=str(tmp_path / "exports"),
        dimensions=None,
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    item = manifest["items"][0]
    assert item["width"] is None
    assert item["height"] is None


# ======================================================================
# L: Manifest integrity & generated text hashing
# ======================================================================

def test_l_manifest_integrity_and_hashes(tmp_path):
    shot = _png(tmp_path, "shot.png")
    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_url(shot)})\n",
        title="Integrity Test",
        target_dir=str(tmp_path / "exports"),
    )
    result = sb.write_bundle(plan)
    assert result.zip_path is not None
    manifest, index_data, readme, members = _read_bundle(result.zip_path)

    assert manifest["schema_version"] in (3, 4)
    assert manifest["index_schema_version"] in (1, 2)
    assert manifest["index_member"] == "silo.index.json"
    assert manifest["requirement_count"] == 1
    assert manifest["group_count"] == 1
    assert manifest["scoped_media_count"] == 1
    assert manifest["unscoped_media_count"] == 0

    hashes = manifest["hashes"]
    with zipfile.ZipFile(result.zip_path, "r") as zf:
        for member_name in ("Integrity Test.md", "silo.index.json", "README.txt", "media/001_shot.png"):
            content = zf.read(member_name)
            assert hashes[member_name] == hashlib.sha256(content).hexdigest()


# ======================================================================
# M: Atomic validation before publication
# ======================================================================

def test_m_atomic_validation_abort_on_corrupt_index(tmp_path):
    shot = _png(tmp_path, "shot.png")
    plan = sb.plan_bundle(
        text=f"• Shot\n  ![]({_url(shot)})\n",
        title="Corrupt Test",
        target_dir=str(tmp_path / "exports"),
    )

    # Tamper with plan.index_data to introduce duplicate requirement ID
    bad_index = {
        "schema_version": 1,
        "requirements": [
            {"id": "REQ-001", "source_order": 1, "text": "A"},
            {"id": "REQ-001", "source_order": 2, "text": "B"},
        ],
        "groups": [],
        "unscoped_media": [],
    }
    from dataclasses import replace
    bad_plan = replace(plan, index_data=bad_index)

    result = sb.write_bundle(bad_plan)
    assert result.zip_path is None
    assert "Index validation failed" in result.error
    # Destination directory left clean
    assert _zips(plan.target_dir) == []


# ======================================================================
# N: Smart reuse boundary across schemas
# ======================================================================

def test_n_smart_reuse_refuses_schema_2_archive(win, tmp_path):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)

    # 1. Build an archive manually pretending to be schema 2
    exports_dir = _exports(win)
    os.makedirs(exports_dir, exist_ok=True)
    fake_zip = os.path.join(exports_dir, "My Silo_bundle_20261003_120000.zip")
    with zipfile.ZipFile(fake_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 2,
            "content_fingerprint": "fake_fp",
        }))
        zf.writestr("media/001_shot.png", b"fake")

    # Record it into history as an existing schema 2 archive
    win.data.setdefault("silo_bundle_history", {})["silo-A"] = {
        "records": [{
            "path": fake_zip,
            "display_title": "My Silo",
            "content_fingerprint": "fake_fp",
            "target_dir": exports_dir,
            "archive_size": os.path.getsize(fake_zip),
            "archive_mtime_ns": 0,
            "created_at": "2026-10-03T12:00:00",
        }]
    }

    # 2. Plain Quick Pack should NOT reuse this schema-2 archive
    _run(win)
    zips = _zips(exports_dir)
    assert len(zips) == 2, "Schema-2 archive must not be reused for schema-3 pack"
    new_zip = [z for z in zips if z != fake_zip][0]
    manifest, index_data, readme, members = _read_bundle(new_zip)
    assert manifest["schema_version"] in (3, 4)
    assert "silo.index.json" in members


def test_n_smart_reuse_accepts_identical_schema_3_pack(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)

    _run(win)
    first_zips = _zips(_exports(win))
    assert len(first_zips) == 1

    # Unchanged repeat pack
    QApplication.clipboard().clear()
    _run(win)
    assert _zips(_exports(win)) == first_zips
    assert win.toasts[-1][0] == "Bundle unchanged"


def test_n_force_repack_bypasses_schema_3_reuse(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)

    _run(win)
    first_zips = _zips(_exports(win))
    assert len(first_zips) == 1

    _run(win, {"force_repack": True})
    second_zips = _zips(_exports(win))
    assert len(second_zips) == 2
    assert win.toasts[-1][0] == "Silo packed"


# ======================================================================
# O: Representative acceptance bundle
# ======================================================================

def test_o_representative_acceptance_bundle(win, tmp_path):
    shot1 = _png(win.silo_dir, "screen_a.png")
    shot2 = _png(win.silo_dir, "screen_b.png")
    _png(win.silo_dir, "unscoped_photo.jpg")
    with open(os.path.join(win.silo_dir, "spec.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 spec")

    win.text = (
        "# UI Improvement Wishlist: (04 Oct - 17:39)\n\n"
        "• P0 Fix crash on opening dialog\n"
        f"  ![]({_url(shot1)})\n"
        "  Reproduction steps:\n"
        "  1) Click select button\n"
        "  2) Enter empty value\n"
        "---\n"
        "## Visual Enhancements\n"
        "• P2 Update contrast of icons\n"
        f"  ![]({_url(shot2)})\n"
        "• P3 Add tooltip\n"
    )

    _run(win, {"include_attachments": True})
    zips = _zips(_exports(win))
    assert len(zips) == 1
    archive_path = zips[0]

    manifest, index_data, readme, members = _read_bundle(archive_path)

    assert manifest["schema_version"] in (3, 4)
    assert manifest["index_schema_version"] in (1, 2)
    assert manifest["requirement_count"] == 3
    assert manifest["group_count"] == 2
    assert manifest["scoped_media_count"] == 2
    assert manifest["unscoped_media_count"] == 1

    # Check index structure
    reqs = index_data["requirements"]
    assert reqs[0]["priority"] == "P0"
    assert reqs[0]["media"] == ["media/001_screen_a.png"]
    assert "1) Click select button" in reqs[0]["text"]

    assert reqs[1]["priority"] == "P2"
    assert reqs[1]["group_id"] == "GROUP-002"
    assert reqs[1]["media"] == ["media/002_screen_b.png"]

    assert reqs[2]["priority"] == "P3"
    assert reqs[2]["group_id"] == "GROUP-002"

    assert index_data["unscoped_media"] == ["media/003_unscoped_photo.jpg"]

    # README content check
    assert "Title: UI Improvement Wishlist: (04 Oct - 17:39)" in readme
    assert "silo.index.json" in readme

    # Attachment check
    assert any(m.startswith("attachments/") and m.endswith("spec.pdf") for m in members)


# ======================================================================
# P: Execution delta benchmark
# ======================================================================

def test_p_execution_delta_benchmark(tmp_path):
    # Text-only
    t0 = time.perf_counter()
    p_text = sb.plan_bundle(
        text="• Req 1\n• Req 2\n• Req 3\n",
        title="Bench Text",
        target_dir=str(tmp_path / "exp_text"),
    )
    r_text = sb.write_bundle(p_text)
    t_text = (time.perf_counter() - t0) * 1000.0
    assert r_text.zip_path is not None

    # 10 images
    img_dir_10 = tmp_path / "imgs_10"
    img_dir_10.mkdir()
    md_10_lines = []
    for i in range(10):
        img_path = _png(img_dir_10, f"img_{i:02d}.png")
        md_10_lines.append(f"• Requirement {i}\n  ![]({_url(img_path)})\n")
    t0 = time.perf_counter()
    p_10 = sb.plan_bundle(
        text="\n".join(md_10_lines),
        title="Bench 10",
        target_dir=str(tmp_path / "exp_10"),
    )
    r_10 = sb.write_bundle(p_10)
    t_10 = (time.perf_counter() - t0) * 1000.0
    assert r_10.zip_path is not None

    # 50 images
    img_dir_50 = tmp_path / "imgs_50"
    img_dir_50.mkdir()
    md_50_lines = []
    for i in range(50):
        img_path = _png(img_dir_50, f"img_{i:02d}.png")
        md_50_lines.append(f"• Requirement {i}\n  ![]({_url(img_path)})\n")
    t0 = time.perf_counter()
    p_50 = sb.plan_bundle(
        text="\n".join(md_50_lines),
        title="Bench 50",
        target_dir=str(tmp_path / "exp_50"),
    )
    r_50 = sb.write_bundle(p_50)
    t_50 = (time.perf_counter() - t0) * 1000.0
    assert r_50.zip_path is not None

    # Verify execution speeds are sub-second
    assert t_text < 500.0, f"Text pack too slow: {t_text:.2f}ms"
    assert t_10 < 1000.0, f"10-image pack too slow: {t_10:.2f}ms"
    assert t_50 < 3000.0, f"50-image pack too slow: {t_50:.2f}ms"
