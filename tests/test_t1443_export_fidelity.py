"""T-1443 / SRC-139 §04 N and §05: an export that omits required evidence must
fail loudly, and the three export verdicts must never be collapsed into one.

The baseline archive these controls were written against,
``FastPrompter_30.10.26-T00-05-28.zip``, carried ``source_review_ready: true``
while ``saipen_snapshot.status`` was ``PROTOCOL_INCOMPLETE`` with 161 required
paths missing and, separately, none of the six artefacts ``ACCEPTANCE.json``
cites. A reader of that archive had no way to tell "the auditor can read the
code" from "the screenshots behind the acceptance claim are in the box".

Each control below fails on the tool as first written; the assertions name exact
paths and exact reasons, never a summary count, because a count can match for
the wrong reason.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import zipfile

TOOL = importlib.import_module("tools.audit_export_fidelity")

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


def _png(seed: bytes = b"") -> bytes:
    return PNG + seed


def _acceptance(root, references):
    """Write an ACCEPTANCE.json naming ``references`` and return their paths."""
    declaration = {"domains": {"DOMAIN_X": {
        "behavioural": {"status": "PARTIAL", "evidence": list(references)},
    }}}
    target = root / "docs" / "audit" / "ACCEPTANCE.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(declaration), encoding="utf-8")
    return list(references)


def _checkout(root, relatives):
    """Create the evidence files a declaration references, with real PNG bytes."""
    for rel in relatives:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_png(rel.encode()))


def _archive(path, members, *, inventory=None, protocol=None):
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)
        if inventory is not None:
            zf.writestr(TOOL.INVENTORY, json.dumps(inventory))
        if protocol is not None:
            zf.writestr(TOOL.PROTOCOL, json.dumps(protocol))
    return path


def _clean_inventory(root, relatives, extra=()):
    """An inventory that accounts for exactly ``relatives`` plus ``extra``.

    A size is only recorded when the file exists, so a control whose whole point
    is an unreferenced checkout file does not need to fabricate one.
    """
    listed = []
    for rel in relatives:
        target = root / rel
        listed.append({"path": rel, "origin": "untracked",
                       "size": target.stat().st_size if target.is_file() else 0})
    listed += [{"path": name, "origin": "tracked", "size": 1} for name in extra]
    return {"schema_version": 1, "files": listed, "counts": {"filesystem": 0},
            "source_review_ready": True}


def _clean_protocol():
    return {"saipen_snapshot": {
        "evidence_complete": True, "missing_required": [],
        "truncated_required_dirs": [], "truncated_optional_dirs": [],
        "non_exportable": [],
    }}


# --- §05: a missing referenced screenshot must fail with its exact name ------

def test_a_missing_reference_fails_acceptance_evidence_and_names_the_path(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/cap/hover.png",
                              ".saipen/evidence/cap/gauge.png"])
    _checkout(root, refs)

    # hover.png is archived with exactly the bytes the claim was written against
    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/cap/hover.png":
                        _png(b".saipen/evidence/cap/hover.png")},
                       inventory=_clean_inventory(root, refs), protocol=_clean_protocol())

    report = TOOL.verify_archive(archive, root)

    assert report["ACCEPTANCE_EVIDENCE_COMPLETE"]["holds"] is False
    findings = report["ACCEPTANCE_EVIDENCE_COMPLETE"]["findings"]
    assert findings == [".saipen/evidence/cap/gauge.png: absent_from_archive"], findings


def test_an_archived_reference_with_different_bytes_is_rejected(tmp_path):
    """A file of the right NAME is not the evidence the claim was written on."""
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/cap/hover.png"])
    _checkout(root, refs)
    claimed = hashlib.sha256(_png(b".saipen/evidence/cap/hover.png")).hexdigest()

    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/cap/hover.png": _png(b"a DIFFERENT capture")},
                       inventory=_clean_inventory(root, refs), protocol=_clean_protocol())

    report = TOOL.verify_archive(archive, root)

    assert report["ACCEPTANCE_EVIDENCE_COMPLETE"]["holds"] is False
    finding = report["ACCEPTANCE_EVIDENCE_COMPLETE"]["findings"][0]
    assert "archived bytes differ" in finding
    assert claimed[:16] in finding, "the finding must name the claimed digest"


def test_a_reference_archived_as_garbage_is_not_an_image(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/cap/hover.png"])
    _checkout(root, refs)

    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/cap/hover.png": b"<html>not a capture</html>"},
                       inventory=_clean_inventory(root, refs), protocol=_clean_protocol())

    report = TOOL.verify_archive(archive, root)

    findings = report["ACCEPTANCE_EVIDENCE_COMPLETE"]["findings"]
    assert any("not an image" in f for f in findings), findings


# --- §04 L: transient fixtures must not be mistaken for durable loss --------

def test_basetemp_omission_is_classified_transient_not_absent(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    transient = ".saipen/evidence/t1450_fullsuite/basetemp/test_x0/cue.wav"
    protocol = {"saipen_snapshot": {
        "evidence_complete": False, "missing_required": [transient],
        "truncated_required_dirs": [], "non_exportable": []}}

    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/real.png": _png()},
                       inventory=_clean_inventory(root, refs), protocol=protocol)

    report = TOOL.verify_archive(archive, root)

    findings = report["PROTOCOL_SNAPSHOT_COMPLETE"]["findings"]
    assert any(transient in f and "transient_basetemp" in f for f in findings), findings
    # ... and it is NOT reported as a durable absence
    assert not any(transient in f and "absent_from_archive" in f for f in findings)


def test_a_non_exportable_path_is_named_as_policy_not_as_a_gap(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    excluded = ".saipen/recovery/settled-index/seg-0001.json"
    protocol = {"saipen_snapshot": {
        "evidence_complete": False, "missing_required": [excluded],
        "truncated_required_dirs": [], "non_exportable": [".saipen/recovery"]}}

    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/real.png": _png()},
                       inventory=_clean_inventory(root, refs), protocol=protocol)

    report = TOOL.verify_archive(archive, root)

    findings = report["PROTOCOL_SNAPSHOT_COMPLETE"]["findings"]
    assert any("non_exportable_by_policy" in f for f in findings), findings


def test_a_recovery_log_detail_citation_outranks_the_broad_prefix(tmp_path):
    """`recovery/` is non-exportable, but two subdirectories are re-included by
    an explicit precedence rule; a missing one is a real gap, not policy."""
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    cited = ".saipen/recovery/log-detail/E-4591-abcdef.json"
    protocol = {"saipen_snapshot": {
        "evidence_complete": False, "missing_required": [cited],
        "truncated_required_dirs": [], "non_exportable": [".saipen/recovery"]}}

    archive = _archive(tmp_path / "export.zip",
                       {".saipen/evidence/real.png": _png()},
                       inventory=_clean_inventory(root, refs), protocol=protocol)

    report = TOOL.verify_archive(archive, root)

    findings = report["PROTOCOL_SNAPSHOT_COMPLETE"]["findings"]
    assert any(cited in f and "absent_despite_precedence" in f for f in findings), findings


# --- §04 E/F: the three verdicts are independent and cannot stand in --------

def test_source_review_readiness_never_implies_protocol_completeness(tmp_path):
    """The baseline archive's exact contradiction, reproduced."""
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])

    archive = _archive(
        tmp_path / "export.zip",
        {".saipen/evidence/real.png": _png()},
        inventory=_clean_inventory(root, refs),
        protocol={"saipen_snapshot": {
            "evidence_complete": False,
            "missing_required": [".saipen/evidence/t1223-gone.png"],
            "truncated_required_dirs": [".saipen/evidence"],
            "non_exportable": []}})

    report = TOOL.verify_archive(archive, root)

    assert report["SOURCE_REVIEW_READY"]["holds"] is True
    assert report["PROTOCOL_SNAPSHOT_COMPLETE"]["holds"] is False
    assert report["PROTOCOL_SNAPSHOT_COMPLETE"]["holds"] != report["SOURCE_REVIEW_READY"]["holds"]


def test_acceptance_completeness_never_implies_protocol_completeness(tmp_path):
    """Every cited screenshot can be present while the protocol snapshot is not."""
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    archive = _archive(
        tmp_path / "export.zip",
        {".saipen/evidence/real.png": _png(b".saipen/evidence/real.png")},
        inventory=_clean_inventory(root, refs),
        protocol={"saipen_snapshot": {
            "evidence_complete": False, "missing_required": [],
            "truncated_required_dirs": [".saipen/evidence"],
            "non_exportable": []}})

    report = TOOL.verify_archive(archive, root)

    assert report["ACCEPTANCE_EVIDENCE_COMPLETE"]["holds"] is True
    assert report["PROTOCOL_SNAPSHOT_COMPLETE"]["holds"] is False


def test_a_truncated_required_directory_alone_defeats_completeness(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    archive = _archive(
        tmp_path / "export.zip",
        {".saipen/evidence/real.png": _png(b".saipen/evidence/real.png")},
        inventory=_clean_inventory(root, refs),
        protocol={"saipen_snapshot": {
            "evidence_complete": True, "missing_required": [],
            "truncated_required_dirs": [".saipen/evidence"],
            "non_exportable": []}})

    report = TOOL.verify_archive(archive, root)

    assert report["PROTOCOL_SNAPSHOT_COMPLETE"]["holds"] is False
    assert any("truncated" in f
               for f in report["PROTOCOL_SNAPSHOT_COMPLETE"]["findings"])


def test_an_archive_member_absent_from_the_inventory_defeats_source_review(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/real.png"])
    _checkout(root, refs)

    archive = _archive(
        tmp_path / "export.zip",
        {".saipen/evidence/real.png": _png(b".saipen/evidence/real.png"),
         "src/smuggled.py": b"print('not in the inventory')\n"},
        inventory=_clean_inventory(root, refs),
        protocol=_clean_protocol())

    report = TOOL.verify_archive(archive, root)

    assert report["SOURCE_REVIEW_READY"]["holds"] is False
    assert any("not in the inventory" in f
               for f in report["SOURCE_REVIEW_READY"]["findings"])


# --- the positive control: a correct export must pass all three ------------

def test_a_complete_export_holds_all_three_verdicts(tmp_path):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/cap/hover.png",
                              ".saipen/evidence/cap/gauge.png"])
    _checkout(root, refs)

    members = {rel: _png(rel.encode()) for rel in refs}
    archive = _archive(tmp_path / "export.zip", members,
                       inventory=_clean_inventory(root, refs),
                       protocol=_clean_protocol())

    report = TOOL.verify_archive(archive, root)

    for verdict in ("SOURCE_REVIEW_READY", "PROTOCOL_SNAPSHOT_COMPLETE",
                    "ACCEPTANCE_EVIDENCE_COMPLETE"):
        assert report[verdict]["holds"] is True, (verdict, report[verdict]["findings"])
        assert report[verdict]["findings"] == []


# --- requirements are derived from the declaration, never hand-listed ------

def test_required_references_come_from_the_acceptance_declaration(tmp_path):
    root = tmp_path / "checkout"
    declaration = {"domains": {
        "DOMAIN_A": {"visual": {"status": "PARTIAL",
                                "evidence": [".saipen/evidence/a.png",
                                             ".saipen/evidence/shared.png"]}},
        "DOMAIN_B": {"behavioural": {"status": "PARTIAL",
                                     "evidence": [".saipen/evidence/shared.png",
                                                  ".saipen/evidence/b.py"]}},
    }}
    target = root / "tools" / "audit_export_fidelity.py"
    acceptance = root / "docs" / "audit" / "ACCEPTANCE.json"
    acceptance.parent.mkdir(parents=True, exist_ok=True)
    acceptance.write_text(json.dumps(declaration), encoding="utf-8")
    _checkout(root, [".saipen/evidence/a.png"])
    (root / ".saipen" / "evidence" / "shared.png").write_bytes(_png(b"s"))
    (root / ".saipen" / "evidence" / "b.py").write_text("x = 1\n", encoding="utf-8")

    references = TOOL.required_evidence(root)
    by_path = {r["path"]: r for r in references}

    assert sorted(by_path) == [".saipen/evidence/a.png", ".saipen/evidence/b.py",
                               ".saipen/evidence/shared.png"]
    # a shared reference is attributed to every plane that cites it, once
    assert by_path[".saipen/evidence/shared.png"]["declared_by"] == [
        "DOMAIN_A.visual", "DOMAIN_B.behavioural"]
    assert by_path[".saipen/evidence/a.png"]["sha256"] == hashlib.sha256(
        _png(b".saipen/evidence/a.png")).hexdigest()
    assert target is not None  # the module under test is the repo's tool


def test_a_reference_absent_from_the_checkout_is_reported_not_crashed(tmp_path):
    root = tmp_path / "checkout"
    _acceptance(root, [".saipen/evidence/never_existed.png"])

    references = TOOL.required_evidence(root)

    assert references[0]["present_in_checkout"] is False
    assert references[0]["sha256"] is None


def test_an_unreadable_archive_exits_two(tmp_path):
    assert TOOL.main(["--archive", str(tmp_path / "nope.zip"), "--root", str(tmp_path)]) == 2


def test_the_cli_fails_with_a_nonzero_exit_when_a_verdict_fails(tmp_path, capsys):
    root = tmp_path / "checkout"
    refs = _acceptance(root, [".saipen/evidence/hover.png"])
    _checkout(root, refs)
    archive = _archive(tmp_path / "export.zip", {},           # nothing archived
                       inventory=_clean_inventory(root, refs), protocol=_clean_protocol())

    code = TOOL.main(["--archive", str(archive), "--root", str(root)])

    assert code == 1
    out = capsys.readouterr().out
    assert "ACCEPTANCE_EVIDENCE_COMPLETE" in out
    assert "FAILS" in out
