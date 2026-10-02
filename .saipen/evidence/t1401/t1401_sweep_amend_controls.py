"""Negative controls for the T-1401 SWEEP amendment.

Drives the REAL `improve.write_sweep_entry` against a scratch project built
from a COPY of the live cycle, so every refusal below is the engine answering
its own question -- never a re-implementation of it, and never a mutation of
the live ledger. Nothing here is mocked: the controls were written against the
real code and caught three separate misreadings of it, each of which is
recorded in the DEC line.

The scratch project needs no Git identity and no report re-stamping, because
an amendment deliberately consults neither (see `_amend_sweep_entry`): it is
gated by the ledger's own invariants plus a mandatory `--verification`. That
is the point being tested, so the harness proving it needs no scaffolding for
the gates it bypasses.

Every control asserts on the REFUSAL TEXT, not merely on the absence of a
write. "It refused" and "it refused for the stated reason" are different
claims and only the second is evidence. Control 10 additionally asserts that
each refusal wrote ZERO bytes.

Run:  python .saipen/evidence/t1401/t1401_sweep_amend_controls.py
Exit 0 only when every control passes.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ENGINE = Path("V:/___VAC/__K/__CODE/_AI_STUFF_AGENTIC/_SAIPEN/tools")
PROJECT = Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter")
CYCLE = "imp-vacterro-fastprompter-20261002-2"
REPORT = "buffy-02/saipen_improve_SAIPEN.md"
BAD_REF = "RUN-1/IMP-002"

sys.path.insert(0, str(ENGINE))
import improve  # noqa: E402


class Failure(Exception):
    pass


def _expect(condition: bool, label: str, detail: str) -> None:
    if not condition:
        raise Failure(f"{label}: {detail}")
    print(f"  ok  {label}")


def _expect_refusal(call, label: str, *must_contain: str) -> None:
    """The call must refuse AND the message must carry every named phrase.

    A refusal for an unrelated reason -- a bad path, a missing ticket, a
    stale cycle -- would satisfy a bare `raises` check while proving the
    control it stands for does not exist."""
    try:
        result = call()
    except improve.ImproveError as exc:
        text = str(exc)
    else:
        raise Failure(f"{label}: expected a refusal, got a commit {result!r}")
    for phrase in must_contain:
        if phrase not in text:
            raise Failure(f"{label}: refused, but not for the reason under test: {text}")
    print(f"  ok  {label}")
    return text


def build_scratch(*, active: bool = False, fresh_report: bool = False) -> Path:
    """A scratch project root holding a COPY of the live cycle.

    `active=True` flips the copied manifest to `active`. `fresh_report=True`
    re-stamps the copied report to the scratch tree's own source identity and
    to the installed protocol version. Both exist only to make the APPEND path
    reachable for controls 3 and 4: every gate the amendment bypasses (the
    completed-cycle gate, the T-619 freshness gate, the protocol-version
    bound bar) fires before the ones those controls test, so without the
    re-stamping they would all be answered by the wrong refusal. The
    amendment controls need neither, which is itself part of what they show."""
    root = Path(tempfile.mkdtemp(prefix="t1401-scratch-"))
    saipen = root / ".saipen"
    saipen.mkdir()
    shutil.copytree(PROJECT / ".saipen" / "improve" / CYCLE, saipen / "improve" / CYCLE)
    for name in ("BOARD.md", "STATE.md"):
        shutil.copy2(PROJECT / ".saipen" / name, saipen / name)
    for log in sorted((PROJECT / ".saipen").glob("LOG*.md")):
        shutil.copy2(log, saipen / log.name)
    if active:
        manifest = saipen / "improve" / CYCLE / "MANIFEST.md"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "cycle_status: complete", "cycle_status: active", 1
            ),
            encoding="utf-8",
        )
    if fresh_report:
        from freshness import compute_source_identity

        identity = compute_source_identity(root)
        report = saipen / "improve" / CYCLE / "buffy-02" / "saipen_improve_SAIPEN.md"
        lines = report.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("source_head:"):
                lines[i] = f"source_head: {identity.source_head}"
            elif line.startswith("source_tree_fingerprint:"):
                lines[i] = f"source_tree_fingerprint: {identity.source_tree_fingerprint}"
            elif line.startswith("saipen_version:"):
                lines[i] = f"saipen_version: {improve._saipen_install_version()}"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def ledger_of(root: Path) -> Path:
    return root / ".saipen" / "improve" / CYCLE / "SWEEP.md"


def entry(**overrides) -> dict:
    base = {
        "run": "RUN-1",
        "imp_id": "002",
        "disposition": "CONFIRMED",
        "ticket": "T-1392",
        "report": REPORT,
        "reproduced": "y",
        "verification": "t1401_reproduction.json",
        "amend": True,
    }
    base.update(overrides)
    return base


def cycle_of(root: Path) -> Path:
    return root / ".saipen" / "improve" / CYCLE


def control_1_the_two_gates_now_agree() -> None:
    """The defect, stated as data. The live line was already rejected by the
    CORE validator; before T-1401 the WRITE-time gate returned [] on it."""
    live = (PROJECT / ".saipen" / "improve" / CYCLE / "SWEEP.md").read_text(
        encoding="utf-8"
    )
    errors = improve.validate_sweep(live)
    _expect(
        any(BAD_REF in e and "unverified finding" in e for e in errors),
        "the live CONFIRMED/reproduced=n line is an error in the writer gate too",
        f"validate_sweep returned {errors!r}",
    )
    fixed = live.replace(
        f"{BAD_REF} [CONFIRMED] T-1392 report={REPORT} reproduced=n",
        f"{BAD_REF} [CONFIRMED] T-1392 report={REPORT} reproduced=y",
    )
    _expect(
        improve.validate_sweep(fixed) == [],
        "and the same line with reproduced=y validates clean",
        f"validate_sweep returned {improve.validate_sweep(fixed)!r}",
    )
    _expect(
        improve.validate_sweep(live.replace(f"{REPORT} reproduced=n", f"{REPORT} reproduced=n").replace(
            "[CONFIRMED] T-1392", "[NOT_REPRODUCED] -"
        )) == [],
        "a reproduced=n under a non-CONFIRMED disposition stays legal",
        "the clause must not fire where reproduced=n is the whole point",
    )


def control_2_an_amendment_repairs_the_ledger() -> None:
    root = build_scratch()
    try:
        before = ledger_of(root).read_text(encoding="utf-8")
        _expect(
            improve.validate_sweep(before) != [],
            "the scratch ledger starts invalid, as the live one is",
            "control 2 is vacuous on an already-valid base",
        )
        result = improve.write_sweep_entry(cycle_of(root), entry())
        _expect(bool(result.get("ok")), "the amendment commits", repr(result))
        after = ledger_of(root).read_text(encoding="utf-8")
        _expect(
            f"{BAD_REF} [CONFIRMED] T-1392 report={REPORT} reproduced=y "
            "verification=t1401_reproduction.json" in after,
            "the live line reads reproduced=y with its evidence bound",
            after,
        )
        _expect(
            improve.validate_sweep(after) == [],
            "and the repaired ledger validates clean",
            f"validate_sweep returned {improve.validate_sweep(after)!r}",
        )
        _expect(
            len(before.splitlines()) == len(after.splitlines()),
            "in place: the amendment adds and removes no line",
            f"{len(before.splitlines())} -> {len(after.splitlines())}",
        )
        _expect(
            "amended" in result and result["amended"]["was"].endswith("reproduced=n"),
            "the transaction result names the superseded line as evidence",
            repr(result.get("amended")),
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_3_a_completed_cycle_is_still_immutable_to_a_writer() -> None:
    """NITRO dogfood III, unchanged. The amendment exemption is not a licence
    to write dispositions into closed work."""
    root = build_scratch(fresh_report=True)
    try:
        before = ledger_of(root).read_text(encoding="utf-8")
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), {**entry(), "amend": False}),
            "a plain write to the completed cycle is refused",
            "is complete, not one of active",
        )
        _expect(
            ledger_of(root).read_text(encoding="utf-8") == before,
            "and it wrote nothing",
            "the ledger changed under a refused write",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_4_a_plain_write_is_still_refused_by_T638() -> None:
    """T-638, unchanged, on an ACTIVE cycle where it is actually reachable."""
    root = build_scratch(active=True, fresh_report=True)
    try:
        before = ledger_of(root).read_text(encoding="utf-8")
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), {**entry(), "amend": False}),
            "a plain write onto the invalid base is refused by T-638",
            "known-INVALID base is never mutated",
            "--amend",
        )
        _expect(
            ledger_of(root).read_text(encoding="utf-8") == before,
            "and it wrote nothing",
            "the ledger changed under a refused write",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_5_an_amendment_cannot_change_authority() -> None:
    for label, over in (
        ("the disposition", {"disposition": "NOT_REPRODUCED", "ticket": "-"}),
        ("the ticket", {"ticket": "T-1391"}),
    ):
        root = build_scratch()
        try:
            before = ledger_of(root).read_text(encoding="utf-8")
            _expect_refusal(
                lambda o=over: improve.write_sweep_entry(cycle_of(root), entry(**o)),
                f"an amendment that rewrites {label} is refused",
                "changes what the ledger authorizes",
                "SUPERSEDED/NOT_REPRODUCED",
            )
            _expect(
                ledger_of(root).read_text(encoding="utf-8") == before,
                "  ... and wrote nothing",
                "the ledger changed under a refused write",
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


def control_6_an_amendment_must_name_its_evidence() -> None:
    """The discipline that replaces the four finding-scoped gates. An
    amendment to committed evidence that names no evidence is refused."""
    root = build_scratch()
    try:
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), entry(verification="-")),
            "an amendment with no --verification is refused",
            "--verification is required",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_7_an_amendment_cannot_invent_a_disposition() -> None:
    root = build_scratch()
    try:
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), entry(imp_id="009")),
            "an amendment onto a finding_ref with no ledger line is refused",
            "the ledger has no line for RUN-1/IMP-009",
            "never creates",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_8_an_amendment_must_change_something() -> None:
    root = build_scratch()
    try:
        improve.write_sweep_entry(cycle_of(root), entry())
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), entry()),
            "an amendment that changes nothing is refused as journal noise",
            "changes nothing",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_9_unrelated_annotations_survive() -> None:
    """Correcting reproduced=n must not silently drop a fixed_by= or an
    earlier verification= that is still true."""
    root = build_scratch()
    try:
        ledger = ledger_of(root)
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(
                f"{BAD_REF} [CONFIRMED] T-1392 report={REPORT} reproduced=n",
                f"{BAD_REF} [CONFIRMED] T-1392 report={REPORT} reproduced=n "
                "fixed_by=T-1392 verification=earlier.json",
            ),
            encoding="utf-8",
        )
        improve.write_sweep_entry(cycle_of(root), entry())
        after = ledger.read_text(encoding="utf-8")
        _expect(
            "reproduced=y fixed_by=T-1392 verification=t1401_reproduction.json" in after,
            "fixed_by= survives an amendment that never named it",
            after,
        )
        _expect(
            "earlier.json" not in after,
            "the superseded verification= is replaced, not left to compete",
            after,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def control_10_an_amendment_is_scoped_to_one_line() -> None:
    """A repeated finding_ref inside ONE cycle is not something this cycle
    has, so an amendment that names the wrong run must miss rather than hit
    the first match."""
    root = build_scratch()
    try:
        _expect_refusal(
            lambda: improve.write_sweep_entry(cycle_of(root), entry(run="RUN-9")),
            "an amendment naming a run with no such line is refused",
            "the ledger has no line for RUN-9/IMP-002",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


CONTROLS = [
    control_1_the_two_gates_now_agree,
    control_2_an_amendment_repairs_the_ledger,
    control_3_a_completed_cycle_is_still_immutable_to_a_writer,
    control_4_a_plain_write_is_still_refused_by_T638,
    control_5_an_amendment_cannot_change_authority,
    control_6_an_amendment_must_name_its_evidence,
    control_7_an_amendment_cannot_invent_a_disposition,
    control_8_an_amendment_must_change_something,
    control_9_unrelated_annotations_survive,
    control_10_an_amendment_is_scoped_to_one_line,
]


def main() -> int:
    failed = 0
    for control in CONTROLS:
        print(f"\n{control.__name__}")
        try:
            control()
        except Failure as exc:
            print(f"  FAIL  {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001 - a control must never crash the run
            print(f"  ERROR {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{len(CONTROLS) - failed}/{len(CONTROLS)} controls passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
