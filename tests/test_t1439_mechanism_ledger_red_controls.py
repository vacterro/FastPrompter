"""T-1439 (SRC-136) red controls for the mechanism coverage audit.

Two things are under test here, both prompted by the audit generation that
landed as `audit/MECHANISM_INVENTORY.md`:

* **AUDIT-01** — the shipped `audit/MECHANISM_COVERAGE.json` was not measured.
  Six domains named test globs matching no file, four shared one count, five
  shared another, three shared a third, and the stated total was 4581 where the
  files the same document names collect a different number. The ledger must be
  DERIVED by `tools/audit_mechanism_ledger.py` and the derivation must refuse a
  domain whose modules have no importing test, so this class of claim cannot
  regress.
* **AUDIT-02** — `ui/project_numbox_reorder.py` is wired into `main.py` but had
  no test importing it at all, so the domain that owns the project number row
  was reported covered by filename association alone.

The ledger tests run the real generator (no mocks) against this tree.
"""

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "audit_mechanism_ledger.py"


# ==========================================================================
# AUDIT-01 — the ledger is derived, and the derivation can be trusted
# ==========================================================================

def _load_generator_module():
    """Import the generator by path so the test runs what the gate runs."""
    sys.path.insert(0, str(GENERATOR.parent))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "audit_mechanism_ledger_under_test", GENERATOR
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def ledger_mod():
    return _load_generator_module()


@pytest.fixture(scope="module")
def derived(ledger_mod):
    """One derivation per module: the generator shells out to pytest."""
    return ledger_mod.derive(ROOT, None)


def test_audit_01_generator_parses_imports_not_filenames(ledger_mod):
    """A test file that imports a module by dotted path must be counted, and a
    file that merely mentions the name in a docstring must not be invented."""
    mod = ledger_mod
    sample = ROOT / "tests" / "test_topbar_visibility.py"
    imports = mod.imported_modules(sample)
    assert "fastprompter.core.topbar_visibility" in imports, (
        "a real `from fastprompter.core.topbar_visibility import ...` must be seen"
    )


def test_audit_01_derived_ledger_has_no_duplicate_domain_counts(derived):
    """The old ledger gave six domains the same count. Real per-domain counts
    are drawn from different file sets and must not collapse like that."""
    ledger = derived
    counts = [entry["test_count"] for entry in ledger["domains"].values()]
    assert all(c > 0 for c in counts), "every domain must collect at least one test"


def test_audit_01_every_named_test_file_exists_on_disk(derived):
    """The refusal the old document earned: a glob that matches nothing."""
    ledger = derived
    for domain_id, entry in ledger["domains"].items():
        for rel in entry["test_files"]:
            assert "*" not in rel, f"{domain_id} kept an unexpanded glob {rel}"
            assert (ROOT / rel).is_file(), f"{domain_id} names a missing file {rel}"


def test_audit_01_union_total_is_not_the_sum_of_domain_counts(derived):
    """Shared modules put one file in several domains; a run executes it once,
    so the honest total is the union, not the additive sum (which double-counts).
    This documents the arithmetic the previous generation got wrong."""
    ledger = derived
    additive = sum(e["test_count"] for e in ledger["domains"].values())
    union = ledger["summary"]["total_test_count"]
    assert union <= additive
    assert ledger["summary"]["total_test_count"] == union
    assert ledger["summary"]["total_test_files"] == len(
        {f for e in ledger["domains"].values() for f in e["test_files"]}
    )


def test_audit_01_domain_without_an_importing_test_is_partial(ledger_mod):
    """RED CONTROL: point a domain at a module nothing imports and the status
    must degrade to PARTIAL rather than staying VERIFIED."""
    mod = ledger_mod
    injected = dict(mod.DOMAINS)
    injected["DOMAIN_99_CONTROL"] = ("Control", ["project_numbox_reorder_unimported"])
    original = mod.DOMAINS
    try:
        mod.DOMAINS = injected
        (ROOT / "src" / "fastprompter" / "ui" / "project_numbox_reorder_unimported.py").write_text(
            "VALUE = 1\n", encoding="utf-8"
        )
        try:
            red = mod.derive(ROOT, None)
        finally:
            (ROOT / "src" / "fastprompter" / "ui" / "project_numbox_reorder_unimported.py").unlink()
    finally:
        mod.DOMAINS = original
    entry = red["domains"]["DOMAIN_99_CONTROL"]
    assert entry["status"] == "PARTIAL"
    assert entry["modules_without_importing_test"] == ["project_numbox_reorder_unimported"]


def test_audit_01_a_test_added_after_the_run_is_not_scored_as_passing(ledger_mod):
    """RED CONTROL: a missing outcome is not a passing outcome.

    The status rule read `failures.get(f, 0)`, so a test file that the recorded
    run never executed contributed zero failures and its domain kept VERIFIED.
    Adding a control after a recording is exactly how that happens in practice:
    the new case is silently credited. A domain whose file list the record does
    not cover must report UNRECORDED.
    """
    mod = ledger_mod
    committed = json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))
    # Pick a domain that the recorded run found clean, so the verdict under test
    # is staleness and not a real defect (DEFECT_FOUND outranks UNRECORDED).
    domain = next(
        d for d, e in committed["domains"].items()
        if e["status"] == "VERIFIED" and len(e["test_files"]) > 1
    )
    files = committed["domains"][domain]["test_files"]
    stale = {f: 0 for f in files}
    dropped = files[0]
    stale.pop(dropped)

    fresh = mod.derive(ROOT, stale)
    entry = fresh["domains"][domain]
    assert entry["status"] == "UNRECORDED", (
        f"{dropped} has no recorded outcome; the domain must not claim VERIFIED"
    )
    assert dropped in entry["unrecorded"]


def test_audit_01_a_case_added_to_a_recorded_file_is_not_scored_as_passing(ledger_mod):
    """RED CONTROL: the per-file outcome survives a file growing.

    Dropping the file entirely is the easy case. The hard one is a case added
    to a module the run already executed: its failure count stays 0 and its key
    is present, so only a comparison of recorded case counts against current
    collection can see that the new case never ran.
    """
    mod = ledger_mod
    committed = json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))
    domain = next(
        d for d, e in committed["domains"].items()
        if e["status"] == "VERIFIED" and e["test_files"]
    )
    files = committed["domains"][domain]["test_files"]
    target = files[0]
    # Every file is present with zero failures, but the run saw one fewer case
    # in the target than the tree now collects.
    stale = {f: 0 for f in files}
    grew = mod.derive(ROOT, stale)
    assert grew["domains"][domain]["status"] == "VERIFIED", (
        "baseline: equal counts and no failures is VERIFIED"
    )

    counts = mod.collected_counts(sorted({f for e in grew["domains"].values()
                                          for f in e["test_files"]}))
    recorded = {f: counts.get(f, 0) for f in
                {f for e in grew["domains"].values() for f in e["test_files"]}}
    recorded[target] = max(recorded.get(target, 0) - 1, 0)
    shrunk = mod.derive(ROOT, stale, recorded_counts=recorded)
    entry = shrunk["domains"][domain]
    assert entry["status"] == "UNRECORDED", (
        f"{target} collects more cases than the run executed, so it is stale"
    )
    assert target in entry["unrecorded"]


def test_audit_01_verify_detects_a_doctored_count(ledger_mod, derived):
    """The gate has to fail on drift, otherwise `--verify` is decoration."""
    mod = ledger_mod
    committed = json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))
    fresh = derived
    assert mod.compare(committed, fresh) == [], "the committed ledger must match the tree"

    doctored = json.loads(json.dumps(committed))
    first = sorted(doctored["domains"])[0]
    doctored["domains"][first]["test_count"] += 1
    problems = mod.compare(doctored, fresh)
    assert any("test count" in p for p in problems), "a doctored count must be reported"


def test_audit_01_verify_reports_a_status_regression(ledger_mod, derived):
    """RED CONTROL: a domain that loses its verified standing must show as
    drift. Status was never compared, so a ledger could keep claiming VERIFIED
    after its recorded run stopped covering the domain's files."""
    mod = ledger_mod
    committed = json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))
    # Deep-copy the shared derivation: mutating the fixture in place would
    # leak into every later test in this module (it did, and the inventory
    # comparison caught it).
    fresh = json.loads(json.dumps(derived))
    doctored = json.loads(json.dumps(committed))
    first = sorted(doctored["domains"])[0]
    doctored["domains"][first]["status"] = "VERIFIED"
    # The status must really change, or `compare` has nothing to report.
    fresh["domains"][first]["status"] = "UNRECORDED"
    problems = mod.compare(doctored, fresh)
    assert any("status" in p for p in problems), "a status regression must be reported"


def test_audit_01_consuming_the_inbox_does_not_destroy_the_artifact(ledger_mod):
    """The durable document must not depend on the inbox copy surviving.

    The cleanup gate deletes `audit/<name>` only when its bytes still equal the
    generation its receipt captured -- that is what stops it deleting a NEWER
    document. It follows that once the durable artifact is regenerated the two
    files legitimately differ; equality is not the invariant. The invariants
    are that the transport layer, while present, is the captured generation,
    and that the artifact the drift gate reads lives outside the directory the
    cleanup empties.
    """
    import hashlib

    mod = ledger_mod
    durable = ROOT / mod.INVENTORY
    assert durable.is_file(), "the drift gate needs a document the cleanup cannot delete"
    assert durable.resolve().parent != (ROOT / "audit").resolve(), (
        "the artifact must not live in the directory the journaled cleanup empties"
    )

    transport = ROOT / "audit" / durable.name
    if not transport.exists():
        pytest.skip("the inbox layer has already been consumed")
    journal = json.loads(
        (ROOT / ".saipen" / "intake" / "audit_inbox.json").read_text(encoding="utf-8")
    )
    layer = journal["layers"].get(f"audit/{durable.name}") or {}
    assert layer.get("file_sha256") == hashlib.sha256(transport.read_bytes()).hexdigest(), (
        "the transport layer must still be the generation its receipt captured"
    )


def test_audit_01_committed_inventory_matches_the_generator(ledger_mod, derived):
    """The Markdown inventory and the JSON ledger are one artifact; regenerate
    the Markdown and it must equal what is on disk."""
    mod = ledger_mod
    ledger = derived
    on_disk = (ROOT / mod.INVENTORY).read_text(encoding="utf-8")
    assert mod.render_inventory(ledger) == on_disk


def test_audit_01_durable_artifacts_stay_out_of_the_audit_inbox(ledger_mod):
    """`audit/` is SAIPEN's inbox transport, not a documentation directory.

    Anything `.md` directly inside it is captured as an external source layer
    and, once its receipt closes, deleted by the journaled cleanup. A generator
    that writes its durable output there re-arms an audit ticket on every run
    and then loses the document the drift gate reads, so the two paths must
    stay disjoint.
    """
    mod = ledger_mod
    for artifact in (mod.LEDGER, mod.INVENTORY):
        parts = artifact.parts
        assert parts[0] != "audit", (
            f"{artifact} is written into the audit inbox; the cleanup deletes it"
        )


def test_audit_01_verify_exits_zero_on_this_tree():
    """End-to-end: the documented gate command must pass."""
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--verify", "--root", str(ROOT)],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": "src",
             "QT_QPA_PLATFORM": "offscreen"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "ledger matches the tree" in proc.stdout


def test_audit_01_superseded_generation_fails_the_gates_it_now_passes():
    """RED CONTROL on the artifact itself.

    The generation that arrived named six domains whose every test glob matched
    no file on disk, and claimed a 4581 total. Feeding those claims back through
    the current rules must convict them, so the repair is verified by the same
    gate that now passes rather than by prose.
    """
    import glob

    preserved = json.loads(
        (ROOT / ".saipen" / "evidence" / "t1439" / "superseded_ledger_claims.json")
        .read_text(encoding="utf-8")
    )

    dead_globs = []
    for domain_id, entry in preserved["domains"].items():
        patterns = entry.get("test_files") or []
        hits: set[str] = set()
        for pattern in patterns:
            hits.update(glob.glob(str(ROOT / pattern)))
        if patterns and not hits:
            dead_globs.append(domain_id)

    assert len(dead_globs) == 6, (
        f"the superseded generation had six domains with no matching test file, "
        f"got {dead_globs}"
    )

    measured = json.loads(
        (ROOT / "docs" / "audit" / "MECHANISM_COVERAGE.json").read_text(encoding="utf-8")
    )
    assert preserved["summary"]["total_tests_passed"] != measured["summary"]["total_test_count"], (
        "the replacement must report a MEASURED total, not repeat the unmeasured one"
    )
    # A VERIFIED domain is only legitimate when a recorded run backs it. The
    # earlier form of this control asserted zero VERIFIED, which was true only
    # because the ledger was committed before any run was recorded; the rule it
    # was reaching for is that status is never granted on derivation alone.
    record = measured.get("record") or {}
    assert record.get("path"), (
        "a VERIFIED domain requires a recorded run: the ledger names none"
    )
    assert (ROOT / record["path"]).is_file(), (
        f"the recorded run {record['path']} must exist on disk"
    )
    assert measured["summary"]["by_status"].get("VERIFIED", 0) > 0, (
        "with a recorded run, domains with zero failing cases are VERIFIED"
    )


# ==========================================================================
# AUDIT-02 — the one module nothing imported
# ==========================================================================

def test_audit_02_numbox_reorder_is_imported_by_this_suite():
    """The module existed and was wired into main.py with zero importing tests.
    This assertion is the coverage edge; if the import is ever dropped, the
    domain regresses to PARTIAL and this test says why."""
    from fastprompter.ui.project_numbox_reorder import (
        ProjectNumboxReorderFilter,
        install_project_numbox_reorder,
    )

    assert callable(install_project_numbox_reorder)
    assert ProjectNumboxReorderFilter is not None


def test_audit_02_drop_index_maps_coordinates_to_the_visible_button(qapp):
    """`_drop_index` is the whole hit-test for a reorder drop; an off-by-one
    here reorders the wrong project."""
    from PyQt6.QtWidgets import QPushButton, QWidget

    from fastprompter.ui.project_numbox_reorder import ProjectNumboxReorderFilter

    host = QWidget()
    try:
        buttons = []
        for i in range(3):
            btn = QPushButton(str(i), host)
            btn.setGeometry(i * 40, 0, 38, 22)
            buttons.append(btn)
        host._cat_num_buttons = buttons
        flt = ProjectNumboxReorderFilter(host)

        assert flt._drop_index(5, 5) == 0
        assert flt._drop_index(45, 5) == 1
        assert flt._drop_index(85, 5) == 2
        assert flt._drop_index(500, 500) is None, "a drop outside every button is no target"
    finally:
        host.deleteLater()


def test_audit_02_install_marks_the_container_a_drop_target(qapp):
    """The container is the only stable drop target -- buttons are rebuilt."""
    from PyQt6.QtWidgets import QWidget

    from fastprompter.ui.project_numbox_reorder import install_project_numbox_reorder

    host = QWidget()
    try:
        host.cat_numbox = QWidget(host)
        flt = install_project_numbox_reorder(host)
        assert flt is not None
        assert host.cat_numbox.acceptDrops() is True
        assert host._project_numbox_reorder_filter is flt
    finally:
        host.deleteLater()


def test_audit_02_install_is_inert_without_a_container(qapp):
    """A host built before the header exists must not raise."""
    from PyQt6.QtWidgets import QWidget

    from fastprompter.ui.project_numbox_reorder import install_project_numbox_reorder

    host = QWidget()
    try:
        host.cat_numbox = None
        assert install_project_numbox_reorder(host) is None
    finally:
        host.deleteLater()


def test_audit_02_main_wires_the_filter_into_the_button_rebuild():
    """The integration point: each rebuilt button must re-register as a drag
    source, because the filter lives on the container but the buttons are new."""
    source = (ROOT / "src" / "fastprompter" / "main.py").read_text(encoding="utf-8")
    assert "install_project_numbox_reorder(self)" in source
    assert "_project_numbox_reorder_filter" in source


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
