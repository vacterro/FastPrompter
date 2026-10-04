"""Regression tests for T-1357: Release receipt validator negative controls.

Validates that:
1. Declared release version differing from EXE ProductVersion is rejected.
2. Missing operator manual acceptance is rejected.
3. Missing or invalid source tree fingerprint is rejected.
4. Missing build evidence is rejected.
5. Missing or failed probe evidence is rejected.
6. Valid exact-source receipt passes with zero failures.
7. Reproducer .saipen/evidence/t1357_receipt_negative_controls.json is proven.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.release_provenance as rp

REPO_ROOT = rp.REPO_ROOT
REAL_EXE = REPO_ROOT / "build" / "FastPrompter.exe"


def _make_valid_receipt(exe_path: Path, version: str | None = None) -> dict:
    if version is None:
        version = rp.read_version(REPO_ROOT)
    exe_info = rp.exe_identity(exe_path)
    commit = rp.git_head(REPO_ROOT)
    fingerprint = rp.source_fingerprint(rp.release_file_set(REPO_ROOT), REPO_ROOT)
    return {
        "schema_version": 1,
        "operation": "release_receipt",
        "version": version,
        "tag": f"v{version}",
        "release_commit": commit,
        "branch": rp.git_branch(REPO_ROOT),
        "source_tree_fingerprint": fingerprint,
        "default_profile_sha256": rp.default_profile_digest(REPO_ROOT),
        "exe_sha256": exe_info["sha256"],
        "exe_size": exe_info["size"],
        "product_version": exe_info["product_version"],
        "build_toolchain": {
            "python": "3.11.9",
            "nuitka": "4.2.1",
        },
        "verification": {
            "full_suite": "4014 passed",
            "build": "BUILD_EXIT 0",
        },
        "probe": {
            "ok": True,
            "exe_sha256": exe_info["sha256"],
        },
        "operator_manual_acceptance": {
            "status": "ACCEPTED",
            "reference": "verified clean build and probe",
            "recorded_at": "2026-09-30T12:00:00Z",
        },
        "recorded_at": "2026-09-30T12:00:00Z",
    }


def _is_current_exe(exe_path: Path) -> bool:
    if not exe_path.is_file():
        return False
    return rp.inspect_build_artifact(exe_path, rp.read_version(REPO_ROOT))["status"] == "current"


@pytest.mark.skipif(
    not _is_current_exe(REAL_EXE),
    reason="Current matching FastPrompter.exe required (present artifact is absent or stale/foreign)",
)
def test_valid_exact_source_receipt_passes():
    version = rp.read_version(REPO_ROOT)
    commit = rp.git_head(REPO_ROOT)
    receipt = _make_valid_receipt(REAL_EXE, version)
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert failures == []


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_reject_wrong_release_version_vs_product_version():
    commit = rp.git_head(REPO_ROOT)
    receipt = _make_valid_receipt(REAL_EXE, "9.9.9")
    failures = rp.validate_receipt(receipt, REAL_EXE, "9.9.9", commit)
    assert any("ProductVersion" in f or "version" in f for f in failures)
    assert any("9.9.9" in f for f in failures)


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_reject_missing_manual_acceptance():
    version = rp.read_version(REPO_ROOT)
    commit = rp.git_head(REPO_ROOT)

    # Completely missing
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt.pop("operator_manual_acceptance")
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("operator_manual_acceptance" in f for f in failures)

    # Status not ACCEPTED
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt["operator_manual_acceptance"]["status"] = "UNRECORDED"
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("operator_manual_acceptance" in f for f in failures)

    # Empty reference
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt["operator_manual_acceptance"]["reference"] = ""
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("operator_manual_acceptance" in f for f in failures)


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_reject_missing_source_fingerprint():
    version = rp.read_version(REPO_ROOT)
    commit = rp.git_head(REPO_ROOT)

    # Missing
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt.pop("source_tree_fingerprint")
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("source_tree_fingerprint" in f for f in failures)

    # Invalid scheme / format
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt["source_tree_fingerprint"] = "invalid-fingerprint"
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("source_tree_fingerprint" in f for f in failures)


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_reject_missing_build_and_probe_evidence():
    version = rp.read_version(REPO_ROOT)
    commit = rp.git_head(REPO_ROOT)

    # Missing verification/build
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt["verification"].pop("build")
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("build" in f.lower() for f in failures)

    # Missing probe
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt.pop("probe")
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("probe" in f.lower() for f in failures)

    # Probe not ok
    receipt = _make_valid_receipt(REAL_EXE, version)
    receipt["probe"]["ok"] = False
    failures = rp.validate_receipt(receipt, REAL_EXE, version, commit)
    assert any("probe" in f.lower() for f in failures)


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_reproducer_negative_control_fails_validator():
    evidence_path = REPO_ROOT / ".saipen" / "evidence" / "t1357_receipt_negative_controls.json"
    assert evidence_path.is_file()
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    fixture_version = data["expected_fixture_version"]
    commit = rp.git_head(REPO_ROOT)

    # The synthetic negative control from the reproducer:
    synthetic_receipt = {
        "version": fixture_version,
        "release_commit": commit,
        "exe_sha256": data["exe"]["sha256"],
        "product_version": data["exe"]["product_version"],
    }
    failures = rp.validate_receipt(synthetic_receipt, REAL_EXE, fixture_version, commit)
    # Must NOT be empty (the bug was failures == [])
    assert len(failures) >= 4
    assert any("productversion" in f.lower() or "version" in f.lower() for f in failures)
    assert any("acceptance" in f.lower() for f in failures)
    assert any("fingerprint" in f.lower() for f in failures)
    assert any("build" in f.lower() or "verification" in f.lower() for f in failures)


def test_inspect_build_artifact_absent(tmp_path: Path):
    missing_exe = tmp_path / "FastPrompter.exe"
    info = rp.inspect_build_artifact(missing_exe, "0.8.71")
    assert info["status"] == "absent"
    assert "EXE missing" in info["message"]


@pytest.mark.skipif(not REAL_EXE.is_file(), reason="Real FastPrompter.exe required")
def test_inspect_build_artifact_stale_or_current():
    pv = rp.exe_product_version(REAL_EXE)
    assert pv
    # When expected is newer than actual PV, reports stale
    stale_info = rp.inspect_build_artifact(REAL_EXE, "99.0.0")
    assert stale_info["status"] == "stale"
    assert "stale local build artifact" in stale_info["message"]
    assert "is older than declared source VERSION '99.0.0'" in stale_info["message"]

    # When expected is older than actual PV, reports foreign
    foreign_info = rp.inspect_build_artifact(REAL_EXE, "0.1.0")
    assert foreign_info["status"] == "foreign"
    assert "mismatched foreign build artifact" in foreign_info["message"]

    # When expected matches actual PV, reports current
    current_info = rp.inspect_build_artifact(REAL_EXE, pv)
    assert current_info["status"] == "current"

