"""Release provenance + tree inventory contracts (0.8.68 release hardening).

These tests pin the tooling that makes a public release trustworthy:

- version parity is a refusal, not a warning;
- the release receipt binds VERSION, commit, EXE SHA256 and ProductVersion;
- the ACCEPTED RC manifest is deterministic and diffable;
- the tree inventory classifies release-critical paths (including the
  cs_style vault assets that T-1241 must NOT exclude) and never invents a
  class for an unknown path.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import release_provenance as rp  # noqa: E402
import release_tree_inventory as rti  # noqa: E402


def _fake_tree(root: Path, version: str = "1.2.3") -> None:
    (root / "src" / "fastprompter" / "core").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(f'version = "{version}"\n', encoding="utf-8")
    (root / "FastPrompter.pyw").write_text(
        f"# nuitka-project: --product-version={version}\n", encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        f'name = "fastprompter"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "src" / "fastprompter" / "core" / "mod.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    for name in ("build.py", "probe_release.py", "release.py", "release_provenance.py",
                 "sync_release_version.py", "set_default_from_current.py"):
        (root / "tools" / name).write_text("# tool\n", encoding="utf-8")


def _fake_exe(root: Path) -> Path:
    exe = root / "build" / "FastPrompter.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ-fake-exe-bytes")
    return exe


def test_version_parity_refuses_drift(tmp_path):
    _fake_tree(tmp_path)
    rp.check_version_parity("1.2.3", tmp_path)
    (tmp_path / "FastPrompter.pyw").write_text(
        "# nuitka-project: --product-version=9.9.9\n", encoding="utf-8"
    )
    with pytest.raises(rp.ProvenanceError) as excinfo:
        rp.check_version_parity("1.2.3", tmp_path)
    assert "1.2.3" in str(excinfo.value)


def test_source_fingerprint_is_deterministic_and_sensitive(tmp_path):
    _fake_tree(tmp_path)
    paths = rp.release_file_set(tmp_path)
    first = rp.source_fingerprint(paths, tmp_path)
    second = rp.source_fingerprint(paths, tmp_path)
    assert first == second
    assert first.startswith(rp.FINGERPRINT_SCHEME + ":")
    (tmp_path / "src" / "fastprompter" / "core" / "mod.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    assert rp.source_fingerprint(paths, tmp_path) != first


def test_validate_receipt_binds_all_four_facts(tmp_path):
    exe = _fake_exe(tmp_path)
    exe_hash = hashlib.sha256(exe.read_bytes()).hexdigest()
    receipt = {
        "version": "1.2.3",
        "release_commit": "a" * 40,
        "exe_sha256": exe_hash,
        "product_version": "",
    }
    assert rp.validate_receipt(receipt, exe, "1.2.3", "a" * 40) == []
    assert rp.validate_receipt(receipt, exe, "1.2.4", "a" * 40)
    assert rp.validate_receipt(receipt, exe, "1.2.3", "b" * 40)
    exe.write_bytes(b"tampered")
    assert rp.validate_receipt(receipt, exe, "1.2.3", "a" * 40)


def test_freeze_manifest_and_compare(tmp_path, monkeypatch):
    _fake_tree(tmp_path)
    exe = _fake_exe(tmp_path)
    monkeypatch.setattr(rp, "git_head", lambda root=rp.REPO_ROOT: "a" * 40)
    monkeypatch.setattr(rp, "git_branch", lambda root=rp.REPO_ROOT: "main")
    out = tmp_path / "manifest.json"
    manifest = rp.freeze_accepted_manifest(
        exe, out, suite_result="1 passed", operator_acceptance="operator", root=tmp_path
    )
    assert manifest["version"] == "1.2.3"
    assert manifest["file_count"] == len(manifest["file_hashes"])
    assert rp.compare_manifest_to_tree(out, tmp_path) == []

    (tmp_path / "src" / "fastprompter" / "core" / "mod.py").write_text(
        "VALUE = 9\n", encoding="utf-8"
    )
    (tmp_path / "src" / "fastprompter" / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    differences = rp.compare_manifest_to_tree(out, tmp_path)
    assert any(item.startswith("CHANGED src/fastprompter/core/mod.py") for item in differences)
    assert any(item.startswith("ADDED src/fastprompter/new.py") for item in differences)


def test_classify_never_drops_cs_style_or_fixtures():
    # T-1241: the cs_style vault assets are ACTIVE shipped dependencies and
    # must stay classified as accepted source, never as debris.
    letter, _ = rti.classify("src/fastprompter/sound/_vault/cs_style/buttonclick.wav")
    assert letter == "A"
    letter, _ = rti.classify("tests/fixtures/antigravity_usage_1_1_25.json")
    assert letter == "B"
    letter, _ = rti.classify("AGENTS.md")
    assert letter == "E"
    letter, _ = rti.classify("tools/release.py")
    assert letter == "A"
    letter, _ = rti.classify("data/local_data_v15.db")
    assert letter == "G"
    letter, _ = rti.classify("some/strange/path.bin")
    assert letter == "I"


def test_parse_porcelain_v2_is_nul_safe():
    raw = (
        b"1 .M N... 100644 100644 100644 abcdef abcdef src/fastprompter/a b.py\0"
        b"2 R. N... 100644 100644 100644 abcdef abcdef R100 new name.py\0old name.py\0"
        b"? untracked file.txt\0"
    )
    records = rti._parse_porcelain_v2(raw)
    assert records[0]["path"] == "src/fastprompter/a b.py"
    assert records[1]["path"] == "new name.py"
    assert records[1]["orig_path"] == "old name.py"
    assert records[2]["path"] == "untracked file.txt"


def test_inventory_report_is_a_report_not_a_mutation(tmp_path, monkeypatch):
    report = rti.build_report(ROOT)
    assert report["totals"]["all"] == len(report["entries"])
    assert set(report["class_counts"]) == set(rti.CLASS_LABELS)
    assert all(entry["class"] in rti.CLASS_LABELS for entry in report["entries"])
    assert all(isinstance(entry["rationale"], str) for entry in report["entries"])
    sample = json.loads(json.dumps(report))
    assert sample["operation"] == "release_tree_inventory"
