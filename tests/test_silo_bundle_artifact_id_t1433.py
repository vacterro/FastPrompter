"""T-1433 — BUNDLE ARTIFACT IDENTITY.

A published bundle carries a stable, human-sayable locator derived from the
FINAL content fingerprint:

    fast_Scheduler_Continuinity_bundle_20261005_201705_FPB6-12015852B4DD.zip

The contract this module pins:

1. ``bundle_artifact_id`` is a pure deterministic function of a full
   fingerprint and the fingerprint schema. No clock, no randomness, no
   filesystem, no Qt.
2. The published basename carries the id minted from the fingerprint that the
   archive's OWN manifest states -- not a planning-time preflight fingerprint,
   which can disagree the moment a media source vanishes before packing.
3. The full ``content_fingerprint`` stays the single authority: the short id is
   its display face, the filename is never proof of ownership, and a transport
   rename never changes who the artifact is.

Case 13 of the handoff ("the full existing bundle suite remains green") is not
a test in this file: it is the VERIFY gate over
tests/test_silo_bundle_*_t14*.py + tests/test_silo_selection_bundle_t1414.py,
recorded as evidence on the ticket.
"""

import json
import os
import shutil
import zipfile
from urllib.parse import quote

import pytest

from fastprompter.core import silo_bundle as sb

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

FULL_FP = "12015852b4dd75ebe7cda24ddfe927391247aa05a36fdd9ed72f9f18fee40ae9"


def _png(dirpath, name="a.png", data=PNG_BYTES):
    path = os.path.join(str(dirpath), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _file_url(path):
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def _pack(tmp_path, text, **kw):
    kw.setdefault("title", "Evening 03 Oct")
    kw.setdefault("target_dir", str(tmp_path / "exports"))
    plan = sb.plan_bundle(text=text, **kw)
    return plan, sb.write_bundle(plan)


def _manifest(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


def _read_member(zip_path, member):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member).decode("utf-8")


def _strip_artifact_identity(zip_path):
    """Rewrite a published archive as a pre-T-1433 one (no identity key)."""
    manifest = _manifest(zip_path)
    manifest.pop("artifact_identity", None)
    original = zipfile.ZipFile(zip_path).namelist()
    tmp = zip_path + ".rewrite"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for member in original:
            if member == "manifest.json":
                out.writestr(member, json.dumps(manifest, indent=2, ensure_ascii=False))
            else:
                with zipfile.ZipFile(zip_path) as src:
                    out.writestr(member, src.read(member))
    # manifest.json is not in manifest["hashes"], so the rewrite keeps the
    # archive deeply verifiable -- which is the point: identity is optional
    # extra structure, never a reuse precondition.
    os.replace(tmp, zip_path)


# ---------------------------------------------------------------------------
# 1-2. The id is a pure, schema-explicit function of one fingerprint.
# ---------------------------------------------------------------------------


def test_artifact_id_is_deterministic():
    """RED: same full fingerprint must always mint the same short locator."""
    first = sb.bundle_artifact_id(FULL_FP)
    second = sb.bundle_artifact_id(FULL_FP)
    assert first == second == "FPB6-12015852B4DD"
    # Case-insensitive input, one identity: a fingerprint is hexadecimal, and
    # a producer that upper-cased it must not mint a second artifact.
    assert sb.bundle_artifact_id(FULL_FP.upper()) == first
    # A different fingerprint is a different artifact.
    other = sb.bundle_artifact_id("b" * 64)
    assert other == "FPB6-BBBBBBBBBBBB"
    assert other != first


def test_artifact_id_uses_fingerprint_schema():
    """RED: the schema is stated in the token, and a bad fingerprint refuses."""
    assert sb.bundle_artifact_id(FULL_FP, fingerprint_schema=6) == "FPB6-12015852B4DD"
    assert sb.bundle_artifact_id(FULL_FP, fingerprint_schema=7) == "FPB7-12015852B4DD"
    assert sb.FINGERPRINT_SCHEMA == 6
    for bad in ("", "not-a-fingerprint", "12015852b4dd", "z" * 64, None):
        with pytest.raises(ValueError):
            sb.bundle_artifact_id(bad)


# ---------------------------------------------------------------------------
# 3-4. The published name and the published manifest state ONE identity.
# ---------------------------------------------------------------------------


def test_new_bundle_filename_contains_final_artifact_id(tmp_path):
    """RED: a published basename ends with ``_<artifact-id>.zip``."""
    shot = _png(tmp_path, "shot.png")
    _plan, result = _pack(tmp_path, f"![]({_file_url(shot)})\n")
    assert result.zip_path and result.artifact_id
    basename = os.path.basename(result.zip_path)
    assert basename.endswith(f"_{result.artifact_id}.zip")
    assert "_bundle_" in basename
    assert result.artifact_id == sb.bundle_artifact_id(result.fingerprint)


def test_filename_id_matches_manifest(tmp_path):
    """RED: filename id == manifest id == id derived from the manifest fingerprint.

    An archive whose name says one artifact and whose manifest says another is
    worse than no name at all, so this is asserted over the produced ZIP.
    """
    shot = _png(tmp_path, "shot.png")
    _plan, result = _pack(tmp_path, f"![]({_file_url(shot)})\n")
    manifest = _manifest(result.zip_path)

    identity = manifest["artifact_identity"]
    assert identity["scheme"] == sb.ARTIFACT_ID_SCHEME
    assert identity["version"] == sb.ARTIFACT_ID_VERSION
    assert identity["fingerprint_schema"] == sb.FINGERPRINT_SCHEMA
    assert identity["content_fingerprint"] == manifest["content_fingerprint"]

    derived = sb.bundle_artifact_id(manifest["content_fingerprint"])
    assert identity["id"] == derived

    basename = os.path.basename(result.zip_path)
    assert basename.endswith(f"_{derived}.zip")
    assert result.artifact_id == derived


# ---------------------------------------------------------------------------
# 5. FINAL TRUTH: planning-time facts may not name a publication-time artifact.
# ---------------------------------------------------------------------------


def test_final_truth_after_source_disappears(tmp_path):
    """RED: a source that vanishes between planning and packing is not named.

    Uses the same seam as T-1417's own final-truth tests: build the plan,
    resolve the preflight identity, then delete one media source before
    ``write_bundle`` runs. The published name must describe what the archive
    ACTUALLY carries.
    """
    kept = _png(tmp_path, "kept.png")
    vanishing = _png(tmp_path, "vanishing.png")
    text = (
        f"![]({_file_url(kept)})\n"
        f"![]({_file_url(vanishing)})\n"
    )
    plan = sb.plan_bundle(text=text, title="Late loss", target_dir=str(tmp_path / "exports"))

    hashes, _cache = sb.resolve_plan_hashes(plan, {})
    preflight_fp = sb.compute_content_fingerprint(plan, hashes)
    preflight_id = sb.bundle_artifact_id(preflight_fp)

    os.remove(vanishing)  # the source disappears after planning
    result = sb.write_bundle(plan)

    assert result.zip_path
    manifest = _manifest(result.zip_path)
    final_fp = manifest["content_fingerprint"]

    # Preflight and final identity genuinely disagree here -- otherwise the
    # test would pass vacuously.
    assert final_fp == result.fingerprint
    assert final_fp != preflight_fp
    assert result.artifact_id != preflight_id

    basename = os.path.basename(result.zip_path)
    assert basename.endswith(f"_{result.artifact_id}.zip")
    assert result.artifact_id == sb.bundle_artifact_id(final_fp)
    assert basename.endswith(f"_{manifest['artifact_identity']['id']}.zip")
    # The stale preflight id is nowhere in the published name.
    assert preflight_id not in basename
    # And the vanished source is honestly reported as missing.
    assert len(result.missing) == 1
    assert all(not item.available for item in result.missing)


# ---------------------------------------------------------------------------
# 6-7. A name is a label; the fingerprint is the identity.
# ---------------------------------------------------------------------------


def test_transport_rename_does_not_change_identity(tmp_path):
    """RED: a renamed archive is still the same logical artifact."""
    shot = _png(tmp_path, "shot.png")
    _plan, result = _pack(tmp_path, f"![]({_file_url(shot)})\n")
    original = result.zip_path
    manifest = _manifest(original)
    fingerprint = manifest["content_fingerprint"]
    artifact_id = manifest["artifact_identity"]["id"]

    renamed = os.path.join(str(tmp_path), "renamed_bundle_FPB6-AAAAAAAAAAAA(2).zip")
    shutil.copy2(original, renamed)

    assert os.path.basename(renamed) != os.path.basename(original)
    assert _manifest(renamed)["content_fingerprint"] == fingerprint
    assert _manifest(renamed)["artifact_identity"]["id"] == artifact_id
    assert sb.verify_reuse_candidate(renamed, fingerprint)
    # The README keeps the identity readable after the rename.
    assert f"Artifact ID: {artifact_id}" in _read_member(renamed, "README.txt")


def test_same_name_different_fingerprint_is_not_same_artifact(tmp_path):
    """RED: filename equality never defeats a fingerprint mismatch."""
    one = _png(tmp_path, "one.png", data=PNG_BYTES + b"one")
    two = _png(tmp_path, "two.png", data=PNG_BYTES + b"two")

    _plan_a, a = _pack(tmp_path, f"![]({_file_url(one)})\n", target_dir=str(tmp_path / "a"))
    _plan_b, b = _pack(tmp_path, f"![]({_file_url(two)})\n", target_dir=str(tmp_path / "b"))

    fp_a = _manifest(a.zip_path)["content_fingerprint"]
    fp_b = _manifest(b.zip_path)["content_fingerprint"]
    assert fp_a != fp_b

    # Forge the collision: B now wears A's exact basename.
    forged = os.path.join(str(tmp_path / "b"), os.path.basename(a.zip_path))
    shutil.move(b.zip_path, forged)
    assert os.path.basename(forged) == os.path.basename(a.zip_path)

    assert sb.verify_reuse_candidate(a.zip_path, fp_a)
    # Same name, wrong identity: refused.
    assert not sb.verify_reuse_candidate(forged, fp_a)
    # Same name, right identity: accepted -- the name is not what decides.
    assert sb.verify_reuse_candidate(forged, fp_b)


# ---------------------------------------------------------------------------
# 8-9. Backward compatibility and no-clobber survive the new naming.
# ---------------------------------------------------------------------------


def test_smart_reuse_old_schema6_name(tmp_path):
    """RED: an older verified bundle keeps its old name and is still reused.

    Backward compatibility beats cosmetic migration: a schema-6 archive whose
    filename predates the artifact id is NOT renamed and NOT republished.
    """
    shot = _png(tmp_path, "shot.png")
    exports = tmp_path / "exports"
    _plan, result = _pack(tmp_path, f"![]({_file_url(shot)})\n")

    fingerprint = _manifest(result.zip_path)["content_fingerprint"]

    # The archive as it was published BEFORE this feature existed: a legacy
    # timestamp-only name and no artifact_identity key in the manifest at all.
    legacy = os.path.join(str(exports), "Evening 03 Oct_bundle_20261003_173945.zip")
    os.rename(result.zip_path, legacy)
    _strip_artifact_identity(legacy)

    assert "artifact_identity" not in _manifest(legacy)
    assert os.path.isfile(legacy)
    assert sb.verify_reuse_candidate(legacy, fingerprint)

    # Retention still treats it as a managed, owned bundle in its own right.
    kept, pruned = sb.prune_silo_history(
        [{"path": legacy, "content_fingerprint": fingerprint,
          "bundle_kind": "silo_bundle"}],
        canonical_exports_dir=str(exports), keep_versions=5)
    assert kept and not pruned
    assert os.path.isfile(legacy)  # never renamed, never deleted


def test_no_clobber(tmp_path):
    """RED: colliding desired basenames still use the existing no-clobber rule."""
    shot = _png(tmp_path, "shot.png")
    text = f"![]({_file_url(shot)})\n"

    first_plan, first = _pack(tmp_path, text)
    second_plan, second = _pack(tmp_path, text)

    # Identical content => identical desired name; the writer must not clobber.
    assert first_plan.archive_name == second_plan.archive_name
    assert first.artifact_id == second.artifact_id
    assert first.zip_path != second.zip_path
    assert os.path.basename(second.zip_path).endswith(
        f"_{second.artifact_id}_2.zip")
    assert os.path.isfile(first.zip_path) and os.path.isfile(second.zip_path)

    # A foreign file already occupying the desired name is left untouched too.
    third_dir = tmp_path / "third"
    desired = sb.artifact_basename(first_plan.archive_name, first.artifact_id)
    foreign = third_dir / desired
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_bytes(b"not a bundle")
    allocated = sb.allocate_bundle_path(str(third_dir), desired)
    assert os.path.basename(allocated) != desired
    assert foreign.read_bytes() == b"not a bundle"
    assert os.path.isfile(first.zip_path)


# ---------------------------------------------------------------------------
# 10-11. Ownership and share-safety are unchanged by the new field.
# ---------------------------------------------------------------------------


def test_retention_does_not_trust_filename_id(tmp_path):
    """RED: an FPB6-shaped name is never proof of FastPrompter ownership."""
    exports = tmp_path / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    # A foreign ZIP wearing a perfectly plausible artifact id.
    foreign = exports / "foreign_bundle_FPB6-12015852B4DD.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 6,
            "content_fingerprint": FULL_FP,
            "artifact_identity": {"id": "FPB6-12015852B4DD"},
        }))

    # ... and a genuine one that must outrank it.
    owned = exports / "owned_bundle_FPB6-0123456789AB.zip"
    with zipfile.ZipFile(owned, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 6,
            "producer": "FastPrompter",
            "bundle_kind": "silo_bundle",
            "content_fingerprint": "a" * 64,
            "artifact_identity": {"id": "FPB6-AAAAAAAAAAAA"},
        }))

    records = [
        {"path": str(owned), "content_fingerprint": "a" * 64, "bundle_kind": "silo_bundle"},
        {"path": str(foreign), "content_fingerprint": FULL_FP, "bundle_kind": "silo_bundle"},
    ]
    kept, pruned = sb.prune_silo_history(
        records, canonical_exports_dir=str(exports), keep_versions=1)

    assert os.path.isfile(foreign)          # plausible name, no proof: preserved
    assert str(foreign) in [r["path"] for r in kept]
    assert os.path.isfile(owned)            # within keep_versions: preserved
    assert pruned == []


def test_share_safe(tmp_path):
    """RED: the identity adds no absolute local path to any shared surface."""
    shot = _png(tmp_path, "shot.png")
    hostile_title = f"Notes from {tmp_path}"
    _plan, result = _pack(tmp_path, f"![]({_file_url(shot)})\n", title=hostile_title)

    manifest_raw = _read_member(result.zip_path, "manifest.json")
    readme = _read_member(result.zip_path, "README.txt")

    for surface in (manifest_raw, readme):
        assert str(tmp_path) not in surface
        assert "\\\\" not in surface.replace("\\\\\\\\", "")

    assert f"Artifact ID: {result.artifact_id}" in readme
    manifest = json.loads(manifest_raw)
    assert str(tmp_path) not in json.dumps(manifest["artifact_identity"])
    assert set(manifest["artifact_identity"]) == {
        "scheme", "version", "id", "fingerprint_schema", "content_fingerprint"}


# ---------------------------------------------------------------------------
# 12. Custom names keep their stem and gain only the identity.
# ---------------------------------------------------------------------------


def test_custom_name_contract(tmp_path):
    """RED: an explicit custom stem is preserved, never replaced."""
    shot = _png(tmp_path, "shot.png")
    _plan, result = _pack(
        tmp_path, f"![]({_file_url(shot)})\n", custom_archive_name="MyAudit.zip")

    basename = os.path.basename(result.zip_path)
    assert basename.startswith("MyAudit_")
    assert basename == f"MyAudit_{result.artifact_id}.zip"

    # The pure codec: stem preserved, id appended once, never twice.
    assert sb.artifact_basename("MyAudit.zip", "FPB6-12015852B4DD") == (
        "MyAudit_FPB6-12015852B4DD.zip")
    assert sb.artifact_basename(
        "MyAudit_FPB6-12015852B4DD.zip", "FPB6-12015852B4DD") == (
        "MyAudit_FPB6-12015852B4DD.zip")
    assert sb.artifact_basename("MyAudit.zip", "") == "MyAudit.zip"

    # A Fast Selection Bundle is a custom name too: its `fast_..._bundle` stem
    # survives and only the identity is added.
    assert sb.artifact_basename("fast_Fix_worker_retry_bundle.zip",
                                "FPB6-12015852B4DD") == (
        "fast_Fix_worker_retry_bundle_FPB6-12015852B4DD.zip")
